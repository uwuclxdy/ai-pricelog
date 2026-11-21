from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog import store, validate
from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import zai_page as detector
from ai_pricelog.scrapers import zai_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://docs.z.ai/guides/overview/pricing"
FIXTURE = Path(__file__).parent / "fixtures" / "zai_page" / "pricing.html"
SCHEMA_KEYS = validate.load_schema_keys(Path(__file__).resolve().parents[1])

EXPECTED_IDS = [
    "glm-5.3-flash",
    "glm-5.3",
    "glm-5.2",
    "glm-5.1",
    "glm-5",
    "glm-5-turbo",
    "glm-4.7",
    "glm-4.7-flashx",
    "glm-4.6",
    "glm-4.5",
    "glm-4.5-x",
    "glm-4.5-air",
    "glm-4.5-airx",
    "glm-4-32b-0414-128k",
    "glm-4.7-flash",
    "glm-4.5-flash",
    "glm-5v-turbo",
    "glm-4.6v",
    "glm-ocr",
    "glm-4.6v-flashx",
    "glm-4.5v",
    "glm-4.6v-flash",
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="zai",
        provider="Z.AI",
        detector="zai_page",
        detector_url=PAGE_URL,
        scraper="zai_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


def test_detect_token_priced_models(monkeypatch):
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    assert detector.detect(cfg()) == EXPECTED_IDS
    # single-rate tables (image, video, ASR) are not per-token priced
    assert "glm-image" not in detector.detect(cfg())


def test_scrape_glm53(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "glm-5.3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1.4 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(4.4 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.26 / 1e6)
    assert pricing.mode == "chat"
    assert pricing.max_tokens_in == pricing.max_tokens_out == 0


def test_scrape_ignores_cells_nested_in_a_rate_cell(monkeypatch):
    # a nested table's cells must not shift the rate columns of their row
    soup = BeautifulSoup(
        "<table><tr><th>Model</th><th>Input</th><th>Cached Input</th>"
        "<th>Cached Input Storage</th><th>Output</th></tr>"
        "<tr><td>GLM-Nested</td><td>$1</td><td>$0.1</td>"
        "<td>$0.2<table><tr><td>$9</td></tr></table></td><td>$2</td></tr></table>",
        "html.parser",
    )
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: soup)
    pricing = scraper.scrape(cfg(), "glm-nested")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.1 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(2 / 1e6)


def test_scrape_promo_takes_charged_rate_not_struck_list_price(monkeypatch):
    # a promo cell renders the struck-through list price before the charged
    # one; the last dollar amount is the rate in force
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "glm-5.3-flash")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.075 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.25 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.015 / 1e6)


def test_scrape_free_cells_price_zero(monkeypatch):
    # free is a price: "Free" and "Limited-time Free" cells are zero rates,
    # a "-" cell stays unpriced
    soup = BeautifulSoup(
        "<table><tr><th>Model</th><th>Input</th><th>Cached Input</th>"
        "<th>Cached Input Storage</th><th>Output</th></tr>"
        "<tr><td>GLM-Free</td><td>Free</td><td>Free</td><td>-</td>"
        "<td>Limited-time Free</td></tr></table>",
        "html.parser",
    )
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: soup)
    pricing = scraper.scrape(cfg(), "glm-free")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.0
    assert pricing.output_cost_per_token == 0.0
    assert pricing.cache_read_cost_per_token == 0.0


def test_scrape_glm45_cache_read_pinned(monkeypatch):
    # 2026-08-26 flip-flop: one pass served every zai row without the cached
    # rate; pin the restored values so a silent drop fails this test
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    for model_id, cache_read in (("glm-4.5", 0.11), ("glm-4.5-air", 0.03)):
        pricing = scraper.scrape(cfg(), model_id)
        assert pricing is not None
        assert pricing.cache_read_cost_per_token == pytest.approx(cache_read / 1e6)


def test_scrape_missing_cached_column_raises(monkeypatch):
    # a table without the column must fail loudly: None would drop the field
    # from the row and the diff reads it as a rate removal
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>Model</th><th>Input</th><th>Output</th></tr>"
            "<tr><td>GLM-4.5</td><td>$0.6</td><td>$2.2</td></tr></table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="Cached Input"):
        scraper.scrape(cfg(), "glm-4.5")


def test_scrape_vision_model(monkeypatch):
    # the vision table shares the text table's per-token columns
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "glm-5v-turbo")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1.2 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(4.0 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.24 / 1e6)


def test_scrape_matches_row_case_insensitively(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "GLM-5.3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1.4 / 1e6)


def test_scrape_free_model_prices_zero(monkeypatch):
    # free is a price: the all-Free rows on the live page scrape as 0.0
    # pairs, never None
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    for model_id in ("glm-4.7-flash", "glm-4.6v-flash"):
        pricing = scraper.scrape(cfg(), model_id)
        assert pricing is not None
        assert pricing.input_cost_per_token == 0.0
        assert pricing.output_cost_per_token == 0.0
        assert pricing.cache_read_cost_per_token == 0.0


def notice_cfg() -> ProviderCfg:
    base = cfg()
    return ProviderCfg(
        key=base.key,
        provider=base.provider,
        detector=base.detector,
        detector_url=base.detector_url,
        scraper=base.scraper,
        scraper_url=base.scraper_url,
        announce_urls=("https://docs.z.ai/devpack/notice/usage-revision.md",),
    )


def serve_notice(monkeypatch: pytest.MonkeyPatch, text: str | None = None) -> None:
    """serve the notice fixture to the scraper; an unscripted url fails loudly."""
    if text is None:
        text = (FIXTURE.parent / "usage-revision.md").read_text(encoding="utf-8")

    def fetch(url: str) -> str:
        if url != "https://docs.z.ai/devpack/notice/usage-revision.md":
            raise AssertionError(f"unscripted fetch for {url}")
        return text

    monkeypatch.setattr(scraper, "fetch_text", fetch)


def variant_notice(peak_hours: str, offset: int = 8) -> str:
    """the committed notice with its peak-hours line swapped for `peak_hours`."""
    fixture = (FIXTURE.parent / "usage-revision.md").read_text(encoding="utf-8")
    committed = "Peak hours: Monday to Friday, 14:00–18:00 Singapore Standard Time (UTC+8)"
    assert fixture.count(committed), "committed notice lost its peak-hours line"
    return fixture.replace(
        committed,
        f"Peak hours: {peak_hours} Singapore Standard Time (UTC+{offset})",
    )


@pytest.fixture(autouse=True)
def fresh_notice_cache():
    scraper._notice_text.cache_clear()
    yield
    scraper._notice_text.cache_clear()


def test_scrape_glm53_attaches_quota_multiplier_entries(monkeypatch):
    # glm-5.3: 1x off-peak is the implicit base, 3x peak rides the peak-hours
    # entry (weekdays, 06:00-10:00 utc)
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    serve_notice(monkeypatch)
    pricing = scraper.scrape(notice_cfg(), "glm-5.3")
    assert pricing is not None
    assert pricing.window_rates == (
        {
            "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "window": [600, 1000],
            "quota_multiplier": 3.0,
        },
    )
    # the notice quotes Singapore time; the scraper converts it to UTC clock
    # windows, so the stamp is UTC
    assert pricing.timezone == "UTC"


def test_scrape_glm53_builds_utc_window_entries(monkeypatch):
    # the converted [start, end] pair is a UTC clock pair, so the built entry
    # stamps UTC and keeps the pair
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    serve_notice(monkeypatch)
    pricing = scraper.scrape(notice_cfg(), "glm-5.3")
    assert pricing is not None
    row = store.build_row("zai", "glm-5.3", pricing, "2026-11-18", PAGE_URL, SCHEMA_KEYS.version)
    assert row["overrides"] == [
        {
            "when": {
                "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                "window": [600, 1000],
                "timezone": "UTC",
            },
            "quota_multiplier": 3.0,
        }
    ]


def test_scrape_glm53_flash_attaches_whole_day_and_peak_entries(monkeypatch):
    # glm-5.3-flash: 0.4x off-peak rides a whole-day entry, 1.2x the
    # peak-hours entry
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    serve_notice(monkeypatch)
    pricing = scraper.scrape(notice_cfg(), "glm-5.3-flash")
    assert pricing is not None
    assert pricing.window_rates == (
        {"quota_multiplier": 0.4},
        {
            "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "window": [600, 1000],
            "quota_multiplier": 1.2,
        },
    )


def test_scrape_peak_window_wholly_before_the_offset_shifts_days_back(monkeypatch):
    # 02:00-07:00 SGT is 18:00-23:00 UTC the previous day, so the day set
    # moves back one weekday with the clock
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    serve_notice(monkeypatch, variant_notice("Monday to Friday, 02:00–07:00"))
    pricing = scraper.scrape(notice_cfg(), "glm-5.3")
    assert pricing is not None
    assert pricing.window_rates == (
        {
            "days": ["monday", "tuesday", "wednesday", "thursday", "sunday"],
            "window": [1800, 2300],
            "quota_multiplier": 3.0,
        },
    )


def test_scrape_peak_window_straddling_utc_midnight_splits_by_day_set(monkeypatch):
    # 06:00-10:00 SGT is 22:00-02:00 UTC: the window splits, the part before
    # midnight on the day set one weekday back, the part after on the
    # notice's own set
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    serve_notice(monkeypatch, variant_notice("Monday to Friday, 06:00–10:00"))
    pricing = scraper.scrape(notice_cfg(), "glm-5.3")
    assert pricing is not None
    assert pricing.window_rates == (
        {
            "days": ["monday", "tuesday", "wednesday", "thursday", "sunday"],
            "window": [2200, 2400],
            "quota_multiplier": 3.0,
        },
        {
            "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "window": [0, 200],
            "quota_multiplier": 3.0,
        },
    )


def test_scrape_peak_window_ending_exactly_at_utc_midnight_stores_2400(monkeypatch):
    # 02:00-08:00 SGT is 18:00-24:00 UTC: the end lands exactly on UTC
    # midnight, stored as 2400 instead of splitting a zero-length tail
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    serve_notice(monkeypatch, variant_notice("Monday to Friday, 02:00–08:00"))
    pricing = scraper.scrape(notice_cfg(), "glm-5.3")
    assert pricing is not None
    assert pricing.window_rates == (
        {
            "days": ["monday", "tuesday", "wednesday", "thursday", "sunday"],
            "window": [1800, 2400],
            "quota_multiplier": 3.0,
        },
    )


def test_scrape_peak_window_ending_minutes_past_utc_midnight_splits(monkeypatch):
    # 02:00-08:30 SGT is 18:00 the previous utc day to 00:30: the end hour
    # reaching the offset hour leaves a tail past utc midnight, so the
    # window splits; an end check of <= the offset would compute [1800, 30],
    # which the part check refuses
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    serve_notice(monkeypatch, variant_notice("Monday to Friday, 02:00–08:30"))
    pricing = scraper.scrape(notice_cfg(), "glm-5.3")
    assert pricing is not None
    assert pricing.window_rates == (
        {
            "days": ["monday", "tuesday", "wednesday", "thursday", "sunday"],
            "window": [1800, 2400],
            "quota_multiplier": 3.0,
        },
        {
            "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "window": [0, 30],
            "quota_multiplier": 3.0,
        },
    )


def test_scrape_peak_start_at_the_offset_hour_keeps_the_day_set(monkeypatch):
    # 08:00 SGT is 00:00 UTC: a start at the offset hour stays on the
    # notice's own days
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    serve_notice(monkeypatch, variant_notice("Monday to Friday, 08:00–12:00"))
    pricing = scraper.scrape(notice_cfg(), "glm-5.3")
    assert pricing is not None
    assert pricing.window_rates == (
        {
            "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "window": [0, 400],
            "quota_multiplier": 3.0,
        },
    )


def test_scrape_peak_days_shift_by_the_quoted_offset_not_a_hardcoded_one(monkeypatch):
    # the wrap boundary is the quoted offset, not UTC+8: 02:00-07:00 UTC+9
    # is 17:00-22:00 UTC the previous day, and an hour between 8 and the
    # quoted offset decides both the shift and the split branches
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    weekday_set = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    back_one = ["monday", "tuesday", "wednesday", "thursday", "sunday"]
    cases = (
        ("Monday to Friday, 02:00–07:00", 9, ((back_one, [1700, 2200]),)),
        ("Monday to Friday, 02:00–05:00", 0, ((weekday_set, [200, 500]),)),
        ("Monday to Friday, 02:00–08:30", 9, ((back_one, [1700, 2330]),)),
        (
            "Monday to Friday, 08:00–10:00",
            9,
            ((back_one, [2300, 2400]), (weekday_set, [0, 100])),
        ),
        # 14:00-14:30 converts: the zero-length check compares minutes too
        ("Monday to Friday, 14:00–14:30", 8, ((weekday_set, [600, 630]),)),
        ("Monday to Friday, 14:30–18:00", 8, ((weekday_set, [630, 1000]),)),
        ("Monday to Friday, 02:30–07:00", 8, ((back_one, [1830, 2300]),)),
        (
            "Monday to Friday, 06:30–10:00",
            8,
            ((back_one, [2230, 2400]), (weekday_set, [0, 200])),
        ),
    )
    for peak_hours, offset, parts in cases:
        serve_notice(monkeypatch, variant_notice(peak_hours, offset))
        scraper._notice_text.cache_clear()
        pricing = scraper.scrape(notice_cfg(), "glm-5.3")
        assert pricing is not None
        assert pricing.window_rates == tuple(
            {"days": days, "window": window, "quota_multiplier": 3.0} for days, window in parts
        )


def test_scrape_shifted_day_range_wrapping_the_week_yields_each_day_once(monkeypatch):
    # monday..sunday shifted back one weekday wraps the week: all seven days,
    # each once, in calendar order. the whole-week set shifts onto itself, so
    # a mid-week range pins the direction the wrap alone cannot show
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    cases = (
        (
            "Monday to Sunday, 02:00–07:00",
            ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
        ),
        (
            "Monday to Wednesday, 02:00–07:00",
            ["monday", "tuesday", "sunday"],
        ),
    )
    for peak_hours, days in cases:
        serve_notice(monkeypatch, variant_notice(peak_hours))
        scraper._notice_text.cache_clear()
        pricing = scraper.scrape(notice_cfg(), "glm-5.3")
        assert pricing is not None
        assert pricing.window_rates == (
            {
                "days": days,
                "window": [1800, 2300],
                "quota_multiplier": 3.0,
            },
        )


def test_scrape_shifted_peak_entries_pass_validate_row(monkeypatch):
    # the entries the converted notices produce ride a built row through the
    # public scrape entry point and pass validate_row: the validator refuses
    # a window with start >= end or an end past 2400, so a window the
    # conversion would store broken fails here, not far from the cause
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    cases = (
        (
            "Monday to Friday, 14:00–18:00",
            8,
            (
                {
                    "when": {
                        "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                        "window": [600, 1000],
                        "timezone": "UTC",
                    },
                    "quota_multiplier": 3.0,
                },
            ),
        ),
        (
            "Monday to Friday, 02:00–07:00",
            8,
            (
                {
                    "when": {
                        "days": ["monday", "tuesday", "wednesday", "thursday", "sunday"],
                        "window": [1800, 2300],
                        "timezone": "UTC",
                    },
                    "quota_multiplier": 3.0,
                },
            ),
        ),
        (
            "Monday to Friday, 06:00–10:00",
            8,
            (
                {
                    "when": {
                        "days": ["monday", "tuesday", "wednesday", "thursday", "sunday"],
                        "window": [2200, 2400],
                        "timezone": "UTC",
                    },
                    "quota_multiplier": 3.0,
                },
                {
                    "when": {
                        "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                        "window": [0, 200],
                        "timezone": "UTC",
                    },
                    "quota_multiplier": 3.0,
                },
            ),
        ),
        (
            "Monday to Friday, 02:00–08:00",
            8,
            (
                {
                    "when": {
                        "days": ["monday", "tuesday", "wednesday", "thursday", "sunday"],
                        "window": [1800, 2400],
                        "timezone": "UTC",
                    },
                    "quota_multiplier": 3.0,
                },
            ),
        ),
        (
            "Monday to Friday, 14:00–08:00",
            8,
            (
                {
                    "when": {
                        "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                        "window": [600, 2400],
                        "timezone": "UTC",
                    },
                    "quota_multiplier": 3.0,
                },
            ),
        ),
        (
            "Monday to Friday, 14:00–24:00",
            8,
            (
                {
                    "when": {
                        "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                        "window": [600, 1600],
                        "timezone": "UTC",
                    },
                    "quota_multiplier": 3.0,
                },
            ),
        ),
        (
            "Monday to Friday, 18:00–24:00",
            0,
            (
                {
                    "when": {
                        "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                        "window": [1800, 2400],
                        "timezone": "UTC",
                    },
                    "quota_multiplier": 3.0,
                },
            ),
        ),
        (
            "Monday to Friday, 23:00–01:00",
            8,
            (
                {
                    "when": {
                        "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                        "window": [1500, 1700],
                        "timezone": "UTC",
                    },
                    "quota_multiplier": 3.0,
                },
            ),
        ),
        (
            "Monday to Friday, 14:00–03:00",
            8,
            (
                {
                    "when": {
                        "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                        "window": [600, 1900],
                        "timezone": "UTC",
                    },
                    "quota_multiplier": 3.0,
                },
            ),
        ),
        (
            "Monday to Friday, 02:00–03:00",
            14,
            (
                {
                    "when": {
                        "days": ["monday", "tuesday", "wednesday", "thursday", "sunday"],
                        "window": [1200, 1300],
                        "timezone": "UTC",
                    },
                    "quota_multiplier": 3.0,
                },
            ),
        ),
    )
    for peak_hours, offset, expected in cases:
        serve_notice(monkeypatch, variant_notice(peak_hours, offset))
        # the notice cache is keyed by url alone, so a second serve in one
        # test must clear it or every iteration reads the first text
        scraper._notice_text.cache_clear()
        pricing = scraper.scrape(notice_cfg(), "glm-5.3")
        assert pricing is not None
        row = store.build_row(
            "zai", "glm-5.3", pricing, "2026-11-18", PAGE_URL, SCHEMA_KEYS.version
        )
        validate.validate_row(row, SCHEMA_KEYS)
        assert row["overrides"] == list(expected)


def test_scrape_peak_clause_with_an_unstorable_utc_window_raises(monkeypatch):
    # a wrap whose converted window crosses utc midnight names no storable
    # same-day window, and a zero-length clause names none either (at the
    # offset hour it would convert to a whole-day [0, 2400] the validator
    # accepts): both raise at the clause instead of shipping a row the
    # validator refuses or a whole-day window it accepts
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    cases = (
        ("Monday to Friday, 22:00–10:00", "22:00–10:00"),
        ("Monday to Friday, 08:00–08:00", "08:00–08:00"),
    )
    for peak_hours, clock_pair in cases:
        serve_notice(monkeypatch, variant_notice(peak_hours))
        scraper._notice_text.cache_clear()
        with pytest.raises(FetchError) as caught:
            scraper.scrape(notice_cfg(), "glm-5.3")
        assert clock_pair in str(caught.value)
        assert notice_cfg().announce_urls[0] in str(caught.value)
        assert "; fix: re-verify the notice's peak hours" in str(caught.value)


def test_scrape_peak_clause_wrapping_singapore_midnight_keeps_its_own_days(monkeypatch):
    # a clause wrapping the notice's own midnight whose converted window is a
    # plain same-day span still stores that span on the notice's own days
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    cases = (
        ("Monday to Friday, 23:00–01:00", [1500, 1700]),
        ("Monday to Friday, 14:00–03:00", [600, 1900]),
    )
    for peak_hours, window in cases:
        serve_notice(monkeypatch, variant_notice(peak_hours))
        scraper._notice_text.cache_clear()
        pricing = scraper.scrape(notice_cfg(), "glm-5.3")
        assert pricing is not None
        assert pricing.window_rates == (
            {
                "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                "window": window,
                "quota_multiplier": 3.0,
            },
        )


def test_scrape_peak_clause_ending_at_24_00_stores_the_notice_day_end(monkeypatch):
    # a clause end of exactly 24:00 is the end of the notice day, not a
    # clock: 14:00-24:00 SGT converts to 06:00-16:00 UTC on the notice's own
    # days, and 18:00-24:00 at UTC+0 lands on UTC midnight, stored as 2400
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    cases = (
        ("Monday to Friday, 14:00–24:00", 8, [600, 1600]),
        ("Monday to Friday, 18:00–24:00", 0, [1800, 2400]),
    )
    for peak_hours, offset, window in cases:
        serve_notice(monkeypatch, variant_notice(peak_hours, offset))
        scraper._notice_text.cache_clear()
        pricing = scraper.scrape(notice_cfg(), "glm-5.3")
        assert pricing is not None
        assert pricing.window_rates == (
            {
                "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                "window": window,
                "quota_multiplier": 3.0,
            },
        )


def test_scrape_peak_offset_past_utc_plus_14_raises(monkeypatch):
    # no zone quotes past UTC+14, so a larger offset is a corrupted notice
    # and fails loudly; a one-weekday shift is right for offsets up to UTC+24
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    for offset in (15, 28):
        serve_notice(monkeypatch, variant_notice("Monday to Friday, 02:00–03:00", offset=offset))
        scraper._notice_text.cache_clear()
        with pytest.raises(FetchError) as caught:
            scraper.scrape(notice_cfg(), "glm-5.3")
        assert f"UTC+{offset}" in str(caught.value)
        assert notice_cfg().announce_urls[0] in str(caught.value)
        assert "; fix: re-verify the notice's zone" in str(caught.value)
    # UTC+14 is the last offset that converts
    serve_notice(monkeypatch, variant_notice("Monday to Friday, 02:00–03:00", offset=14))
    scraper._notice_text.cache_clear()
    pricing = scraper.scrape(notice_cfg(), "glm-5.3")
    assert pricing is not None
    assert pricing.window_rates == (
        {
            "days": ["monday", "tuesday", "wednesday", "thursday", "sunday"],
            "window": [1200, 1300],
            "quota_multiplier": 3.0,
        },
    )


def test_scrape_peak_clause_with_an_impossible_clock_raises(monkeypatch):
    # the clause grammar admits an hour past 23 or a minute past 59; such a
    # clock is no time a row could carry, so the clause breaks loudly. the
    # boundary cases pin an hour of exactly 24 (a start: only an end of
    # 24:00 is the day end), a minute of exactly 60 on either side of the
    # dash, and a 24-hour end with a minute past 0
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    for peak_hours, clock_pair in (
        ("Monday to Friday, 09:60–10:00", "09:60–10:00"),
        ("Monday to Friday, 24:00–02:00", "24:00–02:00"),
        ("Monday to Friday, 14:00–25:00", "14:00–25:00"),
        ("Monday to Friday, 14:00–18:60", "14:00–18:60"),
        ("Monday to Friday, 14:00–24:30", "14:00–24:30"),
        ("Monday to Friday, 24:00-02:00", "24:00-02:00"),
    ):
        serve_notice(monkeypatch, variant_notice(peak_hours))
        scraper._notice_text.cache_clear()
        with pytest.raises(FetchError) as caught:
            scraper.scrape(notice_cfg(), "glm-5.3")
        assert clock_pair in str(caught.value)
        assert notice_cfg().announce_urls[0] in str(caught.value)
        assert "; fix: re-verify the notice's peak hours" in str(caught.value)


def test_scrape_non_quota_model_carries_no_entries(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    serve_notice(monkeypatch)
    pricing = scraper.scrape(notice_cfg(), "glm-5.2")
    assert pricing is not None
    assert pricing.window_rates == ()
    assert pricing.timezone is None


def test_scrape_notice_fetch_failure_leaves_entries_off(monkeypatch):
    # a failed notice fetch must not kill the price row: the base rates land
    # without entries and the next scrape re-attaches them
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())

    def boom(url: str) -> str:
        raise FetchError(f"fetch failed for {url}")

    monkeypatch.setattr(scraper, "fetch_text", boom)
    pricing = scraper.scrape(notice_cfg(), "glm-5.3")
    assert pricing is not None
    assert pricing.window_rates == ()


def test_scrape_broken_quota_clause_raises(monkeypatch):
    # a clause the pattern no longer matches is a page-shape break: a
    # drifted multiplier must never drop silently
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    broken = (
        (FIXTURE.parent / "usage-revision.md")
        .read_text(encoding="utf-8")
        .replace(
            'consume quota at a rate of "1× during off-peak hours and 3× during peak hours"',
            'consume quota at a rate of "1× off-peak"',
        )
    )
    serve_notice(monkeypatch, broken)
    with pytest.raises(FetchError, match="unrecognized quota clause"):
        scraper.scrape(notice_cfg(), "glm-5.3")


def test_scrape_broken_peak_hours_clause_raises(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    broken = (
        (FIXTURE.parent / "usage-revision.md")
        .read_text(encoding="utf-8")
        .replace(
            "Peak hours: Monday to Friday, 14:00–18:00 Singapore Standard Time (UTC+8).",
            "Peak hours: see the app.",
        )
    )
    serve_notice(monkeypatch, broken)
    with pytest.raises(FetchError, match="unrecognized peak-hours clause"):
        scraper.scrape(notice_cfg(), "glm-5.3")


def test_scrape_cached_input_without_rate_is_omitted(monkeypatch):
    # the 32b row carries "-" in the Cached Input column: no cache-read rate
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "glm-4-32b-0414-128k")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.1 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.1 / 1e6)
    assert pricing.cache_read_cost_per_token is None


def test_scrape_unknown_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "glm-9") is None


def test_malformed_page_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<h2>Vision Models</h2><table><tr><td>Model</td></tr></table>", "html.parser"
        ),
    )
    with pytest.raises(FetchError, match="model pricing tables"):
        scraper.scrape(cfg(), "glm-5.3")


def test_detect_no_token_table_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<h2>Image Generation Models</h2><table><tr><td>Model</td><td>Price</td></tr></table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="model pricing tables"):
        detector.detect(cfg())


def test_detect_header_case_drift_still_matches(monkeypatch):
    # the Model/Input/Output header pins match after folding, so a
    # lowercase header still locates the per-token tables
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>model</th><th>input</th><th>cached input</th>"
            "<th>output</th></tr>"
            "<tr><td>GLM-5.3</td><td>$1.4</td><td>$0.26</td><td>$4.4</td></tr></table>",
            "html.parser",
        ),
    )
    assert detector.detect(cfg()) == ["glm-5.3"]


def test_scrape_header_case_drift_still_scrapes(monkeypatch):
    # scrape indexes through the same folded headers detection pins, so a
    # fold-equal but differently-cased Input/Output header still scrapes
    # instead of crashing on the raw-spelling index
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>Model</th><th>input</th><th>Cached Input</th>"
            "<th>output</th></tr>"
            "<tr><td>GLM-5.3</td><td>$1.4</td><td>$0.26</td><td>$4.4</td></tr></table>",
            "html.parser",
        ),
    )
    pricing = scraper.scrape(cfg(), "glm-5.3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1.4 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(4.4 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.26 / 1e6)


def test_scrape_all_lowercase_header_still_scrapes(monkeypatch):
    # a fully lowercased header must scrape: the Cached Input admission is
    # fold-equal too, so a recased page never false-raises the missing-column
    # FetchError
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>model</th><th>input</th><th>cached input</th>"
            "<th>output</th></tr>"
            "<tr><td>GLM-5.3</td><td>$1.4</td><td>$0.26</td><td>$4.4</td></tr></table>",
            "html.parser",
        ),
    )
    pricing = scraper.scrape(cfg(), "glm-5.3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1.4 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.26 / 1e6)


def test_fetch_error_propagates(monkeypatch):
    def boom(url):
        raise FetchError(f"fetch failed for {url}")

    monkeypatch.setattr(detector, "fetch_soup", boom)
    with pytest.raises(FetchError, match=PAGE_URL):
        detector.detect(cfg())

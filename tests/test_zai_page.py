from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import zai_page as detector
from ai_pricelog.scrapers import zai_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://docs.z.ai/guides/overview/pricing"
FIXTURE = Path(__file__).parent / "fixtures" / "zai_page" / "pricing.html"

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


def test_scrape_non_quota_model_carries_no_entries(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    serve_notice(monkeypatch)
    pricing = scraper.scrape(notice_cfg(), "glm-5.2")
    assert pricing is not None
    assert pricing.window_rates == ()


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


def test_fetch_error_propagates(monkeypatch):
    def boom(url):
        raise FetchError(f"fetch failed for {url}")

    monkeypatch.setattr(detector, "fetch_soup", boom)
    with pytest.raises(FetchError, match=PAGE_URL):
        detector.detect(cfg())

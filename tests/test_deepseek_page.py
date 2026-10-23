from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import deepseek_page as detector
from ai_pricelog.scrapers import deepseek_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://api-docs.deepseek.com/quick_start/pricing/"
FIXTURE = Path(__file__).parent / "fixtures" / "deepseek_page" / "pricing.html"


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="deepseek",
        provider="DeepSeek",
        detector="deepseek_page",
        detector_url=PAGE_URL,
        scraper="deepseek_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


def patch_soup(monkeypatch, module, html: str) -> None:
    monkeypatch.setattr(module, "fetch_soup", lambda url: BeautifulSoup(html, "html.parser"))


GUIDE_URL = "https://api-docs.deepseek.com/guides/search"
GUIDE_FIXTURE = Path(__file__).parent / "fixtures" / "deepseek_page" / "search.html"


def load_guide_soup() -> BeautifulSoup:
    return BeautifulSoup(GUIDE_FIXTURE.read_text(), "html.parser")


def soup_for(url: str) -> BeautifulSoup:
    return load_guide_soup() if url == GUIDE_URL else load_soup()


def patch_pricing_soup(monkeypatch, html: str) -> None:
    """serve the synthetic pricing html for the pricing page, the guide fixture for the guide."""
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(html, "html.parser") if url == PAGE_URL else load_guide_soup(),
    )


def test_detect_models(monkeypatch):
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    # the 2026-09-10 page: V4 Flash and V4 Flash Vision Exp retired (billing
    # rule deepseek-v4-retirement-2026-09-10), V4.1 Flash served as
    # "deepseek-flash", with " (n)" footnote markers on the header cells
    assert detector.detect(cfg()) == ["deepseek-flash", "deepseek-v4-pro"]


def test_detect_skips_non_id_header_cells(monkeypatch):
    patch_soup(
        monkeypatch,
        detector,
        "<table><tr><td>MODEL</td><td>note!</td><td>deepseek-v4-flash</td></tr></table>",
    )
    assert detector.detect(cfg()) == ["deepseek-v4-flash"]


def test_detect_malformed_page_raises(monkeypatch):
    patch_soup(monkeypatch, detector, "<table><tr><td>OTHER</td></tr></table>")
    with pytest.raises(FetchError, match="MODEL"):
        detector.detect(cfg())


def test_detect_model_header_case_drift_still_matches(monkeypatch):
    # the first header cell pins as "MODEL" after folding case, so a
    # lowercase spelling still locates the model table
    patch_soup(
        monkeypatch,
        detector,
        "<table><tr><td>model</td><td>deepseek-v4-flash</td></tr></table>",
    )
    assert detector.detect(cfg()) == ["deepseek-v4-flash"]


def test_detect_fetch_error_propagates(monkeypatch):
    def boom(url):
        raise FetchError(f"fetch failed for {url}")

    monkeypatch.setattr(detector, "fetch_soup", boom)
    with pytest.raises(FetchError, match=PAGE_URL):
        detector.detect(cfg())


WINDOWS = ((100, 400), (600, 1000))
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday")


def test_scrape_flash_split_pricing(monkeypatch):
    # the off-peak subrow becomes the default price, the peak subrow the
    # constrained peak entries, and the schedule footnote the windows
    monkeypatch.setattr(scraper, "fetch_soup", soup_for)
    pricing = scraper.scrape(cfg(), "deepseek-flash")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.15 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.6 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.003 / 1e6)
    assert pricing.peak_input_cost_per_token == pytest.approx(0.3 / 1e6)
    assert pricing.peak_output_cost_per_token == pytest.approx(1.2 / 1e6)
    assert pricing.peak_cache_read_cost_per_token == pytest.approx(0.006 / 1e6)
    assert pricing.peak_windows == WINDOWS
    assert pricing.peak_days == WEEKDAYS
    assert pricing.effective_at == "2026-08-23"
    assert pricing.timezone == "Asia/Shanghai"
    assert pricing.mode == "chat"
    assert pricing.max_tokens_out == 384 * 1024
    assert pricing.max_tokens_in == 1024 * 1024


def test_scrape_pro_split_pricing(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", soup_for)
    pricing = scraper.scrape(cfg(), "deepseek-v4-pro")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.66 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(1.98 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.022 / 1e6)
    assert pricing.peak_input_cost_per_token == pytest.approx(1.32 / 1e6)
    assert pricing.peak_output_cost_per_token == pytest.approx(3.96 / 1e6)
    assert pricing.peak_cache_read_cost_per_token == pytest.approx(0.044 / 1e6)
    assert pricing.peak_windows == WINDOWS
    assert pricing.peak_days == WEEKDAYS
    assert pricing.effective_at == "2026-08-23"
    assert pricing.max_tokens_out == 384 * 1024
    assert pricing.max_tokens_in == 1024 * 1024


def test_scrape_vision_exp_split_pricing(monkeypatch):
    # the retired V4 Flash Vision Exp id is no longer on the page: the
    # retirement rule routes its name to V4.1 Flash, and detection no
    # longer lists it, so scraping it yields no pricing
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "deepseek-v4-flash-vision-exp") is None


def test_scrape_unknown_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "deepseek-v3") is None


def test_scrape_model_without_pricing_rows_returns_none(monkeypatch):
    patch_soup(
        monkeypatch,
        scraper,
        "<table><tr><td>MODEL</td><td>deepseek-v4-flash</td></tr>"
        "<tr><td>BASE URL</td><td>x</td></tr></table>",
    )
    assert scraper.scrape(cfg(), "deepseek-v4-flash") is None


def test_scrape_carries_search_and_fetch_fees(monkeypatch):
    # the search/fetch guide prices both endpoints per 1,000 successful
    # requests; the scraper reads each into the per-request fees dict
    guide = (
        "<h2>Billing</h2>"
        "<table><thead><tr><th>API</th><th>Unit</th><th>Price</th></tr></thead>"
        "<tbody><tr><td>Search</td><td>Per 1,000 successful requests</td><td>$0.75</td></tr>"
        "<tr><td>Fetch</td><td>Per 1,000 successful requests</td><td>$0.75</td></tr>"
        "</tbody></table>"
    )
    guide_url = "https://api-docs.deepseek.com/guides/search"

    def soup_for(url):
        return BeautifulSoup(guide, "html.parser") if url == guide_url else load_soup()

    monkeypatch.setattr(scraper, "fetch_soup", soup_for)
    pricing = scraper.scrape(cfg(), "deepseek-v4-pro")
    assert pricing is not None
    assert pricing.fees == {"search": 0.00075, "fetch": 0.00075}


def test_scrape_per_model_max_output_cells(monkeypatch):
    # MAX OUTPUT can list one cell per model column; each model takes its own
    patch_pricing_soup(
        monkeypatch,
        "<table><tr><td>MODEL</td><td>deepseek-v4-flash</td><td>deepseek-v4-pro</td></tr>"
        "<tr><td>MAX OUTPUT</td><td>MAXIMUM: 128K</td><td>MAXIMUM: 256K</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE MISS)</td><td>OFF-PEAK</td>"
        "<td>$0.22</td><td>$0.66</td></tr>"
        "<tr><td>PEAK</td><td>$0.44</td><td>$1.32</td></tr>"
        "<tr><td>1M OUTPUT TOKENS</td><td>OFF-PEAK</td><td>$0.66</td><td>$1.98</td></tr>"
        "<tr><td>PEAK</td><td>$1.32</td><td>$3.96</td></tr></table>"
        "<p>Peak hours are 01:00 - 04:00 and 06:00 - 10:00 UTC.</p>",
    )
    flash = scraper.scrape(cfg(), "deepseek-v4-flash")
    assert flash is not None
    assert flash.max_tokens_out == 128 * 1024
    pro = scraper.scrape(cfg(), "deepseek-v4-pro")
    assert pro is not None
    assert pro.max_tokens_out == 256 * 1024


def test_scrape_per_model_cell_without_k_value_is_zero(monkeypatch):
    # a per-model MAX OUTPUT cell carrying no K value must not inherit another
    # model's value: the merged-cell fallback only applies to merged rows
    patch_pricing_soup(
        monkeypatch,
        "<table><tr><td>MODEL</td><td>deepseek-v4-flash</td><td>deepseek-v4-pro</td></tr>"
        "<tr><td>MAX OUTPUT</td><td>MAXIMUM: 128K</td><td>UNLIMITED</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE MISS)</td><td>OFF-PEAK</td>"
        "<td>$0.22</td><td>$0.66</td></tr>"
        "<tr><td>PEAK</td><td>$0.44</td><td>$1.32</td></tr>"
        "<tr><td>1M OUTPUT TOKENS</td><td>OFF-PEAK</td><td>$0.66</td><td>$1.98</td></tr>"
        "<tr><td>PEAK</td><td>$1.32</td><td>$3.96</td></tr></table>"
        "<p>Peak hours are 01:00 - 04:00 and 06:00 - 10:00 UTC.</p>",
    )
    flash = scraper.scrape(cfg(), "deepseek-v4-flash")
    assert flash is not None
    assert flash.max_tokens_out == 128 * 1024
    pro = scraper.scrape(cfg(), "deepseek-v4-pro")
    assert pro is not None
    assert pro.max_tokens_out == 0


def test_scrape_off_peak_only_is_flat_pricing(monkeypatch):
    # labels carrying no PEAK subrow are flat: no peak fields, no windows
    patch_pricing_soup(
        monkeypatch,
        "<table><tr><td>MODEL</td><td>deepseek-v4-flash</td></tr>"
        "<tr><td>MAX OUTPUT</td><td>MAXIMUM: 128K</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE MISS)</td><td>OFF-PEAK</td><td>$0.22</td></tr>"
        "<tr><td>1M OUTPUT TOKENS</td><td>OFF-PEAK</td><td>$0.66</td></tr></table>",
    )
    pricing = scraper.scrape(cfg(), "deepseek-v4-flash")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.22 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.66 / 1e6)
    assert pricing.peak_input_cost_per_token is None
    assert pricing.peak_output_cost_per_token is None
    assert pricing.peak_windows == ()
    assert pricing.max_tokens_out == 128 * 1024


def test_scrape_cache_hit_without_peak_subrow_is_flat(monkeypatch):
    # a CACHE HIT label carrying no PEAK subrow is flat: cache_read only
    patch_pricing_soup(
        monkeypatch,
        "<table><tr><td>MODEL</td><td>deepseek-v4-flash</td></tr>"
        "<tr><td>MAX OUTPUT</td><td>MAXIMUM: 128K</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE MISS)</td><td>OFF-PEAK</td><td>$0.22</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE HIT)</td><td>OFF-PEAK</td><td>$0.007</td></tr>"
        "<tr><td>1M OUTPUT TOKENS</td><td>OFF-PEAK</td><td>$0.66</td></tr></table>",
    )
    pricing = scraper.scrape(cfg(), "deepseek-v4-flash")
    assert pricing is not None
    assert pricing.cache_read_cost_per_token == pytest.approx(0.007 / 1e6)
    assert pricing.peak_cache_read_cost_per_token is None
    assert pricing.peak_windows == ()


def test_scrape_flat_cache_hit_with_split_input_output(monkeypatch):
    # CACHE HIT without a PEAK subrow while CACHE MISS/OUTPUT are split: the
    # cache read stays flat, the peak fields cover input/output only
    patch_pricing_soup(
        monkeypatch,
        "<table><tr><td>MODEL</td><td>deepseek-v4-flash</td></tr>"
        "<tr><td>MAX OUTPUT</td><td>MAXIMUM: 128K</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE MISS)</td><td>OFF-PEAK</td><td>$0.22</td></tr>"
        "<tr><td>PEAK</td><td>$0.44</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE HIT)</td><td>OFF-PEAK</td><td>$0.007</td></tr>"
        "<tr><td>1M OUTPUT TOKENS</td><td>OFF-PEAK</td><td>$0.66</td></tr>"
        "<tr><td>PEAK</td><td>$1.32</td></tr></table>"
        "<p>Peak hours are 01:00 - 04:00 and 06:00 - 10:00 UTC.</p>",
    )
    pricing = scraper.scrape(cfg(), "deepseek-v4-flash")
    assert pricing is not None
    assert pricing.cache_read_cost_per_token == pytest.approx(0.007 / 1e6)
    assert pricing.peak_cache_read_cost_per_token is None
    assert pricing.peak_input_cost_per_token == pytest.approx(0.44 / 1e6)
    assert pricing.peak_output_cost_per_token == pytest.approx(1.32 / 1e6)
    assert pricing.peak_windows == WINDOWS
    # no weekday clause in the footnote: windows apply every day, and the
    # weekend rule has no effective stamp
    assert pricing.peak_days == ()
    assert pricing.effective_at is None


def test_scrape_cache_hit_peak_without_input_output_peak_returns_none(monkeypatch):
    # a PEAK subrow on the CACHE HIT label only is an unusable split, like
    # any other one-sided peak row
    patch_soup(
        monkeypatch,
        scraper,
        "<table><tr><td>MODEL</td><td>deepseek-v4-flash</td></tr>"
        "<tr><td>MAX OUTPUT</td><td>MAXIMUM: 128K</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE MISS)</td><td>OFF-PEAK</td><td>$0.22</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE HIT)</td><td>OFF-PEAK</td><td>$0.007</td></tr>"
        "<tr><td>PEAK</td><td>$0.014</td></tr>"
        "<tr><td>1M OUTPUT TOKENS</td><td>OFF-PEAK</td><td>$0.66</td></tr></table>",
    )
    assert scraper.scrape(cfg(), "deepseek-v4-flash") is None


def test_scrape_peak_cache_read_without_footnote_fails(monkeypatch):
    # peak cache-read is a peak field: without the schedule footnote it fails
    # the same way any peak row does
    patch_soup(
        monkeypatch,
        scraper,
        "<table><tr><td>MODEL</td><td>deepseek-v4-flash</td></tr>"
        "<tr><td>MAX OUTPUT</td><td>MAXIMUM: 128K</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE MISS)</td><td>OFF-PEAK</td><td>$0.22</td></tr>"
        "<tr><td>PEAK</td><td>$0.44</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE HIT)</td><td>OFF-PEAK</td><td>$0.007</td></tr>"
        "<tr><td>PEAK</td><td>$0.014</td></tr>"
        "<tr><td>1M OUTPUT TOKENS</td><td>OFF-PEAK</td><td>$0.66</td></tr>"
        "<tr><td>PEAK</td><td>$1.32</td></tr></table>",
    )
    with pytest.raises(FetchError, match="footnote"):
        scraper.scrape(cfg(), "deepseek-v4-flash")


def test_scrape_peak_rows_without_footnote_fail(monkeypatch):
    # peak prices are mandatory with the peak windows (validate.py enforces it), so
    # peak subrows without the schedule footnote are a scrape failure
    patch_soup(
        monkeypatch,
        scraper,
        "<table><tr><td>MODEL</td><td>deepseek-v4-flash</td></tr>"
        "<tr><td>MAX OUTPUT</td><td>MAXIMUM: 128K</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE MISS)</td><td>OFF-PEAK</td><td>$0.22</td></tr>"
        "<tr><td>PEAK</td><td>$0.44</td></tr>"
        "<tr><td>1M OUTPUT TOKENS</td><td>OFF-PEAK</td><td>$0.66</td></tr>"
        "<tr><td>PEAK</td><td>$1.32</td></tr></table>",
    )
    with pytest.raises(FetchError, match="footnote"):
        scraper.scrape(cfg(), "deepseek-v4-flash")


def test_scrape_footnote_without_peak_rows_is_flat(monkeypatch):
    patch_pricing_soup(
        monkeypatch,
        "<table><tr><td>MODEL</td><td>deepseek-v4-flash</td></tr>"
        "<tr><td>MAX OUTPUT</td><td>MAXIMUM: 128K</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE MISS)</td><td>OFF-PEAK</td><td>$0.22</td></tr>"
        "<tr><td>1M OUTPUT TOKENS</td><td>OFF-PEAK</td><td>$0.66</td></tr></table>"
        "<p>Off-peak rates are half of the peak rates. "
        "Peak hours are 01:00 - 04:00 and 06:00 - 10:00 UTC (all other hours are off-peak).</p>",
    )
    pricing = scraper.scrape(cfg(), "deepseek-v4-flash")
    assert pricing is not None
    assert pricing.peak_input_cost_per_token is None
    assert pricing.peak_windows == ()


def test_scrape_one_sided_peak_rows_return_none(monkeypatch):
    # a PEAK subrow on one label only is an unusable split: no pricing
    patch_soup(
        monkeypatch,
        scraper,
        "<table><tr><td>MODEL</td><td>deepseek-v4-flash</td></tr>"
        "<tr><td>MAX OUTPUT</td><td>MAXIMUM: 128K</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE MISS)</td><td>OFF-PEAK</td><td>$0.22</td></tr>"
        "<tr><td>PEAK</td><td>$0.44</td></tr>"
        "<tr><td>1M OUTPUT TOKENS</td><td>OFF-PEAK</td><td>$0.66</td></tr></table>",
    )
    assert scraper.scrape(cfg(), "deepseek-v4-flash") is None


def test_scrape_unrecognized_weekday_clause_fails(monkeypatch):
    # a weekday clause the scraper cannot map must fail loudly, not schedule
    # wrongly
    patch_soup(
        monkeypatch,
        scraper,
        "<table><tr><td>MODEL</td><td>deepseek-v4-flash</td></tr>"
        "<tr><td>MAX OUTPUT</td><td>MAXIMUM: 128K</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE MISS)</td><td>OFF-PEAK</td><td>$0.22</td></tr>"
        "<tr><td>PEAK</td><td>$0.44</td></tr>"
        "<tr><td>1M OUTPUT TOKENS</td><td>OFF-PEAK</td><td>$0.66</td></tr>"
        "<tr><td>PEAK</td><td>$1.32</td></tr></table>"
        "<p>Peak hours are 01:00 - 04:00 and 06:00 - 10:00 UTC,"
        " Tuesday through Saturday (all other hours are off-peak).</p>",
    )
    with pytest.raises(FetchError, match="weekday clause"):
        scraper.scrape(cfg(), "deepseek-v4-flash")


def test_scrape_window_past_beijing_boundary_fails(monkeypatch):
    # a window ending after 16:00 UTC no longer shares its weekday with the
    # beijing billing day; with the weekday clause present the schedule needs
    # a timezone-aware shape
    patch_soup(
        monkeypatch,
        scraper,
        "<table><tr><td>MODEL</td><td>deepseek-v4-flash</td></tr>"
        "<tr><td>MAX OUTPUT</td><td>MAXIMUM: 128K</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE MISS)</td><td>OFF-PEAK</td><td>$0.22</td></tr>"
        "<tr><td>PEAK</td><td>$0.44</td></tr>"
        "<tr><td>1M OUTPUT TOKENS</td><td>OFF-PEAK</td><td>$0.66</td></tr>"
        "<tr><td>PEAK</td><td>$1.32</td></tr></table>"
        "<p>Peak hours are 12:00 - 18:00 and 20:00 - 22:00 UTC,"
        " Monday through Friday (all other hours are off-peak).</p>",
    )
    with pytest.raises(FetchError, match="16:00 UTC"):
        scraper.scrape(cfg(), "deepseek-v4-flash")


def test_scrape_window_past_boundary_without_clause_is_every_day(monkeypatch):
    # no weekday clause: windows past 16:00 UTC are expressible (every-day
    # schedules need no weekday equivalence), and no effective stamp applies
    patch_pricing_soup(
        monkeypatch,
        "<table><tr><td>MODEL</td><td>deepseek-v4-flash</td></tr>"
        "<tr><td>MAX OUTPUT</td><td>MAXIMUM: 128K</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE MISS)</td><td>OFF-PEAK</td><td>$0.22</td></tr>"
        "<tr><td>PEAK</td><td>$0.44</td></tr>"
        "<tr><td>1M OUTPUT TOKENS</td><td>OFF-PEAK</td><td>$0.66</td></tr>"
        "<tr><td>PEAK</td><td>$1.32</td></tr></table>"
        "<p>Peak hours are 12:00 - 18:00 and 20:00 - 22:00 UTC"
        " (all other hours are off-peak).</p>",
    )
    pricing = scraper.scrape(cfg(), "deepseek-v4-flash")
    assert pricing is not None
    assert pricing.peak_windows == ((1200, 1800), (2000, 2200))
    assert pricing.peak_days == ()
    assert pricing.effective_at is None


def test_scrape_clause_in_own_sentence_sets_days(monkeypatch):
    # the clause may leave the window sentence as long as it stays in the
    # footnote paragraph
    patch_pricing_soup(
        monkeypatch,
        "<table><tr><td>MODEL</td><td>deepseek-v4-flash</td></tr>"
        "<tr><td>MAX OUTPUT</td><td>MAXIMUM: 128K</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE MISS)</td><td>OFF-PEAK</td><td>$0.22</td></tr>"
        "<tr><td>PEAK</td><td>$0.44</td></tr>"
        "<tr><td>1M OUTPUT TOKENS</td><td>OFF-PEAK</td><td>$0.66</td></tr>"
        "<tr><td>PEAK</td><td>$1.32</td></tr></table>"
        "<p>Peak hours are 01:00 - 04:00 and 06:00 - 10:00 UTC."
        " Peak rates apply Monday through Friday.</p>",
    )
    pricing = scraper.scrape(cfg(), "deepseek-v4-flash")
    assert pricing is not None
    assert pricing.peak_days == WEEKDAYS
    assert pricing.effective_at == "2026-08-23"


def test_scrape_weekdays_wording_fails(monkeypatch):
    # "weekdays" without the recognized clause is an unknown schedule
    patch_soup(
        monkeypatch,
        scraper,
        "<table><tr><td>MODEL</td><td>deepseek-v4-flash</td></tr>"
        "<tr><td>MAX OUTPUT</td><td>MAXIMUM: 128K</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE MISS)</td><td>OFF-PEAK</td><td>$0.22</td></tr>"
        "<tr><td>PEAK</td><td>$0.44</td></tr>"
        "<tr><td>1M OUTPUT TOKENS</td><td>OFF-PEAK</td><td>$0.66</td></tr>"
        "<tr><td>PEAK</td><td>$1.32</td></tr></table>"
        "<p>Peak hours are 01:00 - 04:00 and 06:00 - 10:00 UTC on weekdays.</p>",
    )
    with pytest.raises(FetchError, match="weekday clause"):
        scraper.scrape(cfg(), "deepseek-v4-flash")


def test_scrape_abbreviated_weekday_wording_fails(monkeypatch):
    # "Mon-Fri" is an unknown schedule spelling and must fail loudly
    patch_soup(
        monkeypatch,
        scraper,
        "<table><tr><td>MODEL</td><td>deepseek-v4-flash</td></tr>"
        "<tr><td>MAX OUTPUT</td><td>MAXIMUM: 128K</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE MISS)</td><td>OFF-PEAK</td><td>$0.22</td></tr>"
        "<tr><td>PEAK</td><td>$0.44</td></tr>"
        "<tr><td>1M OUTPUT TOKENS</td><td>OFF-PEAK</td><td>$0.66</td></tr>"
        "<tr><td>PEAK</td><td>$1.32</td></tr></table>"
        "<p>Peak hours are 01:00 - 04:00 and 06:00 - 10:00 UTC, Mon-Fri.</p>",
    )
    with pytest.raises(FetchError, match="weekday clause"):
        scraper.scrape(cfg(), "deepseek-v4-flash")


def test_guide_fees_parse_the_live_fixture():
    assert scraper._guide_fees(load_guide_soup(), GUIDE_URL) == {
        "search": 0.00075,
        "fetch": 0.00075,
    }


def test_guide_fees_missing_fetch_fee_raises(monkeypatch):
    # a billing table missing one fee fails the scrape loudly
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: (
            BeautifulSoup(
                "<table><thead><tr><th>API</th><th>Unit</th><th>Price</th></tr></thead>"
                "<tbody><tr><td>Search</td><td>Per 1,000 successful requests</td>"
                "<td>$0.75</td></tr></tbody></table>",
                "html.parser",
            )
            if url == GUIDE_URL
            else load_soup()
        ),
    )
    with pytest.raises(FetchError, match="missing fetch fee"):
        scraper.scrape(cfg(), "deepseek-v4-pro")


def test_guide_fees_no_billing_table_raises():
    with pytest.raises(FetchError, match="billing table"):
        scraper._guide_fees(BeautifulSoup("<p>no table</p>", "html.parser"), GUIDE_URL)


def test_scrape_guide_fetch_failure_raises(monkeypatch):
    def boom(url):
        if url == GUIDE_URL:
            raise FetchError(f"fetch failed for {url}")
        return load_soup()

    monkeypatch.setattr(scraper, "fetch_soup", boom)
    with pytest.raises(FetchError, match=GUIDE_URL):
        scraper.scrape(cfg(), "deepseek-v4-pro")


def test_guide_fees_follow_the_stated_unit():
    # a rescaled per-10,000 unit must still read per-request: the divisor
    # follows the Unit cell, never a hardcoded 1,000
    guide = (
        "<table><thead><tr><th>API</th><th>Unit</th><th>Price</th></tr></thead>"
        "<tbody><tr><td>Search</td><td>Per 10,000 successful requests</td><td>$7.50</td></tr>"
        "<tr><td>Fetch</td><td>Per 10,000 successful requests</td><td>$7.50</td></tr>"
        "</tbody></table>"
    )
    assert scraper._guide_fees(BeautifulSoup(guide, "html.parser"), GUIDE_URL) == {
        "search": 0.00075,
        "fetch": 0.00075,
    }


def test_guide_fees_unrecognized_unit_raises():
    guide = (
        "<table><thead><tr><th>API</th><th>Unit</th><th>Price</th></tr></thead>"
        "<tbody><tr><td>Search</td><td>Per 1,000 tokens</td><td>$0.75</td></tr>"
        "<tr><td>Fetch</td><td>Per 1,000 tokens</td><td>$0.75</td></tr>"
        "</tbody></table>"
    )
    with pytest.raises(FetchError, match="unit"):
        scraper._guide_fees(BeautifulSoup(guide, "html.parser"), GUIDE_URL)


def test_a_huge_window_value_raises_a_fetch_error():
    # a 4300+ digit value overflows int(); the reader must bound the run and
    # name the cell instead of raising ValueError/OverflowError
    rows = [["MAX OUTPUT", "9" * 5000 + "K"]]
    with pytest.raises(FetchError):
        scraper._window_tokens(rows, ["m"], "m", "MAX OUTPUT", scraper._K_PATTERN, 1024)

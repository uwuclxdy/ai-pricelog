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


def test_detect_models(monkeypatch):
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    assert detector.detect(cfg()) == [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "deepseek-v4-flash-vision-exp",
    ]


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
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "deepseek-v4-flash")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.22 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.66 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.007 / 1e6)
    assert pricing.peak_input_cost_per_token == pytest.approx(0.44 / 1e6)
    assert pricing.peak_output_cost_per_token == pytest.approx(1.32 / 1e6)
    assert pricing.peak_cache_read_cost_per_token == pytest.approx(0.014 / 1e6)
    assert pricing.peak_windows == WINDOWS
    assert pricing.peak_days == WEEKDAYS
    assert pricing.effective_at == "2026-08-23"
    assert pricing.timezone == "Asia/Shanghai"
    assert pricing.mode == "chat"
    assert pricing.max_tokens_out == 384 * 1024
    assert pricing.max_tokens_in == 1024 * 1024


def test_scrape_pro_split_pricing(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
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
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "deepseek-v4-flash-vision-exp")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.22 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.66 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.007 / 1e6)
    assert pricing.peak_input_cost_per_token == pytest.approx(0.44 / 1e6)
    assert pricing.peak_output_cost_per_token == pytest.approx(1.32 / 1e6)
    assert pricing.peak_cache_read_cost_per_token == pytest.approx(0.014 / 1e6)
    assert pricing.peak_windows == WINDOWS
    assert pricing.peak_days == WEEKDAYS
    assert pricing.effective_at == "2026-08-23"
    assert pricing.max_tokens_out == 384 * 1024
    assert pricing.max_tokens_in == 1024 * 1024


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


def test_scrape_per_model_max_output_cells(monkeypatch):
    # MAX OUTPUT can list one cell per model column; each model takes its own
    patch_soup(
        monkeypatch,
        scraper,
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
    patch_soup(
        monkeypatch,
        scraper,
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
    patch_soup(
        monkeypatch,
        scraper,
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
    patch_soup(
        monkeypatch,
        scraper,
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
    patch_soup(
        monkeypatch,
        scraper,
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
    patch_soup(
        monkeypatch,
        scraper,
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
    patch_soup(
        monkeypatch,
        scraper,
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
    patch_soup(
        monkeypatch,
        scraper,
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

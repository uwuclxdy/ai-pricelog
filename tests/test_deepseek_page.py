from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from autopr_genai_prices.config import ProviderCfg
from autopr_genai_prices.detectors import deepseek_page as detector
from autopr_genai_prices.scrapers import deepseek_page as scraper
from autopr_genai_prices.web import FetchError

PAGE_URL = "https://api-docs.deepseek.com/quick_start/pricing"
FIXTURE = Path(__file__).parent / "fixtures" / "deepseek_page" / "pricing.html"


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="deepseek",
        yml="deepseek.yml",
        or_prefix="deepseek",
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
    assert detector.detect(cfg()) == ["deepseek-v4-flash", "deepseek-v4-pro"]


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


def test_detect_fetch_error_propagates(monkeypatch):
    def boom(url):
        raise FetchError(f"fetch failed for {url}")

    monkeypatch.setattr(detector, "fetch_soup", boom)
    with pytest.raises(FetchError, match=PAGE_URL):
        detector.detect(cfg())


WINDOWS = (("01:00:00Z", "04:00:00Z"), ("06:00:00Z", "10:00:00Z"))


def test_scrape_flash_split_pricing(monkeypatch):
    # the off-peak subrow becomes the default price, the peak subrow the
    # constrained peak entries, and the schedule footnote the windows
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "deepseek-v4-flash")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.22 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.66 / 1e6)
    assert pricing.peak_input_cost_per_token == pytest.approx(0.44 / 1e6)
    assert pricing.peak_output_cost_per_token == pytest.approx(1.32 / 1e6)
    assert pricing.peak_windows == WINDOWS
    assert pricing.mode == "chat"
    assert pricing.max_tokens == 384 * 1024


def test_scrape_pro_split_pricing(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "deepseek-v4-pro")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.66 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(1.98 / 1e6)
    assert pricing.peak_input_cost_per_token == pytest.approx(1.32 / 1e6)
    assert pricing.peak_output_cost_per_token == pytest.approx(3.96 / 1e6)
    assert pricing.peak_windows == WINDOWS
    assert pricing.max_tokens == 384 * 1024


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
    assert flash.max_tokens == 128 * 1024
    pro = scraper.scrape(cfg(), "deepseek-v4-pro")
    assert pro is not None
    assert pro.max_tokens == 256 * 1024


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
    assert flash.max_tokens == 128 * 1024
    pro = scraper.scrape(cfg(), "deepseek-v4-pro")
    assert pro is not None
    assert pro.max_tokens == 0


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
    assert pricing.max_tokens == 128 * 1024


def test_scrape_peak_rows_without_footnote_fail(monkeypatch):
    # peak prices are mandatory with the peak windows (yml.py enforces it), so
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

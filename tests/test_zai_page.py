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


def test_scrape_free_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "glm-4.7-flash") is None
    assert scraper.scrape(cfg(), "glm-4.6v-flash") is None


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

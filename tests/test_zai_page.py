from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from autopr_genai_prices.config import ProviderCfg
from autopr_genai_prices.detectors import zai_page as detector
from autopr_genai_prices.scrapers import zai_page as scraper
from autopr_genai_prices.web import FetchError

PAGE_URL = "https://docs.z.ai/guides/overview/pricing"
FIXTURE = Path(__file__).parent / "fixtures" / "zai_page" / "pricing.html"

EXPECTED_IDS = [
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
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="zai",
        provider="zai",
        namespace="zai",
        detector="zai_page",
        detector_url=PAGE_URL,
        scraper="zai_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


def test_detect_text_models(monkeypatch):
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    assert detector.detect(cfg()) == EXPECTED_IDS
    assert "glm-5v-turbo" not in detector.detect(cfg())


def test_scrape_glm53(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "glm-5.3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1.4 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(4.4 / 1e6)
    assert pricing.mode == "chat"
    assert pricing.max_tokens == 0


def test_scrape_matches_row_case_insensitively(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "GLM-5.3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1.4 / 1e6)


def test_scrape_free_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "glm-4.7-flash") is None


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
    with pytest.raises(FetchError, match="text-models"):
        scraper.scrape(cfg(), "glm-5.3")


def test_detect_no_text_table_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<h2>Vision Models</h2><table><tr><td>Model</td></tr></table>", "html.parser"
        ),
    )
    with pytest.raises(FetchError, match="text-models"):
        detector.detect(cfg())


def test_fetch_error_propagates(monkeypatch):
    def boom(url):
        raise FetchError(f"fetch failed for {url}")

    monkeypatch.setattr(detector, "fetch_soup", boom)
    with pytest.raises(FetchError, match=PAGE_URL):
        detector.detect(cfg())

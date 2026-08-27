"""openai pricing pair tests, pinned against the saved live page."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import openai_page as detector
from ai_pricelog.scrapers import openai_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://platform.openai.com/docs/pricing"
FIXTURE = Path(__file__).parent / "fixtures" / "openai_page" / "pricing.html"

EXPECTED_IDS = [
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "gpt-5.5-pro",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.4-pro",
    "gpt-5.2",
    "gpt-5.2-pro",
    "gpt-5.1",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-5-pro",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-4o",
    "gpt-4o-2024-05-13",
    "gpt-4o-mini",
    "o1",
    "o1-pro",
    "o3-pro",
    "o3",
    "o4-mini",
    "o3-mini",
    "gpt-4-turbo-2024-04-09",
    "gpt-4-0613",
    "gpt-3.5-turbo",
    "gpt-3.5-turbo-0125",
    "gpt-3.5-turbo-1106",
    "gpt-3.5-turbo-instruct",
    "davinci-002",
    "babbage-002",
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="openai",
        provider="OpenAI",
        detector="openai_page",
        detector_url=PAGE_URL,
        scraper="openai_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


def island_soup(tier: str, rows: list) -> BeautifulSoup:
    props = json.dumps({"tier": tier, "rows": rows}).replace('"', "&quot;")
    return BeautifulSoup(
        f'<astro-island component-export="TextTokenPricingTables" props="{props}"></astro-island>',
        "html.parser",
    )


def test_detect_ids(monkeypatch):
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_scrape_five_column_row(monkeypatch):
    # five-column row: input, cached read, cache write (dropped), output
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "gpt-5.6-sol")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(4 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.4 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(20 / 1e6)
    assert pricing.mode == "chat"


def test_scrape_four_column_row(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "gpt-4o")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(2.5 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(1.25 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(10 / 1e6)


def test_scrape_null_cache_read(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "o3-pro")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(20 / 1e6)
    assert pricing.cache_read_cost_per_token is None
    assert pricing.output_cost_per_token == pytest.approx(80 / 1e6)


def test_scrape_annotation_name(monkeypatch):
    # the page annotates gpt-5.5 with its context window; the bare name is the id
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "gpt-5.5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(5 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.5 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(30 / 1e6)


def test_scrape_unknown_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "gpt-6") is None


def test_scrape_missing_standard_island_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: island_soup("batch", [["gpt-5.6-sol", 2, 0.2, 2.5, 10]]),
    )
    with pytest.raises(FetchError, match="no standard pricing table"):
        scraper.scrape(cfg(), "gpt-5.6-sol")


def test_detect_missing_standard_island_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: island_soup("flex", [["gpt-5.6-sol", 6, 0.6, 7.5, 30]]),
    )
    with pytest.raises(FetchError, match="no standard pricing table"):
        detector.detect(cfg())


def test_detect_malformed_row_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: island_soup("standard", [["gpt-5.6-sol", 4, 0.4]]),
    )
    with pytest.raises(FetchError, match="outside the pricing shape"):
        detector.detect(cfg())

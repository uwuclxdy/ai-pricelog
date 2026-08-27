from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import watsonx_page as detector
from ai_pricelog.scrapers import watsonx_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://www.ibm.com/products/watsonx-ai/pricing"
FIXTURE = Path(__file__).parent / "fixtures" / "watsonx_page" / "pricing.html"

EXPECTED_IDS = [
    "granite-4h-small",
    "granite-8b-code-instruct",
    "granite-guardian-3-8b",
    "llama-4-maverick-17b-128e-instruct-fp8",
    "llama-3-3-70b-instruct",
    "llama-3-2-11b-vision-instruct",
    "llama-guard-3-11b-vision",
    "mistral-large-2512",
    "mistral-medium-2505",
    "mistral-small-3-1-24b-instruct-2503",
    "gpt-oss-120b",
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="watsonx",
        provider="IBM",
        detector="watsonx_page",
        detector_url=PAGE_URL,
        scraper="watsonx_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


def test_detect_priced_models(monkeypatch):
    # unpriced rows ("Not available") are skipped; ids follow page order
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_scrape_granite_4h_small(monkeypatch):
    # two-amount cell, input then output; first-party page reads
    # USD 0.0636 input / USD 0.265 output per 1M tokens
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "granite-4h-small")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.0636 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.265 / 1e6)
    assert pricing.cache_read_cost_per_token is None
    assert pricing.mode == "chat"


def test_scrape_llama_4_maverick_fp8(monkeypatch):
    # first-party page reads USD 0.371 input / USD 1.484 output per 1M tokens
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "llama-4-maverick-17b-128e-instruct-fp8")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.371 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(1.484 / 1e6)


def test_scrape_single_amount_bills_both_directions(monkeypatch):
    # the watsonx single-rate convention: USD 0.636 per 1M tokens both ways
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "granite-8b-code-instruct")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.636 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.636 / 1e6)


def test_scrape_mistral_medium_2505(monkeypatch):
    # the page spells "USD 9.5per 1M tokens output" (missing space); pinned to
    # the first-party USD 3.18 input / USD 9.5 output per 1M tokens
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "mistral-medium-2505")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.18 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(9.5 / 1e6)


def test_scrape_not_available_returns_none(monkeypatch):
    # llama-3-1-8b is on the page, its pay-as-you-go cell reads "Not available"
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "llama-3-1-8b") is None


def test_scrape_unknown_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "gpt-99") is None


def test_malformed_amount_count_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<c4d-pricing-table>"
            "<c4d-pricing-table-head><c4d-pricing-table-header-row>"
            "<c4d-pricing-table-header-cell>Model Name</c4d-pricing-table-header-cell>"
            "<c4d-pricing-table-header-cell>Model Provider</c4d-pricing-table-header-cell>"
            "<c4d-pricing-table-header-cell>Pay as you go</c4d-pricing-table-header-cell>"
            "</c4d-pricing-table-header-row></c4d-pricing-table-head>"
            "<c4d-pricing-table-body><c4d-pricing-table-row>"
            "<c4d-pricing-table-header-cell>Granite 4H Small</c4d-pricing-table-header-cell>"
            "<c4d-pricing-table-cell>IBM</c4d-pricing-table-cell>"
            "<c4d-pricing-table-cell>USD 1.00 per 1M tokens input USD 2.00 per 1M tokens"
            " output USD 3.00</c4d-pricing-table-cell>"
            "</c4d-pricing-table-row></c4d-pricing-table-body>"
            "</c4d-pricing-table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="3 amounts, want 1 or 2"):
        scraper.scrape(cfg(), "granite-4h-small")


def test_missing_table_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<c4d-pricing-table>"
            "<c4d-pricing-table-head><c4d-pricing-table-header-row>"
            "<c4d-pricing-table-header-cell>Model Name</c4d-pricing-table-header-cell>"
            "<c4d-pricing-table-header-cell>Pay as you go</c4d-pricing-table-header-cell>"
            "</c4d-pricing-table-header-row></c4d-pricing-table-head>"
            "</c4d-pricing-table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="no per-token model table"):
        scraper.scrape(cfg(), "granite-4h-small")


def test_detect_no_priced_rows_raises(monkeypatch):
    # a table where every pay-as-you-go cell reads "Not available" prices
    # nothing; empty detection is a parse failure, never a quiet empty run
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<c4d-pricing-table>"
            "<c4d-pricing-table-head><c4d-pricing-table-header-row>"
            "<c4d-pricing-table-header-cell>Model Name</c4d-pricing-table-header-cell>"
            "<c4d-pricing-table-header-cell>Model Provider</c4d-pricing-table-header-cell>"
            "<c4d-pricing-table-header-cell>Pay as you go</c4d-pricing-table-header-cell>"
            "</c4d-pricing-table-header-row></c4d-pricing-table-head>"
            "<c4d-pricing-table-body><c4d-pricing-table-row>"
            "<c4d-pricing-table-header-cell>Granite 4H Small</c4d-pricing-table-header-cell>"
            "<c4d-pricing-table-cell>IBM</c4d-pricing-table-cell>"
            "<c4d-pricing-table-cell>Not available</c4d-pricing-table-cell>"
            "</c4d-pricing-table-row></c4d-pricing-table-body>"
            "</c4d-pricing-table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="no model ids"):
        detector.detect(cfg())


def test_detect_strips_new_suffix(monkeypatch):
    # model names suffixed "New" normalize to the base id; no fixture row
    # prices a "New" model, so the suffix path is pinned synthetically
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<c4d-pricing-table>"
            "<c4d-pricing-table-head><c4d-pricing-table-header-row>"
            "<c4d-pricing-table-header-cell>Model Name</c4d-pricing-table-header-cell>"
            "<c4d-pricing-table-header-cell>Model Provider</c4d-pricing-table-header-cell>"
            "<c4d-pricing-table-header-cell>Pay as you go</c4d-pricing-table-header-cell>"
            "</c4d-pricing-table-header-row></c4d-pricing-table-head>"
            "<c4d-pricing-table-body><c4d-pricing-table-row>"
            "<c4d-pricing-table-header-cell>Granite 4H Small New</c4d-pricing-table-header-cell>"
            "<c4d-pricing-table-cell>IBM</c4d-pricing-table-cell>"
            "<c4d-pricing-table-cell>USD 0.0636 per 1M tokens input USD 0.265 per 1M"
            " tokens output</c4d-pricing-table-cell>"
            "</c4d-pricing-table-row></c4d-pricing-table-body>"
            "</c4d-pricing-table>",
            "html.parser",
        ),
    )
    assert detector.detect(cfg()) == ["granite-4h-small"]


def test_detect_missing_table_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<c4d-pricing-table>"
            "<c4d-pricing-table-head><c4d-pricing-table-header-row>"
            "<c4d-pricing-table-header-cell>Use case</c4d-pricing-table-header-cell>"
            "</c4d-pricing-table-header-row></c4d-pricing-table-head>"
            "</c4d-pricing-table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="no per-token model table"):
        detector.detect(cfg())

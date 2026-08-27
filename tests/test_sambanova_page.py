from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import sambanova_page as detector
from ai_pricelog.scrapers import sambanova_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://cloud.sambanova.ai/pricing"
FIXTURE = Path(__file__).parent / "fixtures" / "sambanova_page" / "pricing.html"

EXPECTED_IDS = [
    "minimax-m2.7",
    "deepseek-v3.1",
    "deepseek-v3.2",
    "gemma-4-31b-it",
    "gpt-oss-120b",
    "meta-llama-3.3-70b-instruct",
    "minimax-m3",
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="sambanova",
        provider="SambaNova",
        detector="sambanova_page",
        detector_url=PAGE_URL,
        scraper="sambanova_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


def test_detect_models(monkeypatch):
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_scrape_minimax_m2_7(monkeypatch):
    # the one row with a cached rate, first-party page cells 0.06 / 0.60 / 2.40 USD
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "minimax-m2.7")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.60 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(2.40 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.06 / 1e6)
    assert pricing.mode == "chat"


def test_scrape_deepseek_v3_1(monkeypatch):
    # N/A cached cell, first-party page cells N/A / 3 / 4.50 USD
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "deepseek-v3.1")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.0 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(4.50 / 1e6)
    assert pricing.cache_read_cost_per_token is None


def test_scrape_meta_llama_3_3_70b(monkeypatch):
    # N/A cached cell, first-party page cells N/A / 0.60 / 1.20 USD
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "meta-llama-3.3-70b-instruct")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.60 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(1.20 / 1e6)
    assert pricing.cache_read_cost_per_token is None


def test_scrape_unknown_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "deepseek-v4-pro") is None


def test_scrape_malformed_input_cell_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>Model</th><th>Cached Input Tokens</th>"
            "<th>Input (per 1M tokens)</th><th>Output (per 1M tokens)</th></tr>"
            "<tr><td>MiniMax-M2.7</td><td>N/A</td><td>FREE</td><td>2.40 USD</td></tr>"
            "</table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="no per-1M amount"):
        scraper.scrape(cfg(), "minimax-m2.7")


def test_scrape_malformed_cached_cell_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>Model</th><th>Cached Input Tokens</th>"
            "<th>Input (per 1M tokens)</th><th>Output (per 1M tokens)</th></tr>"
            "<tr><td>MiniMax-M2.7</td><td>soon</td><td>0.60 USD</td><td>2.40 USD</td></tr>"
            "</table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="unreadable cached-input cell"):
        scraper.scrape(cfg(), "minimax-m2.7")


def test_scrape_malformed_output_cell_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>Model</th><th>Cached Input Tokens</th>"
            "<th>Input (per 1M tokens)</th><th>Output (per 1M tokens)</th></tr>"
            "<tr><td>MiniMax-M2.7</td><td>N/A</td><td>0.60 USD</td><td>FREE</td></tr>"
            "</table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="no per-1M amount"):
        scraper.scrape(cfg(), "minimax-m2.7")


def test_scrape_short_row_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>Model</th><th>Cached Input Tokens</th>"
            "<th>Input (per 1M tokens)</th><th>Output (per 1M tokens)</th></tr>"
            "<tr><td>MiniMax-M2.7</td><td>N/A</td><td>0.60 USD</td></tr></table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="3 cells, want 4"):
        scraper.scrape(cfg(), "minimax-m2.7")


def test_detect_no_model_rows_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>Model</th><th>Cached Input Tokens</th>"
            "<th>Input (per 1M tokens)</th><th>Output (per 1M tokens)</th></tr></table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="no model ids"):
        detector.detect(cfg())


def test_scrape_missing_table_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>Base Model</th><th>LoRA SFT</th></tr></table>", "html.parser"
        ),
    )
    with pytest.raises(FetchError, match="no pricing table"):
        scraper.scrape(cfg(), "minimax-m2.7")


def test_detect_missing_table_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>Model</th><th>Price</th></tr></table>", "html.parser"
        ),
    )
    with pytest.raises(FetchError, match="no pricing table"):
        detector.detect(cfg())

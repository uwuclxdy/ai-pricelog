from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import fireworks_page as detector
from ai_pricelog.scrapers import fireworks_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://docs.fireworks.ai/serverless/pricing"
FIXTURE = Path(__file__).parent / "fixtures" / "fireworks_page" / "pricing.html"

EXPECTED_IDS = [
    "kimi-k3",
    "kimi-k3-fast",
    "kimi-k3-us",
    "kimi-k2.7-code",
    "kimi-k2.7-code-fast",
    "kimi-k2.6",
    "kimi-k2.6-fast",
    "deepseek-v4-pro",
    "deepseek-v4-pro-0813",
    "deepseek-v4-flash-0731",
    "glm-5.2",
    "glm-5.2-fast",
    "glm-5.2-fast-us",
    "qwen-3.7-plus",
    "qwen-3.8-max",
    "minimax-m3",
    "minimax-m2.7",
    "openai-gpt-oss-120b",
    "openai-gpt-oss-20b",
    "muse-glimmer-30b",
    "nvidia-nemotron-3.5-lightning-30b-a3b",
    "nvidia-nemotron-3-ultra-preview",
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="fireworks",
        provider="Fireworks",
        detector="fireworks_page",
        detector_url=PAGE_URL,
        scraper="fireworks_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


def test_detect_serverless_models(monkeypatch):
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_scrape_kimi_k3(monkeypatch):
    # cell order input / cached-input / output, verified against the
    # first-party kimi-k3 rate 3.0 / 0.3 / 15.0
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.0 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(15.0 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.3 / 1e6)
    assert pricing.mode == "chat"


def test_scrape_fast_sku_standard_tier(monkeypatch):
    # fast skus price only in the Standard column; the "—" Priority cell
    # stays unread
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "kimi-k3-fast")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(4.5 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(22.5 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.45 / 1e6)


def test_scrape_shared_api_id_skus(monkeypatch):
    # Kimi K3, Kimi K3 Fast, and Kimi K3 US share one api id but price
    # separately; the display-name ids keep them apart
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "kimi-k3-us")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.3 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(16.5 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.33 / 1e6)


def test_scrape_unknown_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "kimi-k9") is None


def test_malformed_cell_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>Model</th><th>Standard</th><th>Priority</th></tr>"
            "<tr><td>Kimi K3</td><td>$3.00 / $15.00</td><td>—</td></tr></table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="2 amounts, want 3"):
        scraper.scrape(cfg(), "kimi-k3")


def test_missing_table_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>Base Model</th><th>LoRA SFT</th></tr></table>", "html.parser"
        ),
    )
    with pytest.raises(FetchError, match="no serverless pricing table"):
        scraper.scrape(cfg(), "kimi-k3")


def test_detect_missing_table_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>Model</th><th>Price</th></tr></table>", "html.parser"
        ),
    )
    with pytest.raises(FetchError, match="no serverless pricing table"):
        detector.detect(cfg())

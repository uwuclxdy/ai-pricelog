from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import baseten_page as detector
from ai_pricelog.scrapers import baseten_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://www.baseten.co/pricing"
FIXTURE = Path(__file__).parent / "fixtures" / "baseten_page" / "pricing.html"

EXPECTED_IDS = [
    "glm-53-flash",
    "glm-52",
    "glm-52-fast",
    "glm-4-7",
    "deepseek-v4-pro-0813",
    "deepseek-v4",
    "deepseek-v4-flash-0731",
    "kimi-k3",
    "kimi-k26",
    "kimi-k27-code",
    "inkling-small",
    "inkling",
    "nvidia-nemotron-ultra",
    "gpt-oss-120b",
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="baseten",
        provider="Baseten",
        detector="baseten_page",
        detector_url=PAGE_URL,
        scraper="baseten_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


def test_detect_models(monkeypatch):
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_scrape_glm_53_flash(monkeypatch):
    # column order Model | Input | Cache Input | Output from the page's own
    # server-rendered header; checked against the first-party GLM-5.3-Flash
    # list rates on docs.z.ai (input 0.15 / output 0.50 per 1M tokens)
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "glm-53-flash")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.15 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.50 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.03 / 1e6)
    assert pricing.mode == "chat"


def test_scrape_nvidia_nemotron_3_ultra(monkeypatch):
    # first-party: NVIDIA quotes Nemotron 3 Ultra at 0.60 in / 2.40 out per 1M
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "nvidia-nemotron-ultra")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.60 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(2.40 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.12 / 1e6)


def test_scrape_kimi_k3(monkeypatch):
    # matches the kimi-k3 rate pinned in the fireworks tests against the
    # first-party source (3.0 / 0.3 / 15.0 per 1M)
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.00 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(15.00 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.30 / 1e6)


def test_scrape_model_without_cache_rate(monkeypatch):
    # gpt-oss-120b renders "-" in the Cache Input column: no cache rate
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "gpt-oss-120b")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.10 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.50 / 1e6)
    assert pricing.cache_read_cost_per_token is None


def test_scrape_unknown_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "glm-99") is None


_ROW_HTML = (
    "<div>"
    '<div class="grid">'
    "<div>Model</div><div>Input</div><div>Cache Input</div><div>Output</div>"
    "</div>"
    '<div class="grid">'
    '<div><div class="hidden md:flex"><a href="/library/glm-53-flash/">'
    "GLM-5.3-Flash</a></div></div>"
    '<div><div class="hidden md:flex">{input_text}</div></div>'
    '<div><div class="hidden md:flex">$0.03</div></div>'
    '<div><div class="hidden md:flex">$0.50</div></div>'
    "</div>"
    "</div>"
)


def test_scrape_malformed_input_cell_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(_ROW_HTML.format(input_text="free"), "html.parser"),
    )
    with pytest.raises(FetchError, match="0 amounts, want 1"):
        scraper.scrape(cfg(), "glm-53-flash")


def test_scrape_malformed_row_raises(monkeypatch):
    html = (
        "<div>"
        '<div class="grid">'
        "<div>Model</div><div>Input</div><div>Cache Input</div><div>Output</div>"
        "</div>"
        '<div class="grid">'
        '<div><div class="hidden md:flex"><a href="/library/glm-53-flash/">'
        "GLM-5.3-Flash</a></div></div>"
        '<div><div class="hidden md:flex">$0.15</div></div>'
        '<div><div class="hidden md:flex">$0.50</div></div>'
        "</div>"
        "</div>"
    )
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(html, "html.parser"),
    )
    with pytest.raises(FetchError, match="3 cells, want 4"):
        scraper.scrape(cfg(), "glm-53-flash")


def test_scrape_missing_table_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup("<div><div>Model</div><div>Price</div></div>", "html.parser"),
    )
    with pytest.raises(FetchError, match="no Model APIs pricing table"):
        scraper.scrape(cfg(), "glm-53-flash")


def test_detect_missing_table_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup("<div><div>Model</div><div>Price</div></div>", "html.parser"),
    )
    with pytest.raises(FetchError, match="no Model APIs pricing table"):
        detector.detect(cfg())


def test_detect_row_without_library_link_raises(monkeypatch):
    html = (
        "<div>"
        '<div class="grid">'
        "<div>Model</div><div>Input</div><div>Cache Input</div><div>Output</div>"
        "</div>"
        '<div class="grid">'
        '<div><div class="hidden md:flex"><a href="/something/else/">'
        "GLM-5.3-Flash</a></div></div>"
        '<div><div class="hidden md:flex">$0.15</div></div>'
        '<div><div class="hidden md:flex">$0.03</div></div>'
        '<div><div class="hidden md:flex">$0.50</div></div>'
        "</div>"
        "</div>"
    )
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(html, "html.parser"),
    )
    with pytest.raises(FetchError, match="unexpected model link"):
        detector.detect(cfg())

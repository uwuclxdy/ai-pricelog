"""ai21 pricing pair tests, pinned against the saved live page."""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import ai21_page as detector
from ai_pricelog.scrapers import ai21_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://www.ai21.com/pricing"
FIXTURE = Path(__file__).parent / "fixtures" / "ai21_page" / "pricing.html"


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="ai21",
        provider="AI21",
        detector="ai21_page",
        detector_url=PAGE_URL,
        scraper="ai21_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


def cards_soup(*cards: str) -> BeautifulSoup:
    return BeautifulSoup(
        '<div class="block b-cards b-cards--type-models">' + "".join(cards) + "</div>",
        "html.parser",
    )


def card(title: str, footer: str) -> str:
    return (
        f'<div class="card"><div class="card__body"><h3 class="card__title">{title}</h3>'
        f'<div class="card__text">a model</div><div class="card__footer">{footer}</div>'
        f"</div></div>"
    )


def test_detect_ids(monkeypatch):
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    assert detector.detect(cfg()) == ["jamba-mini", "jamba-large"]


def test_scrape_jamba_mini(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "jamba-mini")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.2 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.4 / 1e6)
    assert pricing.cache_read_cost_per_token is None
    assert pricing.mode == "chat"


def test_scrape_jamba_large(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "jamba-large")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(2 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(8 / 1e6)


def test_scrape_unknown_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "jamba-1.5-mini") is None


def test_scrape_card_without_price_line_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: cards_soup(card("Jamba Mini", "efficient and lightweight")),
    )
    with pytest.raises(FetchError, match="0 price lines, want 1"):
        scraper.scrape(cfg(), "jamba-mini")


def test_detect_card_without_footer_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: cards_soup(
            '<div class="card"><div class="card__body">'
            '<h3 class="card__title">Jamba Mini</h3></div></div>'
        ),
    )
    with pytest.raises(FetchError, match="without a title or footer"):
        detector.detect(cfg())


def test_detect_no_cards_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup("<html><body></body></html>", "html.parser"),
    )
    with pytest.raises(FetchError, match="no foundation model cards"):
        detector.detect(cfg())

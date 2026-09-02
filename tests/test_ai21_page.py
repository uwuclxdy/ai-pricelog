"""ai21 pricing pair tests, pinned against the saved live page."""

from __future__ import annotations

import logging
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


def title_only_card(title: str) -> str:
    return (
        '<div class="card"><div class="card__body">'
        f'<h3 class="card__title">{title}</h3></div></div>'
    )


def serve(monkeypatch: pytest.MonkeyPatch, soup: BeautifulSoup, module=detector) -> None:
    monkeypatch.setattr(module, "fetch_soup", lambda url, headers=None: soup)


def test_detect_ids(monkeypatch):
    serve(monkeypatch, load_soup())
    assert detector.detect(cfg()) == ["jamba-mini", "jamba-large"]


def test_detect_fetches_with_browser_ua(monkeypatch):
    seen: dict[str, object] = {}

    def fake(url, headers=None):
        seen["headers"] = headers
        return load_soup()

    monkeypatch.setattr(detector, "fetch_soup", fake)
    detector.detect(cfg())
    assert seen["headers"] == detector._UA


def test_scrape_jamba_mini(monkeypatch):
    serve(monkeypatch, load_soup(), scraper)
    pricing = scraper.scrape(cfg(), "jamba-mini")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.2 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.4 / 1e6)
    assert pricing.cache_read_cost_per_token is None
    assert pricing.mode == "chat"


def test_scrape_jamba_large(monkeypatch):
    serve(monkeypatch, load_soup(), scraper)
    pricing = scraper.scrape(cfg(), "jamba-large")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(2 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(8 / 1e6)


def test_scrape_unknown_model_returns_none(monkeypatch):
    serve(monkeypatch, load_soup(), scraper)
    assert scraper.scrape(cfg(), "jamba-1.5-mini") is None


def test_scrape_card_without_price_line_raises(monkeypatch):
    serve(monkeypatch, cards_soup(card("Jamba Mini", "efficient and lightweight")), scraper)
    with pytest.raises(FetchError, match="0 price lines, want 1"):
        scraper.scrape(cfg(), "jamba-mini")


def test_scrape_matched_card_without_footer_raises(monkeypatch):
    serve(monkeypatch, cards_soup(title_only_card("Jamba Mini")), scraper)
    with pytest.raises(FetchError, match="without a footer"):
        scraper.scrape(cfg(), "jamba-mini")


def test_scrape_skips_unrelated_out_of_charset_cards(monkeypatch):
    # an unrelated card whose title cannot slug must not block the chosen
    # model (detect already reported it)
    soup = cards_soup(
        card("★", "efficient and lightweight"),
        card("Jamba Large", "$2 / 1M input tokens$8 / 1M output tokens"),
    )
    serve(monkeypatch, soup, scraper)
    pricing = scraper.scrape(cfg(), "jamba-large")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(2 / 1e6)


def test_detect_card_without_footer_skips(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    soup = cards_soup(
        title_only_card("Jamba Mini"),
        card("Jamba Large", "$2 / 1M input tokens$8 / 1M output tokens"),
    )
    serve(monkeypatch, soup)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["jamba-large"]
    assert "detect skip for ai21" in caplog.text


def test_detect_out_of_charset_title_skips(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    soup = cards_soup(
        card("★", "$0.2 / 1M input tokens$0.4 / 1M output tokens"),
        card("Jamba Large", "$2 / 1M input tokens$8 / 1M output tokens"),
    )
    serve(monkeypatch, soup)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["jamba-large"]
    assert "outside the id charset" in caplog.text


def test_detect_all_cards_malformed_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    serve(monkeypatch, cards_soup(title_only_card("Jamba Mini")))
    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(FetchError, match="no foundation model cards"),
    ):
        detector.detect(cfg())
    assert "detect skip for ai21" in caplog.text


def test_detect_no_cards_raises(monkeypatch):
    serve(monkeypatch, BeautifulSoup("<html><body></body></html>", "html.parser"))
    with pytest.raises(FetchError, match="no foundation model cards"):
        detector.detect(cfg())

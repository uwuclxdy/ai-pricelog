from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import avian_page as detector
from ai_pricelog.scrapers import avian_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://www.avian.io/pricing"
FIXTURE = Path(__file__).parent / "fixtures" / "avian_page" / "pricing.html"

EXPECTED_IDS = [
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "deepseek-v4-pro-0813",
    "deepseek-v3.2-legacy",
    "minimax-m2.5",
    "glm-4.7",
    "glm-5",
    "glm-5.1",
    "glm-5.2",
    "kimi-k2.5",
    "kimi-k2.6",
    "mimo-v2.5-small",
    "mimo-v2.5-pro",
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="avian",
        provider="Avian",
        detector="avian_page",
        detector_url=PAGE_URL,
        scraper="avian_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


def model_card(label: str, meta: str, **prices: str | None) -> str:
    """one av-model-card; a price block with a None value is omitted."""
    blocks = "".join(
        f'<div class="av-mp"><div class="av-mp-label">{name}</div>'
        f'<div class="av-mp-val">{value}</div></div>'
        for name, value in prices.items()
        if value is not None
    )
    return (
        f'<div class="av-model-card">'
        f'<div class="av-model-label">{label}</div>'
        f'<div class="av-model-prices">{blocks}</div>'
        f'<div class="av-model-meta">{meta}</div>'
        f"</div>"
    )


def synthetic_page(*cards: str) -> BeautifulSoup:
    return BeautifulSoup(f'<div id="avModelGrid">{"".join(cards)}</div>', "html.parser")


@pytest.fixture
def serve_soup(monkeypatch: pytest.MonkeyPatch):
    def feed(url: str) -> BeautifulSoup:
        return load_soup()

    monkeypatch.setattr(detector, "fetch_soup", feed)
    monkeypatch.setattr(scraper, "fetch_soup", feed)


def test_detect_returns_all_cards_in_page_order(serve_soup):
    # page order crosses the vendor boundaries: deepseek (0-3), minimax (4),
    # zhipu (5-8), moonshot (9-10), xiaomi (11-12)
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_detect_excludes_filter_tabs_and_dedicated_note(serve_soup):
    # the filter tab labels and the Dedicated Deployments note live in the same
    # section as the grid; neither may leak into the id list
    ids = detector.detect(cfg())
    for leaked in ("deepseek", "moonshot", "zhipu", "minimax", "xiaomi", "dedicated-deployments"):
        assert leaked not in ids


def test_detect_card_outside_grid_is_ignored(monkeypatch):
    priced = model_card("MiniMax M2.5", "196K context", Input="$1", Output="$2")
    page = (
        f'<div id="avModelGrid">{priced}</div>'
        # a dedicated-deployments-style card outside the grid has no per-token prices
        f'<div class="av-model-card"><div class="av-model-label">Dedicated Foo</div></div>'
    )
    monkeypatch.setattr(detector, "fetch_soup", lambda url: BeautifulSoup(page, "html.parser"))
    assert detector.detect(cfg()) == ["minimax-m2.5"]


def test_detect_slug_rule(monkeypatch):
    # the new-model entry id is the lowercase-hyphen slug of the page spelling:
    # lowercase, dots kept, other non-alphanumeric runs -> "-", edges trimmed
    page = synthetic_page(
        model_card("MiMo-V2.5 Small", "1M context", Input="$1", Output="$2"),
        model_card("DeepSeek V3.2 (Legacy)", "163K context", Input="$1", Output="$2"),
        model_card("GLM-4.7", "202K context", Input="$1", Output="$2"),
    )
    monkeypatch.setattr(detector, "fetch_soup", lambda url: page)
    assert detector.detect(cfg()) == ["mimo-v2.5-small", "deepseek-v3.2-legacy", "glm-4.7"]


def test_detect_vendor_group_boundary(monkeypatch):
    # adjacent cards from different vendor groups both detect, each into its
    # own id: nothing bleeds across the group boundary
    page = synthetic_page(
        model_card("Kimi K2.5", "262K context", Input="$1", Output="$2"),
        model_card("MiMo-V2.5 Pro", "1M context", Input="$1", Output="$2"),
    )
    monkeypatch.setattr(detector, "fetch_soup", lambda url: page)
    assert detector.detect(cfg()) == ["kimi-k2.5", "mimo-v2.5-pro"]


def test_detect_no_grid_raises(monkeypatch):
    monkeypatch.setattr(
        detector, "fetch_soup", lambda url: BeautifulSoup("<div>nothing</div>", "html.parser")
    )
    with pytest.raises(FetchError, match="model grid"):
        detector.detect(cfg())


def test_detect_grid_without_cards_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            '<div id="avModelGrid"><div class="av-filter-tab">MiniMax</div></div>', "html.parser"
        ),
    )
    with pytest.raises(FetchError, match="model cards"):
        detector.detect(cfg())


def test_fetch_error_propagates(monkeypatch):
    def boom(url):
        raise FetchError(f"fetch failed for {url}")

    monkeypatch.setattr(detector, "fetch_soup", boom)
    with pytest.raises(FetchError, match=PAGE_URL):
        detector.detect(cfg())


def test_scrape_exact_prices_with_cache(serve_soup):
    pricing = scraper.scrape(cfg(), "mimo-v2.5-small")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.2 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.4 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.05 / 1e6)
    assert pricing.mode == "chat"
    assert pricing.max_tokens_in == 1_000_000


def test_scrape_max_tokens_in_from_context(serve_soup):
    # "262K context" -> 262000; K = 1000, M = 1000000 (the page abbreviates)
    pricing = scraper.scrape(cfg(), "kimi-k2.5")
    assert pricing is not None
    assert pricing.max_tokens_in == 262_000
    pricing = scraper.scrape(cfg(), "deepseek-v3.2-legacy")
    assert pricing is not None
    assert pricing.max_tokens_in == 163_000


def test_scrape_model_without_cache(monkeypatch):
    # a card with no Cache block still prices the model; cache stays None
    page = synthetic_page(model_card("MiniMax M2.5", "196K context", Input="$0.27", Output="$1.08"))
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: page)
    pricing = scraper.scrape(cfg(), "minimax-m2.5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.27 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(1.08 / 1e6)
    assert pricing.cache_read_cost_per_token is None
    assert pricing.max_tokens_in == 196_000


def test_scrape_zero_cache_keeps_field_none(monkeypatch):
    # a $0 cache rate is not a usable per-token rate; the field stays None
    page = synthetic_page(
        model_card("MiniMax M2.5", "196K context", Input="$0.27", Output="$1.08", Cache="$0")
    )
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: page)
    pricing = scraper.scrape(cfg(), "minimax-m2.5")
    assert pricing is not None
    assert pricing.cache_read_cost_per_token is None


def test_scrape_matches_page_spelling(serve_soup):
    # the page spells the id "MiMo-V2.5 Small"; the slug must match it too
    pricing = scraper.scrape(cfg(), "MiMo-V2.5 Small")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.2 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.4 / 1e6)


def test_scrape_unknown_model_returns_none(serve_soup):
    assert scraper.scrape(cfg(), "llama-4") is None


def test_scrape_unpriced_row_returns_none(monkeypatch):
    # a card whose input cell carries no dollar amount is not priced yet
    page = synthetic_page(
        model_card("Kimi K2.5", "262K context", Input="-", Output="$2.2", Cache="$0.225")
    )
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: page)
    assert scraper.scrape(cfg(), "kimi-k2.5") is None


def test_scrape_zero_input_returns_none(monkeypatch):
    # a $0 input rate is not a usable rate
    page = synthetic_page(
        model_card("Kimi K2.5", "262K context", Input="$0", Output="$2.2", Cache="$0.225")
    )
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: page)
    assert scraper.scrape(cfg(), "kimi-k2.5") is None


def test_scrape_no_grid_raises(monkeypatch):
    monkeypatch.setattr(
        scraper, "fetch_soup", lambda url: BeautifulSoup("<div>nothing</div>", "html.parser")
    )
    with pytest.raises(FetchError, match="model grid"):
        scraper.scrape(cfg(), "mimo-v2.5-small")

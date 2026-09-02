from __future__ import annotations

import logging
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog import web
from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import cohere_page
from ai_pricelog.pricing import Pricing
from ai_pricelog.scrapers import cohere_page as cohere_scraper

FIXTURES = Path(__file__).parent / "fixtures" / "cohere_page"
PAGE_URL = "https://cohere.com/pricing"

EXPECTED_IDS = [
    "command-a-plus",
    "command-r",
    "command-r7b",
    "embed-4",
    "north-mini-code",
    "embed-4-small",
    "embed-4-medium",
    "rerank-3.5-medium",
    "rerank-4-fast-medium",
    "rerank-4-pro-medium",
    "rerank-4-pro-large",
    "command",
    "command-light",
    "command-r-03-2024",
    "command-r-plus-04-2024",
    "command-r-plus-08-2024",
]

TABLE_SNIPPET = (
    '<div class="grid justify-start [grid-template-columns:repeat(4,minmax(150px,1fr))]">'
    "<div><p>Model</p></div>"
    "<div><p>Performance Tier</p></div>"
    "<div><p>Hourly rate per instance</p></div>"
    "<div><p>Monthly rate per instance</p></div>"
    "</div>"
    '<div class="grid justify-start [grid-template-columns:repeat(4,minmax(150px,1fr))]">'
    "<div><p><strong>Embed 4</strong></p></div>"
    "<div><p>Small</p></div>"
    "<div><p>$4.00</p></div>"
    "<div><p>$2,500</p></div>"
    "</div>"
    '<div class="grid justify-start [grid-template-columns:repeat(4,minmax(150px,1fr))]">'
    "<div><p><strong>Rerank 4 Pro</strong></p></div>"
    "<div><p>Large</p></div>"
    "<div><p>$10.00</p></div>"
    "<div><p>$6,500</p></div>"
    "</div>"
)

PROSE_SNIPPET = (
    "<ul>"
    "<li>Command pricing is $1.00/1M tokens for input and $2.00/1M tokens for output</li>"
    "<li>Command R+ 08-2024 pricing is $2.50/1M tokens for input and $10.00/1M tokens"
    " for output</li>"
    "</ul>"
)

# the model cards as they sit in the page's __next_f flight payload: one
# json object per card, json-escaped inside the script string
CARD_SNIPPET = (
    '<script>self.__next_f.push([1,"'
    r"{\"_type\":\"pricingGroup\",\"models\":["
    r"{\"_key\":\"a\",\"_type\":\"model\",\"modelName\":\"Command R\",\"per\":\"1M tokens\","
    r"\"pricings\":[{\"_key\":\"p\",\"_type\":\"pricing\",\"inputLabel\":\"Input\","
    r"\"inputPrice\":0.15,\"outputLabel\":\"Output\",\"outputPrice\":0.6}]},"
    r"{\"_key\":\"b\",\"_type\":\"model\",\"modelName\":\"Command R7B\",\"per\":\"1M tokens\","
    r"\"pricings\":[{\"_key\":\"q\",\"_type\":\"pricing\",\"inputLabel\":\"Input\","
    r"\"inputPrice\":0.0375,\"outputLabel\":\"Output\",\"outputPrice\":0.15}]},"
    r"{\"_key\":\"c\",\"_type\":\"model\",\"modelName\":\"Embed 4\",\"per\":\"1M tokens\","
    r"\"pricings\":[{\"_key\":\"r\",\"_type\":\"pricing\",\"inputLabel\":\"Cost\","
    r"\"inputPrice\":0.12,\"outputLabel\":\"Image cost\",\"outputPrice\":0.47}]}"
    r'"]}'
    '"]);</script>'
)

# cards of every seed decision: no pricings list (North), a free 0/0 card
# (Command A+), a zero-output card (Some Model), and a one-sided card
# billing per 1K searches (Rerank 4 Fast). free is a price: the 0/0 and
# zero-output cards seed, the rest stay excluded.
UNPRICED_CARD_SNIPPET = (
    '<script>self.__next_f.push([1,"'
    r"{\"_type\":\"pricingGroup\",\"models\":["
    r"{\"_key\":\"a\",\"_type\":\"model\",\"modelName\":\"North\",\"per\":\"1M tokens\"},"
    r"{\"_key\":\"b\",\"_type\":\"model\",\"modelName\":\"Command A+\",\"per\":\"Free\","
    r"\"pricings\":[{\"_key\":\"p\",\"_type\":\"pricing\",\"inputLabel\":\"API key\","
    r"\"inputPrice\":0,\"outputLabel\":\"Model download\",\"outputPrice\":0}]},"
    r"{\"_key\":\"c\",\"_type\":\"model\",\"modelName\":\"Some Model\",\"per\":\"1M tokens\","
    r"\"pricings\":[{\"_key\":\"q\",\"_type\":\"pricing\",\"inputLabel\":\"Input\","
    r"\"inputPrice\":0.5,\"outputLabel\":\"Output\",\"outputPrice\":0}]},"
    r"{\"_key\":\"d\",\"_type\":\"model\",\"modelName\":\"Rerank 4 Fast\",\"per\":\"1M tokens\","
    r"\"pricings\":[{\"_key\":\"r\",\"_type\":\"pricing\",\"inputLabel\":\"Cost\","
    r"\"inputPrice\":2,\"outputLabel\":\"Output\",\"overridePer\":\"1K searches\"}]}"
    r'"]}'
    '"]);</script>'
)


def make_cfg(url: str = PAGE_URL) -> ProviderCfg:
    return ProviderCfg(
        key="cohere",
        provider="Cohere",
        detector="cohere_page",
        detector_url=url,
        scraper="cohere_page",
        scraper_url=url,
    )


def serve_html(monkeypatch: pytest.MonkeyPatch, html: str) -> None:
    # the scraper shares the detector's cached _page parse, so the single
    # fetch seam is the detector module's fetch_soup.
    monkeypatch.setattr(cohere_page, "fetch_soup", lambda url: BeautifulSoup(html, "html.parser"))


@pytest.fixture(autouse=True)
def fresh_page_cache():
    # _page is cached per url for the pipeline's detect-then-scrape pass; each
    # test serves its own page content, so the cache must not leak across tests.
    cohere_page._page.cache_clear()
    yield
    cohere_page._page.cache_clear()


@pytest.fixture
def live_page(monkeypatch: pytest.MonkeyPatch) -> None:
    serve_html(monkeypatch, (FIXTURES / "pricing.html").read_text(encoding="utf-8"))


def test_detect_lists_models_in_page_order(live_page):
    # model cards first, then vault rows, then the faq prose
    assert cohere_page.detect(make_cfg()) == EXPECTED_IDS


def test_detect_excludes_unpriced_content(live_page):
    # cards without a pricings list, one-sided per-search cards, and the aya
    # research faq answer (not a "pricing is" sentence): none of them may
    # leak into detection
    ids = cohere_page.detect(make_cfg())
    for excluded in (
        "north",
        "compass",
        "transcribe",
        "rerank-4-fast",
        "rerank-4-pro",
        "aya-expanse",
    ):
        assert excluded not in ids


def test_detect_cards_only(monkeypatch):
    serve_html(monkeypatch, CARD_SNIPPET)
    assert cohere_page.detect(make_cfg()) == ["command-r", "command-r7b", "embed-4"]


def test_detect_free_and_zero_output_cards_seed(monkeypatch):
    # free is a price: the 0/0 card and the zero-output card seed; the
    # pricings-less and one-sided cards stay out
    serve_html(monkeypatch, UNPRICED_CARD_SNIPPET)
    assert cohere_page.detect(make_cfg()) == ["command-a-plus", "some-model"]


def test_scrape_free_card_prices_zero(monkeypatch):
    # the free card's row lands with 0.0 fields, never None
    serve_html(monkeypatch, UNPRICED_CARD_SNIPPET)
    pricing = cohere_scraper.scrape(make_cfg(), "command-a-plus")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.0
    assert pricing.output_cost_per_token == 0.0


def test_detect_all_cards_unpriced_raises(monkeypatch):
    # a page where no card seeds is a parse failure, and the parse failure
    # is loud
    serve_html(
        monkeypatch,
        '<script>self.__next_f.push([1,"'
        r"{\"_type\":\"pricingGroup\",\"models\":["
        r"{\"_key\":\"a\",\"_type\":\"model\",\"modelName\":\"North\",\"per\":\"1M tokens\"}]}"
        '"]);</script>',
    )
    with pytest.raises(web.FetchError, match="no priced models"):
        cohere_page.detect(make_cfg())


def test_detect_malformed_card_skips(monkeypatch, caplog):
    # a card without a modelName is additive drift: skipped with a
    # warning, the other cards still seed
    serve_html(
        monkeypatch,
        '<script>self.__next_f.push([1,"'
        r"{\"_type\":\"pricingGroup\",\"models\":["
        r"{\"_key\":\"a\",\"_type\":\"model\",\"highlightModel\":false},"
        r"{\"_key\":\"b\",\"_type\":\"model\",\"modelName\":\"Command R\",\"per\":\"1M tokens\","
        r"\"pricings\":[{\"_key\":\"p\",\"_type\":\"pricing\",\"inputLabel\":\"Input\","
        r"\"inputPrice\":0.15,\"outputLabel\":\"Output\",\"outputPrice\":0.6}]}"
        r'"]}'
        '"]);</script>',
    )
    with caplog.at_level(logging.WARNING):
        assert cohere_page.detect(make_cfg()) == ["command-r"]
    assert "detect skip for cohere" in caplog.text
    assert "malformed model card" in caplog.text


def test_detect_malformed_card_pricings_skips(monkeypatch, caplog):
    # a card whose pricings carry no input rate is additive drift: skipped
    # with a warning, the other cards still seed
    serve_html(
        monkeypatch,
        '<script>self.__next_f.push([1,"'
        r"{\"_type\":\"pricingGroup\",\"models\":["
        r"{\"_key\":\"a\",\"_type\":\"model\",\"modelName\":\"Command R\","
        r"\"pricings\":[{\"_type\":\"pricing\",\"outputLabel\":\"Output\",\"outputPrice\":0.6}]},"
        r"{\"_key\":\"b\",\"_type\":\"model\",\"modelName\":\"Command R7B\",\"per\":\"1M tokens\","
        r"\"pricings\":[{\"_key\":\"p\",\"_type\":\"pricing\",\"inputLabel\":\"Input\","
        r"\"inputPrice\":0.0375,\"outputLabel\":\"Output\",\"outputPrice\":0.15}]}"
        r'"]}'
        '"]);</script>',
    )
    with caplog.at_level(logging.WARNING):
        assert cohere_page.detect(make_cfg()) == ["command-r7b"]
    assert "detect skip for cohere" in caplog.text
    assert "malformed pricings" in caplog.text


def test_scrape_unrelated_malformed_card_does_not_block(monkeypatch):
    # a malformed card the scan passes over is additive drift detect
    # reported; the chosen model still scrapes
    serve_html(
        monkeypatch,
        '<script>self.__next_f.push([1,"'
        r"{\"_type\":\"pricingGroup\",\"models\":["
        r"{\"_key\":\"a\",\"_type\":\"model\",\"highlightModel\":false},"
        r"{\"_key\":\"b\",\"_type\":\"model\",\"modelName\":\"Command R\",\"per\":\"1M tokens\","
        r"\"pricings\":[{\"_key\":\"p\",\"_type\":\"pricing\",\"inputLabel\":\"Input\","
        r"\"inputPrice\":0.15,\"outputLabel\":\"Output\",\"outputPrice\":0.6}]}"
        r'"]}'
        '"]);</script>',
    )
    pricing = cohere_scraper.scrape(make_cfg(), "command-r")
    assert pricing == Pricing(0.15 / 1e6, 0.6 / 1e6, "chat")


def test_scrape_prose_model_command(live_page):
    pricing = cohere_scraper.scrape(make_cfg(), "command")
    assert pricing == Pricing(1e-6, 2e-6, "chat")
    assert pricing is not None
    assert pricing.max_tokens_in == pricing.max_tokens_out == 0
    assert pricing.cache_read_cost_per_token is None
    assert pricing.peak_input_cost_per_token is None
    assert pricing.peak_output_cost_per_token is None
    assert pricing.peak_windows == ()


def test_scrape_prose_model_command_light(live_page):
    pricing = cohere_scraper.scrape(make_cfg(), "command-light")
    assert pricing == Pricing(0.3 / 1e6, 0.6 / 1e6, "chat")


def test_scrape_dated_release_rates(live_page):
    cfg = make_cfg()
    assert cohere_scraper.scrape(cfg, "command-r-03-2024") == Pricing(0.5 / 1e6, 1.5 / 1e6, "chat")
    assert cohere_scraper.scrape(cfg, "command-r-plus-04-2024") == Pricing(3e-6, 15e-6, "chat")
    assert cohere_scraper.scrape(cfg, "command-r-plus-08-2024") == Pricing(2.5e-6, 10e-6, "chat")


def test_scrape_table_models_return_none(live_page):
    # the model vault table bills per instance (hourly/monthly), not per
    # token: no usable per-token rate until the page publishes one
    cfg = make_cfg()
    assert cohere_scraper.scrape(cfg, "embed-4-small") is None
    assert cohere_scraper.scrape(cfg, "rerank-4-pro-large") is None


def test_scrape_card_models(live_page):
    # the current model cards carry per-token rates, USD per 1M tokens
    cfg = make_cfg()
    assert cohere_scraper.scrape(cfg, "command-r") == Pricing(0.15 / 1e6, 0.6 / 1e6, "chat")
    assert cohere_scraper.scrape(cfg, "command-r7b") == Pricing(0.0375 / 1e6, 0.15 / 1e6, "chat")


def test_scrape_card_image_cost_is_not_output(live_page):
    # Embed 4's "Image cost" is a per-image rate, not an output token rate:
    # embedding models bill no output tokens, so the output price is 0
    pricing = cohere_scraper.scrape(make_cfg(), "embed-4")
    assert pricing == Pricing(0.12 / 1e6, 0.0, "chat")


def test_scrape_matches_page_spelling(live_page):
    # the page spells the id "Command"; the slug-normalized id must match too
    cfg = make_cfg()
    assert cohere_scraper.scrape(cfg, "Command") == Pricing(1e-6, 2e-6, "chat")
    assert cohere_scraper.scrape(cfg, "Command R") == Pricing(0.15 / 1e6, 0.6 / 1e6, "chat")
    assert cohere_scraper.scrape(cfg, "Embed 4 Small") is None


def test_scrape_unknown_model_returns_none(live_page):
    cfg = make_cfg()
    assert cohere_scraper.scrape(cfg, "north") is None
    assert cohere_scraper.scrape(cfg, "command-a") is None


def test_detect_table_only(monkeypatch):
    serve_html(monkeypatch, TABLE_SNIPPET)
    assert cohere_page.detect(make_cfg()) == ["embed-4-small", "rerank-4-pro-large"]


def test_detect_prose_only(monkeypatch):
    serve_html(monkeypatch, PROSE_SNIPPET)
    assert cohere_page.detect(make_cfg()) == ["command", "command-r-plus-08-2024"]


def test_detect_skips_malformed_prose(monkeypatch):
    # a sentence without the input amount is not a rate: skip it, keep the rest
    serve_html(
        monkeypatch,
        "<ul>"
        "<li>Command pricing is $1.00/1M tokens for input and $2.00/1M tokens for output</li>"
        "<li>Command-light pricing is $0.30/1M tokens for input and output</li>"
        "</ul>",
    )
    assert cohere_page.detect(make_cfg()) == ["command"]


def test_detect_malformed_table_row_skips(monkeypatch, caplog):
    # a vault row outside the four-cell shape is additive drift: skipped
    # with a warning, later rows still seed
    serve_html(
        monkeypatch,
        '<div class="grid justify-start [grid-template-columns:repeat(4,minmax(150px,1fr))]">'
        "<div><p>Model</p></div>"
        "<div><p>Performance Tier</p></div>"
        "<div><p>Hourly rate per instance</p></div>"
        "<div><p>Monthly rate per instance</p></div>"
        "</div>"
        '<div class="grid justify-start [grid-template-columns:repeat(4,minmax(150px,1fr))]">'
        "<div><p>Embed 4</p></div>"
        "<div><p>Small</p></div>"
        "<div><p>$4.00</p></div>"
        "</div>"
        '<div class="grid justify-start [grid-template-columns:repeat(4,minmax(150px,1fr))]">'
        "<div><p><strong>Rerank 4 Pro</strong></p></div>"
        "<div><p>Large</p></div>"
        "<div><p>$10.00</p></div>"
        "<div><p>$6,500</p></div>"
        "</div>",
    )
    with caplog.at_level(logging.WARNING):
        assert cohere_page.detect(make_cfg()) == ["rerank-4-pro-large"]
    assert "detect skip for cohere" in caplog.text
    assert "malformed model vault row" in caplog.text


def test_detect_folded_vault_header_matches(monkeypatch):
    # header wording drift (case) still matches after folding
    serve_html(
        monkeypatch,
        '<div class="grid justify-start [grid-template-columns:repeat(4,minmax(150px,1fr))]">'
        "<div><p>model</p></div>"
        "<div><p>performance tier</p></div>"
        "<div><p>HOURLY rate per instance</p></div>"
        "<div><p>Monthly rate per instance</p></div>"
        "</div>"
        '<div class="grid justify-start [grid-template-columns:repeat(4,minmax(150px,1fr))]">'
        "<div><p><strong>Rerank 4 Pro</strong></p></div>"
        "<div><p>Large</p></div>"
        "<div><p>$10.00</p></div>"
        "<div><p>$6,500</p></div>"
        "</div>",
    )
    assert cohere_page.detect(make_cfg()) == ["rerank-4-pro-large"]


def test_detect_raises_when_no_pricing_content(monkeypatch):
    serve_html(monkeypatch, "<html><body><p>nothing priced here</p></body></html>")
    with pytest.raises(web.FetchError, match="no priced models"):
        cohere_page.detect(make_cfg())


def test_scrape_raises_when_no_pricing_content(monkeypatch):
    serve_html(monkeypatch, "<html><body><p>nothing priced here</p></body></html>")
    with pytest.raises(web.FetchError, match="no priced models"):
        cohere_scraper.scrape(make_cfg(), "command")


def test_detect_propagates_fetch_error(monkeypatch):
    def boom(url: str):
        raise web.FetchError("boom")

    monkeypatch.setattr(cohere_page, "fetch_soup", boom)
    with pytest.raises(web.FetchError, match="boom"):
        cohere_page.detect(make_cfg())


def test_page_parsed_once_per_url(monkeypatch):
    fetches = {"count": 0}

    def counting_fetch(url: str):
        fetches["count"] += 1
        html = (FIXTURES / "pricing.html").read_text(encoding="utf-8")
        return BeautifulSoup(html, "html.parser")

    monkeypatch.setattr(cohere_page, "fetch_soup", counting_fetch)
    cfg = make_cfg("https://cohere.com/pricing/once")
    assert sorted(cohere_page.detect(cfg)) == sorted(EXPECTED_IDS)
    assert cohere_scraper.scrape(cfg, "command") is not None
    assert sorted(cohere_page.detect(cfg)) == sorted(EXPECTED_IDS)
    assert fetches["count"] == 1

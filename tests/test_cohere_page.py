from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from autopr_genai_prices import web
from autopr_genai_prices.config import ProviderCfg
from autopr_genai_prices.detectors import cohere_page
from autopr_genai_prices.pricing import Pricing
from autopr_genai_prices.scrapers import cohere_page as cohere_scraper

FIXTURES = Path(__file__).parent / "fixtures" / "cohere_page"
PAGE_URL = "https://cohere.com/pricing"

EXPECTED_IDS = [
    "embed-4-small",
    "embed-4-medium",
    "rerank-3.5-medium",
    "rerank-4-fast-medium",
    "rerank-4-pro-medium",
    "rerank-4-pro-large",
    "command",
    "command-light",
    "command-r-03-2024",
    "command-r-plus-08-2024",
    "command-r-plus-04-2024",
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


def make_cfg(url: str = PAGE_URL) -> ProviderCfg:
    return ProviderCfg(
        key="cohere",
        yml="cohere.yml",
        or_prefix="cohere",
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
    # model vault rows first, then the faq prose; the dated Command R+
    # releases emit newest first so the refresh pass diffs the freshest rate
    assert cohere_page.detect(make_cfg()) == EXPECTED_IDS


def test_detect_excludes_unpriced_content(live_page):
    # pricing cards carry no dollar rates, and the aya research faq answer is
    # not a "pricing is" sentence: none of them may leak into detection
    ids = cohere_page.detect(make_cfg())
    for excluded in (
        "north",
        "compass",
        "transcribe",
        "command-a-plus",
        "command-r7b",
        "aya-expanse",
    ):
        assert excluded not in ids


def test_scrape_prose_model_command(live_page):
    pricing = cohere_scraper.scrape(make_cfg(), "command")
    assert pricing == Pricing(1e-6, 2e-6, "chat")
    assert pricing is not None
    assert pricing.max_tokens == 0
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


def test_scrape_matches_page_spelling(live_page):
    # the page spells the id "Command"; the slug-normalized id must match too
    cfg = make_cfg()
    assert cohere_scraper.scrape(cfg, "Command") == Pricing(1e-6, 2e-6, "chat")
    assert cohere_scraper.scrape(cfg, "Embed 4 Small") is None


def test_scrape_unknown_model_returns_none(live_page):
    cfg = make_cfg()
    assert cohere_scraper.scrape(cfg, "north") is None
    assert cohere_scraper.scrape(cfg, "command-a") is None


def test_dedup_keys_dated_releases():
    # page ids spelled as dated releases normalize to the tracked ids,
    # measured against prices/providers/cohere.yml (2026-08-24)
    cases = {
        "command-r-03-2024": ("command-r",),
        "command-r-plus-04-2024": ("command-r-plus",),
        "command-r-plus-08-2024": ("command-r-plus",),
    }
    for page_id, tracked in cases.items():
        assert cohere_scraper.dedup_keys(page_id) == tracked, page_id


def test_dedup_keys_plain_ids_return_nothing():
    for page_id in ("command", "command-light", "embed-4-small", "rerank-4-pro-large"):
        assert cohere_scraper.dedup_keys(page_id) == (), page_id


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


def test_detect_raises_on_malformed_table_row(monkeypatch):
    serve_html(
        monkeypatch,
        '<div class="grid [grid-template-columns:repeat(4,minmax(150px,1fr))]">'
        "<div><p>Model</p></div>"
        "<div><p>Performance Tier</p></div>"
        "<div><p>Hourly rate per instance</p></div>"
        "<div><p>Monthly rate per instance</p></div>"
        "</div>"
        '<div class="grid [grid-template-columns:repeat(4,minmax(150px,1fr))]">'
        "<div><p>Embed 4</p></div>"
        "<div><p>Small</p></div>"
        "<div><p>$4.00</p></div>"
        "</div>",
    )
    with pytest.raises(web.FetchError, match="malformed model vault row"):
        cohere_page.detect(make_cfg())


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

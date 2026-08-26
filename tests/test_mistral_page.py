from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog import web
from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import mistral_page
from ai_pricelog.pricing import Pricing
from ai_pricelog.scrapers import mistral_page as mistral_scraper

FIXTURES = Path(__file__).parent / "fixtures" / "mistral_page"
CARDS_URL = "https://docs.mistral.ai/models/model-cards/"
PRICING_URL = "https://docs.mistral.ai/inference/pricing"

# the detector emits the stored spellings (dedup_keys conventions): dashed
# dated tails compact (codestral-25-08 -> codestral-2508) and the ministral
# generation segment drops (ministral-3-14b-25-12 -> ministral-14b-2512).
# cards-page order first; the pricing-page set adds nothing not already listed.
EXPECTED_IDS = [
    "mistral-medium-2604",
    "ocr-4-1",
    "zai-glm-5-2",
    "mistral-small-2603",
    "voxtral-mini-transcribe-2602",
    "voxtral-mini-transcribe-realtime-2602",
    "mistral-large-2512",
    "ministral-14b-2512",
    "ministral-8b-2512",
    "ministral-3b-2512",
    "ocr-4-0",
    "ocr-2512",
    "voxtral-tts-2603",
    "voxtral-small-2507",
    "codestral-2508",
    "codestral-embed-2505",
    "mistral-embed-2312",
    "shieldstral-1-0",
    "mistral-moderation-2603",
    "leanstral-1-5",
    "leanstral-2603",
    "mistral-medium-2508",
    "mistral-small-2506",
    "voxtral-mini-transcribe-2507",
    "devstral-2512",
    "magistral-medium-2507",
    "mistral-small-creative-2512",
    "devstral-small-2512",
    "magistral-medium-2509",
    "magistral-small-2509",
    "magistral-small-2507",
    "voxtral-mini-2507",
    "devstral-medium-2507",
    "devstral-small-2507",
    "magistral-medium-2506",
    "magistral-small-2506",
    "ocr-2505",
    "devstral-small-2505",
    "mistral-medium-2505",
    "mistral-small-2503",
    "ocr-2503",
    "mistral-saba-2502",
    "mistral-small-2501",
    "codestral-2501",
    "mistral-large-2411",
    "pixtral-large-2411",
    "mistral-moderation-2411",
    "ministral-3b-24-1",
    "ministral-8b-24-1",
    "mistral-small-2409",
    "pixtral-12b-2409",
    "mistral-large-2407",
    "mistral-nemo-12b-2407",
    "codestral-mamba-7b-0-1",
    "mathstral-7b-0-1",
    "codestral-2405",
    "mistral-7b-0-3",
    "mixtral-8x22b-0-1-0-3",
    "mistral-small-2402",
    "mistral-large-2402",
    "mistral-next",
    "mistral-medium-2312",
    "mixtral-8x7b-0-1",
    "mistral-7b-0-2",
    "mistral-7b-0-1",
]


def make_cfg() -> ProviderCfg:
    return ProviderCfg(
        key="mistral",
        provider="Mistral",
        detector="mistral_page",
        detector_url=CARDS_URL,
        scraper="mistral_page",
        scraper_url=PRICING_URL,
    )


def serve(monkeypatch: pytest.MonkeyPatch, module, pages: dict[str, str]) -> None:
    """serve one html per url; an unserved url fails the test loudly."""
    soups = {url: BeautifulSoup(html, "html.parser") for url, html in pages.items()}

    def fetch(url: str) -> BeautifulSoup:
        if url not in soups:
            raise AssertionError(f"unscripted fetch for {url}")
        return soups[url]

    monkeypatch.setattr(module, "fetch_soup", fetch)


@pytest.fixture
def live_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(
        monkeypatch,
        mistral_page,
        {
            CARDS_URL: (FIXTURES / "model_cards.html").read_text(encoding="utf-8"),
            PRICING_URL: (FIXTURES / "pricing.html").read_text(encoding="utf-8"),
        },
    )


@pytest.fixture
def live_pricing(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(
        monkeypatch,
        mistral_scraper,
        {PRICING_URL: (FIXTURES / "pricing.html").read_text(encoding="utf-8")},
    )


def test_detect_lists_every_slug_in_page_order(live_pages):
    assert mistral_page.detect(make_cfg()) == EXPECTED_IDS


def test_detect_includes_priced_models_missing_from_cards(monkeypatch):
    # the cards index under-lists; the pricing page carries the priced set
    serve(
        monkeypatch,
        mistral_page,
        {
            CARDS_URL: '<html><body><a href="/models/legacy-only">legacy</a></body></html>',
            PRICING_URL: (FIXTURES / "pricing.html").read_text(encoding="utf-8"),
        },
    )
    ids = mistral_page.detect(make_cfg())
    assert ids[0] == "legacy-only"
    for priced in ("mistral-large-2512", "codestral-2508", "zai-glm-5-2", "ministral-14b-2512"):
        assert priced in ids


def test_detect_emits_stored_spellings(monkeypatch):
    serve(
        monkeypatch,
        mistral_page,
        {
            CARDS_URL: (
                '<html><body><a href="/models/codestral-25-08">c</a>'
                '<a href="/models/ministral-3-14b-25-12">m</a>'
                '<a href="/models/ocr-4-1">o</a></body></html>'
            ),
            PRICING_URL: '<html><body><a href="/models/codestral-25-08">c</a></body></html>',
        },
    )
    assert mistral_page.detect(make_cfg()) == [
        "codestral-2508",
        "ministral-14b-2512",
        "ocr-4-1",
    ]


def test_detect_raises_when_no_model_links(monkeypatch):
    html = '<html><body><a href="/api">api</a></body></html>'
    serve(monkeypatch, mistral_page, {CARDS_URL: html, PRICING_URL: html})
    with pytest.raises(web.FetchError, match="no model links"):
        mistral_page.detect(make_cfg())


def test_detect_raises_when_pricing_page_has_no_model_links(monkeypatch):
    serve(
        monkeypatch,
        mistral_page,
        {
            CARDS_URL: '<html><body><a href="/models/aaa">A</a></body></html>',
            PRICING_URL: '<html><body><a href="/api">api</a></body></html>',
        },
    )
    with pytest.raises(web.FetchError, match="no model links"):
        mistral_page.detect(make_cfg())


def test_detect_propagates_fetch_error(monkeypatch):
    def boom(url: str) -> BeautifulSoup:
        raise web.FetchError("boom")

    monkeypatch.setattr(mistral_page, "fetch_soup", boom)
    with pytest.raises(web.FetchError, match="boom"):
        mistral_page.detect(make_cfg())


def test_scrape_flagship_prices(live_pricing):
    cfg = make_cfg()
    # 0.05 lands 1 ulp off the round decimal, hence approx
    assert mistral_scraper.scrape(cfg, "mistral-large-3-25-12") == Pricing(
        5e-7, 1.5e-6, "chat", 0, pytest.approx(5e-8, rel=1e-12)
    )
    assert mistral_scraper.scrape(cfg, "mistral-medium-3-5-26-04") == Pricing(
        1.5e-6, 7.5e-6, "chat", 0, 1.5e-7
    )
    assert mistral_scraper.scrape(cfg, "mistral-small-4-0-26-03") == Pricing(
        1.5e-7, 6e-7, "chat", 0, 1.5e-8
    )


def test_scrape_ministral_prices(live_pricing):
    cfg = make_cfg()
    # 0.2 and 0.1 cents per 1M land 1 ulp off the round decimal, hence approx
    assert mistral_scraper.scrape(cfg, "ministral-3-14b-25-12") == Pricing(
        pytest.approx(2e-7, rel=1e-12), pytest.approx(2e-7, rel=1e-12), "chat", 0, 2e-8
    )
    assert mistral_scraper.scrape(cfg, "ministral-3-3b-25-12") == Pricing(
        pytest.approx(1e-7, rel=1e-12), pytest.approx(1e-7, rel=1e-12), "chat", 0, 1e-8
    )


def test_scrape_token_priced_tables_beyond_flagship(live_pricing):
    cfg = make_cfg()
    assert mistral_scraper.scrape(cfg, "zai-glm-5-2") == Pricing(1.4e-6, 4.4e-6, "chat", 0, 1.4e-7)
    assert mistral_scraper.scrape(cfg, "codestral-25-08") == Pricing(
        3e-7, pytest.approx(9e-7, rel=1e-12), "chat", 0, 3e-8
    )


def test_scrape_accepts_stored_spellings(live_pricing):
    # the detector emits the stored spelling; scrape must match it to the row
    cfg = make_cfg()
    assert mistral_scraper.scrape(cfg, "codestral-2508") == Pricing(
        3e-7, pytest.approx(9e-7, rel=1e-12), "chat", 0, 3e-8
    )
    assert mistral_scraper.scrape(cfg, "ministral-14b-2512") == Pricing(
        pytest.approx(2e-7, rel=1e-12), pytest.approx(2e-7, rel=1e-12), "chat", 0, 2e-8
    )
    assert mistral_scraper.scrape(cfg, "mistral-large-2512") == Pricing(
        5e-7, 1.5e-6, "chat", 0, pytest.approx(5e-8, rel=1e-12)
    )


def test_scrape_cache_read_row_mtok(live_pricing):
    # the domain-knowledge pin: zai-glm-5-2 cache reads cost $0.14 per 1M
    from ai_pricelog import store

    cfg = make_cfg()
    pricing = mistral_scraper.scrape(cfg, "zai-glm-5-2")
    assert pricing is not None
    row = store.build_row(cfg.key, "zai-glm-5-2", pricing, "2026-08-26", cfg.scraper_url)
    assert row["cache_read_mtok"] == 0.14


def test_scrape_non_token_units_return_none(live_pricing):
    cfg = make_cfg()
    assert mistral_scraper.scrape(cfg, "ocr-4-1") is None
    assert mistral_scraper.scrape(cfg, "voxtral-mini-transcribe-26-02") is None
    assert mistral_scraper.scrape(cfg, "voxtral-tts-26-03") is None


def test_scrape_free_cells_return_none(live_pricing):
    cfg = make_cfg()
    assert mistral_scraper.scrape(cfg, "mistral-moderation-26-03") is None
    assert mistral_scraper.scrape(cfg, "leanstral-1-5") is None


def test_scrape_missing_output_return_none(live_pricing):
    assert mistral_scraper.scrape(make_cfg(), "codestral-embed-25-05") is None


def test_scrape_model_absent_from_pricing_return_none(live_pricing):
    # on the cards page but has no pricing row
    assert mistral_scraper.scrape(make_cfg(), "mistral-7b-0-3") is None


def test_scrape_propagates_fetch_error(monkeypatch):
    def boom(url: str) -> BeautifulSoup:
        raise web.FetchError("boom")

    monkeypatch.setattr(mistral_scraper, "fetch_soup", boom)
    with pytest.raises(web.FetchError, match="boom"):
        mistral_scraper.scrape(make_cfg(), "mistral-large-3-25-12")


def test_scrape_raises_when_no_token_table(monkeypatch):
    html = (
        "<html><body><section><p>Prices as marked</p><table>"
        "<tr><th>Model</th><th>Input</th><th>Cached input</th><th>Output</th></tr>"
        "</table></section></body></html>"
    )
    serve(monkeypatch, mistral_scraper, {PRICING_URL: html})
    with pytest.raises(web.FetchError, match="no per-token pricing tables"):
        mistral_scraper.scrape(make_cfg(), "mistral-large-3-25-12")


def test_scrape_raises_on_header_mismatch(monkeypatch):
    html = (
        "<html><body><section><p>Prices /M Tokens</p><table>"
        "<tr><th>Model</th><th>Input</th></tr>"
        "</table></section></body></html>"
    )
    serve(monkeypatch, mistral_scraper, {PRICING_URL: html})
    with pytest.raises(web.FetchError, match="no per-token pricing tables"):
        mistral_scraper.scrape(make_cfg(), "mistral-large-3-25-12")


def test_scrape_matches_row_by_exact_slug(monkeypatch):
    html = (
        "<html><body><section><p>Prices /M Tokens</p><table>"
        "<tr><th>Model</th><th>Input</th><th>Cached input</th><th>Output</th></tr>"
        '<tr><td><a href="/models/aaa">A</a></td><td>Free</td><td>Free</td><td>Free</td></tr>'
        '<tr><td><a href="/models/bbb">B</a></td><td>$1</td><td>$0.1</td><td>$2</td></tr>'
        '<tr><td><a href="/models/ccc">C</a></td><td>$4 /1000 Pages</td>'
        "<td>$0.4 /1000 Pages</td><td>$8 /1000 Pages</td></tr>"
        '<tr><td><a href="/models/ddd">D</a></td><td>$1</td><td>Free</td><td>$2</td></tr>'
        "</table></section></body></html>"
    )
    serve(monkeypatch, mistral_scraper, {PRICING_URL: html})
    cfg = make_cfg()
    # 0.1 lands 1 ulp off the round decimal, hence approx
    assert mistral_scraper.scrape(cfg, "bbb") == Pricing(
        1e-6, 2e-6, "chat", 0, pytest.approx(1e-7, rel=1e-12)
    )
    assert mistral_scraper.scrape(cfg, "aaa") is None
    # unit-priced row inside a token section: the cell regex must reject it
    assert mistral_scraper.scrape(cfg, "ccc") is None
    # a non-dollar cached cell leaves the cache-read cost None
    assert mistral_scraper.scrape(cfg, "ddd") == Pricing(1e-6, 2e-6, "chat", 0, None)


def test_dedup_keys_compaction():
    from ai_pricelog.scrapers.mistral_page import dedup_keys

    # page slug -> the stored spellings, measured 2026-08-19
    cases = {
        "codestral-25-08": ["codestral-2508"],
        "codestral-25-01": ["codestral-2501"],
        "mistral-medium-3-5-26-04": ["mistral-medium-2604"],
        "mistral-small-4-0-26-03": ["mistral-small-2603"],
        "mistral-large-3-25-12": ["mistral-large-2512"],
        "mistral-large-2-1-24-11": ["mistral-large-2411"],
        "mistral-large-2-0-24-07": ["mistral-large-2407"],
        "pixtral-large-24-11": ["pixtral-large-2411"],
        "devstral-2-25-12": ["devstral-2512"],
        "magistral-medium-1-1-25-07": ["magistral-medium-2507"],
        "ministral-3-14b-25-12": ["ministral-3-14b-2512", "ministral-14b-2512"],
        "ministral-3-3b-25-12": ["ministral-3-3b-2512", "ministral-3b-2512"],
    }
    for slug, tracked in cases.items():
        assert dedup_keys(slug) == tracked, slug


def test_dedup_keys_unchanged_spellings_return_nothing():
    from ai_pricelog.scrapers.mistral_page import dedup_keys

    for slug in ("codestral-2508", "mistral-medium-3-5", "mistral-7b-0-3", "ocr-4-0"):
        assert dedup_keys(slug) == [], slug

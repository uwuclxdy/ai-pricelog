from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from autopr_genai_prices import web
from autopr_genai_prices.config import ProviderCfg
from autopr_genai_prices.detectors import mistral_page
from autopr_genai_prices.pricing import Pricing
from autopr_genai_prices.scrapers import mistral_page as mistral_scraper

FIXTURES = Path(__file__).parent / "fixtures" / "mistral_page"
CARDS_URL = "https://docs.mistral.ai/models/model-cards/"
PRICING_URL = "https://docs.mistral.ai/inference/pricing"

EXPECTED_IDS = [
    "mistral-medium-3-5-26-04",
    "ocr-4-1",
    "zai-glm-5-2",
    "mistral-small-4-0-26-03",
    "voxtral-mini-transcribe-26-02",
    "voxtral-mini-transcribe-realtime-26-02",
    "mistral-large-3-25-12",
    "ministral-3-14b-25-12",
    "ministral-3-8b-25-12",
    "ministral-3-3b-25-12",
    "ocr-4-0",
    "ocr-3-25-12",
    "voxtral-tts-26-03",
    "voxtral-small-25-07",
    "codestral-25-08",
    "codestral-embed-25-05",
    "mistral-embed-23-12",
    "shieldstral-1-0",
    "mistral-moderation-26-03",
    "leanstral-1-5",
    "leanstral-26-03",
    "mistral-medium-3-1-25-08",
    "mistral-small-3-2-25-06",
    "voxtral-mini-transcribe-25-07",
    "devstral-2-25-12",
    "magistral-medium-1-1-25-07",
    "mistral-small-creative-25-12",
    "devstral-small-2-25-12",
    "magistral-medium-1-2-25-09",
    "magistral-small-1-2-25-09",
    "magistral-small-1-1-25-07",
    "voxtral-mini-25-07",
    "devstral-medium-1-0-25-07",
    "devstral-small-1-1-25-07",
    "magistral-medium-1-0-25-06",
    "magistral-small-1-0-25-06",
    "ocr-2-25-05",
    "devstral-small-1-0-25-05",
    "mistral-medium-3-25-05",
    "mistral-small-3-1-25-03",
    "ocr-25-03",
    "mistral-saba-25-02",
    "mistral-small-3-0-25-01",
    "codestral-25-01",
    "mistral-large-2-1-24-11",
    "pixtral-large-24-11",
    "mistral-moderation-24-11",
    "ministral-3b-24-1",
    "ministral-8b-24-1",
    "mistral-small-2-0-24-09",
    "pixtral-12b-24-09",
    "mistral-large-2-0-24-07",
    "mistral-nemo-12b-24-07",
    "codestral-mamba-7b-0-1",
    "mathstral-7b-0-1",
    "codestral-24-05",
    "mistral-7b-0-3",
    "mixtral-8x22b-0-1-0-3",
    "mistral-small-1-0-24-02",
    "mistral-large-1-0-24-02",
    "mistral-next",
    "mistral-medium-1-0-23-12",
    "mixtral-8x7b-0-1",
    "mistral-7b-0-2",
    "mistral-7b-0-1",
]


def make_cfg() -> ProviderCfg:
    return ProviderCfg(
        key="mistral",
        yml="mistral.yml",
        or_prefix="mistralai",
        detector="mistral_page",
        detector_url=CARDS_URL,
        scraper="mistral_page",
        scraper_url=PRICING_URL,
    )


def serve(monkeypatch: pytest.MonkeyPatch, module, html: str) -> None:
    monkeypatch.setattr(module, "fetch_soup", lambda url: BeautifulSoup(html, "html.parser"))


@pytest.fixture
def live_cards(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, mistral_page, (FIXTURES / "model_cards.html").read_text(encoding="utf-8"))


@pytest.fixture
def live_pricing(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(
        monkeypatch,
        mistral_scraper,
        (FIXTURES / "pricing.html").read_text(encoding="utf-8"),
    )


def test_detect_lists_every_slug_in_page_order(live_cards):
    assert mistral_page.detect(make_cfg()) == EXPECTED_IDS


def test_detect_raises_when_no_model_links(monkeypatch):
    serve(monkeypatch, mistral_page, '<html><body><a href="/api">api</a></body></html>')
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
    assert mistral_scraper.scrape(cfg, "mistral-large-3-25-12") == Pricing(5e-7, 1.5e-6, "chat", 0)
    assert mistral_scraper.scrape(cfg, "mistral-medium-3-5-26-04") == Pricing(
        1.5e-6, 7.5e-6, "chat", 0
    )
    assert mistral_scraper.scrape(cfg, "mistral-small-4-0-26-03") == Pricing(
        1.5e-7, 6e-7, "chat", 0
    )


def test_scrape_ministral_prices(live_pricing):
    cfg = make_cfg()
    # 0.2 and 0.1 cents per 1M land 1 ulp off the round decimal, hence approx
    assert mistral_scraper.scrape(cfg, "ministral-3-14b-25-12") == Pricing(
        pytest.approx(2e-7, rel=1e-12), pytest.approx(2e-7, rel=1e-12), "chat", 0
    )
    assert mistral_scraper.scrape(cfg, "ministral-3-3b-25-12") == Pricing(
        pytest.approx(1e-7, rel=1e-12), pytest.approx(1e-7, rel=1e-12), "chat", 0
    )


def test_scrape_token_priced_tables_beyond_flagship(live_pricing):
    cfg = make_cfg()
    assert mistral_scraper.scrape(cfg, "zai-glm-5-2") == Pricing(1.4e-6, 4.4e-6, "chat", 0)
    assert mistral_scraper.scrape(cfg, "codestral-25-08") == Pricing(
        3e-7, pytest.approx(9e-7, rel=1e-12), "chat", 0
    )


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
    serve(monkeypatch, mistral_scraper, html)
    with pytest.raises(web.FetchError, match="no per-token pricing tables"):
        mistral_scraper.scrape(make_cfg(), "mistral-large-3-25-12")


def test_scrape_raises_on_header_mismatch(monkeypatch):
    html = (
        "<html><body><section><p>Prices /M Tokens</p><table>"
        "<tr><th>Model</th><th>Input</th></tr>"
        "</table></section></body></html>"
    )
    serve(monkeypatch, mistral_scraper, html)
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
        "</table></section></body></html>"
    )
    serve(monkeypatch, mistral_scraper, html)
    cfg = make_cfg()
    assert mistral_scraper.scrape(cfg, "bbb") == Pricing(1e-6, 2e-6, "chat", 0)
    assert mistral_scraper.scrape(cfg, "aaa") is None
    # unit-priced row inside a token section: the cell regex must reject it
    assert mistral_scraper.scrape(cfg, "ccc") is None


def test_dedup_keys_compaction():
    from autopr_genai_prices.scrapers.mistral_page import dedup_keys

    # page slug -> the target's tracked spelling, measured against
    # prices/providers/mistral.yml (codestral-2508 etc., 2026-08-19)
    cases = {
        "codestral-25-08": "codestral-2508",
        "codestral-25-01": "codestral-2501",
        "mistral-medium-3-5-26-04": "mistral-medium-2604",
        "mistral-small-4-0-26-03": "mistral-small-2603",
        "mistral-large-3-25-12": "mistral-large-2512",
        "mistral-large-2-1-24-11": "mistral-large-2411",
        "mistral-large-2-0-24-07": "mistral-large-2407",
        "pixtral-large-24-11": "pixtral-large-2411",
        "devstral-2-25-12": "devstral-2512",
        "magistral-medium-1-1-25-07": "magistral-medium-2507",
    }
    for slug, tracked in cases.items():
        assert dedup_keys(slug) == [tracked], slug


def test_dedup_keys_unchanged_spellings_return_nothing():
    from autopr_genai_prices.scrapers.mistral_page import dedup_keys

    for slug in ("codestral-2508", "mistral-medium-3-5", "mistral-7b-0-3", "ocr-4-0"):
        assert dedup_keys(slug) == [], slug

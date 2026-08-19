from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from autopr_genai_prices.config import ProviderCfg
from autopr_genai_prices.detectors import perplexity_page as detector
from autopr_genai_prices.scrapers import perplexity_page as scraper
from autopr_genai_prices.web import FetchError

PAGE_URL = "https://docs.perplexity.ai/guides/pricing"
FIXTURE = Path(__file__).parent / "fixtures" / "perplexity_page" / "pricing.html"

EXPECTED_IDS = ["sonar", "sonar-pro", "sonar-reasoning-pro", "sonar-deep-research"]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="perplexity",
        provider="perplexity",
        namespace="perplexity",
        detector="perplexity_page",
        detector_url=PAGE_URL,
        scraper="perplexity_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


def synthetic_soup(*rows: tuple[str, ...]) -> BeautifulSoup:
    header = (
        "<table><tr><th>Model</th><th>Input Tokens ($/1M)</th><th>Output Tokens ($/1M)</th></tr>"
    )
    body = "".join(f"<tr>{''.join(f'<td>{cell}</td>' for cell in row)}</tr>" for row in rows)
    return BeautifulSoup(f"{header}{body}</table>", "html.parser")


def test_detect_sonar_models(monkeypatch):
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    ids = detector.detect(cfg())
    assert ids == EXPECTED_IDS
    # the fixture page carries request-fee and embeddings tables; their ids
    # must not leak into detection
    for leaked in (
        "pplx-embed-v1-0.6b",
        "pplx-embed-v1-4b",
        "pplx-embed-context-v1-0.6b",
        "pplx-embed-context-v1-4b",
    ):
        assert leaked not in ids


def test_detect_skips_unusable_model_cells(monkeypatch):
    # an empty model cell is not a model; a cell with a footnote is not a
    # litellm key and is skipped rather than emitted as a junk id
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: synthetic_soup(
            ("Sonar", "$1", "$1"), ("", "$1", "$1"), ("Sonar Pro (beta)", "$1", "$1"), ()
        ),
    )
    assert detector.detect(cfg()) == ["sonar"]


def test_detect_no_ids_raises(monkeypatch):
    # a token-pricing table whose model cells all fail the id pattern is a
    # parse failure, not a silent empty detection
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: synthetic_soup(("Sonar Pro (beta)", "$1", "$1")),
    )
    with pytest.raises(FetchError, match="no model ids"):
        detector.detect(cfg())


def test_detect_no_token_table_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><td>Tool</td><td>Price</td></tr></table>", "html.parser"
        ),
    )
    with pytest.raises(FetchError, match="token pricing"):
        detector.detect(cfg())


def test_fetch_error_propagates(monkeypatch):
    def boom(url):
        raise FetchError(f"fetch failed for {url}")

    monkeypatch.setattr(detector, "fetch_soup", boom)
    with pytest.raises(FetchError, match=PAGE_URL):
        detector.detect(cfg())


def test_scrape_sonar(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "sonar")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(1 / 1e6)
    assert pricing.mode == "chat"
    assert pricing.max_tokens == 0


def test_scrape_sonar_pro(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "sonar-pro")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(15 / 1e6)


def test_scrape_sonar_reasoning_pro(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "sonar-reasoning-pro")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(2 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(8 / 1e6)


def test_scrape_sonar_deep_research_ignores_other_columns(monkeypatch):
    # the deep-research row is the only one with citation/search/reasoning
    # prices; reasoning ($3) differs from output ($8), so the output price
    # must come from the output column, not the reasoning column. the input
    # axis is pinned by the other rows, whose citation cell is "-"
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "sonar-deep-research")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(2 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(8 / 1e6)


def test_scrape_matches_page_spelling(monkeypatch):
    # the page spells the id "Sonar Pro"; the normalized id must match too
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "Sonar Pro")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(15 / 1e6)


def test_scrape_unknown_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "sonar-mini") is None


def test_scrape_unpriced_row_returns_none(monkeypatch):
    # a model whose input cell carries no dollar amount is not priced yet
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: synthetic_soup(("Sonar", "$1", "$1"), ("Sonar Pro", "-", "$15")),
    )
    assert scraper.scrape(cfg(), "sonar-pro") is None


def test_scrape_malformed_row_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: synthetic_soup(("Sonar", "$1")),
    )
    with pytest.raises(FetchError, match="malformed pricing row"):
        scraper.scrape(cfg(), "sonar")


def test_scrape_no_token_table_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><td>Tool</td><td>Price</td></tr></table>", "html.parser"
        ),
    )
    with pytest.raises(FetchError, match="token pricing"):
        scraper.scrape(cfg(), "sonar")


def test_scrape_thousands_separator(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: synthetic_soup(("Sonar", "$1,000", "$2,000.5")),
    )
    pricing = scraper.scrape(cfg(), "sonar")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1000.0 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(2000.5 / 1e6)

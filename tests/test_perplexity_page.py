from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import perplexity_page as detector
from ai_pricelog.scrapers import perplexity_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://docs.perplexity.ai/docs/agent-api/models"
FIXTURE = Path(__file__).parent / "fixtures" / "perplexity_page" / "models.html"

# the 2026-09-29 repoint: the guides/pricing token table is gone (308 +
# restructure); the watch is the agent-api catalog's perplexity rows, held
# to sonar (ruled 2026-09-29). the sunset ids are simply absent from the
# emitted set; the pipeline's absence counters do the rest.
EXPECTED_IDS = ["sonar"]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="perplexity",
        provider="Perplexity",
        detector="perplexity_page",
        detector_url=PAGE_URL,
        scraper="perplexity_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


def synthetic_soup(*rows: tuple[str, ...]) -> BeautifulSoup:
    header = (
        "<table><tr><th>Model</th><th>Input ($/1M)</th><th>Output ($/1M)</th>"
        "<th>Cache read ($/1M)</th><th>Service tiers</th><th>Docs</th></tr>"
    )
    body = "".join(f"<tr>{''.join(f'<td>{cell}</td>' for cell in row)}</tr>" for row in rows)
    return BeautifulSoup(f"{header}{body}</table>", "html.parser")


def test_detect_emits_sonar_only(monkeypatch):
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    ids = detector.detect(cfg())
    assert ids == EXPECTED_IDS
    # the catalog's other perplexity-hosted rows are resold models excluded
    # at the source; other vendors' rows never become candidates
    for excluded in (
        "glm-5.3",
        "glm-5.3-flash",
        "kimi-k3",
        "nemotron-3-ultra-550b-a55b",
        "gpt-6-sol",
    ):
        assert excluded not in ids


def test_detect_excludes_resold_rows(monkeypatch):
    # zai / moonshot / nvidia own the catalog's other perplexity-hosted
    # models; a perplexity copy would shadow the owning source's row, so
    # the resold ids never become candidates
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: synthetic_soup(
            ("perplexity/glm-5.3", "1.40", "4.40", "0.26", "—", "GLM"),
            ("perplexity/sonar", "0.25", "2.50", "0.0625", "—", "—"),
        ),
    )
    assert detector.detect(cfg()) == ["sonar"]


def test_detect_skips_unusable_model_cells(monkeypatch):
    # an empty model cell is not a model; a footnote suffix is not a stored
    # id; other-vendor rows (tiered long-context cells included) pass under
    # the scan
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: synthetic_soup(
            ("perplexity/sonar", "0.25", "2.50", "0.0625", "—", "—"),
            ("", "0.25", "2.50", "0.0625", "—", "—"),
            ("perplexity/sonar-pro (beta)", "3", "15", "0.3", "—", "—"),
            ("openai/gpt-6-sol", "2.00 (≤272k) 4.00 (>272k)", "10.00", "0.10", "—", "—"),
            (),
        ),
    )
    assert detector.detect(cfg()) == ["sonar"]


def test_detect_no_ids_raises(monkeypatch):
    # pinned tables with no perplexity row are a parse failure, not a
    # silent empty detection
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: synthetic_soup(("openai/gpt-6-sol", "2.00", "10.00", "0.10", "—", "—")),
    )
    with pytest.raises(FetchError, match="no perplexity model ids"):
        detector.detect(cfg())


def test_detect_no_pricing_table_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><td>Tool</td><td>Price</td></tr></table>", "html.parser"
        ),
    )
    with pytest.raises(FetchError, match="agent-api pricing table"):
        detector.detect(cfg())


def test_detect_header_wording_drift_still_matches(monkeypatch):
    # the pinned trio matches after folding case and whitespace, so
    # lowercase spellings still locate the tables
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>Model</th><th>input ($/1m)</th><th>output ($/1m)</th>"
            "<th>cache read ($/1m)</th><th>Service tiers</th><th>Docs</th></tr>"
            "<tr><td>perplexity/sonar</td><td>0.25</td><td>2.50</td><td>0.0625</td>"
            "<td>—</td><td>—</td></tr></table>",
            "html.parser",
        ),
    )
    assert detector.detect(cfg()) == ["sonar"]


def test_fetch_error_propagates(monkeypatch):
    def boom(url):
        raise FetchError(f"fetch failed for {url}")

    monkeypatch.setattr(detector, "fetch_soup", boom)
    with pytest.raises(FetchError, match=PAGE_URL):
        detector.detect(cfg())


def test_scrape_sonar(monkeypatch):
    # the page row spells the id `perplexity/sonar`; the store keys on
    # `sonar`, and the three rates differ, so a swapped column cannot pass
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "sonar")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.25 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(2.50 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.0625 / 1e6)
    assert pricing.mode == "chat"
    assert pricing.max_tokens_in == pricing.max_tokens_out == 0


def test_scrape_excluded_ids_return_none(monkeypatch):
    # excluded at the source: neither a resold id nor another vendor's row
    # answers a perplexity scrape
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "glm-5.3") is None
    assert scraper.scrape(cfg(), "gpt-6-sol") is None


def test_scrape_unknown_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "sonar-mini") is None


def test_scrape_unpriced_row_returns_none(monkeypatch):
    # a model whose input cell carries no number is not priced
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: synthetic_soup(
            ("perplexity/sonar", "0.25", "2.50", "0.0625", "—", "—"),
            ("perplexity/sonar-pro", "—", "15.00", "0.30", "—", "—"),
        ),
    )
    assert scraper.scrape(cfg(), "sonar-pro") is None


def test_scrape_malformed_row_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: synthetic_soup(("perplexity/sonar", "0.25")),
    )
    with pytest.raises(FetchError, match="malformed pricing row"):
        scraper.scrape(cfg(), "sonar")


def test_scrape_no_pricing_table_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><td>Tool</td><td>Price</td></tr></table>", "html.parser"
        ),
    )
    with pytest.raises(FetchError, match="agent-api pricing table"):
        scraper.scrape(cfg(), "sonar")


def test_scrape_thousands_separator(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: synthetic_soup(("perplexity/sonar", "$1,000", "$2,000.5", "$0.50", "—", "—")),
    )
    pricing = scraper.scrape(cfg(), "sonar")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1000.0 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(2000.5 / 1e6)


def test_scrape_header_wording_drift_still_scrapes(monkeypatch):
    # scrape indexes the same folded headers detection pins, so a
    # fold-equal but differently-spelled header row still scrapes instead
    # of crashing on the raw-spelling index
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>Model</th><th>input ($/1m)</th><th>output ($/1m)</th>"
            "<th>cache read ($/1m)</th><th>Service tiers</th><th>Docs</th></tr>"
            "<tr><td>perplexity/sonar</td><td>0.25</td><td>2.50</td><td>0.0625</td>"
            "<td>—</td><td>—</td></tr></table>",
            "html.parser",
        ),
    )
    pricing = scraper.scrape(cfg(), "sonar")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.25 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.0625 / 1e6)


def test_scrape_tiered_cell_returns_none(monkeypatch):
    # a tiered long-context cell on a watched row carries two numbers in
    # one cell: no single rate, so the row is unpriced (skip-and-retry),
    # never a first-tier misread
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: synthetic_soup(
            ("perplexity/sonar", "2.00 (≤272k) 4.00 (>272k)", "10.00", "0.10", "—", "—"),
        ),
    )
    assert scraper.scrape(cfg(), "sonar") is None

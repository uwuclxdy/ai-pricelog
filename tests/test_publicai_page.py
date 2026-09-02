from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import publicai_page as detector
from ai_pricelog.scrapers import publicai_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://platform.publicai.co/models"
FIXTURE = Path(__file__).parent / "fixtures" / "publicai_page" / "pricing.html"

EXPECTED_IDS = [
    "swiss-ai/apertus-v1.5-8b",
    "swiss-ai/apertus-v1.5-8b-thinking",
    "swiss-ai/apertus-v1.5-70b",
    "swiss-ai/apertus-v1.5-70b-thinking",
    "swiss-ai/apertus-8b-instruct",
    "swiss-ai/apertus-70b-instruct",
    "aisingapore/gemma-sea-lion-v4-27b-it",
    "aisingapore/qwen-sea-lion-v4-32b-it",
    "allenai/olmo-3-7b-instruct",
    "speakleash/bielik-11b-v3.0-instruct",
    "utter-project/eurollm-22b-instruct-2512",
]

_MODELS_TABLE = (
    "<table><thead><tr><th>Model ID</th><th>Context Length</th><th>Pricing</th>"
    "<th>Country of Origin</th></tr></thead><tbody>{rows}</tbody></table>"
)


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="publicai",
        provider="PublicAI",
        detector="publicai_page",
        detector_url=PAGE_URL,
        scraper="publicai_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


def test_detect_models(monkeypatch):
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_scrape_apertus_8b(monkeypatch):
    # pricing cell "$0.10 / $0.20 per 1M tokens", context "262K", verified
    # against the first-party page fixture
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "swiss-ai/apertus-v1.5-8b")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.10 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.20 / 1e6)
    assert pricing.max_tokens_in == 262000
    assert pricing.mode == "chat"


def test_scrape_sea_lion_32b(monkeypatch):
    # pricing cell "$0.25 / $0.50 per 1M tokens", context "128K"; the
    # verbatim page spelling (uppercase) matches through case-folding
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "aisingapore/Qwen-SEA-LION-v4-32B-IT")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.25 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.50 / 1e6)
    assert pricing.max_tokens_in == 128000


def test_scrape_unknown_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "swiss-ai/nope") is None


def test_detect_skips_non_token_rows(monkeypatch):
    # a row whose pricing cell is not input / output per 1M tokens (an
    # embedding-style per-1K cell) is out of scope
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            _MODELS_TABLE.format(
                rows=(
                    "<tr><td><a>swiss-ai/apertus-v1.5-8b</a></td><td>262K</td>"
                    "<td>$0.10 / $0.20<span>per 1M tokens</span></td><td>CH</td></tr>"
                    "<tr><td><a>some/embed</a></td><td>8K</td>"
                    "<td>$0.01<span>per 1K tokens</span></td><td>CH</td></tr>"
                )
            ),
            "html.parser",
        ),
    )
    assert detector.detect(cfg()) == ["swiss-ai/apertus-v1.5-8b"]


def test_malformed_pricing_cell_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            _MODELS_TABLE.format(
                rows=(
                    "<tr><td><a>swiss-ai/apertus-v1.5-8b</a></td><td>262K</td>"
                    "<td>$0.10<span>per 1M tokens</span></td><td>CH</td></tr>"
                )
            ),
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="1 amounts, want 2"):
        scraper.scrape(cfg(), "swiss-ai/apertus-v1.5-8b")


def test_malformed_context_cell_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            _MODELS_TABLE.format(
                rows=(
                    "<tr><td><a>swiss-ai/apertus-v1.5-8b</a></td><td>262K tokens</td>"
                    "<td>$0.10 / $0.20<span>per 1M tokens</span></td><td>CH</td></tr>"
                )
            ),
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="malformed context cell"):
        scraper.scrape(cfg(), "swiss-ai/apertus-v1.5-8b")


def test_detect_no_usable_ids_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            _MODELS_TABLE.format(
                rows=(
                    "<tr><td><a>some/embed</a></td><td>8K</td>"
                    "<td>$0.01<span>per 1K tokens</span></td><td>CH</td></tr>"
                )
            ),
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="no model ids"):
        detector.detect(cfg())


def test_missing_table_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>Model</th><th>Price</th></tr></table>", "html.parser"
        ),
    )
    with pytest.raises(FetchError, match="no models table"):
        scraper.scrape(cfg(), "swiss-ai/apertus-v1.5-8b")


def test_detect_missing_table_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>Model</th><th>Price</th></tr></table>", "html.parser"
        ),
    )
    with pytest.raises(FetchError, match="no models table"):
        detector.detect(cfg())


def test_detect_header_wording_drift_still_matches(monkeypatch):
    # the models-table header pins match after folding case, whitespace, and
    # &/and: an internal whitespace run (casefold alone cannot absorb it)
    # still locates the table
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><thead><tr><th>Model  ID</th><th>Context Length</th><th>Pricing</th>"
            "<th>Country of Origin</th></tr></thead><tbody>"
            "<tr><td><a>swiss-ai/apertus-v1.5-8b</a></td><td>262K</td>"
            "<td>$0.10 / $0.20<span>per 1M tokens</span></td><td>CH</td></tr>"
            "</tbody></table>",
            "html.parser",
        ),
    )
    assert detector.detect(cfg()) == ["swiss-ai/apertus-v1.5-8b"]


def test_scrape_unrelated_short_row_does_not_block(monkeypatch):
    # a short drifted row for another model is additive drift detection
    # already skips; scraping the chosen model must not break on it
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            _MODELS_TABLE.format(
                rows=(
                    "<tr><td>stray</td></tr>"
                    "<tr><td><a>swiss-ai/apertus-v1.5-8b</a></td><td>262K</td>"
                    "<td>$0.10 / $0.20<span>per 1M tokens</span></td><td>CH</td></tr>"
                )
            ),
            "html.parser",
        ),
    )
    pricing = scraper.scrape(cfg(), "swiss-ai/apertus-v1.5-8b")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.10 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.20 / 1e6)


def test_scrape_matched_row_with_extra_amount_raises(monkeypatch):
    # the matched row's pricing cell must hold exactly two amounts: a third
    # is a page-shape break, never a silent read of the first two
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            _MODELS_TABLE.format(
                rows=(
                    "<tr><td><a>swiss-ai/apertus-v1.5-8b</a></td><td>262K</td>"
                    "<td>$0.10 / $0.20 / $0.30<span>per 1M tokens</span></td><td>CH</td></tr>"
                )
            ),
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="3 amounts, want 2"):
        scraper.scrape(cfg(), "swiss-ai/apertus-v1.5-8b")

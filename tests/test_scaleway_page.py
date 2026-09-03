"""scaleway pricing pair tests, pinned against the saved live pricing page.

the fixture is the byte-verbatim "Generative API" table of the capture:
bytes [200773, 212042) of the full page, from the model <table> through
the </table> that follows the last row's Try anchor (content-derived, not
a fixed offset - the page's css-class hashes shift byte positions between
captures). the slice holds the complete table: one thead row + 15 tbody
rows; the gpu-per-hour table stays out.
"""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path

import pytest

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import scaleway_page as detector
from ai_pricelog.scrapers import scaleway_page as scraper
from ai_pricelog.store import build_row, resolve_rate
from ai_pricelog.validate import load_schema_keys
from ai_pricelog.web import FetchError

PAGE_URL = "https://www.scaleway.com/en/pricing/model-as-a-service/"
FIXTURE = Path(__file__).parent / "fixtures" / "scaleway_page" / "pricing.html"

# every fixture row carrying per-token euro rates, page order; whisper
# (per audio minute) is skipped
EXPECTED_IDS = [
    "glm-5.2",
    "deepseek-v4-flash-0731",
    "qwen3.5-397b-a17b",
    "qwen3.6-35b-a3b",
    "gemma-4-26b-a4b-it",
    "mistral-medium-3.5-128b",
    "llama-3.3-70b-instruct",
    "qwen3-235b-a22b-instruct-2507",
    "qwen3-coder-30b-a3b-instruct",
    "qwen3-embedding-8b",
    "pixtral-12b-2409",
    "mistral-small-3.2-24b-instruct-2506",
    "gpt-oss-120b",
    "bge-multilingual-gemma2",
]


VERSION = load_schema_keys(Path(__file__).resolve().parents[1]).version


def make_cfg(url: str = PAGE_URL) -> ProviderCfg:
    return ProviderCfg(
        key="scaleway",
        provider="Scaleway",
        detector="scaleway_page",
        detector_url=url,
        scraper="scaleway_page",
        scraper_url=url,
    )


@pytest.fixture(autouse=True)
def fresh_page_cache():
    # _page caches the parsed soup per url for the pipeline's
    # detect-then-scrape pass; each test serves its own page, so the cache
    # must not leak across tests.
    detector._page.cache_clear()
    yield
    detector._page.cache_clear()


@pytest.fixture
def live_page(monkeypatch: pytest.MonkeyPatch) -> None:
    # the single fetch seam is the detector module's fetch_soup: the scraper
    # shares the detector's cached _page.
    def feed(url: str):
        from bs4 import BeautifulSoup

        return BeautifulSoup(FIXTURE.read_text(), "html.parser")

    monkeypatch.setattr(detector, "fetch_soup", feed)


_TABLE_HEADER = (
    "<tr><th><button><span>Name</span></button></th>"
    "<th><button><span>Tasks</span></button></th>"
    "<th><button><span>Input tokens</span></button></th>"
    "<th><button><span>Output tokens</span></button></th>"
    "<th></th></tr>"
)


def table(*rows: str) -> str:
    return (
        '<table><caption class="sr-only">Generative API</caption>'
        f"<thead>{_TABLE_HEADER}</thead><tbody>{''.join(rows)}</tbody></table>"
    )


def row(slug: str, input_cell: str, output_cell: str, *, with_link: bool = True) -> str:
    try_cell = ""
    if with_link:
        try_cell = (
            f"<a href='https://console.scaleway.com/generative-api/"
            f"models/fr-par/playground?modelName={slug}'>Try</a>"
        )
    return (
        f"<tr><td colspan='1'>{slug}</td><td colspan='1'>Chat</td>"
        f"<td colspan='1'><span class='white'>{input_cell}</span></td>"
        f"<td colspan='1'><span class='white'>{output_cell}</span></td>"
        f"<td colspan='1'>{try_cell}</td></tr>"
    )


def serve(monkeypatch: pytest.MonkeyPatch, html: str) -> None:
    from bs4 import BeautifulSoup

    monkeypatch.setattr(detector, "fetch_soup", lambda url: BeautifulSoup(html, "html.parser"))


def test_detect_ids(live_page):
    assert detector.detect(make_cfg()) == EXPECTED_IDS


def test_detect_skips_audio_rows(live_page):
    # whisper is priced per audio minute, a known unpriced form for a
    # per-token pair; it must not read as a delisting later
    ids = detector.detect(make_cfg())
    assert "whisper-large-v3" not in ids


def test_fixture_holds_the_complete_table():
    # the fixture is a byte slice of the capture; pin its shape so a future
    # trim cannot cut the last row's Try link mid-anchor again
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(FIXTURE.read_text(), "html.parser")
    table = soup.find("table")
    rows = table.find("tbody").find_all("tr", recursive=False)
    assert len(rows) == 15
    last_cells = rows[-1].find_all("td")
    assert last_cells[0].get_text(" ", strip=True) == "bge-multilingual-gemma2"
    link = last_cells[4].find("a", href=True)
    assert link is not None
    assert link["href"].endswith("modelName=bge-multilingual-gemma2")


def test_scrape_last_row_via_try_link(live_page):
    # the capture's last row carries its Try link like every other row;
    # the id cross-check must not be skipped for it
    pricing = scraper.scrape(make_cfg(), "bge-multilingual-gemma2")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.10 / 1e6)
    assert pricing.output_cost_per_token == 0.0


def test_scrape_empty_try_cell_falls_back_to_name(monkeypatch: pytest.MonkeyPatch):
    # a priced row without a Try link still resolves its id from the Name
    # cell (parse_id fallback); the link is a cross-check, not the source
    text = table(
        row("glm-5.2", "€1.80 / million tokens", "€5.50 / million tokens", with_link=False)
    )
    serve(monkeypatch, text)
    pricing = scraper.scrape(make_cfg(), "glm-5.2")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1.80 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(5.50 / 1e6)


def test_scrape_glm_5_2(live_page):
    pricing = scraper.scrape(make_cfg(), "glm-5.2")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1.80 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(5.50 / 1e6)
    assert pricing.cache_read_cost_per_token is None
    assert pricing.currency == "EUR"
    assert pricing.unit == "tokens"
    assert pricing.mode == "chat"
    assert pricing.max_tokens_in == 0
    assert pricing.peak_input_cost_per_token is None


def test_scrape_cached_input(live_page):
    pricing = scraper.scrape(make_cfg(), "deepseek-v4-flash-0731")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.40 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.08 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.80 / 1e6)
    assert pricing.currency == "EUR"


def test_scrape_free_output_is_zero_rate(live_page):
    # embeddings quote Free for output; a zero rate beside a priced input
    # scrapes normally (the google embeddings convention)
    pricing = scraper.scrape(make_cfg(), "qwen3-embedding-8b")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.10 / 1e6)
    assert pricing.output_cost_per_token == 0.0


def test_scrape_audio_row_returns_none(live_page):
    assert scraper.scrape(make_cfg(), "whisper-large-v3") is None


def test_scrape_unknown_model_returns_none(live_page):
    assert scraper.scrape(make_cfg(), "glm-5.3") is None


def test_detect_zero_rate_rows_emitted(monkeypatch: pytest.MonkeyPatch):
    # a stored free model must stay mapped, or absence would count it and
    # open a phantom delisting; the scraper decides instead
    text = table(
        row("free-model", "Free", "Free"),
        row("glm-5.2", "€1.80 / million tokens", "€5.50 / million tokens"),
    )
    serve(monkeypatch, text)
    assert detector.detect(make_cfg()) == ["free-model", "glm-5.2"]


def test_scrape_both_zero_rates_price_zero(monkeypatch: pytest.MonkeyPatch):
    # free is a price: a fully free row scrapes as a 0.0/0.0 pair, never None
    text = table(row("free-model", "Free", "Free"))
    serve(monkeypatch, text)
    pricing = scraper.scrape(make_cfg(), "free-model")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.0
    assert pricing.output_cost_per_token == 0.0


def test_detect_unknown_input_shape_skips_with_warning(monkeypatch: pytest.MonkeyPatch, caplog):
    # a drifted input-cell shape is additive drift: the row skips with a
    # warning naming the cell, and the well-shaped rows still emit
    text = table(
        row("glm-5.3", "€0.15 per 1M input", "€5.50 / million tokens"),
        row("glm-5.2", "€1.80 / million tokens", "€5.50 / million tokens"),
    )
    serve(monkeypatch, text)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == ["glm-5.2"]
    assert "detect skip for scaleway" in caplog.text
    assert "unreadable input price cell" in caplog.text


def test_detect_unknown_output_shape_skips_with_warning(monkeypatch: pytest.MonkeyPatch, caplog):
    text = table(
        row("glm-5.3", "€1.80 / million tokens", "€5.50 per 1M output"),
        row("glm-5.2", "€1.80 / million tokens", "€5.50 / million tokens"),
    )
    serve(monkeypatch, text)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == ["glm-5.2"]
    assert "detect skip for scaleway" in caplog.text
    assert "unreadable output price cell" in caplog.text


def test_detect_id_link_mismatch_skips_with_warning(monkeypatch: pytest.MonkeyPatch, caplog):
    # a Try-link disagreement is additive drift: the row skips with a
    # warning and the well-shaped rows still emit
    text = table(
        row("glm-5.3", "€1.80 / million tokens", "€5.50 / million tokens"),
        row("glm-5.2", "€1.80 / million tokens", "€5.50 / million tokens"),
    ).replace("modelName=glm-5.3", "modelName=glm-5.2")
    serve(monkeypatch, text)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == ["glm-5.2"]
    assert "detect skip for scaleway" in caplog.text
    assert "modelName disagrees" in caplog.text


def test_detect_header_wording_drift_still_locates_table(monkeypatch: pytest.MonkeyPatch):
    # the header pins fold case and whitespace: wording drift must not read
    # as a missing table
    drifted = (
        "<tr><th><button><span>name</span></button></th>"
        "<th><button><span> TASKS </span></button></th>"
        "<th><button><span>Input  Tokens</span></button></th>"
        "<th><button><span>output tokens</span></button></th>"
        "<th></th></tr>"
    )
    text = table(row("glm-5.2", "€1.80 / million tokens", "€5.50 / million tokens")).replace(
        _TABLE_HEADER, drifted
    )
    serve(monkeypatch, text)
    assert detector.detect(make_cfg()) == ["glm-5.2"]


def test_scrape_unrelated_id_mismatch_tolerated(monkeypatch: pytest.MonkeyPatch):
    # a Try-link disagreement on another model's row is additive drift
    # detection already reported; the match scan passes it over
    text = table(
        row("glm-5.3", "€1.80 / million tokens", "€5.50 / million tokens"),
        row("glm-5.2", "€1.80 / million tokens", "€5.50 / million tokens"),
    ).replace("modelName=glm-5.3", "modelName=glm-5.2")
    serve(monkeypatch, text)
    pricing = scraper.scrape(make_cfg(), "glm-5.2")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1.80 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(5.50 / 1e6)


def test_scrape_matched_row_unknown_input_shape_raises(monkeypatch: pytest.MonkeyPatch):
    # the matched row's cells are strict: a drifted input shape raises, it
    # must not read as the model missing
    text = table(row("glm-5.2", "€0.15 per 1M input", "€5.50 / million tokens"))
    serve(monkeypatch, text)
    with pytest.raises(FetchError, match="unreadable input price cell"):
        scraper.scrape(make_cfg(), "glm-5.2")


def test_detect_missing_table_raises(monkeypatch: pytest.MonkeyPatch):
    serve(monkeypatch, "<html><body><table><caption>Other</caption></table></body></html>")
    with pytest.raises(FetchError, match="no generative-api pricing table"):
        detector.detect(make_cfg())


def test_detect_no_priced_rows_raises(monkeypatch: pytest.MonkeyPatch):
    text = table(row("whisper-large-v3", "€0.003 / Audio minute", "Free"))
    serve(monkeypatch, text)
    with pytest.raises(FetchError, match="no per-token model rows"):
        detector.detect(make_cfg())


def test_dedup_keys_dated_snapshots():
    # dated slug spellings map to the base id the store holds: openrouter
    # carries deepseek/deepseek-v4-flash as a base id, and the openrouter
    # fixture's canonical_slug facts name
    # mistralai/mistral-small-3.2-24b-instruct-2506 as the dated variant of
    # mistralai/mistral-small-3.2-24b-instruct, measured 2026-08-29
    assert scraper.dedup_keys("deepseek-v4-flash-0731") == ("deepseek-v4-flash",)
    assert scraper.dedup_keys("mistral-small-3.2-24b-instruct-2506") == (
        "mistral-small-3.2-24b-instruct",
    )


def test_dedup_keys_other_ids_return_nothing():
    # pixtral-12b-2409 keeps its suffix: it is mistral's canonical release
    # name (codestral-2508 carries the same shape as an openrouter id), not
    # a dated snapshot of a pixtral-12b base. the qwen spelling passes
    # through unchanged: no source stores a qwen3-235b-a22b-instruct base
    # (openrouter holds qwen3-235b-a22b / -2507 / -thinking-2507 only)
    for model_id in (
        "glm-5.2",
        "gpt-oss-120b",
        "pixtral-12b-2409",
        "qwen3.5-397b-a17b",
        "qwen3-235b-a22b-instruct-2507",
    ):
        assert scraper.dedup_keys(model_id) == (), model_id


def test_build_row_converts_eur_quote_to_usd(live_page):
    pricing = scraper.scrape(make_cfg(), "glm-5.2")
    assert pricing is not None
    resolve = partial(resolve_rate, {"EUR": {"2026-08-28": 1.1643}}, None)
    row = build_row(
        "scaleway", "glm-5.2", pricing, "2026-08-28", PAGE_URL, VERSION, resolve=resolve
    )
    assert list(row) == [
        "schema",
        "source",
        "model_id",
        "observed_at",
        "currency",
        "rates",
        "provenance",
    ]
    assert row["currency"] == "EUR"
    assert row["provenance"]["fx_rate"] == 1.1643
    assert row["provenance"]["fx_rate_date"] == "2026-08-28"
    assert row["rates"]["input"] == pytest.approx(1.80 * 1.1643)
    assert row["rates"]["output"] == pytest.approx(5.50 * 1.1643)
    assert row["provenance"]["url"] == PAGE_URL

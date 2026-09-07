"""databricks pricing pair tests, pinned against the saved live pricing page.

the fixture is the full 2026-09-07 capture of the foundation-model-serving
pricing page. the per-token rates live in two tables ("Standard Pay Per
Token" and "Priority Pay Per Token", each `Input | Output | Cache read`);
the page carries display names only, so ids resolve through the detector's
display-name mapping.
"""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path

import pytest

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import databricks_page as detector
from ai_pricelog.scrapers import databricks_page as scraper
from ai_pricelog.store import build_row, resolve_rate
from ai_pricelog.validate import load_schema_keys
from ai_pricelog.web import FetchError

PAGE_URL = "https://www.databricks.com/product/pricing/foundation-model-serving"
FIXTURE = Path(__file__).parent / "fixtures" / "databricks_page" / "pricing.html"

# every priced row across the two per-token tables, page order; the merged
# "GLM-5.2, 5.3" row covers both store ids at one rate pair; the Priority
# table rows carry "-priority" ids; embedding rows emit with output 0.0
EXPECTED_IDS = [
    "kimi-k3",
    "glm-5.2",
    "glm-5.3",
    "deepseek-v4-pro",
    "inkling",
    "kimi-k2.7",
    "glm-5.3-flash",
    "deepseek-v4-flash",
    "qwen3.5-122b-a10b",
    "llama-4-maverick",
    "llama-3.3-70b-instruct",
    "qwen3-next-80b-a3b-instruct",
    "gpt-oss-120b",
    "gemma-3-12b-it",
    "llama-3.1-8b-instruct",
    "gpt-oss-20b",
    "gte",
    "bge-large",
    "qwen3-embedding-0.6b",
    "glm-5.2-priority",
    "qwen3.5-122b-a10b-priority",
]


VERSION = load_schema_keys(Path(__file__).resolve().parents[1]).version


def make_cfg(url: str = PAGE_URL) -> ProviderCfg:
    return ProviderCfg(
        key="databricks",
        provider="Databricks",
        detector="databricks_page",
        detector_url=url,
        scraper="databricks_page",
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


# the two watched tables share the header shape: a "Model" + tier-span first
# row, then the Input | Output | Cache read sub-header. _model_tables pins
# the sub-header (which excludes the per-hour Provisioned Throughput table)
# and the two-row header shape (which excludes the single-row Batch
# Inference table); the tier span decides which watched table a row is in.
_STANDARD_HEADER = (
    "<tr><th rowspan='2'>Model</th><th colspan='3'>"
    "Standard Pay Per Token (DBU Per 1M Tokens)</th></tr>"
    "<tr><th>Input</th><th>Output</th><th>Cache read</th></tr>"
)
_PRIORITY_HEADER = (
    "<tr><th rowspan='2'>Model</th><th colspan='3'>"
    "Priority Pay Per Token (DBU Per 1M Tokens)</th></tr>"
    "<tr><th>Input</th><th>Output</th><th>Cache read</th></tr>"
)
_HOURLY_HEADER = (
    "<tr><th rowspan='2'>Model</th><th colspan='3'>Provisioned Throughput"
    " (DBU Per Hour)</th></tr>"
    "<tr><th>On-demand</th><th>1 month reservation</th><th>3 month reservation</th></tr>"
)


def table(header: str, *rows: str) -> str:
    return f"<table class='table'><thead>{header}</thead><tbody>{''.join(rows)}</tbody></table>"


def row(
    name: str,
    input_cell: str,
    output_cell: str,
    cache_cell: str = "-",
) -> str:
    return (
        f"<tr><td>{name}</td><td class='!text-center'>{input_cell}</td>"
        f"<td class='!text-center'>{output_cell}</td>"
        f"<td class='!text-center'>{cache_cell}</td></tr>"
    )


def serve(monkeypatch: pytest.MonkeyPatch, html: str) -> None:
    from bs4 import BeautifulSoup

    monkeypatch.setattr(detector, "fetch_soup", lambda url: BeautifulSoup(html, "html.parser"))


def _detect_serve(monkeypatch: pytest.MonkeyPatch, tables: list[str]) -> None:
    serve(monkeypatch, "<html><body>" + "".join(tables) + "</body></html>")


def test_detect_ids(live_page):
    assert detector.detect(make_cfg()) == EXPECTED_IDS


def test_detect_merged_glm_row_covers_both_store_ids(live_page):
    # the "GLM-5.2, 5.3" row carries one rate pair covering two store ids;
    # dropping either would phantom-delist a live model
    ids = detector.detect(make_cfg())
    assert "glm-5.2" in ids and "glm-5.3" in ids


def test_detect_matches_both_pay_per_token_tables(monkeypatch: pytest.MonkeyPatch):
    # both watched tables pin the Input | Output | Cache read sub-header; the
    # per-hour table never matches the pin (its sub-header names reservation
    # terms), so only the standard and priority tables yield rows
    _detect_serve(
        monkeypatch,
        [
            table(_STANDARD_HEADER, row("GLM-5.2, 5.3", "20.000", "62.857", "3.714")),
            table(_PRIORITY_HEADER, row("GLM-5.2", "35.000", "110.000", "6.500")),
            table(_HOURLY_HEADER, row("GLM-5.2, 5.3", "142.857", "-", "-")),
        ],
    )
    assert detector.detect(make_cfg()) == ["glm-5.2", "glm-5.3", "glm-5.2-priority"]


def test_detect_skips_dash_rate_rows(monkeypatch: pytest.MonkeyPatch):
    # the per-token tables mark unpriced cells with "-": a model whose
    # input cell reads "-" carries no per-token pricing and skips silently,
    # the n/a convention of the old table
    _detect_serve(
        monkeypatch,
        [
            table(
                _STANDARD_HEADER,
                row("GTE", "-", "-", "-"),
                row("GLM-5.2, 5.3", "20.000", "62.857", "3.714"),
            )
        ],
    )
    assert detector.detect(make_cfg()) == ["glm-5.2", "glm-5.3"]


def test_detect_hourly_table_alone_raises(monkeypatch: pytest.MonkeyPatch):
    # a page whose per-token tables are gone still raises (structural
    # absence, plan #22): the per-hour table shares the two-header shape
    # but its sub-header names reservation terms
    _detect_serve(monkeypatch, [table(_HOURLY_HEADER, row("GLM-5.2", "142.857", "-", "-"))])
    with pytest.raises(FetchError, match="no foundation-model-serving dbu table"):
        detector.detect(make_cfg())


def test_detect_reworded_tier_span_raises(monkeypatch: pytest.MonkeyPatch):
    # the tier pin matches one of the two known wordings or raises: the
    # tables share display names, so a priority row read under the standard
    # mapping silently dedupes its base id away instead of pinging
    header = (
        "<tr><th rowspan='2'>Model</th><th colspan='3'>"
        "Priority Pay Per Token (DBU Per 1M Tokens) (beta)</th></tr>"
        "<tr><th>Input</th><th>Output</th><th>Cache read</th></tr>"
    )
    _detect_serve(
        monkeypatch,
        [
            table(_STANDARD_HEADER, row("GLM-5.2, 5.3", "20.000", "62.857", "3.714")),
            table(header, row("Qwen 3.5 122B", "6.286", "62.857", "-")),
        ],
    )
    with pytest.raises(FetchError, match="unreadable pay-per-token tier span"):
        detector.detect(make_cfg())


def test_scrape_kimi_k3(live_page):
    pricing = scraper.scrape(make_cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(42.857 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(214.286 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(4.286 / 1e6)
    assert pricing.currency == "DBU"
    assert pricing.unit == "tokens"
    assert pricing.mode == "chat"
    assert pricing.max_tokens_in == 0


def test_scrape_glm_5_2(live_page):
    pricing = scraper.scrape(make_cfg(), "glm-5.2")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(20.000 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(62.857 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(3.714 / 1e6)
    assert pricing.currency == "DBU"


def test_scrape_glm_5_3_matches_merged_row(live_page):
    # glm-5.3 shares the merged "GLM-5.2, 5.3" row's rates
    pricing = scraper.scrape(make_cfg(), "glm-5.3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(20.000 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(62.857 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(3.714 / 1e6)


def test_scrape_glm_5_3_flash(live_page):
    pricing = scraper.scrape(make_cfg(), "glm-5.3-flash")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(2.143 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(7.143 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.429 / 1e6)


def test_scrape_matched_row_odd_cell_raises(monkeypatch: pytest.MonkeyPatch):
    # the matched row's cells are strict: an unknown shape raises, never
    # reads as unpriced (plan #22)
    text = table(_STANDARD_HEADER, row("Kimi K3", "42.857 DBU", "214.286"))
    serve(monkeypatch, text)
    with pytest.raises(FetchError, match="unreadable dbu rate cell"):
        scraper.scrape(make_cfg(), "kimi-k3")


def test_scrape_skips_unrelated_odd_rows(monkeypatch: pytest.MonkeyPatch):
    text = table(
        _STANDARD_HEADER,
        row("Kimi K3", "42.857 DBU", "214.286"),
        row("GLM-5.2, 5.3", "20.000", "62.857"),
    )
    serve(monkeypatch, text)
    pricing = scraper.scrape(make_cfg(), "glm-5.2")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(20.000 / 1e6)


def test_scrape_skips_unmapped_rows(monkeypatch: pytest.MonkeyPatch):
    text = table(
        _STANDARD_HEADER,
        row("Brand New Model", "20.000", "62.857"),
        row("GLM-5.2, 5.3", "20.000", "62.857"),
    )
    serve(monkeypatch, text)
    pricing = scraper.scrape(make_cfg(), "glm-5.2")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(20.000 / 1e6)


def test_scrape_priority_tier(live_page):
    pricing = scraper.scrape(make_cfg(), "glm-5.2-priority")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(35.000 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(110.000 / 1e6)


def test_scrape_priority_table_row_never_matches_base_id(monkeypatch: pytest.MonkeyPatch):
    # the base id's row scan must stay scoped to the standard table: the
    # priority table's GLM-5.2 row must not answer a glm-5.2 scrape
    text = table(_PRIORITY_HEADER, row("GLM-5.2", "35.000", "110.000", "6.500"))
    serve(monkeypatch, text)
    assert scraper.scrape(make_cfg(), "glm-5.2") is None


def test_scrape_without_cache_read(live_page):
    pricing = scraper.scrape(make_cfg(), "gpt-oss-120b")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(2.143 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(8.571 / 1e6)
    assert pricing.cache_read_cost_per_token is None


def test_scrape_embedding_rows_have_zero_output(live_page):
    # embedding rows quote "-" output (no output billing) and scrape with a
    # zero output rate, the google embeddings convention
    gte = scraper.scrape(make_cfg(), "gte")
    assert gte is not None
    assert gte.input_cost_per_token == pytest.approx(1.857 / 1e6)
    assert gte.output_cost_per_token == 0.0
    assert gte.cache_read_cost_per_token is None
    bge = scraper.scrape(make_cfg(), "bge-large")
    assert bge is not None
    assert bge.input_cost_per_token == pytest.approx(1.429 / 1e6)
    assert bge.output_cost_per_token == 0.0
    qwen = scraper.scrape(make_cfg(), "qwen3-embedding-0.6b")
    assert qwen is not None
    assert qwen.input_cost_per_token == pytest.approx(0.286 / 1e6)
    assert qwen.output_cost_per_token == 0.0


def test_scrape_unknown_model_returns_none(live_page):
    assert scraper.scrape(make_cfg(), "glm-6") is None


def test_scrape_dash_input_returns_none(monkeypatch: pytest.MonkeyPatch):
    # the matched row's "-" input cell means the model carries no
    # per-token pricing: None, never a priced row
    text = table(
        _STANDARD_HEADER,
        row("GLM-5.2, 5.3", "-", "-", "-"),
        row("Kimi K3", "42.857", "214.286", "4.286"),
    )
    serve(monkeypatch, text)
    assert scraper.scrape(make_cfg(), "glm-5.2") is None


def test_detect_zero_rate_rows_emitted(monkeypatch: pytest.MonkeyPatch):
    # a stored free model must stay mapped, or absence would count it and
    # open a phantom delisting; the scraper decides instead
    text = table(
        _STANDARD_HEADER,
        row("GLM-5.2, 5.3", "0.000", "0.000"),
        row("GPT-OSS-120B", "2.143", "8.571"),
    )
    serve(monkeypatch, text)
    assert detector.detect(make_cfg()) == ["glm-5.2", "glm-5.3", "gpt-oss-120b"]


def test_scrape_both_zero_rates_price_zero(monkeypatch: pytest.MonkeyPatch):
    # free is a price: a fully free row scrapes as a 0.0/0.0 pair, never None
    text = table(_STANDARD_HEADER, row("GLM-5.2, 5.3", "0.000", "0.000"))
    serve(monkeypatch, text)
    pricing = scraper.scrape(make_cfg(), "glm-5.2")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.0
    assert pricing.output_cost_per_token == 0.0


def test_detect_unknown_rate_shape_skips(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # a drifted rate-cell shape is additive drift: the row skips with a
    # warning (plan #22); the scrape-side strictness for the matched row
    # is the wrong-data guard
    text = table(
        _STANDARD_HEADER,
        row("GLM-5.2", "20.000 DBU", "62.857"),
        row("Kimi K3", "42.857", "214.286"),
    )
    serve(monkeypatch, text)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == ["kimi-k3"]
    assert "unreadable dbu rate cell" in caplog.text


def test_detect_unknown_output_shape_skips(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    text = table(
        _STANDARD_HEADER,
        row("GLM-5.2", "20.000", "62.857 DBU"),
        row("Kimi K3", "42.857", "214.286"),
    )
    serve(monkeypatch, text)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == ["kimi-k3"]
    assert "unreadable dbu rate cell" in caplog.text


def test_detect_unknown_cache_shape_skips(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    text = table(
        _STANDARD_HEADER,
        row("GLM-5.2", "20.000", "62.857", "3.714 DBU"),
        row("Kimi K3", "42.857", "214.286"),
    )
    serve(monkeypatch, text)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == ["kimi-k3"]
    assert "unreadable dbu rate cell" in caplog.text


def test_detect_unmapped_name_skips(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # a priced row whose display name the mapping does not hold skips with
    # a warning; one new model can no longer blind the provider (plan #22)
    text = table(
        _STANDARD_HEADER,
        row("Brand New Model", "20.000", "62.857"),
        row("GLM-5.2, 5.3", "20.000", "62.857"),
    )
    serve(monkeypatch, text)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == ["glm-5.2", "glm-5.3"]
    assert "unmapped model name" in caplog.text


def test_detect_all_rows_skipped_raises(monkeypatch: pytest.MonkeyPatch):
    text = table(_STANDARD_HEADER, row("GLM-5.2", "20.000 DBU", "62.857"))
    serve(monkeypatch, text)
    with pytest.raises(FetchError, match="no per-token model rows"):
        detector.detect(make_cfg())


def test_detect_missing_table_raises(monkeypatch: pytest.MonkeyPatch):
    serve(monkeypatch, "<html><body><table><tr><td>a</td></tr></table></body></html>")
    with pytest.raises(FetchError, match="no foundation-model-serving dbu table"):
        detector.detect(make_cfg())


def test_detect_no_priced_rows_raises(monkeypatch: pytest.MonkeyPatch):
    text = table(
        _STANDARD_HEADER,
        row("GLM-5.2", "-", "-"),
        row("Kimi K3", "-", "-"),
    )
    serve(monkeypatch, text)
    with pytest.raises(FetchError, match="no per-token model rows"):
        detector.detect(make_cfg())


def test_dedup_keys_dated_snapshots():
    # the page dropped the deepseek snapshot dates in the 2026-09-05
    # restructure; the base page spelling maps to the dated stored spelling
    # its rows live under (the pipeline calls dedup_keys with page ids), so
    # the era track continues instead of forking
    assert scraper.dedup_keys("deepseek-v4-pro") == ("deepseek-v4-pro-0813",)
    assert scraper.dedup_keys("deepseek-v4-flash") == ("deepseek-v4-flash-0731",)


def test_dedup_keys_other_ids_return_nothing():
    # priority tiers are tiers, not dated snapshots of the base model
    for model_id in ("glm-5.2", "glm-5.2-priority", "kimi-k3", "qwen3.5-122b-a10b"):
        assert scraper.dedup_keys(model_id) == (), model_id


def test_build_row_converts_dbu_quote_via_provider_rate(live_page):
    pricing = scraper.scrape(make_cfg(), "kimi-k3")
    assert pricing is not None
    resolve = partial(resolve_rate, {}, 0.07)
    row = build_row(
        "databricks", "kimi-k3", pricing, "2026-08-28", PAGE_URL, VERSION, resolve=resolve
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
    assert row["currency"] == "DBU"
    assert row["provenance"]["fx_rate"] == 0.07
    assert row["provenance"]["fx_rate_date"] == "2026-08-28"
    assert row["rates"]["input"] == pytest.approx(42.857 * 0.07)
    assert row["rates"]["output"] == pytest.approx(214.286 * 0.07)
    assert row["rates"]["cache_read"] == pytest.approx(4.286 * 0.07)
    assert row["provenance"]["url"] == PAGE_URL

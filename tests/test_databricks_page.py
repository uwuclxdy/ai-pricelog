"""databricks pricing pair tests, pinned against the saved live pricing page.

the fixture is the full 2026-08-28 capture of the foundation-model-serving
pricing page. the table carries display names only, so ids resolve through
the detector's display-name mapping.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

import pytest

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import databricks_page as detector
from ai_pricelog.scrapers import databricks_page as scraper
from ai_pricelog.store import build_row, resolve_rate
from ai_pricelog.web import FetchError

PAGE_URL = "https://www.databricks.com/product/pricing/foundation-model-serving"
FIXTURE = Path(__file__).parent / "fixtures" / "databricks_page" / "pricing.html"

# every fixture row with a numeric input DBU rate, page order; embedding
# rows carry a numeric input and "n/a" output (no output billing) and emit
# with an output rate of 0.0; provisioned-only rows (all n/a) are skipped
EXPECTED_IDS = [
    "kimi-k3",
    "kimi-k2.7",
    "glm-5.2",
    "glm-5.2-priority",
    "inkling",
    "deepseek-v4-pro-0813",
    "deepseek-v4-flash-0731",
    "qwen3.5-122b-a10b",
    "qwen3.5-122b-a10b-priority",
    "qwen3-next-80b-a3b-instruct",
    "gpt-oss-120b",
    "gpt-oss-20b",
    "llama-4-maverick",
    "llama-3.3-70b-instruct",
    "gemma-3-12b-it",
    "llama-3.1-8b-instruct",
    "qwen3-embedding-0.6b",
    "gte",
    "bge-large",
]


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


_TABLE_HEADER = (
    "<tr><th rowspan='2'>Model</th><th colspan='3'>Pay-Per-Token</th>"
    "<th colspan='2'>Provisioned Throughput</th></tr>"
    "<tr><th>DBU / M input tokens</th><th>DBU / M output tokens</th>"
    "<th>DBU / M cache read tokens</th>"
    "<th>DBU / hour (entry capacity)</th><th>DBU / hour (scaling capacity)</th></tr>"
)


def table(*rows: str) -> str:
    return (
        f"<table class='table'><thead>{_TABLE_HEADER}</thead><tbody>{''.join(rows)}</tbody></table>"
    )


def row(
    name: str,
    input_cell: str,
    output_cell: str,
    cache_cell: str = "n/a",
    entry_cell: str = "n/a",
    scaling_cell: str = "n/a",
) -> str:
    return (
        f"<tr><td>{name}</td><td class='!text-center'>{input_cell}</td>"
        f"<td class='!text-center'>{output_cell}</td>"
        f"<td class='!text-center'>{cache_cell}</td>"
        f"<td class='!text-center'>{entry_cell}</td>"
        f"<td class='!text-center'>{scaling_cell}</td></tr>"
    )


def serve(monkeypatch: pytest.MonkeyPatch, html: str) -> None:
    from bs4 import BeautifulSoup

    monkeypatch.setattr(detector, "fetch_soup", lambda url: BeautifulSoup(html, "html.parser"))


def test_detect_ids(live_page):
    assert detector.detect(make_cfg()) == EXPECTED_IDS


def test_detect_skips_unpriced_rows(live_page):
    # provisioned-only rows (all n/a) carry no per-token input and are
    # skipped; the regional-uplift marker strips off the Kimi name
    ids = detector.detect(make_cfg())
    for absent in ("llama-3.2-3b-instruct", "llama-3.2-1b-instruct"):
        assert absent not in ids
    assert "kimi-k3" in ids


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


def test_scrape_priority_tier(live_page):
    pricing = scraper.scrape(make_cfg(), "glm-5.2-priority")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(35.000 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(110.000 / 1e6)


def test_scrape_without_cache_read(live_page):
    pricing = scraper.scrape(make_cfg(), "gpt-oss-120b")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(2.143 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(8.571 / 1e6)
    assert pricing.cache_read_cost_per_token is None


def test_scrape_embedding_rows_have_zero_output(live_page):
    # embedding rows quote "n/a" output (no output billing) and scrape with
    # a zero output rate, the google embeddings convention
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


def test_scrape_unpriced_rows_return_none(live_page):
    assert scraper.scrape(make_cfg(), "llama-3.2-3b-instruct") is None


def test_scrape_unknown_model_returns_none(live_page):
    assert scraper.scrape(make_cfg(), "glm-5.3") is None


def test_detect_zero_rate_rows_emitted(monkeypatch: pytest.MonkeyPatch):
    # a stored free model must stay mapped, or absence would count it and
    # open a phantom delisting; the scraper decides instead
    text = table(
        row("GLM-5.2", "0.000", "0.000"),
        row("GPT OSS 120B", "2.143", "8.571"),
    )
    serve(monkeypatch, text)
    assert detector.detect(make_cfg()) == ["glm-5.2", "gpt-oss-120b"]


def test_scrape_both_zero_rates_price_zero(monkeypatch: pytest.MonkeyPatch):
    # free is a price: a fully free row scrapes as a 0.0/0.0 pair, never None
    text = table(row("GLM-5.2", "0.000", "0.000"))
    serve(monkeypatch, text)
    pricing = scraper.scrape(make_cfg(), "glm-5.2")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.0
    assert pricing.output_cost_per_token == 0.0


def test_detect_unknown_rate_shape_raises(monkeypatch: pytest.MonkeyPatch):
    # a drifted rate-cell shape must fail the run, never read as an
    # unpriced row (two such runs would open a phantom delisting pr)
    text = table(row("GLM-5.2", "20.000 DBU", "62.857"))
    serve(monkeypatch, text)
    with pytest.raises(FetchError, match="unreadable dbu rate cell"):
        detector.detect(make_cfg())


def test_detect_unknown_output_shape_raises(monkeypatch: pytest.MonkeyPatch):
    # the same _rate path for the output column: only numeric and "n/a"
    # are known shapes
    text = table(row("GLM-5.2", "20.000", "62.857 DBU"))
    serve(monkeypatch, text)
    with pytest.raises(FetchError, match="unreadable dbu rate cell"):
        detector.detect(make_cfg())


def test_detect_unknown_cache_shape_raises(monkeypatch: pytest.MonkeyPatch):
    text = table(row("GLM-5.2", "20.000", "62.857", "3.714 DBU"))
    serve(monkeypatch, text)
    with pytest.raises(FetchError, match="unreadable dbu rate cell"):
        detector.detect(make_cfg())


def test_detect_unmapped_name_raises(monkeypatch: pytest.MonkeyPatch):
    # a priced row whose display name the mapping does not hold must fail
    # the run, never emit an invented id
    text = table(row("Brand New Model", "20.000", "62.857"))
    serve(monkeypatch, text)
    with pytest.raises(FetchError, match="unmapped model name"):
        detector.detect(make_cfg())


def test_detect_missing_table_raises(monkeypatch: pytest.MonkeyPatch):
    serve(monkeypatch, "<html><body><table><tr><td>a</td></tr></table></body></html>")
    with pytest.raises(FetchError, match="no foundation-model-serving dbu table"):
        detector.detect(make_cfg())


def test_detect_no_priced_rows_raises(monkeypatch: pytest.MonkeyPatch):
    text = table(row("GLM-5.2", "n/a", "n/a"), row("Kimi K3", "n/a", "n/a"))
    serve(monkeypatch, text)
    with pytest.raises(FetchError, match="no per-token model rows"):
        detector.detect(make_cfg())


def test_dedup_keys_dated_snapshots():
    # display names with a snapshot date map to the base id the store
    # holds; openrouter carries both base and dated ids, measured 2026-08-29
    assert scraper.dedup_keys("deepseek-v4-pro-0813") == ("deepseek-v4-pro",)
    assert scraper.dedup_keys("deepseek-v4-flash-0731") == ("deepseek-v4-flash",)


def test_dedup_keys_other_ids_return_nothing():
    # priority tiers are tiers, not dated snapshots of the base model
    for model_id in ("glm-5.2", "glm-5.2-priority", "kimi-k3", "qwen3.5-122b-a10b"):
        assert scraper.dedup_keys(model_id) == (), model_id


def test_build_row_converts_dbu_quote_via_provider_rate(live_page):
    pricing = scraper.scrape(make_cfg(), "kimi-k3")
    assert pricing is not None
    resolve = partial(resolve_rate, {}, 0.07)
    row = build_row("databricks", "kimi-k3", pricing, "2026-08-28", PAGE_URL, resolve=resolve)
    assert list(row) == [
        "source",
        "model_id",
        "observed_at",
        "currency",
        "currency_rate",
        "currency_rate_date",
        "input_mtok",
        "output_mtok",
        "cache_read_mtok",
        "url",
    ]
    assert row["currency"] == "DBU"
    assert row["currency_rate"] == 0.07
    assert row["currency_rate_date"] == "2026-08-28"
    assert row["input_mtok"] == pytest.approx(42.857 * 0.07)
    assert row["output_mtok"] == pytest.approx(214.286 * 0.07)
    assert row["cache_read_mtok"] == pytest.approx(4.286 * 0.07)
    assert row["url"] == PAGE_URL

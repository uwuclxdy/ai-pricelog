"""databricks pricing pair tests, pinned against the saved live pricing page.

the fixture is the full 2026-10-14 capture of the foundation-model-serving
pricing page. the per-token rates live in two tables ("Pay Per Token" and
"Priority Pay Per Token", each `Input | Output | Cache read`; the standard
table's span read "Standard Pay Per Token" until the page dropped the
qualifier, by 2026-10-06); the page carries display names only, so ids
resolve through the detector's display-name mapping.
"""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path

import pytest

from ai_pricelog import health
from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import databricks_page as detector
from ai_pricelog.scrapers import databricks_page as scraper
from ai_pricelog.store import build_row, resolve_rate
from ai_pricelog.validate import load_schema_keys
from ai_pricelog.web import FetchError

PAGE_URL = "https://www.databricks.com/product/pricing/foundation-model-serving"
FIXTURE = Path(__file__).parent / "fixtures" / "databricks_page" / "pricing.html"

# every priced row across the two per-token tables, page order; the merged
# "GLM-5.2, 5.3" row covers both store ids at one rate pair in EACH table;
# the Priority table rows carry "-priority" ids; embedding rows emit with
# output 0.0
EXPECTED_IDS = [
    "kimi-k3",
    "glm-5.2",
    "glm-5.3",
    "deepseek-v4-pro",
    "inkling",
    "kimi-k2.7",
    "glm-5.3-flash",
    "deepseek-v4.1-flash",
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
    "kimi-k3-priority",
    "glm-5.2-priority",
    "glm-5.3-priority",
    "glm-5.3-flash-priority",
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
            table(
                _STANDARD_HEADER,
                row("GTE", "1.857", "-", "-"),
                row("GLM-5.2, 5.3", "20.000", "62.857", "3.714"),
            ),
            table(_PRIORITY_HEADER, row("GLM-5.2, 5.3", "35.000", "110.000", "6.500")),
            table(_HOURLY_HEADER, row("GLM-5.2, 5.3", "142.857", "-", "-")),
        ],
    )
    assert detector.detect(make_cfg()) == [
        "gte",
        "glm-5.2",
        "glm-5.3",
        "glm-5.2-priority",
        "glm-5.3-priority",
    ]


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
                row("BGE Large", "1.000", "-", "-"),
                row("GLM-5.2, 5.3", "20.000", "62.857", "3.714"),
            )
        ],
    )
    assert detector.detect(make_cfg()) == ["bge-large", "glm-5.2", "glm-5.3"]


def test_detect_hourly_table_alone_raises(monkeypatch: pytest.MonkeyPatch):
    # a page whose per-token tables are gone still raises (structural
    # absence, plan #22): the per-hour table shares the two-header shape
    # but its sub-header names reservation terms
    _detect_serve(monkeypatch, [table(_HOURLY_HEADER, row("GLM-5.2", "142.857", "-", "-"))])
    with pytest.raises(FetchError, match="no foundation-model-serving dbu table"):
        detector.detect(make_cfg())


def test_detect_unqualified_span_is_the_standard_tier(monkeypatch: pytest.MonkeyPatch):
    # the page dropped the standard table's "Standard" qualifier (issue 458):
    # the bare span still names the standard tier, so its rows keep their
    # base ids while the priority table keeps its "-priority" ids
    unqualified = _STANDARD_HEADER.replace("Standard Pay Per Token", "Pay Per Token")
    assert unqualified != _STANDARD_HEADER
    _detect_serve(
        monkeypatch,
        [
            table(
                unqualified,
                row("GTE", "1.857", "-", "-"),
                row("GLM-5.2, 5.3", "20.000", "62.857", "3.714"),
            ),
            table(_PRIORITY_HEADER, row("GLM-5.2, 5.3", "35.000", "110.000", "6.500")),
        ],
    )
    assert detector.detect(make_cfg()) == [
        "gte",
        "glm-5.2",
        "glm-5.3",
        "glm-5.2-priority",
        "glm-5.3-priority",
    ]


def _detect_error(monkeypatch: pytest.MonkeyPatch, tables: list[str]) -> str:
    _detect_serve(monkeypatch, tables)
    with pytest.raises(FetchError) as excinfo:
        detector.detect(make_cfg())
    return str(excinfo.value)


def test_detect_unknown_tier_qualifier_raises(monkeypatch: pytest.MonkeyPatch):
    # tolerating the dropped "Standard" must not admit any other qualifier: a
    # guessed tier for a new "Flex" table would price its rows under the base
    # ids or under the "-priority" ids
    flex = _STANDARD_HEADER.replace("Standard Pay Per Token", "Flex Pay Per Token")
    tables = [
        table(_STANDARD_HEADER, row("GLM-5.2, 5.3", "20.000", "62.857", "3.714")),
        table(flex, row("GLM-5.2, 5.3", "10.000", "31.429", "1.857")),
    ]
    assert _detect_error(monkeypatch, tables) == (
        f"unreadable pay-per-token tier span 'flex pay per token (dbu per 1m tokens)' on {PAGE_URL}"
    )


def test_detect_reworded_tier_span_raises(monkeypatch: pytest.MonkeyPatch):
    # a reworded tier span outside the pins raises rather than guessing a tier
    reworded = _PRIORITY_HEADER.replace(
        "Priority Pay Per Token (DBU Per 1M Tokens)",
        "Priority Pay Per Token (DBU Per 1M Tokens) (beta)",
    )
    tables = [
        table(_STANDARD_HEADER, row("GLM-5.2, 5.3", "20.000", "62.857", "3.714")),
        table(reworded, row("Qwen 3.5 122B", "6.286", "62.857", "-")),
    ]
    assert _detect_error(monkeypatch, tables) == (
        "unreadable pay-per-token tier span"
        f" 'priority pay per token (dbu per 1m tokens) (beta)' on {PAGE_URL}"
    )


def test_detect_priority_table_losing_its_qualifier_raises(monkeypatch: pytest.MonkeyPatch):
    # the page dropped "Standard" once; dropping "Priority" the same way leaves
    # two bare spans that both read as standard, and the priority rows would
    # price the base ids or vanish behind them with no warning
    bare = _STANDARD_HEADER.replace("Standard Pay Per Token", "Pay Per Token")
    tables = [
        table(bare, row("GLM-5.2, 5.3", "20.000", "62.857", "3.714")),
        table(bare, row("GLM-5.2, 5.3", "35.000", "110.000", "6.500")),
    ]
    expected = f"two pay-per-token tables read as the standard tier on {PAGE_URL}"
    assert _detect_error(monkeypatch, tables) == expected
    with pytest.raises(FetchError) as excinfo:
        scraper.scrape(make_cfg(), "glm-5.2")
    assert str(excinfo.value) == expected


def test_detect_two_priority_tables_raise(monkeypatch: pytest.MonkeyPatch):
    tables = [
        table(_STANDARD_HEADER, row("GLM-5.2, 5.3", "20.000", "62.857", "3.714")),
        table(_PRIORITY_HEADER, row("GLM-5.2, 5.3", "35.000", "110.000", "6.500")),
        table(_PRIORITY_HEADER, row("Qwen 3.5 122B", "6.286", "62.857", "-")),
    ]
    assert _detect_error(monkeypatch, tables) == (
        f"two pay-per-token tables read as the priority tier on {PAGE_URL}"
    )


@pytest.mark.parametrize(
    ("drifted", "kept", "span"),
    [
        # the standard table's sub-header drifts while the priority table goes
        # bare: the priority table would read as the only standard table and
        # price the base ids at priority rates
        (
            _STANDARD_HEADER.replace("<th>Cache read</th>", "<th>Cached input</th>"),
            _PRIORITY_HEADER.replace("Priority Pay Per Token", "Pay Per Token"),
            "standard pay per token (dbu per 1m tokens)",
        ),
        # the priority table's sub-header drifts: its rows would vanish and
        # every "-priority" id would read as delisted
        (
            _PRIORITY_HEADER.replace("<th>Cache read</th>", "<th>Cached input</th>"),
            _STANDARD_HEADER,
            "priority pay per token (dbu per 1m tokens)",
        ),
    ],
    ids=["standard-drifts-priority-bare", "priority-drifts"],
)
def test_detect_pinned_table_off_the_sub_header_pin_raises(
    monkeypatch: pytest.MonkeyPatch, drifted: str, kept: str, span: str
):
    tables = [
        table(drifted, row("GLM-5.2, 5.3", "20.000", "62.857", "3.714")),
        table(kept, row("GLM-5.2, 5.3", "35.000", "110.000", "6.500")),
    ]
    assert _detect_error(monkeypatch, tables) == (
        f"pay-per-token table {span!r} off the sub-header pin on {PAGE_URL}"
    )


def test_detect_pinned_table_without_a_sub_header_raises(monkeypatch: pytest.MonkeyPatch):
    one_row = (
        "<tr><th>Model</th><th colspan='3'>Priority Pay Per Token (DBU Per 1M Tokens)</th></tr>"
    )
    tables = [
        table(_STANDARD_HEADER, row("GLM-5.2, 5.3", "20.000", "62.857", "3.714")),
        table(one_row, row("GLM-5.2, 5.3", "35.000", "110.000", "6.500")),
    ]
    assert _detect_error(monkeypatch, tables) == (
        "pay-per-token table 'priority pay per token (dbu per 1m tokens)'"
        f" off the sub-header pin on {PAGE_URL}"
    )


def test_detect_missing_standard_table_raises(monkeypatch: pytest.MonkeyPatch):
    # a page whose standard table is gone (or drifted off the sub-header pin)
    # would emit only "-priority" ids and delist every base id after two runs
    tables = [table(_PRIORITY_HEADER, row("GLM-5.2, 5.3", "35.000", "110.000", "6.500"))]
    assert _detect_error(monkeypatch, tables) == (f"no standard pay-per-token table on {PAGE_URL}")


_NO_STANDARD_ONLY = (
    "pay-per-token table read as the standard tier carries no readable priced"
    f" standard-only row on {PAGE_URL}"
)


def test_detect_relabelled_priority_table_alone_raises(monkeypatch: pytest.MonkeyPatch):
    # the standard table gone and the priority span gone bare: the lone table
    # reads as the standard tier and its priority rates would price the base
    # ids; the priority tier lists no standard-only model, so the table raises
    bare = _PRIORITY_HEADER.replace("Priority Pay Per Token", "Pay Per Token")
    assert bare != _PRIORITY_HEADER
    tables = [
        table(
            bare,
            row("Kimi K3 ⌖", "60.000", "300.000", "6.000"),
            row("GLM-5.2, 5.3", "35.000", "110.000", "6.500"),
            row("GLM-5.3 Flash", "8.000", "28.000", "0.800"),
            row("Qwen 3.5 122B", "6.286", "62.857", "-"),
        )
    ]
    assert _detect_error(monkeypatch, tables) == _NO_STANDARD_ONLY
    with pytest.raises(FetchError) as excinfo:
        scraper.scrape(make_cfg(), "kimi-k3")
    assert str(excinfo.value) == _NO_STANDARD_ONLY


def test_detect_lone_standard_table_reads_after_priority_retirement(
    monkeypatch: pytest.MonkeyPatch,
):
    # a retired priority tier leaves the standard table alone on the page; it
    # lists standard-only models (GTE), so it keeps reading as the standard
    # tier and only the "-priority" ids go absent
    bare = _STANDARD_HEADER.replace("Standard Pay Per Token", "Pay Per Token")
    _detect_serve(
        monkeypatch,
        [
            table(
                bare,
                row("Kimi K3 ⌖", "42.857", "214.286", "4.286"),
                row("GTE", "1.857", "-", "-"),
            )
        ],
    )
    assert detector.detect(make_cfg()) == ["kimi-k3", "gte"]


def test_detect_relabelled_priority_table_with_an_unpriced_standard_only_row_raises(
    monkeypatch: pytest.MonkeyPatch,
):
    # a "-" row is unpriced (detect skips it), so it is no evidence that a
    # table is the standard one: a relabelled priority table listing GTE as
    # "-" still raises
    bare = _PRIORITY_HEADER.replace("Priority Pay Per Token", "Pay Per Token")
    tables = [
        table(
            bare,
            row("Kimi K3 ⌖", "60.000", "300.000", "6.000"),
            row("GLM-5.2, 5.3", "35.000", "110.000", "6.500"),
            row("GTE", "-", "-", "-"),
        )
    ]
    assert _detect_error(monkeypatch, tables) == _NO_STANDARD_ONLY


@pytest.mark.parametrize("order", ["page-order", "reordered"])
def test_detect_swapped_tier_labels_raise(monkeypatch: pytest.MonkeyPatch, order: str):
    # both tables stay with their tier labels swapped: the table read as
    # standard holds the priority rows and prices no standard-only model
    standard_rows_labelled_priority = table(
        _STANDARD_HEADER.replace("Standard Pay Per Token", "Priority Pay Per Token"),
        row("Kimi K3 ⌖", "42.857", "214.286", "4.286"),
        row("GTE", "1.857", "-", "-"),
    )
    priority_rows_labelled_bare = table(
        _PRIORITY_HEADER.replace("Priority Pay Per Token", "Pay Per Token"),
        row("Kimi K3 ⌖", "60.000", "300.000", "6.000"),
    )
    tables = [standard_rows_labelled_priority, priority_rows_labelled_bare]
    if order == "reordered":
        tables.reverse()
    assert _detect_error(monkeypatch, tables) == _NO_STANDARD_ONLY


_PRIORITY_ROWS = row("Kimi K3 ⌖", "60.000", "300.000", "6.000") + row(
    "GLM-5.2, 5.3", "35.000", "110.000", "6.500"
)


@pytest.mark.parametrize(
    "priority_table",
    [
        f"<table class='table'><tbody>{_PRIORITY_HEADER}{_PRIORITY_ROWS}</tbody></table>",
        table(
            _PRIORITY_HEADER.replace("<th", "<td").replace("</th>", "</td>"),
            row("Kimi K3 ⌖", "60.000", "300.000", "6.000"),
        ),
    ],
    ids=["header-rows-in-tbody", "td-header-cells"],
)
def test_detect_priority_table_off_the_structural_pin_raises(
    monkeypatch: pytest.MonkeyPatch, priority_table: str
):
    # a priority table that drops out of the pin's structural view would
    # vanish with every "-priority" id; a table carrying a pinned tier span
    # and naming a known model raises off-pin instead
    tables = [
        table(
            _STANDARD_HEADER,
            row("Kimi K3 ⌖", "42.857", "214.286", "4.286"),
            row("GTE", "1.857", "-", "-"),
        ),
        priority_table,
    ]
    assert _detect_error(monkeypatch, tables) == (
        "pay-per-token table 'priority pay per token (dbu per 1m tokens)'"
        f" off the sub-header pin on {PAGE_URL}"
    )


def test_detect_spacer_row_in_a_lone_standard_table_reads(monkeypatch: pytest.MonkeyPatch):
    # a cell-less spacer row names no model; the guard reads past it
    bare = _STANDARD_HEADER.replace("Standard Pay Per Token", "Pay Per Token")
    _detect_serve(
        monkeypatch,
        [
            table(
                bare,
                "<tr></tr>",
                row("Kimi K3 ⌖", "42.857", "214.286", "4.286"),
                row("GTE", "1.857", "-", "-"),
            )
        ],
    )
    assert detector.detect(make_cfg()) == ["kimi-k3", "gte"]


def test_detect_uplift_marked_standard_only_name_counts(monkeypatch: pytest.MonkeyPatch):
    # the guard reads names through parse_id's normalizer, so an uplift
    # marker on the only standard-only name still counts
    bare = _STANDARD_HEADER.replace("Standard Pay Per Token", "Pay Per Token")
    _detect_serve(
        monkeypatch,
        [
            table(
                bare,
                row("Kimi K3 ⌖", "42.857", "214.286", "4.286"),
                row("GTE ⌖", "1.857", "-", "-"),
            )
        ],
    )
    assert detector.detect(make_cfg()) == ["kimi-k3", "gte"]


_STANDARD_TABLE = table(
    _STANDARD_HEADER,
    row("Kimi K3 ⌖", "42.857", "214.286", "4.286"),
    row("GTE", "1.857", "-", "-"),
)
_PRIORITY_BODY = row("Kimi K3 ⌖", "60.000", "300.000", "6.000") + row(
    "GLM-5.2, 5.3", "35.000", "110.000", "6.500"
)
_PRIORITY_OFF_PIN = (
    "pay-per-token table 'priority pay per token (dbu per 1m tokens)'"
    f" off the sub-header pin on {PAGE_URL}"
)


@pytest.mark.parametrize(
    "priority_thead",
    [
        # the tier span restyled into a full-width first row
        "<tr><th colspan='4'>Priority Pay Per Token (DBU Per 1M Tokens)</th></tr>"
        "<tr><th>Model</th><th>Input</th><th>Output</th><th>Cache read</th></tr>",
        # a banner row added above the tier row
        "<tr><th colspan='4'>New: Priority tier</th></tr>" + _PRIORITY_HEADER,
        # a third header row under the sub-header
        _PRIORITY_HEADER + "<tr><th>note</th></tr>",
    ],
    ids=["spanning-tier-row", "banner-row", "third-header-row"],
)
def test_detect_priority_table_with_a_moved_tier_span_raises(
    monkeypatch: pytest.MonkeyPatch, priority_thead: str
):
    # a pricing table (it names known models) whose own cells carry a pinned
    # tier span anywhere, but which misses the structural pin, raises instead
    # of vanishing with every "-priority" id
    priority = (
        f"<table class='table'><thead>{priority_thead}</thead>"
        f"<tbody>{_PRIORITY_BODY}</tbody></table>"
    )
    assert _detect_error(monkeypatch, [_STANDARD_TABLE, priority]) == _PRIORITY_OFF_PIN


@pytest.mark.parametrize(
    "priority",
    [
        f"<table class='table'><thead>{_PRIORITY_HEADER}{_PRIORITY_BODY}</thead></table>",
        f"<table class='table'><thead>{_PRIORITY_HEADER}{_PRIORITY_BODY}</table>",
    ],
    ids=["model-rows-in-thead", "model-rows-in-unclosed-thead"],
)
def test_detect_priority_table_with_model_rows_in_its_thead_raises(
    monkeypatch: pytest.MonkeyPatch, priority: str
):
    # a table's thead rows count for the off-pin check too: model rows there
    # name known models, so the off-pin table raises instead of vanishing with
    # every "-priority" id
    assert _detect_error(monkeypatch, [_STANDARD_TABLE, priority]) == _PRIORITY_OFF_PIN


def test_detect_priority_table_nested_in_a_layout_table_raises(monkeypatch: pytest.MonkeyPatch):
    wrapped = (
        "<table><thead><tr><th>Priority pricing</th></tr></thead><tbody><tr><td>"
        + table(_PRIORITY_HEADER, _PRIORITY_BODY)
        + "</td></tr></tbody></table>"
    )
    assert _detect_error(monkeypatch, [_STANDARD_TABLE, wrapped]) == (
        "pay-per-token table 'priority pay per token (dbu per 1m tokens)'"
        f" nested in another table on {PAGE_URL}"
    )


def test_detect_legend_table_carrying_a_tier_span_reads(monkeypatch: pytest.MonkeyPatch):
    # a table that names no known model is no pricing table: a pinned span
    # in its cells raises nothing
    legend = (
        "<table><tr><th>Tier</th><th>Pay Per Token (DBU Per 1M Tokens)</th>"
        "<th>Priority Pay Per Token (DBU Per 1M Tokens)</th></tr>"
        "<tr><td>SLA</td><td>best effort</td><td>99.9%</td></tr></table>"
    )
    _detect_serve(monkeypatch, [_STANDARD_TABLE, table(_PRIORITY_HEADER, _PRIORITY_BODY), legend])
    assert detector.detect(make_cfg()) == [
        "kimi-k3",
        "gte",
        "kimi-k3-priority",
        "glm-5.2-priority",
        "glm-5.3-priority",
    ]


def test_detect_standard_table_nested_in_a_layout_table_raises(monkeypatch: pytest.MonkeyPatch):
    # a nested standard table still looks like a pricing table (pinned span
    # plus a mapped display), so it raises its own message instead of the
    # "no standard pay-per-token table" a lone priority table reads
    wrapped = (
        "<table><thead><tr><th>Standard pricing</th></tr></thead><tbody><tr><td>"
        + _STANDARD_TABLE
        + "</td></tr></tbody></table>"
    )
    assert _detect_error(monkeypatch, [table(_PRIORITY_HEADER, _PRIORITY_BODY), wrapped]) == (
        "pay-per-token table 'standard pay per token (dbu per 1m tokens)'"
        f" nested in another table on {PAGE_URL}"
    )


def test_detect_reads_every_tbody_of_a_table(monkeypatch: pytest.MonkeyPatch):
    # a standard table split into chat and embedding groups keeps both
    split = (
        f"<table class='table'><thead>{_STANDARD_HEADER}</thead>"
        f"<tbody>{row('Kimi K3 ⌖', '42.857', '214.286', '4.286')}"
        f"{row('GPT-OSS-120B', '2.143', '8.571')}</tbody>"
        f"<tbody>{row('GTE', '1.857', '-', '-')}"
        f"{row('BGE Large', '1.429', '-', '-')}</tbody></table>"
    )
    _detect_serve(monkeypatch, [split, table(_PRIORITY_HEADER, _PRIORITY_BODY)])
    assert detector.detect(make_cfg()) == [
        "kimi-k3",
        "gpt-oss-120b",
        "gte",
        "bge-large",
        "kimi-k3-priority",
        "glm-5.2-priority",
        "glm-5.3-priority",
    ]
    pricing = scraper.scrape(make_cfg(), "bge-large")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1.429 / 1e6)


def test_detect_three_cell_standard_only_row_is_no_evidence(monkeypatch: pytest.MonkeyPatch):
    # the guard counts only four-cell priced rows: a short GTE row in a
    # relabelled priority table does not make it the standard table
    bare = _PRIORITY_HEADER.replace("Priority Pay Per Token", "Pay Per Token")
    tables = [table(bare, _PRIORITY_BODY, "<tr><td>GTE</td><td>1.857</td><td>-</td></tr>")]
    assert _detect_error(monkeypatch, tables) == _NO_STANDARD_ONLY


def _warning_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def test_detect_section_row_warns_without_freezing_counters(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # a one-cell section row names no model: it warns on the soft parse-skip
    # line, never the detect-skip line that freezes the absence counters
    bare = _STANDARD_HEADER.replace("Standard Pay Per Token", "Pay Per Token")
    _detect_serve(
        monkeypatch,
        [
            table(
                bare,
                "<tr><td colspan='4'>Embedding models</td></tr>",
                row("Kimi K3 ⌖", "42.857", "214.286", "4.286"),
                row("GTE", "1.857", "-", "-"),
            )
        ],
    )
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == ["kimi-k3", "gte"]
    lines = _warning_lines(caplog)
    assert not any(health.DETECT_SKIP.search(line) for line in lines)
    assert lines == [f"parse skip for databricks: section row 'Embedding models' on {PAGE_URL}"]
    # the run log carries basicConfig's LEVEL:logger: prefix the health step anchors on
    run_log = [f"WARNING:{detector.__name__}:{line}" for line in lines]
    assert health.parse_log(run_log) == {"databricks": {"hard": [], "soft": run_log}}


def _lone_standard_with(monkeypatch: pytest.MonkeyPatch, odd_row: str) -> None:
    bare = _STANDARD_HEADER.replace("Standard Pay Per Token", "Pay Per Token")
    _detect_serve(
        monkeypatch,
        [
            table(
                bare,
                odd_row,
                row("Kimi K3 ⌖", "42.857", "214.286", "4.286"),
                row("GTE", "1.857", "-", "-"),
            )
        ],
    )


def test_detect_one_cell_row_naming_a_model_still_freezes(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # a collapsed row that names a mapped model is a broken model row, not a
    # section label: the id set is incomplete, so the counters freeze
    _lone_standard_with(monkeypatch, "<tr><td colspan='4'>BGE Large</td></tr>")
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == ["kimi-k3", "gte"]
    assert _warning_lines(caplog) == [
        f"detect skip for databricks: row outside the pricing shape on {PAGE_URL}: 'BGE Large'"
    ]


@pytest.mark.parametrize(
    "odd_row",
    [
        "<tr><td colspan='4'>BGE Large (new)</td></tr>",
        "<tr><td colspan='4'>BGE\xa0Large</td></tr>",
        "<tr><td colspan='4'><div>BGE Large ⌖</div><div>1.429</div>"
        "<div>-</div><div>-</div></td></tr>",
        "<tr><td colspan='4'><table><tbody>"
        + row("BGE Large", "9.999", "-", "-")
        + "</tbody></table></td></tr>",
        "<tr><td colspan='4'>Foundation 9B 2.143</td></tr>",
        "<tr><td colspan='4'>BGE Large</td></tr>",
        "<tr><td colspan='4'>BGE  Large</td></tr>",
        "<tr><td colspan='4'>BGE\n    Large</td></tr>",
        "<tr><td colspan='4'>BGE LARGE</td></tr>",
        "<tr><td colspan='4'><table><tbody>"
        + row("BGE Large (new)", "9.999", "-", "-")
        + "</tbody></table></td></tr>",
        "<tr><td colspan='4'><table><tbody><tr><td>9.999</td><td>BGE Large</td></tr>"
        "</tbody></table></td></tr>",
        "<tr><td colspan='4'><table><thead><tr><th>BGE Large</th></tr></thead>"
        "<tbody><tr><td>note</td></tr></tbody></table></td></tr>",
        "<tr><td colspan='4'><table><tbody><tr><td>9.999</td><td>-</td></tr>"
        "</tbody></table></td></tr>",
        "<tr><td colspan='4'>see footnote 4</td></tr>",
        "<tr><td colspan='4'>Generation 2 embedding models</td></tr>",
        "<tr><td>Embedding</td><td>models</td></tr>",
        "<tr><td>BGE-Large</td><td>Contact us</td><td>-</td><td>-</td></tr>",
        "<tr><td>BGE-Large</td><td>1,429</td><td>-</td><td>-</td></tr>",
        "<tr><td>Embedding models</td><td>n/a</td><td>n/a</td><td>n/a</td></tr>",
        "<tr><td colspan='4'>BGE-Large 1 - -</td></tr>",
        "<tr><td colspan='4'><b>BG</b>E Large</td></tr>",
        "<tr><td colspan='4'>BGE-Large $1.43 / - / -</td></tr>",
        "<tr><td colspan='4'>GTE family</td></tr>",
        "<tr><td>Llama⁴ Maverick</td><td></td><td></td><td></td></tr>",
        "<tr><td colspan='4'>Llama⁴ Maverick</td></tr>",
        "<tr><td colspan='4'>BGE-Large ①</td></tr>",
        "<tr>BGE Large 1.429 - -</tr>",
        "<tr><table><tbody>" + row("BGE Large", "1.429", "-", "-") + "</tbody></table></tr>",
        "<tr><td></td>BGE Large 1.429<td></td><td></td><td></td></tr>",
        "<tr><td>Embedding models</td><span><td>BGE Large</td><td>1.429</td></span></tr>",
        "<tr><td colspan='4'>BGE-Large</td></tr>",
        "<tr><td colspan='4'>BGE_Large</td></tr>",
        "<tr><td colspan='4'>B<b>GE</b> <i>Lar</i>ge</td></tr>",
        "<tr><td colspan='4'><img src='bge.png' alt='model'></td></tr>",
        "<tr><td colspan='4'>Embedding models<table><tbody><tr><td>BGE-Large</td>"
        "<td>contact sales</td></tr></tbody></table></td></tr>",
        "<tr><td colspan='4'>BGE-Large contact sales</td></tr>",
        "<tr><td colspan='4'>BGE&amp;Large</td></tr>",
        "<tr><td colspan='4'>New: BGE-Large</td></tr>",
        "<tr><td colspan='4'>BGE-Large (preview)</td></tr>",
        "<tr><td colspan='4'>BGE_Large embedding</td></tr>",
        "<tr><td colspan='4'>B.G.E. Large models</td></tr>",
        "<tr><td>Embedding models</td>BGE-Large</tr>",
        "<tr><td>Model</td><td>Input</td><td>Output</td><td>Cache read</td>BGE Large 1.429</tr>",
        "<tr><td>Model</td><td>Input</td><td>Output</td><td>Cache read</td>BGE-Large</tr>",
        "<tr><td colspan='4'><svg role='img' aria-label='BGE Large'><use href='#bge'></use>"
        "</svg></td></tr>",
        "<tr><td colspan='4'><picture><source srcset='bge.webp'></picture></td></tr>",
        "<tr><td colspan='4'><object data='bge.svg'></object></td></tr>",
        "<tr><td colspan='4'><input type='image' alt='BGE Large'></td></tr>",
        "<tr><td colspan='4'><span class='icon-bge' title='BGE Large'></span></td></tr>",
        "<tr><td>Embedding models</td>BGE Large 1.429</tr>",
        "<tr><td colspan='4'><img src='bge-large.png'></td></tr>",
        "<tr><td colspan='4'><svg><use href='#bge-large'></use></svg></td></tr>",
        "<tr><td colspan='4'><embed src='bge-large.svg'></td></tr>",
        "<tr><td colspan='4'><canvas></canvas></td></tr>",
        "<tr><td colspan='4'><iframe src='bge-large.html'></iframe></td></tr>",
        "<tr><td colspan='4'><video src='bge-large.mp4'></video></td></tr>",
    ],
    ids=[
        "renamed-model",
        "nbsp-model",
        "collapsed-model-row",
        "nested-model-row",
        "rate-shaped",
        "thin-space-model",
        "double-space-model",
        "newline-model",
        "uppercase-model",
        "nested-renamed-model-row",
        "nested-rate-then-model",
        "nested-thead-model",
        "nested-rates-only",
        "label-with-an-integer",
        "label-with-a-generation-number",
        "two-cell-label",
        "renamed-row-with-a-text-input",
        "renamed-row-with-a-comma-decimal",
        "label-with-filler-cells",
        "collapsed-row-with-integer-rates",
        "name-split-by-inline-markup",
        "collapsed-row-with-dollar-rates",
        "label-naming-a-display-word",
        "superscript-digit-with-blank-rates",
        "superscript-digit-collapsed",
        "circled-digit",
        "text-in-a-cell-less-row",
        "nested-table-directly-under-the-row",
        "text-between-blank-cells",
        "model-cells-under-a-wrapper-beside-a-label",
        "hyphenated-display",
        "underscored-display",
        "display-split-by-markup",
        "image-only-cell",
        "label-holding-a-nested-table",
        "display-inside-other-text",
        "display-joined-by-an-entity-ampersand",
        "display-after-a-prefix",
        "display-before-a-paren",
        "underscored-display-in-text",
        "dotted-display-letters",
        "bare-display-text-beside-a-label-cell",
        "header-row-with-bare-model-text",
        "header-row-with-a-bare-display",
        "svg-named-model",
        "picture-element",
        "object-element",
        "image-input",
        "titled-icon",
        "label-cell-with-bare-model-text",
        "bare-image",
        "bare-svg",
        "embed-element",
        "canvas-element",
        "iframe-element",
        "video-element",
    ],
)
def test_detect_one_cell_row_that_may_be_a_model_row_freezes(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, odd_row: str
):
    # anything that is not plainly a label may be a broken model row and keeps
    # the counter-freezing detect skip (cloudy, 2026-10-19: a wrong soft call
    # delists a live model, a wrong freeze only pauses delistings): a mapped
    # display (as a word or letter by letter), any digit, a nested table, a
    # graphic or a name attribute, a header row with extra text, or more than
    # one non-empty cell
    _lone_standard_with(monkeypatch, odd_row)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == ["kimi-k3", "gte"]
    lines = _warning_lines(caplog)
    assert any(health.DETECT_SKIP.search(line) for line in lines)
    assert not any(line.startswith("parse skip for databricks:") for line in lines)


@pytest.mark.parametrize(
    ("odd_row", "label"),
    [
        ("<tr></tr>", ""),
        ("<tr><td></td><td></td><td></td><td></td></tr>", ""),
        ("<tr><td>Embedding models</td><td></td><td></td><td></td></tr>", "Embedding models"),
        (
            "<tr><td>Model</td><td>Input</td><td>Output</td><td>Cache read</td></tr>",
            "Model Input Output Cache read",
        ),
        ("<tr><td colspan='4'>GTEx models</td></tr>", "GTEx models"),
        ("<tr><td colspan='4'>bigtent offers</td></tr>", "bigtent offers"),
        ("<tr><td colspan='4'>Inklings and others</td></tr>", "Inklings and others"),
        ("<tr><td colspan='4'><!-- BGE Large 1.429 --></td></tr>", ""),
    ],
    ids=[
        "cell-less-spacer",
        "four-cell-spacer",
        "four-cell-label",
        "repeated-header-row",
        "display-inside-a-longer-word",
        "display-across-a-word-edge",
        "display-as-a-word-prefix",
        "comment-only-cell",
    ],
)
def test_detect_row_naming_no_model_warns_without_freezing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, odd_row: str, label: str
):
    # a section row is plainly a label: no graphic, name attribute or nested
    # table anywhere, and blank, a repeated header row, or one non-empty cell
    # with no digit and no mapped display (as a word or letter by letter); it
    # warns on the soft line and never freezes the counters
    _lone_standard_with(monkeypatch, odd_row)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == ["kimi-k3", "gte"]
    assert _warning_lines(caplog) == [
        f"parse skip for databricks: section row {label!r} on {PAGE_URL}"
    ]


_TWO_TABLE_IDS = ["kimi-k3", "gte", "kimi-k3-priority", "glm-5.2-priority", "glm-5.3-priority"]


def test_detect_priority_rows_beside_a_nested_tbody_read(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # the priority rows sit straight under <table> and one row nests a
    # footnote table with a tbody: the own rows read, the nested table's row
    # never prices an id, and the footnote row, holding a nested table, is no
    # plain label, so it keeps the freeze
    note = (
        "<tr><td colspan='4'><table><tbody><tr><td>see footnote 4</td></tr>"
        "</tbody></table></td></tr>"
    )
    priority = (
        f"<table class='table'><thead>{_PRIORITY_HEADER}</thead>{_PRIORITY_BODY}{note}</table>"
    )
    _detect_serve(monkeypatch, [_STANDARD_TABLE, priority])
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == _TWO_TABLE_IDS
    assert any(health.DETECT_SKIP.search(line) for line in _warning_lines(caplog))


_KIMI_CELLS = "<td>Kimi K3 ⌖</td><td>42.857</td><td>214.286</td><td>4.286</td>"
_BGE_CELLS = "<td>BGE Large</td><td>1.429</td><td>-</td><td>-</td>"
_GTE_CELLS = "<td>GTE</td><td>1.857</td><td>-</td><td>-</td>"


@pytest.mark.parametrize(
    "body",
    [
        f"<tr>{_KIMI_CELLS}<tr>{_BGE_CELLS}</tr></tr><tr>{_GTE_CELLS}</tr>",
        f"<tr>{_KIMI_CELLS}<tr>{_BGE_CELLS}<tr>{_GTE_CELLS}",
        f"<tr>{_KIMI_CELLS}</tr><div><tr>{_BGE_CELLS}</tr></div><tr>{_GTE_CELLS}</tr>",
    ],
    ids=["one-omitted-end-tag", "every-end-tag-omitted", "wrapper-between-tbody-and-row"],
)
def test_detect_and_scrape_read_rows_whose_nearest_table_is_this_one(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, body: str
):
    # an omitted </tr> (valid HTML) nests the next row inside the last one;
    # every row whose nearest table is this table is its own row
    bare = _STANDARD_HEADER.replace("Standard Pay Per Token", "Pay Per Token")
    html = f"<table class='table'><thead>{bare}</thead><tbody>{body}</tbody></table>"
    _detect_serve(monkeypatch, [html])
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == ["kimi-k3", "bge-large", "gte"]
    assert _warning_lines(caplog) == []
    pricing = scraper.scrape(make_cfg(), "bge-large")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1.429 / 1e6)


@pytest.mark.parametrize("wrapper", ["a href='#bge'", "div"], ids=["anchor", "div"])
def test_detect_and_scrape_read_cells_under_a_wrapper_element(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, wrapper: str
):
    # html.parser keeps an element between <tr> and its cells; the row's own
    # cells are the cells whose nearest row is this row, so the priced row reads
    tag = wrapper.split()[0]
    wrapped_row = (
        f"<tr><{wrapper}><td>BGE Large</td><td>1.429</td><td>-</td><td>-</td></{tag}></tr>"
    )
    _lone_standard_with(monkeypatch, wrapped_row)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == ["bge-large", "kimi-k3", "gte"]
    assert _warning_lines(caplog) == []
    pricing = scraper.scrape(make_cfg(), "bge-large")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1.429 / 1e6)


def test_detect_unpriced_dash_row_stays_silent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # a "-" input cell is the known unpriced form: no line at all
    _lone_standard_with(monkeypatch, row("Llama 5 70B", "-", "-", "-"))
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == ["kimi-k3", "gte"]
    assert _warning_lines(caplog) == []


_ONE_ROW_HEADER = "<tr><th>Model</th><th>Input</th><th>Output</th><th>Cache read</th></tr>"
_STANDARD_SPAN = "Pay Per Token (DBU Per 1M Tokens)"
_PRIORITY_SPAN = "Priority Pay Per Token (DBU Per 1M Tokens)"
_STANDARD_BODY = row("Kimi K3 ⌖", "42.857", "214.286", "4.286") + row("GTE", "1.857", "-", "-")


def _captioned(span: str, body: str) -> str:
    return (
        f"<table class='table'><caption>{span}</caption>"
        f"<thead>{_ONE_ROW_HEADER}</thead><tbody>{body}</tbody></table>"
    )


def _headed(span: str, body: str) -> str:
    return (
        f"<h3>{span}</h3><table class='table'>"
        f"<thead>{_ONE_ROW_HEADER}</thead><tbody>{body}</tbody></table>"
    )


# the live page wraps each table alone in this div, with its h3 outside it
# (2026-10-14 fixture), so a heading is never the table's own sibling
def _wrapped(html: str) -> str:
    return f"<div class='max-w-full overflow-x-auto'>{html}</div>"


def _one_row_table(body: str) -> str:
    return f"<table class='table'><thead>{_ONE_ROW_HEADER}</thead><tbody>{body}</tbody></table>"


def _live_headed(span: str, body: str, between: str = "") -> str:
    return f"<h3>{span}</h3>{between}{_wrapped(_one_row_table(body))}"


@pytest.mark.parametrize(
    "tables",
    [
        [_STANDARD_TABLE, _captioned(_PRIORITY_SPAN, _PRIORITY_BODY)],
        [_captioned(_STANDARD_SPAN, _STANDARD_BODY), table(_PRIORITY_HEADER, _PRIORITY_BODY)],
        [_STANDARD_TABLE, _headed(_PRIORITY_SPAN, _PRIORITY_BODY)],
        [_headed(_STANDARD_SPAN, _STANDARD_BODY), table(_PRIORITY_HEADER, _PRIORITY_BODY)],
        [
            _STANDARD_TABLE,
            f"<table class='table'><thead>{_PRIORITY_HEADER}</thead>{_PRIORITY_BODY}</table>",
        ],
        [
            _STANDARD_TABLE,
            f"<table class='table'><thead>{_PRIORITY_HEADER}</thead>"
            f"<tbody>{row('Kimi K3 ⌖', '60.000', '300.000', '6.000')}</tbody>"
            f"<tfoot>{row('GLM-5.2, 5.3', '35.000', '110.000', '6.500')}</tfoot></table>",
        ],
        [_STANDARD_TABLE, _live_headed(_PRIORITY_SPAN, _PRIORITY_BODY)],
        [_live_headed(_STANDARD_SPAN, _STANDARD_BODY), table(_PRIORITY_HEADER, _PRIORITY_BODY)],
        [_STANDARD_TABLE, _live_headed(_PRIORITY_SPAN, _PRIORITY_BODY, "<p>prices per 1M</p>")],
        [
            _STANDARD_TABLE,
            f"<h3>{_PRIORITY_SPAN}</h3>"
            + _wrapped(
                _captioned("", _PRIORITY_BODY).replace(
                    "<caption></caption>", "<caption> </caption>"
                )
            ),
        ],
    ],
    ids=[
        "priority-span-in-caption",
        "standard-span-in-caption",
        "priority-span-in-heading",
        "standard-span-in-heading",
        "priority-rows-without-tbody",
        "priority-row-in-tfoot",
        "priority-heading-over-live-wrapper",
        "standard-heading-over-live-wrapper",
        "heading-then-paragraph-then-wrapper",
        "empty-caption-under-a-heading",
    ],
)
def test_detect_and_scrape_read_a_moved_span_or_rows_outside_tbody(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tables: list[str]
):
    # a tier span in a <caption> or in the heading over a one-row thead, and
    # rows straight under <table> or in a <tfoot>, used to hide the table or
    # the rows silently; each shape now detects and scrapes
    _detect_serve(monkeypatch, tables)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == _TWO_TABLE_IDS
    assert _warning_lines(caplog) == []
    standard = scraper.scrape(make_cfg(), "kimi-k3")
    assert standard is not None
    assert standard.input_cost_per_token == pytest.approx(42.857 / 1e6)
    priority = scraper.scrape(make_cfg(), "glm-5.2-priority")
    assert priority is not None
    assert priority.input_cost_per_token == pytest.approx(35.0 / 1e6)
    assert priority.cache_read_cost_per_token == pytest.approx(6.5 / 1e6)


_REWORDED_PRIORITY = _PRIORITY_HEADER.replace(_PRIORITY_SPAN, "Priority tier (DBU per 1M tokens)")


@pytest.mark.parametrize(
    "priority",
    [
        f"<table class='table'><tbody>{_REWORDED_PRIORITY}{_PRIORITY_BODY}</tbody></table>",
        _one_row_table(_PRIORITY_BODY),
        f"<table class='table'><tbody>{_ONE_ROW_HEADER}{_PRIORITY_BODY}</tbody></table>",
        f"<table class='table'><thead>{_REWORDED_PRIORITY}<tr><th>note</th></tr></thead>"
        f"<tbody>{_PRIORITY_BODY}</tbody></table>",
        f"<table class='table'><caption>{_PRIORITY_SPAN}</caption><thead>"
        f"{_ONE_ROW_HEADER.replace('<th', '<td').replace('</th>', '</td>')}</thead>"
        f"<tbody>{_PRIORITY_BODY}</tbody></table>",
    ],
    ids=[
        "reworded-two-row-header-in-tbody",
        "one-row-thead-without-a-span",
        "one-row-header-in-tbody",
        "three-row-thead-reworded-span",
        "td-cells-in-a-one-row-thead",
    ],
)
def test_detect_unpinned_table_naming_the_sub_header_and_a_model_raises(
    monkeypatch: pytest.MonkeyPatch, priority: str
):
    # the table pins nothing and never reads a tier span (none present, or one
    # the header shape cannot use), but its own cells (thead rows included)
    # still name Input | Output | Cache read and a mapped model, so it raises
    # instead of vanishing with every "-priority" id
    assert _detect_error(monkeypatch, [_STANDARD_TABLE, priority]) == (
        f"unpinned table naming Input | Output | Cache read and a mapped model on {PAGE_URL}"
    )


@pytest.mark.parametrize(
    "priority",
    [
        _captioned("Priority tier (DBU per 1M tokens)", _PRIORITY_BODY),
        _live_headed("Priority tier (DBU per 1M tokens)", _PRIORITY_BODY),
    ],
    ids=["reworded-caption", "reworded-heading"],
)
def test_detect_reworded_caption_or_heading_span_raises(
    monkeypatch: pytest.MonkeyPatch, priority: str
):
    # plan #41 holds on the new span sources: a reworded span raises, never guesses
    assert _detect_error(monkeypatch, [_STANDARD_TABLE, priority]) == (
        f"unreadable pay-per-token tier span 'priority tier (dbu per 1m tokens)' on {PAGE_URL}"
    )


@pytest.mark.parametrize(
    "extra",
    [
        _captioned("Partner models (USD per 1M tokens)", row("Foo 1", "1.000", "2.000")),
        "<table><tr><th>Input</th><th>Output</th><th>Cache read</th></tr>"
        "<tr><td>per 1M</td><td>per 1M</td><td>per 1M</td></tr></table>",
        "<h3>Batch Inference</h3>"
        + _wrapped(table(_HOURLY_HEADER, row("Kimi K3 ⌖", "-", "142.857", "128.571"))),
    ],
    ids=["captioned-table-naming-no-model", "legend-with-the-sub-header", "heading-over-hourly"],
)
def test_detect_tables_that_name_no_priced_model_read(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, extra: str
):
    # a table naming no mapped model, or one whose header is not the one-row
    # per-token header, is no pricing table: nothing raises and nothing warns
    _detect_serve(monkeypatch, [_STANDARD_TABLE, table(_PRIORITY_HEADER, _PRIORITY_BODY), extra])
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == _TWO_TABLE_IDS
    assert _warning_lines(caplog) == []


def test_detect_live_layout_heading_over_a_pinned_table_reads(monkeypatch: pytest.MonkeyPatch):
    # the live headings ("Priority Pay Per Token") sit over two-row pinned
    # tables; the span comes from the table's own header, never the heading
    _detect_serve(
        monkeypatch,
        [
            "<h3>Pay Per Token</h3>" + _wrapped(_STANDARD_TABLE),
            "<h3>Priority Pay Per Token</h3>" + _wrapped(table(_PRIORITY_HEADER, _PRIORITY_BODY)),
        ],
    )
    assert detector.detect(make_cfg()) == _TWO_TABLE_IDS


_NESTED_PRIORITY = (
    "pay-per-token table 'priority pay per token (dbu per 1m tokens)'"
    f" nested in another table on {PAGE_URL}"
)


@pytest.mark.parametrize(
    "wrapper",
    [
        "<table><thead><tr><th>Priority pricing</th></tr></thead><tbody><tr><td>"
        + _captioned(_PRIORITY_SPAN, _PRIORITY_BODY)
        + "</td></tr></tbody></table>",
        "<table><tr><td>" + table(_PRIORITY_HEADER, _PRIORITY_BODY) + "</td></tr></table>",
    ],
    ids=["captioned-table-in-a-layout-table", "pinned-table-in-a-tbody-less-wrapper"],
)
def test_detect_nested_priority_table_raises_the_nested_message(
    monkeypatch: pytest.MonkeyPatch, wrapper: str
):
    # a wrapper must never claim the nested table's thead or span
    assert _detect_error(monkeypatch, [_STANDARD_TABLE, wrapper]) == _NESTED_PRIORITY


def test_detect_heading_over_a_wrapper_table_holding_the_priority_table_raises(
    monkeypatch: pytest.MonkeyPatch,
):
    inner = _one_row_table(_PRIORITY_BODY)
    wrapper = f"<h3>{_PRIORITY_SPAN}</h3><table><tr><td>{inner}</td></tr></table>"
    assert _detect_error(monkeypatch, [_STANDARD_TABLE, wrapper]) == (
        f"pay-per-token table nested in another table on {PAGE_URL}"
    )


def _header_table(header_rows: str, caption: str = "") -> str:
    caption_html = f"<caption>{caption}</caption>" if caption else ""
    return (
        f"<table class='table'>{caption_html}<thead>{header_rows}</thead>"
        f"<tbody>{_PRIORITY_BODY}</tbody></table>"
    )


@pytest.mark.parametrize(
    "priority",
    [
        _header_table(
            "<tr><th>Models</th><th>Input</th><th>Output</th><th>Cache read</th></tr>",
            caption=_PRIORITY_SPAN,
        ),
        _header_table(
            "<tr><th>Model name</th><th>Input</th><th>Output</th><th>Cache read</th></tr>"
        ),
        f"<h3>{_PRIORITY_SPAN}</h3>"
        + _wrapped(
            _header_table("<tr><th></th><th>Input</th><th>Output</th><th>Cache read</th></tr>")
        ),
        _header_table(
            "<tr><th>Model</th><th>Context</th><th>Input</th><th>Output</th>"
            "<th>Cache read</th></tr>"
        ),
        _header_table(
            "<tr><th rowspan='2'>Model</th><th colspan='3'>Priority tier (DBU per 1M tokens)"
            "</th></tr><tr><th></th><th>Input</th><th>Output</th><th>Cache read</th></tr>"
        ),
    ],
    ids=[
        "models-lead-under-a-caption",
        "model-name-lead",
        "empty-corner-under-a-heading",
        "context-column",
        "empty-cell-before-the-sub-header",
    ],
)
def test_detect_sub_header_anywhere_in_a_row_keeps_the_table_loud(
    monkeypatch: pytest.MonkeyPatch, priority: str
):
    # Input | Output | Cache read as three consecutive own cells, wherever the
    # row starts, plus a mapped model: the table raises, never vanishes
    assert _detect_error(monkeypatch, [_STANDARD_TABLE, priority]) == (
        f"unpinned table naming Input | Output | Cache read and a mapped model on {PAGE_URL}"
    )


def test_detect_and_scrape_agree_past_an_unpriced_duplicate_row(monkeypatch: pytest.MonkeyPatch):
    # a "-" listing of Kimi K3 in an earlier tbody and its priced row in a
    # later one: detect skips the "-" row, so scrape must too, or the id is
    # detected while its price never refreshes
    standard = (
        f"<table class='table'><thead>{_STANDARD_HEADER}</thead>"
        f"<tbody>{row('Kimi K3 ⌖', '-', '-', '-')}</tbody>"
        f"<tbody>{row('Kimi K3 ⌖', '42.857', '214.286', '4.286')}"
        f"{row('GTE', '1.857', '-', '-')}</tbody></table>"
    )
    _detect_serve(monkeypatch, [standard, table(_PRIORITY_HEADER, _PRIORITY_BODY)])
    assert "kimi-k3" in detector.detect(make_cfg())
    pricing = scraper.scrape(make_cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(42.857 / 1e6)


def test_detect_model_naming_table_nesting_a_span_legend_reads(monkeypatch: pytest.MonkeyPatch):
    # a span in a nested table's cell is no span of the outer table
    legend = "<table><tr><th>Tier</th><th>Pay Per Token (DBU Per 1M Tokens)</th></tr></table>"
    outer = f"<table><tr><td>Kimi K3</td><td>{legend}</td></tr></table>"
    _detect_serve(monkeypatch, [_STANDARD_TABLE, table(_PRIORITY_HEADER, _PRIORITY_BODY), outer])
    assert detector.detect(make_cfg()) == _TWO_TABLE_IDS


def test_detect_span_legend_wrapping_the_hourly_table_reads(monkeypatch: pytest.MonkeyPatch):
    # the model rows of a nested table are no rows of the outer legend
    hourly = table(_HOURLY_HEADER, row("Kimi K3 ⌖", "-", "142.857", "128.571"))
    wrapper = (
        "<table><tr><th>Tier</th><th>Pay Per Token (DBU Per 1M Tokens)</th></tr>"
        f"<tr><td colspan='2'>{hourly}</td></tr></table>"
    )
    _detect_serve(monkeypatch, [_STANDARD_TABLE, table(_PRIORITY_HEADER, _PRIORITY_BODY), wrapper])
    assert detector.detect(make_cfg()) == _TWO_TABLE_IDS


def test_detect_off_pin_priority_with_a_spacer_row_raises_off_pin(
    monkeypatch: pytest.MonkeyPatch,
):
    spanning = (
        "<tr><th colspan='4'>Priority Pay Per Token (DBU Per 1M Tokens)</th></tr>"
        "<tr><th>Model</th><th>Input</th><th>Output</th><th>Cache read</th></tr>"
    )
    priority = (
        f"<table class='table'><thead>{spanning}</thead>"
        f"<tbody><tr></tr>{_PRIORITY_BODY}</tbody></table>"
    )
    assert _detect_error(monkeypatch, [_STANDARD_TABLE, priority]) == _PRIORITY_OFF_PIN


def test_guard_reads_standard_only_rows_in_a_later_tbody(monkeypatch: pytest.MonkeyPatch):
    split = (
        f"<table class='table'><thead>{_STANDARD_HEADER}</thead>"
        f"<tbody>{row('Kimi K3 ⌖', '42.857', '214.286', '4.286')}</tbody>"
        f"<tbody>{row('GTE', '1.857', '-', '-')}</tbody></table>"
    )
    _detect_serve(monkeypatch, [split, table(_PRIORITY_HEADER, _PRIORITY_BODY)])
    assert detector.detect(make_cfg()) == _TWO_TABLE_IDS


def test_detect_nested_table_rows_stay_out_of_the_outer_table(monkeypatch: pytest.MonkeyPatch):
    # a tbody of a table nested in a pinned table's cell is not the pinned
    # table's tbody: its row must never price an id
    note = (
        "<tr><td colspan='4'><table><tbody>"
        f"{row('BGE Large', '9.999', '-', '-')}</tbody></table></td></tr>"
    )
    standard = table(
        _STANDARD_HEADER,
        row("Kimi K3 ⌖", "42.857", "214.286", "4.286"),
        row("GTE", "1.857", "-", "-"),
        note,
    )
    _detect_serve(monkeypatch, [standard, table(_PRIORITY_HEADER, _PRIORITY_BODY)])
    assert "bge-large" not in detector.detect(make_cfg())


def test_detect_folded_span_reads_the_own_row_past_a_nested_first_row(
    monkeypatch: pytest.MonkeyPatch,
):
    # a legend table's row ahead of the table's own rows is no tier span row:
    # reading it flipped the standard table to priority and raised
    legend = f"<div><table><tr><td>Legend</td><td>{_PRIORITY_SPAN}</td></tr></table></div>"
    standard = _STANDARD_TABLE.replace("<thead>", legend + "<thead>", 1)
    _detect_serve(monkeypatch, [standard, table(_PRIORITY_HEADER, _PRIORITY_BODY)])
    assert detector.detect(make_cfg()) == _TWO_TABLE_IDS


def test_detect_folded_span_skips_a_nested_cell_in_the_first_row(
    monkeypatch: pytest.MonkeyPatch,
):
    # a nested cell inside the first header cell is no second cell of the
    # row: reading it flipped the standard table to priority and raised
    nested = f"<table><tr><td>{_PRIORITY_SPAN}</td><td>x</td></tr></table>"
    header = (
        f"<tr><th>{nested}Model</th>"
        f"<th>Standard Pay Per Token (DBU Per 1M Tokens)</th></tr>"
        f"<tr><th>Input</th><th>Output</th><th>Cache read</th></tr>"
    )
    standard = table(
        header,
        row("Kimi K3 ⌖", "42.857", "214.286", "4.286"),
        row("GTE", "1.857", "-", "-"),
    )
    _detect_serve(monkeypatch, [standard, table(_PRIORITY_HEADER, _PRIORITY_BODY)])
    assert detector.detect(make_cfg()) == _TWO_TABLE_IDS


def test_detect_structural_pin_ignores_a_nested_sub_header_row(
    monkeypatch: pytest.MonkeyPatch,
):
    # the second header row's nested table is no cell of that row: pinning on
    # its cells made the table a second priority table and raised
    sub = "<table><tr><th>Input</th><th>Output</th><th>Cache read</th></tr></table>"
    header = (
        f"<tr><th rowspan='2'>Model</th><th colspan='3'>{_PRIORITY_SPAN}</th></tr><tr>{sub}</tr>"
    )
    bogus = table(header, row("Bespoke 1", "1.000", "2.000", "3.000"))
    _detect_serve(monkeypatch, [_STANDARD_TABLE, table(_PRIORITY_HEADER, _PRIORITY_BODY), bogus])
    assert detector.detect(make_cfg()) == _TWO_TABLE_IDS


def test_detect_one_row_thead_ignores_nested_header_cells(
    monkeypatch: pytest.MonkeyPatch,
):
    # thead row cells nested in another table are no cells of the row: they
    # completed the one-row header and the caption span made a second
    # priority table
    nested = "<table><tr><th>Input</th><th>Output</th><th>Cache read</th></tr></table>"
    legend = (
        f"<table class='table'><caption>{_PRIORITY_SPAN}</caption>"
        f"<thead><tr><th>Model</th>{nested}</tr></thead>"
        f"<tbody>{row('Bespoke 1', '1.000', '2.000', '3.000')}</tbody></table>"
    )
    _detect_serve(monkeypatch, [_STANDARD_TABLE, table(_PRIORITY_HEADER, _PRIORITY_BODY), legend])
    assert detector.detect(make_cfg()) == _TWO_TABLE_IDS


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
    text = table(
        _STANDARD_HEADER,
        row("GTE", "1.857", "-", "-"),
        row("Kimi K3", "42.857 DBU", "214.286"),
    )
    serve(monkeypatch, text)
    with pytest.raises(FetchError, match="unreadable dbu rate cell"):
        scraper.scrape(make_cfg(), "kimi-k3")


def test_scrape_skips_unrelated_odd_rows(monkeypatch: pytest.MonkeyPatch):
    text = table(
        _STANDARD_HEADER,
        row("GTE", "1.857", "-", "-"),
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
        row("GTE", "1.857", "-", "-"),
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
    # priority table's merged GLM row must not answer a glm-5.2 scrape when
    # the standard table carries no GLM row
    text = table(_STANDARD_HEADER, row("GTE", "1.857", "-", "-")) + table(
        _PRIORITY_HEADER, row("GLM-5.2, 5.3", "35.000", "110.000", "6.500")
    )
    serve(monkeypatch, text)
    assert scraper.scrape(make_cfg(), "glm-5.2") is None


def test_scrape_priority_merged_row_covers_both_ids(live_page):
    # the priority table's merged "GLM-5.2, 5.3" row carries one rate pair
    # for both "-priority" ids, the standard table's merged-row shape
    for model_id in ("glm-5.2-priority", "glm-5.3-priority"):
        pricing = scraper.scrape(make_cfg(), model_id)
        assert pricing is not None, model_id
        assert pricing.input_cost_per_token == pytest.approx(35.000 / 1e6)
        assert pricing.output_cost_per_token == pytest.approx(110.000 / 1e6)
        assert pricing.cache_read_cost_per_token == pytest.approx(6.500 / 1e6)


def test_scrape_new_priority_listings(live_page):
    kimi = scraper.scrape(make_cfg(), "kimi-k3-priority")
    assert kimi is not None
    assert kimi.input_cost_per_token == pytest.approx(75.000 / 1e6)
    assert kimi.output_cost_per_token == pytest.approx(375.000 / 1e6)
    assert kimi.cache_read_cost_per_token == pytest.approx(7.500 / 1e6)
    flash = scraper.scrape(make_cfg(), "glm-5.3-flash-priority")
    assert flash is not None
    assert flash.input_cost_per_token == pytest.approx(3.750 / 1e6)
    assert flash.output_cost_per_token == pytest.approx(12.500 / 1e6)
    assert flash.cache_read_cost_per_token == pytest.approx(0.750 / 1e6)


def test_scrape_deepseek_v4_1_flash(live_page):
    pricing = scraper.scrape(make_cfg(), "deepseek-v4.1-flash")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(4.286 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(17.143 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.429 / 1e6)
    assert pricing.currency == "DBU"


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
        row("GTE", "1.857", "-", "-"),
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
    text = table(
        _STANDARD_HEADER,
        row("GTE", "1.857", "-", "-"),
        row("GLM-5.2, 5.3", "0.000", "0.000"),
    )
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
        row("GTE", "1.857", "-", "-"),
        row("GLM-5.2", "20.000 DBU", "62.857"),
        row("Kimi K3", "42.857", "214.286"),
    )
    serve(monkeypatch, text)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == ["gte", "kimi-k3"]
    assert "unreadable dbu rate cell" in caplog.text


def test_detect_unknown_output_shape_skips(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    text = table(
        _STANDARD_HEADER,
        row("GTE", "1.857", "-", "-"),
        row("GLM-5.2", "20.000", "62.857 DBU"),
        row("Kimi K3", "42.857", "214.286"),
    )
    serve(monkeypatch, text)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == ["gte", "kimi-k3"]
    assert "unreadable dbu rate cell" in caplog.text


def test_detect_unknown_cache_shape_skips(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    text = table(
        _STANDARD_HEADER,
        row("GTE", "1.857", "-", "-"),
        row("GLM-5.2", "20.000", "62.857", "3.714 DBU"),
        row("Kimi K3", "42.857", "214.286"),
    )
    serve(monkeypatch, text)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == ["gte", "kimi-k3"]
    assert "unreadable dbu rate cell" in caplog.text


def test_detect_unmapped_name_skips(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # a priced row whose display name the mapping does not hold skips with
    # a warning; one new model can no longer blind the provider (plan #22)
    text = table(
        _STANDARD_HEADER,
        row("GTE", "1.857", "-", "-"),
        row("Brand New Model", "20.000", "62.857"),
        row("GLM-5.2, 5.3", "20.000", "62.857"),
    )
    serve(monkeypatch, text)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(make_cfg()) == ["gte", "glm-5.2", "glm-5.3"]
    assert "unmapped model name" in caplog.text


def test_detect_all_rows_skipped_raises(monkeypatch: pytest.MonkeyPatch):
    # GTE's priced input satisfies the guard, then its output cell fails the
    # strict read, so every row skips and the empty result still raises
    text = table(
        _STANDARD_HEADER,
        row("GTE", "1.857", "1.000 DBU", "-"),
        row("GLM-5.2", "20.000 DBU", "62.857"),
    )
    serve(monkeypatch, text)
    with pytest.raises(FetchError) as excinfo:
        detector.detect(make_cfg())
    assert str(excinfo.value) == f"no per-token model rows on {PAGE_URL}"


def test_detect_missing_table_raises(monkeypatch: pytest.MonkeyPatch):
    serve(monkeypatch, "<html><body><table><tr><td>a</td></tr></table></body></html>")
    with pytest.raises(FetchError, match="no foundation-model-serving dbu table"):
        detector.detect(make_cfg())


def test_detect_no_priced_rows_raises(monkeypatch: pytest.MonkeyPatch):
    text = table(
        _STANDARD_HEADER,
        row("GTE", "-", "-", "-"),
        row("GLM-5.2", "-", "-"),
        row("Kimi K3", "-", "-"),
    )
    serve(monkeypatch, text)
    # a table pricing nothing prices no standard-only model either: the guard
    # is the earlier raise
    with pytest.raises(FetchError) as excinfo:
        detector.detect(make_cfg())
    assert str(excinfo.value) == _NO_STANDARD_ONLY


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

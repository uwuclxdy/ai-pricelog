from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import moonshot_page as detector
from ai_pricelog.scrapers import moonshot_page as scraper
from ai_pricelog.web import FetchError

MODELS_URL = "https://platform.kimi.ai/docs/models.md"
INDEX_URL = "https://platform.kimi.ai/docs/llms.txt"
CHAT_URL = "https://platform.kimi.ai/docs/pricing/chat.md"
FLIGHT_URL = "https://platform.kimi.ai/docs/pricing/chat"
FIXTURES = Path(__file__).parent / "fixtures" / "moonshot_page"

PAGES = {
    "models": (MODELS_URL, "models.md"),
    "models-2026-11-19": (MODELS_URL, "models-2026-11-19.md"),
    "llms": (INDEX_URL, "llms.txt"),
    "chat": (CHAT_URL, "chat.md"),
    "chat-2026-11-18": (CHAT_URL, "chat-2026-11-18.md"),
    "rendered-2026-11-18": (FLIGHT_URL, "chat-rendered-2026-11-18.html"),
}

# the stored moonshot ids whose newest row on the branch base is no removal
# (latest observations 2026-10-31), pinned by value so a later landed row
# does not rewrite these tests
STORED_LIVE_IDS = [
    "kimi-k2.6",
    "kimi-k2.7-code",
    "kimi-k2.7-code-highspeed",
    "kimi-k3",
    "kimi-k3.1-pro",
    "kimi-k3.1-pro-highspeed",
]

EXPECTED_IDS = [
    "kimi-k3",
    "kimi-k2.7-code",
    "kimi-k2.7-code-highspeed",
    "kimi-k2.6",
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="moonshot",
        provider="Moonshot AI",
        detector="moonshot_page",
        detector_url=MODELS_URL,
        scraper="moonshot_page",
        scraper_url=INDEX_URL,
    )


def fixture_fetch(*pages: str) -> Callable[[str], str]:
    data = {PAGES[name][0]: (FIXTURES / PAGES[name][1]).read_text() for name in pages}

    def fake(url: str) -> str:
        if url not in data:
            raise FetchError(f"fetch failed for {url}: no fixture")
        return data[url]

    return fake


@pytest.fixture(autouse=True)
def clear_index_cache():
    scraper._load_index.cache_clear()
    scraper._page_text.cache_clear()
    yield
    scraper._load_index.cache_clear()
    scraper._page_text.cache_clear()


def test_detect_models(monkeypatch):
    monkeypatch.setattr(detector, "fetch_text", fixture_fetch("models"))
    ids = detector.detect(cfg())
    assert ids == EXPECTED_IDS
    assert "kimi-k2.5" not in ids  # retired 2026-08-31, deprecated table excluded
    assert "moonshot-v1-8k" not in ids


def test_detect_keeps_rows_after_a_line_separator_in_a_cell(monkeypatch):
    # str.splitlines() cut the row at U+2028 and reset the table, so every
    # later row left detection and its absence counter ran
    page = (FIXTURES / "models.md").read_text()
    anchor = "Kimi's dedicated coding model."
    assert page.count(anchor) == 1
    torn = page.replace(anchor, "Kimi's dedicated\u2028coding model.")
    monkeypatch.setattr(detector, "fetch_text", lambda url: torn)
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_detect_malformed_page_raises(monkeypatch):
    monkeypatch.setattr(detector, "fetch_text", lambda url: "# no tables here\n")
    with pytest.raises(FetchError, match="Model Name"):
        detector.detect(cfg())


def test_detect_header_wording_drift_still_matches(monkeypatch):
    # the Model Name header pins after folding case and whitespace, so a
    # drifted spelling still locates the model tables
    monkeypatch.setattr(
        detector,
        "fetch_text",
        lambda url: "| Model   Name | Context |\n| --- | --- |\n| `kimi-k3` | 1M |\n",
    )
    assert detector.detect(cfg()) == ["kimi-k3"]


def test_scrape_k3(monkeypatch):
    # the live llms.txt also carries an /api/chat.md link; resolution must
    # key on /pricing/ so it cannot match that one. kimi-k3 lives in the K3
    # series table, the FIRST DocTable block: the scrape must search every
    # block, not just the last
    monkeypatch.setattr(scraper, "fetch_text", fixture_fetch("llms", "chat"))
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.00 / 1e6)  # cache miss, not hit
    assert pricing.cache_read_cost_per_token == pytest.approx(0.30 / 1e6)
    assert pricing.cache_write_cost_per_token == pytest.approx(3.00 / 1e6)
    assert pricing.cache_write_1h_cost_per_token == pytest.approx(6.00 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(15.00 / 1e6)
    assert pricing.mode == "chat"
    assert pricing.max_tokens_in == 1_048_576
    assert pricing.url == CHAT_URL


def test_scrape_k26(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_text", fixture_fetch("llms", "chat"))
    pricing = scraper.scrape(cfg(), "kimi-k2.6")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.95 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.16 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(4.00 / 1e6)
    assert pricing.max_tokens_in == 262_144
    assert pricing.url == CHAT_URL


def test_scrape_k27_code_and_highspeed(monkeypatch):
    # the two longer ids match their own rows, not each other's
    monkeypatch.setattr(scraper, "fetch_text", fixture_fetch("llms", "chat"))
    code = scraper.scrape(cfg(), "kimi-k2.7-code")
    assert code is not None
    assert code.input_cost_per_token == pytest.approx(0.95 / 1e6)
    assert code.cache_read_cost_per_token == pytest.approx(0.19 / 1e6)
    assert code.output_cost_per_token == pytest.approx(4.00 / 1e6)
    assert code.max_tokens_in == 262_144
    assert code.url == CHAT_URL
    highspeed = scraper.scrape(cfg(), "kimi-k2.7-code-highspeed")
    assert highspeed is not None
    assert highspeed.input_cost_per_token == pytest.approx(1.90 / 1e6)
    assert highspeed.cache_read_cost_per_token == pytest.approx(0.38 / 1e6)
    assert highspeed.output_cost_per_token == pytest.approx(8.00 / 1e6)
    assert highspeed.max_tokens_in == 262_144
    assert highspeed.url == CHAT_URL


def test_scrape_absent_model_returns_none(monkeypatch):
    # no row for the model on the merged page -> unpriced, not an exception
    monkeypatch.setattr(scraper, "fetch_text", fixture_fetch("llms", "chat"))
    assert scraper.scrape(cfg(), "kimi-k9") is None


def test_scrape_index_without_chat_link_raises(monkeypatch):
    # batch/tools/limits are pricing pages but not model-inference ones
    index_text = "\n".join(
        [
            "- [BatchJob Pricing](https://platform.kimi.ai/docs/pricing/batch.md): batch",
            "- [WebSearch Pricing](https://platform.kimi.ai/docs/pricing/tools.md): tools",
            "- [Rate Limiting](https://platform.kimi.ai/docs/pricing/limits.md): limits",
        ]
    )
    monkeypatch.setattr(scraper, "fetch_text", lambda url: index_text)
    with pytest.raises(FetchError, match=INDEX_URL):
        scraper.scrape(cfg(), "kimi-k3")


def test_scrape_index_with_ambiguous_chat_links_raises(monkeypatch):
    index_text = "\n".join(
        [
            "- [Pricing One](https://platform.kimi.ai/docs/pricing/chat.md): one",
            "- [Pricing Two](https://platform.kimi.ai/docs/pricing/chat.md): two",
        ]
    )
    monkeypatch.setattr(scraper, "fetch_text", lambda url: index_text)
    with pytest.raises(FetchError, match=INDEX_URL):
        scraper.scrape(cfg(), "kimi-k3")


def test_scrape_page_without_doctable_raises(monkeypatch):
    def fake(url: str) -> str:
        if url == INDEX_URL:
            return (FIXTURES / "llms.txt").read_text()
        if url == CHAT_URL:
            return "# no pricing table here\n"
        if url == FLIGHT_URL:
            return _flight_page()
        raise AssertionError(f"unexpected fetch of {url}")

    monkeypatch.setattr(scraper, "fetch_text", fake)
    with pytest.raises(FetchError, match="DocTable"):
        scraper.scrape(cfg(), "kimi-k3")


def test_scrape_page_without_model_table_raises(monkeypatch):
    # a DocTable without a Model column is not a pricing table; a page whose
    # tables are all like that is a shape break, not "model absent"
    page_text = '<DocTable columns={[{ title: "Unit" }]}\n  rows={[["1M tokens"]]}\n/>\n'

    def fake(url: str) -> str:
        if url == INDEX_URL:
            return (FIXTURES / "llms.txt").read_text()
        if url == CHAT_URL:
            return page_text
        if url == FLIGHT_URL:
            return _flight_page()
        raise AssertionError(f"unexpected fetch of {url}")

    monkeypatch.setattr(scraper, "fetch_text", fake)
    with pytest.raises(FetchError, match="Model pricing table"):
        scraper.scrape(cfg(), "kimi-k3")


def test_scrape_skips_non_pricing_table(monkeypatch):
    # non-pricing DocTables on both sides of the pricing one are skipped, not
    # a failure; the leading one executes _pricing's no-Model-column branch,
    # the trailing one makes the pre-fix last-block-only read fail
    page_text = (
        '<DocTable columns={[{ title: "Unit" }]}\n  rows={[["1M tokens"]]}\n/>\n'
        + (FIXTURES / "chat.md").read_text()
        + '<DocTable columns={[{ title: "Unit" }]}\n  rows={[["1M tokens"]]}\n/>\n'
    )

    def fake(url: str) -> str:
        if url == INDEX_URL:
            return (FIXTURES / "llms.txt").read_text()
        if url == CHAT_URL:
            return page_text
        raise AssertionError(f"unexpected fetch of {url}")

    monkeypatch.setattr(scraper, "fetch_text", fake)
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.00 / 1e6)


def test_malformed_block_does_not_borrow_later_props(monkeypatch):
    # a block missing its rows prop must raise, not adopt the next block's
    # rows and silently return swapped rates
    page_text = (
        "<DocTable\n"
        '  columns={[{ title: "Model" }, { title: "Input Price" }, { title: "Output Price" }]}\n'
        "/>\n" + (FIXTURES / "chat.md").read_text()
    )

    def fake(url: str) -> str:
        if url == INDEX_URL:
            return (FIXTURES / "llms.txt").read_text()
        if url == CHAT_URL:
            return page_text
        raise AssertionError(f"unexpected fetch of {url}")

    monkeypatch.setattr(scraper, "fetch_text", fake)
    with pytest.raises(FetchError, match="missing columns or rows props"):
        scraper.scrape(cfg(), "kimi-k3")


def test_scrape_index_fetched_once(monkeypatch):
    base = fixture_fetch("llms", "chat")
    calls = {"index": 0}

    def counting(url: str) -> str:
        if url == INDEX_URL:
            calls["index"] += 1
        return base(url)

    monkeypatch.setattr(scraper, "fetch_text", counting)
    assert scraper.scrape(cfg(), "kimi-k3") is not None
    assert scraper.scrape(cfg(), "kimi-k2.6") is not None
    assert scraper.scrape(cfg(), "kimi-k9") is None
    assert calls["index"] == 1


def test_scrape_index_failure_propagates(monkeypatch):
    def boom(url):
        raise FetchError(f"fetch failed for {url}")

    monkeypatch.setattr(scraper, "fetch_text", boom)
    with pytest.raises(FetchError, match=INDEX_URL):
        scraper.scrape(cfg(), "kimi-k3")


def test_pricing_plain_input_column_without_cache_split():
    # a table without the cache columns still parses via the plain
    # "Input Price" path (the retired v1 page shape)
    doc = (
        ["Model", "Input Price", "Output Price", "Context Window"],
        [["moonshot-v1-8k", "$0.20", "$2.00", "8,192 tokens"]],
    )
    pricing = scraper._pricing(doc, "moonshot-v1-8k", CHAT_URL)
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.20 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(2.00 / 1e6)
    assert pricing.max_tokens_in == 8192
    assert pricing.cache_read_cost_per_token is None


def test_pricing_tolerates_non_string_context_cell():
    # the context cell is str()-wrapped like its sibling cells
    doc = (
        ["Model", "Input Price (Cache Miss)", "Output Price", "Context Window"],
        [["kimi-k2.6", "$0.95", "$4.00", 262_144]],
    )
    pricing = scraper._pricing(doc, "kimi-k2.6", CHAT_URL)
    assert pricing is not None
    assert pricing.max_tokens_in == 262_144
    assert pricing.cache_read_cost_per_token is None


_HTML_TABLE = """
<table>
  <thead>
    <tr>
      <th>Model</th><th>Input Price</th><th>Cached Input Price</th>
      <th>Output Price</th><th>Context Window</th>
    </tr>
  </thead>
  <tbody>
    <tr><td>kimi-k3</td><td>$0.30</td><td>$0.03</td><td>$1.20</td><td>1,048,576 tokens</td></tr>
  </tbody>
</table>
"""

_EMPTY_SHELL = """
<table>
  <thead>
    <tr />
  </thead>

  <tbody />
</table>
"""

_PLACEHOLDER_SHELL = """
<table>
  <thead><tr><th>Model</th><th>Input Price</th><th>Output Price</th></tr></thead>
  <tbody><tr><td>&#8203;</td><td>&#8203;</td><td>&#8203;</td></tr></tbody>
</table>
"""


def _chat_page(monkeypatch: pytest.MonkeyPatch, page_text: str, flight: str | None = None) -> None:
    """serve the markdown export, and the rendered page's payload chunks when
    the reader falls back to them; `flight` None serves a page with no table."""
    scraper._page_text.cache_clear()
    flight_text = _flight_page(*([flight] if flight is not None else []))

    def fake(url: str) -> str:
        if url == INDEX_URL:
            return (FIXTURES / "llms.txt").read_text()
        if url == CHAT_URL:
            return page_text
        if url == FLIGHT_URL:
            return flight_text
        raise AssertionError(f"unexpected fetch of {url}")

    monkeypatch.setattr(scraper, "fetch_text", fake)


def _flight_page(*payloads: str) -> str:
    """the rendered docs page's flight-push shape: one script tag per payload
    chunk, the payload a JSON string like the server's own."""
    pushes = "".join(
        f"<script>self.__next_f.push([1,{json.dumps(payload)}])</script>" for payload in payloads
    )
    return f"<!DOCTYPE html><html><body>{pushes}</body></html>"


# the rendered table's own column titles, observed on the live page 2026-10-31
_K3_FLIGHT_CALL = (
    "_jsx(_MdxComponentBoundary,{name:`DocTable`,children:_jsx(DocTable,{"
    "className:`doc-table-bordered`,corner:{top:`Model`,bottom:`Name`},"
    "columns:[{title:`Model`,width:`25%`},{title:`Input`,width:`15%`},"
    "{title:`Output`,width:`15%`},"
    "{title:_jsx(Tooltip,{tip:`Cached input is billed at this rate.`,"
    "children:`Cached Input`}),width:`15%`},"
    "{title:_jsx(Tooltip,{tip:`Writing a prompt prefix with a 5-minute TTL.`,"
    "children:`5m writes`}),width:`15%`},"
    "{title:_jsx(Tooltip,{tip:`Writing a prompt prefix with a 1-hour TTL.`,"
    "children:`1h writes`}),width:`15%`}],"
    "rows:[[_jsx(_components.a,{href:`/guide/kimi-k3-1-pro-quickstart`,"
    "children:`kimi-k3`}),`$3.00 / MTok`,`$15.00 / MTok`,`$0.30 / MTok`,"
    "`$3.00 / MTok`,`$6.00 / MTok`]]})})"
)

_K2_FLIGHT_CALL = (
    "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`},"
    "{title:_jsx(Tooltip,{tip:`Cached input is billed at this rate.`,"
    "children:`Cached Input`})}],"
    "rows:[[_jsx(_components.a,{href:`/guide/kimi-k2-7-code-quickstart`,"
    "children:`kimi-k2.7-code`}),`$0.95 / MTok`,`$4.00 / MTok`,`$0.19 / MTok`]]})"
)

# the page renders one props-carrying call beside a prop-less one, and the
# DocTable module definition sits in the same stream
_SHELL_FLIGHT_CALL = (
    "_jsx(DocTable,{className:`doc-table-bordered`,corner:{top:`Model`,bottom:`Name`}})"
)
_DOC_TABLE_SOURCE = (
    "const DocTable=({columns=[],rows=[],groups=[],corner=null,className=``})=>{return null};"
)


def test_scrape_reads_the_flight_payload_when_the_markdown_export_is_empty(monkeypatch):
    # since 2026-10-23 the .md export carries empty table shells while the
    # rendered page still holds both series tables, as DocTable calls in its
    # flight payload inside an MdxComponentBoundary wrapper
    _chat_page(monkeypatch, _EMPTY_SHELL, _K3_FLIGHT_CALL)
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.00 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(15.00 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.30 / 1e6)
    assert pricing.cache_write_cost_per_token == pytest.approx(3.00 / 1e6)
    assert pricing.cache_write_1h_cost_per_token == pytest.approx(6.00 / 1e6)
    assert pricing.url == FLIGHT_URL


def test_the_flight_payload_prices_the_k2_series_table(monkeypatch):
    _chat_page(monkeypatch, _EMPTY_SHELL, _K3_FLIGHT_CALL + _K2_FLIGHT_CALL)
    pricing = scraper.scrape(cfg(), "kimi-k2.7-code")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.95 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(4.00 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.19 / 1e6)


def test_a_props_less_doctable_call_contributes_no_table(monkeypatch):
    # the rendered page carries a prop-less DocTable beside the real one; it
    # names no rate and must neither raise nor hide the table after it
    _chat_page(monkeypatch, _EMPTY_SHELL, _SHELL_FLIGHT_CALL + _K3_FLIGHT_CALL)
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.00 / 1e6)


def test_the_component_source_reads_as_no_table(monkeypatch):
    # the module definition uses the same name and carries columns/rows
    # defaults; reading it as a table would price nothing and mask a dark page
    _chat_page(monkeypatch, _EMPTY_SHELL, _DOC_TABLE_SOURCE)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "kimi-k3")
    assert str(exc.value).endswith(FLIGHT_URL)


def test_a_flight_payload_with_no_table_raises(monkeypatch):
    _chat_page(monkeypatch, _EMPTY_SHELL)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "kimi-k3")
    assert str(exc.value).endswith(FLIGHT_URL)


def test_the_markdown_export_wins_when_it_carries_the_table(monkeypatch):
    # a restored export costs no second fetch of the rendered page
    def fake(url: str) -> str:
        if url == INDEX_URL:
            return (FIXTURES / "llms.txt").read_text()
        if url == CHAT_URL:
            return (FIXTURES / "chat.md").read_text()
        raise AssertionError(f"unexpected fetch of {url}")

    monkeypatch.setattr(scraper, "fetch_text", fake)
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.url == CHAT_URL


def test_an_incidental_export_table_still_falls_back_to_the_payload(monkeypatch):
    # the fallback answers "does the export price anything", not "does it
    # carry a table": a Unit table beside the empty shells must not hold the
    # reader on the export while the payload carries the rates
    unit = '<DocTable columns={[{ title: "Unit" }]}\n  rows={[["1M tokens"]]}\n/>\n'
    _chat_page(monkeypatch, unit, _K3_FLIGHT_CALL)
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.00 / 1e6)


def test_a_data_less_export_doctable_reads_as_no_table():
    # the export's priced-columns shell is the shell _html_docs and
    # _jsx_docs drop; read as a table it would price every model absent
    shell = (
        '<DocTable columns={[{ title: "Model" }, { title: "Input Price" },'
        ' { title: "Output Price" }]}\n  rows={[]}\n/>\n'
    )
    blank = (
        '<DocTable columns={[{ title: "Model" }, { title: "Input Price" },'
        ' { title: "Output Price" }]}\n  rows={[["", ""]]}\n/>\n'
    )
    assert scraper._doc_tables(shell) == []
    assert scraper._doc_tables(blank) == []
    # a block carrying a printable row still reads as a table
    tables = scraper._doc_tables((FIXTURES / "chat.md").read_text())
    assert len(tables) > 1, f"priced export tables kept: {len(tables)}"


def test_a_data_less_export_doctable_falls_back_to_the_rendered_page(monkeypatch):
    shell = (
        '<DocTable columns={[{ title: "Model" }, { title: "Input Price" },'
        ' { title: "Output Price" }]}\n  rows={[]}\n/>\n'
    )
    _chat_page(monkeypatch, shell, _K3_FLIGHT_CALL)
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.00 / 1e6)
    assert pricing.url == FLIGHT_URL


def test_a_data_less_export_doctable_beside_a_priced_one_prices_from_the_export(monkeypatch):
    # dropping the shell must not cost the export its priced block: the
    # priced block wins and no rendered page is fetched
    shell = (
        '<DocTable columns={[{ title: "Model" }, { title: "Input Price" },'
        ' { title: "Output Price" }]}\n  rows={[]}\n/>\n'
    )

    def fake(url: str) -> str:
        if url == INDEX_URL:
            return (FIXTURES / "llms.txt").read_text()
        if url == CHAT_URL:
            return shell + (FIXTURES / "chat.md").read_text()
        raise AssertionError(f"unexpected fetch of {url}")

    monkeypatch.setattr(scraper, "fetch_text", fake)
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.00 / 1e6)
    assert pricing.url == CHAT_URL


def test_a_payload_pricing_table_with_no_row_still_raises(monkeypatch):
    # pricing columns with no data row is the same shell the html side
    # refuses; reading it as "model absent" would read a dark page as a
    # delisting half
    empty_call = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`}],rows:[]})"
    )
    _chat_page(monkeypatch, _EMPTY_SHELL, empty_call)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "kimi-k3")
    assert str(exc.value).endswith(FLIGHT_URL)


def test_a_non_pricing_flight_table_with_numeric_cells_is_skipped(monkeypatch):
    # an incidental table is skipped before its cells are read, so a number
    # or a null in a table that names no rate blinds nothing
    incidental = "_jsx(DocTable,{columns:[{title:`Region`}],rows:[[1], [null]]})"
    _chat_page(monkeypatch, _EMPTY_SHELL, incidental + _K3_FLIGHT_CALL)
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.00 / 1e6)


def test_a_docs_example_inside_a_payload_string_prices_nothing(monkeypatch):
    # a documentation sample carries the call head as page text; scanning into
    # a string literal would price a fabricated $0.01 row over the real table
    sample = (
        '_jsx(_components.pre,{children:`_jsx(DocTable,{columns:[{title:"Model"},'
        '{title:"Input"},{title:"Output"}],rows:[["kimi-k3","$0.01 / MTok",'
        '"$0.02 / MTok"]]}) is the docs example`})'
    )
    _chat_page(monkeypatch, _EMPTY_SHELL, sample + _K3_FLIGHT_CALL)
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.00 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(15.00 / 1e6)


def test_a_payload_literal_that_does_not_decode_raises(monkeypatch):
    def fake(url: str) -> str:
        if url == INDEX_URL:
            return (FIXTURES / "llms.txt").read_text()
        if url == CHAT_URL:
            return _EMPTY_SHELL
        if url == FLIGHT_URL:
            return '<script>self.__next_f.push([1,"bad \\q escape"])</script>'
        raise AssertionError(f"unexpected fetch of {url}")

    monkeypatch.setattr(scraper, "fetch_text", fake)
    with pytest.raises(FetchError, match="does not decode"):
        scraper.scrape(cfg(), "kimi-k3")


def test_a_template_interpolation_in_a_cell_raises(monkeypatch):
    call = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`}],"
        "rows:[[`kimi-k3`,`$3.00 / MTok`,`${fee}`]]})"
    )
    _chat_page(monkeypatch, _EMPTY_SHELL, call)
    with pytest.raises(FetchError, match="interpolation"):
        scraper.scrape(cfg(), "kimi-k3")


def test_the_flight_grammar_reads_the_live_prop_shapes(monkeypatch):
    # the live call carries numeric props (groups spans) and booleans beside
    # the columns/rows; the grammar must read past them, not raise
    call = (
        "_jsx(DocTable,{className:`doc-table-bordered`,groups:[{title:`Base tokens`,span:2}],"
        "corner:null,columns:[{title:`Model`},{title:`Input`},{title:`Output`}],"
        "rows:[[`kimi-k3`,`$3.00 / MTok`,`$15.00 / MTok`]]})"
    )
    _chat_page(monkeypatch, _EMPTY_SHELL, call)
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.00 / 1e6)


def test_the_rendered_page_is_fetched_once_across_scrapes(monkeypatch):
    calls: list[str] = []

    def fake(url: str) -> str:
        if url == INDEX_URL:
            return (FIXTURES / "llms.txt").read_text()
        if url == CHAT_URL:
            return _EMPTY_SHELL
        if url == FLIGHT_URL:
            calls.append(url)
            return _flight_page(_K3_FLIGHT_CALL + _K2_FLIGHT_CALL)
        raise AssertionError(f"unexpected fetch of {url}")

    monkeypatch.setattr(scraper, "fetch_text", fake)
    assert scraper.scrape(cfg(), "kimi-k3") is not None
    assert scraper.scrape(cfg(), "kimi-k2.7-code") is not None
    assert calls == [FLIGHT_URL]


def test_scrape_reads_the_html_table_shape(monkeypatch):
    # the docs platform writes plain HTML tables instead of <DocTable> props
    # since 2026-10; when the rows come back, they must price through the
    # same reader. web.py already owns the html-table helpers
    # (own_table_rows / own_cells / header_labels)
    _chat_page(monkeypatch, _HTML_TABLE)
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.30 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(1.20 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.03 / 1e6)
    assert pricing.max_tokens_in == 1_048_576


@pytest.mark.parametrize(
    "page_text", [_EMPTY_SHELL, _PLACEHOLDER_SHELL], ids=["empty-shell", "placeholder-row"]
)
def test_a_shell_with_no_readable_row_still_raises(monkeypatch, page_text):
    # the page as observed 2026-10-23 ships a self-closed header row and an
    # empty body; a table whose only data row is zero-width placeholders is
    # the same shell. both must stay a loud shape break, never a silent
    # "model absent" (which would read as a delisting half), and the
    # rendered page carrying no table either leaves it loud
    _chat_page(monkeypatch, page_text)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "kimi-k3")
    assert CHAT_URL in str(exc.value)
    assert str(exc.value).endswith(FLIGHT_URL)


def test_a_huge_context_cell_raises_a_fetch_error():
    # a 4300+ digit count reaches int() and raises ValueError, which is no
    # FetchError: the reader must bound the run and name the cell
    doc = (
        ["Model", "Input Price", "Output Price", "Context Window"],
        [["kimi-k3", "$0.30", "$1.20", "9" * 5000]],
    )
    with pytest.raises(FetchError, match="kimi-k3"):
        scraper._pricing(doc, "kimi-k3", CHAT_URL)


def test_a_context_cell_past_the_shared_count_bound_raises():
    # the reader uses web.MAX_COUNT_DIGITS, the same bound the other count
    # readers share, so a 13-digit run is no context length
    doc = (
        ["Model", "Input Price", "Output Price", "Context Window"],
        [["kimi-k3", "$0.30", "$1.20", "9" * 13 + " tokens"]],
    )
    with pytest.raises(FetchError, match="kimi-k3"):
        scraper._pricing(doc, "kimi-k3", CHAT_URL)


_COLSPAN_TABLE = """
<table>
  <thead>
    <tr>
      <th>Model</th><th>Input Price</th><th colspan="2">Cache Write</th>
      <th>Output Price</th><th>Context Window</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>kimi-k3</td><td>$0.30</td><td>$0.06</td><td>$0.03</td>
      <td>$1.20</td><td>1,048,576 tokens</td>
    </tr>
  </tbody>
</table>
"""


def test_scrape_reads_a_colspan_header_grid(monkeypatch):
    # a spanned header shifts every later title: without the grid, output
    # prices the third cell ($0.03) and context reads $1.20
    _chat_page(monkeypatch, _COLSPAN_TABLE)
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.30 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(1.20 / 1e6)
    assert pricing.cache_read_cost_per_token is None
    assert pricing.max_tokens_in == 1_048_576


def test_a_fenced_example_table_contributes_no_doc(monkeypatch):
    # a docs example inside a markdown code fence is prose, not a pricing table
    _chat_page(monkeypatch, "```\n" + _HTML_TABLE + "\n```\n")
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "kimi-k3")
    assert CHAT_URL in str(exc.value)


def test_a_tab_after_the_closing_fence_closes_it(monkeypatch):
    # CommonMark lets a closing run be followed by spaces OR tabs. a reader
    # that takes spaces only never closes, blanks the rest of the page and
    # raises on a table it should have priced
    _chat_page(monkeypatch, "```\n" + _HTML_TABLE + "\n```\t\n" + _HTML_TABLE)
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.30 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(1.20 / 1e6)


def test_a_backtick_in_a_backtick_fence_info_string_opens_no_fence(monkeypatch):
    # CommonMark forbids a backtick in a backtick fence's info string, so the
    # line is prose and the table under it is real
    _chat_page(monkeypatch, "```kimi `k3` example\n" + _HTML_TABLE + "\n")
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.30 / 1e6)


def test_a_tilde_fence_info_string_may_hold_a_backtick(monkeypatch):
    # tildes carry no such restriction: this still opens, so the example table
    # inside stays prose and the page has no pricing table
    _chat_page(monkeypatch, "~~~kimi `k3` example\n" + _HTML_TABLE + "\n~~~\n")
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "kimi-k3")
    assert CHAT_URL in str(exc.value)


_INCIDENTAL_TABLE = """
<table>
  <thead><tr><th>Model</th><th>Context Window</th></tr></thead>
  <tbody><tr><td>kimi-k3</td><td>1,048,576 tokens</td></tr></tbody>
</table>
"""


def test_an_incidental_model_table_does_not_block_a_priced_one(monkeypatch):
    # a Model-headed table without Input/Output columns names no rate; the
    # priced table after it still prices
    _chat_page(monkeypatch, _INCIDENTAL_TABLE + _HTML_TABLE)
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.30 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(1.20 / 1e6)


def test_a_page_with_only_an_incidental_model_table_raises(monkeypatch):
    _chat_page(monkeypatch, _INCIDENTAL_TABLE)
    with pytest.raises(FetchError, match="Model pricing table"):
        scraper.scrape(cfg(), "kimi-k3")


def test_a_tfoot_summary_row_is_no_data(monkeypatch):
    # a summary row under <tfoot> is no model row, so a shell carrying only
    # one is still a loud shape break
    shell = (
        "<table><thead><tr><th>Model</th><th>Input Price</th><th>Output Price</th>"
        "</tr></thead><tbody /><tfoot><tr><td>Total</td><td>$1.00</td><td>$2.00</td>"
        "</tr></tfoot></table>"
    )
    _chat_page(monkeypatch, shell)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "kimi-k3")
    assert CHAT_URL in str(exc.value)
    # a tfoot beside a priced body row never stands in for it
    _chat_page(
        monkeypatch,
        _HTML_TABLE.replace(
            "</tbody>",
            "</tbody><tfoot><tr><td>Total</td><td>$9.00</td><td>$9.00</td></tr></tfoot>",
        ),
    )
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.30 / 1e6)


# --- the 2026-11-18 rendered page: the Mintlify manifest template ----------

# every kimi row of the live page's two series tables, page order: (input,
# output, cached input, 5m writes, 1h writes) USD per MTok as the page prints
# them; the K2 series carries no cache-write columns
LIVE_ROWS = {
    "kimi-k3.1-pro": (2.00, 10.00, 0.20, 2.00, 4.00),
    "kimi-k3.1-pro-highspeed": (4.00, 20.00, 0.20, 4.00, 8.00),
    "kimi-k3": (3.00, 15.00, 0.30, 3.00, 6.00),
    "kimi-k2.7-code": (0.95, 4.00, 0.19, None, None),
    "kimi-k2.7-code-highspeed": (1.90, 8.00, 0.38, None, None),
    "kimi-k2.6": (0.95, 4.00, 0.16, None, None),
}


def _manifest(source: str) -> dict[str, object]:
    return {"page": {"mdx": {"mdxSource": {"compiledSource": source}}}}


def _manifest_template(manifest: object) -> str:
    return f'<template data-mint="manifest">{json.dumps(manifest)}</template>'


def _manifest_page(manifest: object) -> str:
    """a rendered page carrying one Mintlify manifest template, the shape
    https://platform.kimi.ai/docs/pricing/chat served on 2026-11-18."""
    return f"<!doctype html><html><body>{_manifest_template(manifest)}</body></html>"


def _priced_source(input_price: float) -> str:
    """a compiled MDX source holding one priced DocTable call for kimi-k3."""
    return (
        f"_jsx(DocTable,{{columns:[{{title:`Model`}},{{title:`Input`}},{{title:`Output`}}],"
        f"rows:[[`kimi-k3`,`${input_price:.2f} / MTok`,`$15.00 / MTok`]]}})"
    )


def _serve_rendered(monkeypatch: pytest.MonkeyPatch, export_text: str, rendered_text: str) -> None:
    """serve the markdown export and an arbitrary rendered page."""
    scraper._page_text.cache_clear()

    def fake(url: str) -> str:
        if url == INDEX_URL:
            return (FIXTURES / "llms.txt").read_text()
        if url == CHAT_URL:
            return export_text
        if url == FLIGHT_URL:
            return rendered_text
        raise AssertionError(f"unexpected fetch of {url}")

    monkeypatch.setattr(scraper, "fetch_text", fake)


def test_scrape_prices_every_row_of_the_live_rendered_page(monkeypatch):
    # 2026-11-18: the export renders two empty shells and the rendered page
    # ships no self.__next_f chunk; both series tables ride the manifest
    # template's compiled MDX source
    monkeypatch.setattr(
        scraper, "fetch_text", fixture_fetch("llms", "chat-2026-11-18", "rendered-2026-11-18")
    )
    for model_id, expected in LIVE_ROWS.items():
        input_cost, output_cost, cached, write, write_1h = expected
        pricing = scraper.scrape(cfg(), model_id)
        assert pricing is not None, model_id
        assert pricing.input_cost_per_token == pytest.approx(input_cost / 1e6)
        assert pricing.output_cost_per_token == pytest.approx(output_cost / 1e6)
        assert pricing.cache_read_cost_per_token == pytest.approx(cached / 1e6)
        assert pricing.cache_write_cost_per_token == (
            None if write is None else pytest.approx(write / 1e6)
        )
        assert pricing.cache_write_1h_cost_per_token == (
            None if write_1h is None else pytest.approx(write_1h / 1e6)
        )
        assert pricing.url == FLIGHT_URL


def test_a_manifest_source_without_a_doctable_raises_the_no_pricing_table_error(monkeypatch):
    # a compiled source carrying no priced call is a dark page, never every
    # model absent
    source = "const DocTable=({columns=[],rows=[],groups=[],corner=null,className=``})=>null;"
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(_manifest(source)))
    with pytest.raises(FetchError, match="no pricing table") as exc:
        scraper.scrape(cfg(), "kimi-k3")
    assert str(exc.value).endswith(FLIGHT_URL)


def test_a_manifest_template_that_does_not_decode_raises(monkeypatch):
    # a manifest whose JSON does not decode is a shape break: the reader
    # raises naming the page instead of reading the page as no table
    _serve_rendered(
        monkeypatch, _EMPTY_SHELL, '<template data-mint="manifest">{not json</template>'
    )
    with pytest.raises(FetchError, match="does not decode") as exc:
        scraper.scrape(cfg(), "kimi-k3")
    assert FLIGHT_URL in str(exc.value)


@pytest.mark.parametrize(
    ("manifest", "anchor"),
    [
        ([], "the manifest is not an object"),
        ({"page": "x"}, "page is not an object"),
        ({"page": {}}, "no 'mdx'"),
        ({"page": {"mdx": {"mdxSource": {}}}}, "no 'compiledSource'"),
        ({"page": {"mdx": {"mdxSource": None}}}, "page.mdx.mdxSource is not an object"),
    ],
    ids=[
        "manifest-not-object",
        "page-not-object",
        "no-mdx",
        "no-compiled-source",
        "source-not-object",
    ],
)
def test_a_manifest_node_the_reader_needs_is_missing_or_wrong(monkeypatch, manifest, anchor):
    # a shape no capture shows: the raise names the node that failed instead
    # of guessing another key or another surface
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(manifest))
    with pytest.raises(FetchError, match=anchor) as exc:
        scraper.scrape(cfg(), "kimi-k3")
    assert FLIGHT_URL in str(exc.value)


def test_a_compiled_source_that_is_not_a_string_raises(monkeypatch):
    _serve_rendered(
        monkeypatch,
        _EMPTY_SHELL,
        _manifest_page({"page": {"mdx": {"mdxSource": {"compiledSource": 42}}}}),
    )
    with pytest.raises(FetchError, match="compiled MDX source") as exc:
        scraper.scrape(cfg(), "kimi-k3")
    assert FLIGHT_URL in str(exc.value)


def test_two_manifest_templates_raise(monkeypatch):
    # which of two manifests carries the tables is unknowable, so the reader
    # raises the way the index's ambiguous chat link does; either manifest
    # alone would price kimi-k3, so a reader that picks one returns a rate
    _serve_rendered(
        monkeypatch,
        _EMPTY_SHELL,
        _manifest_page(_manifest(_priced_source(9.00)))
        + _manifest_page(_manifest(_priced_source(1.00))),
    )
    with pytest.raises(FetchError, match="expected one manifest template") as exc:
        scraper.scrape(cfg(), "kimi-k3")
    assert FLIGHT_URL in str(exc.value)


def test_both_the_flight_payload_and_the_manifest_pricing_raises(monkeypatch):
    # which surface holds the page's rates is unknowable when both carry a
    # pricing table, so the shared read raises the way it does on two
    # manifests; the priced set reads through it, so it raises too
    template = _manifest_template(_manifest(_priced_source(9.00)))
    rendered = _flight_page(_K3_FLIGHT_CALL).replace("</body>", template + "</body>")
    _serve_rendered(monkeypatch, _EMPTY_SHELL, rendered)
    with pytest.raises(FetchError, match="flight payload and the manifest") as exc:
        scraper.scrape(cfg(), "kimi-k3")
    assert FLIGHT_URL in str(exc.value)
    with pytest.raises(FetchError, match="flight payload and the manifest"):
        detector.detect_priced(cfg())


def test_a_flight_payload_with_no_table_still_prices_from_the_manifest(monkeypatch):
    # a flight chunk that yields no priced table keeps the manifest fallback
    template = _manifest_template(_manifest(_priced_source(3.00)))
    rendered = _flight_page(_SHELL_FLIGHT_CALL).replace("</body>", template + "</body>")
    _serve_rendered(monkeypatch, _EMPTY_SHELL, rendered)
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.00 / 1e6)
    assert pricing.url == FLIGHT_URL


def test_a_manifest_with_no_priced_table_leaves_the_flight_payload_pricing(monkeypatch):
    # only a manifest that prices too makes the surfaces ambiguous; one that
    # yields no priced table leaves the flight rates in place
    source = "const DocTable=({columns=[],rows=[],groups=[],corner=null,className=``})=>null;"
    template = _manifest_template(_manifest(source))
    rendered = _flight_page(_K3_FLIGHT_CALL).replace("</body>", template + "</body>")
    _serve_rendered(monkeypatch, _EMPTY_SHELL, rendered)
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.00 / 1e6)


def test_a_broken_manifest_beside_a_priced_flight_payload_raises(monkeypatch):
    # the manifest is read even when the flight payload prices the page, so
    # one that does not decode stays a shape break instead of losing silently
    rendered = _flight_page(_K3_FLIGHT_CALL).replace(
        "</body>", '<template data-mint="manifest">{not json</template></body>'
    )
    _serve_rendered(monkeypatch, _EMPTY_SHELL, rendered)
    with pytest.raises(FetchError, match="does not decode"):
        scraper.scrape(cfg(), "kimi-k3")


def test_the_2026_11_18_captures_carry_the_shapes_this_fix_reads():
    # the fixtures are the live bytes: the export renders empty table shells
    # and the rendered page carries one manifest template holding the series
    # tables' DocTable calls, with no flight chunk
    export = (FIXTURES / "chat-2026-11-18.md").read_text()
    rendered = (FIXTURES / "chat-rendered-2026-11-18.html").read_text()
    assert "<thead>\n    <tr />\n  </thead>" in export
    assert "<tbody />" in export
    assert "$" not in export
    assert "self.__next_f" not in rendered
    assert rendered.count('<template data-mint="manifest">') == 1
    assert "_jsx(DocTable,{" in rendered
    # positive controls: the old export carries the dollar amounts and the
    # flight fixture carries the chunk spelling the live page dropped
    assert "$" in (FIXTURES / "chat.md").read_text()
    assert "self.__next_f" in _flight_page("<payload/>")


# --- the chat page's priced set: what the absence counters key on ----------

# every id the chat page priced on 2026-11-19, in page order. measured that
# day: the export and the manifest's compiled source were byte-identical to
# the 2026-11-18 captures, so those two fixtures stand for today's page;
# models.md is the page that moved (the three K2 ids into its deprecated table)
LIVE_PRICED_IDS = [
    "kimi-k3.1-pro",
    "kimi-k3.1-pro-highspeed",
    "kimi-k3",
    "kimi-k2.7-code",
    "kimi-k2.7-code-highspeed",
    "kimi-k2.6",
]


def test_detect_priced_lists_every_id_the_live_chat_page_prices(monkeypatch):
    # the absence counters key on this set: a stored non-removed id it drops
    # is planned for removal on its second absent observation
    monkeypatch.setattr(
        scraper, "fetch_text", fixture_fetch("llms", "chat-2026-11-18", "rendered-2026-11-18")
    )
    priced = detector.detect_priced(cfg())
    assert priced == LIVE_PRICED_IDS
    assert set(STORED_LIVE_IDS) <= set(priced)


def test_detect_priced_reads_the_markdown_export_when_it_carries_the_table(monkeypatch):
    # the export-first order holds for the priced set too: a restored export
    # costs no fetch of the rendered page
    monkeypatch.setattr(scraper, "fetch_text", fixture_fetch("llms", "chat"))
    assert detector.detect_priced(cfg()) == [
        "kimi-k3",
        "kimi-k2.7-code",
        "kimi-k2.7-code-highspeed",
        "kimi-k2.6",
    ]


def test_detect_priced_skips_a_row_too_short_to_carry_a_model(monkeypatch):
    # a row array shorter than the model column is no model row: the reader
    # skips it the way `scrape` does, never raising IndexError
    call = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`}],"
        "rows:[[],[`kimi-k3`,`$3.00 / MTok`,`$15.00 / MTok`]]})"
    )
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(_manifest(call)))
    assert detector.detect_priced(cfg()) == ["kimi-k3"]


def test_a_row_missing_its_last_column_prices_nothing(monkeypatch):
    # the row must carry every column the table is read through, so a row
    # whose length equals the highest column index lacks its last column and
    # prices nothing
    call = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`},"
        "{title:`Context Window`}],"
        "rows:[[`kimi-k3`,`$3.00 / MTok`,`$15.00 / MTok`]]})"
    )
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(_manifest(call)))
    with pytest.raises(FetchError, match="no priced model rows"):
        detector.detect_priced(cfg())


def test_detect_priced_keeps_only_model_ids_once(monkeypatch):
    # a first cell that is no model id (a display heading) and an id priced in
    # two tables never enter the priced set twice
    call = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`}],"
        "rows:[[`All models`,`$3.00 / MTok`,`$15.00 / MTok`],"
        "[`kimi-k3`,`$3.00 / MTok`,`$15.00 / MTok`],"
        "[`kimi-k3`,`$3.00 / MTok`,`$15.00 / MTok`]]})"
    )
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(_manifest(call + call)))
    assert detector.detect_priced(cfg()) == ["kimi-k3"]


def test_detect_priced_reads_a_repeated_model_row_like_scrape(monkeypatch):
    # `scrape` settles a repeated model cell on its first row, so a first row
    # with no rate leaves the id unpriced even when a later copy is priced
    call = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`}],"
        "rows:[[`kimi-k3`,`tbd`,`tbd`],[`kimi-k3`,`$3.00 / MTok`,`$15.00 / MTok`],"
        "[`kimi-k4`,`$1.00 / MTok`,`$2.00 / MTok`]]})"
    )
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(_manifest(call)))
    assert detector.detect_priced(cfg()) == ["kimi-k4"]


def test_priced_model_ids_lists_a_repeated_cell_once(monkeypatch):
    # the public priced list holds one entry per distinct model cell text,
    # page order; a second row for the same cell appends nothing, in its own
    # table or a later one
    call = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`}],"
        "rows:[[`kimi-k3`,`$3.00 / MTok`,`$15.00 / MTok`],"
        "[`kimi-k3`,`$3.00 / MTok`,`$15.00 / MTok`]]})"
    )
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(_manifest(call + call)))
    ids, _url = scraper.priced_model_ids(cfg())
    assert ids == ["kimi-k3"]


def test_priced_model_ids_reads_a_later_malformed_copy_like_scrape(monkeypatch):
    # `scrape` stops at the first table that prices an id, so a later table's
    # unreadable copy of it reaches neither read
    first = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`}],"
        "rows:[[`kimi-k3`,`$3.00 / MTok`,`$15.00 / MTok`]]})"
    )
    later = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`}],"
        "rows:[[`kimi-k3`,`$3, 00 / MTok`,`$1.00 / MTok`]]})"
    )
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(_manifest(first + later)))
    assert scraper.scrape(cfg(), "kimi-k3") is not None
    ids, _url = scraper.priced_model_ids(cfg())
    assert ids == ["kimi-k3"]
    assert detector.detect_priced(cfg()) == ["kimi-k3"]


def test_priced_model_ids_lists_a_later_priced_table_like_scrape(monkeypatch):
    # a cell is listed when any table prices it, the way `scrape` searches
    # every table: an empty row in an earlier table lists nothing by itself,
    # and a later table's priced row puts the id in the set
    first = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`}],"
        "rows:[[`kimi-k15`,``,``]]})"
    )
    later = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`}],"
        "rows:[[`kimi-k15`,`$3.00 / MTok`,`$15.00 / MTok`]]})"
    )
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(_manifest(first + later)))
    assert detector.detect_priced(cfg()) == ["kimi-k15"]
    assert scraper.scrape(cfg(), "kimi-k15") is not None


def test_detect_priced_reads_a_case_variant_copy_like_scrape(monkeypatch):
    # `scrape` matches a model cell case-insensitively, so the first copy
    # settles the id: a priced later copy under another case prices nothing
    call = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`}],"
        "rows:[[`kimi-k3`,`tbd`,`tbd`],[`KIMI-K3`,`$3.00 / MTok`,`$15.00 / MTok`]]})"
    )
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(_manifest(call)))
    with pytest.raises(FetchError, match="no priced model rows"):
        detector.detect_priced(cfg())


def test_detect_priced_lists_a_case_variant_row(monkeypatch):
    # one row spelling its model cell in another case still lists the id and
    # prices it: the cell and the requested id both fold case
    call = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`}],"
        "rows:[[`KIMI-K3`,`$3.00 / MTok`,`$15.00 / MTok`]]})"
    )
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(_manifest(call)))
    assert detector.detect_priced(cfg()) == ["kimi-k3"]
    assert scraper.scrape(cfg(), "kimi-k3") is not None


def test_detect_still_omits_the_deprecated_table(monkeypatch):
    # the 2026-11-19 models page moved the three K2 ids into its Deprecated
    # Models table; candidates keep coming from the same read as before
    monkeypatch.setattr(detector, "fetch_text", fixture_fetch("models-2026-11-19"))
    assert detector.detect(cfg()) == ["kimi-k3.1-pro", "kimi-k3.1-pro-highspeed", "kimi-k3"]


def rendered_without_row(rendered: str, model_id: str) -> str:
    """a copy of the rendered page with the pricing row of `model_id` removed."""
    pattern = re.compile(r"\[`" + re.escape(model_id) + r"`[^\]]*\]")
    page, removed = pattern.subn("", rendered)
    assert removed == 1
    return page


def test_detect_priced_omits_an_id_the_chat_page_stops_pricing(monkeypatch):
    # near miss: an id whose row leaves the page is no longer priced, so the
    # absence counters can still count it absent
    rendered = rendered_without_row(
        (FIXTURES / "chat-rendered-2026-11-18.html").read_text(encoding="utf-8"), "kimi-k2.6"
    )

    def fake(url: str) -> str:
        if url == INDEX_URL:
            return (FIXTURES / "llms.txt").read_text(encoding="utf-8")
        if url == CHAT_URL:
            return (FIXTURES / "chat-2026-11-18.md").read_text(encoding="utf-8")
        if url == FLIGHT_URL:
            return rendered
        raise AssertionError(f"unexpected fetch of {url}")

    monkeypatch.setattr(scraper, "fetch_text", fake)
    assert detector.detect_priced(cfg()) == [
        model_id for model_id in LIVE_PRICED_IDS if model_id != "kimi-k2.6"
    ]


def test_detect_priced_raises_when_no_price_table_is_extracted(monkeypatch):
    # a manifest whose compiled source holds no priced call: an empty set
    # would mark every stored id absent, so the reader's no-pricing-table
    # break stands
    source = "const DocTable=({columns=[],rows=[],groups=[],corner=null,className=``})=>null;"
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(_manifest(source)))
    with pytest.raises(FetchError, match="no pricing table"):
        detector.detect_priced(cfg())


def test_detect_priced_raises_when_no_row_carries_a_rate(monkeypatch):
    # a priced-columns table whose input and output cells carry no amount is
    # no priced set either
    call = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`}],"
        "rows:[[`kimi-k3`,`tbd`,`tbd`]]})"
    )
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(_manifest(call)))
    with pytest.raises(FetchError, match="no priced model rows"):
        detector.detect_priced(cfg())


def test_detect_priced_lists_a_readable_row_beside_an_unreadable_heading(monkeypatch):
    # a heading row's unreadable amount is no id and never reaches the priced
    # set; the readable row beside it still keys absence
    call = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`}],"
        "rows:[[`All models (batch)`,`$3, 00 / MTok`,`$15.00 / MTok`],"
        "[`kimi-k3`,`$3.00 / MTok`,`$15.00 / MTok`]]})"
    )
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(_manifest(call)))
    assert detector.detect_priced(cfg()) == ["kimi-k3"]


def test_detect_priced_lists_an_unreadable_row_while_its_scrape_raises(monkeypatch):
    # an unreadable amount still lists the id, so the absence pass never
    # counts it absent; the id's own scrape raises the unreadable-rate error
    # naming it
    call = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`}],"
        "rows:[[`kimi-k9`,`$3, 00 / MTok`,`$15.00 / MTok`]]})"
    )
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(_manifest(call)))
    assert detector.detect_priced(cfg()) == ["kimi-k9"]
    with pytest.raises(FetchError, match="kimi-k9"):
        scraper.scrape(cfg(), "kimi-k9")


def test_detect_priced_lists_an_unreadable_output_amount_too(monkeypatch):
    # the output cell's unreadable amount lists the id the same way, and its
    # scrape still raises
    call = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`}],"
        "rows:[[`kimi-k9`,`$3.00 / MTok`,`$15, 00 / MTok`]]})"
    )
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(_manifest(call)))
    assert detector.detect_priced(cfg()) == ["kimi-k9"]
    with pytest.raises(FetchError, match="kimi-k9"):
        scraper.scrape(cfg(), "kimi-k9")


def test_detect_priced_lists_a_mixed_unreadable_and_empty_price_row(monkeypatch):
    # an unreadable amount lists the id whatever the other price cell
    # carries: an unreadable input beside an empty output, and its mirror,
    # both reach the priced set, and each id's own scrape raises naming it
    call = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`}],"
        "rows:[[`kimi-k9`,`$3, 00 / MTok`,``],[`kimi-k10`,``,`$15, 00 / MTok`],"
        "[`kimi-k3`,`$3.00 / MTok`,`$15.00 / MTok`]]})"
    )
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(_manifest(call)))
    assert detector.detect_priced(cfg()) == ["kimi-k9", "kimi-k10", "kimi-k3"]
    with pytest.raises(FetchError, match="kimi-k9"):
        scraper.scrape(cfg(), "kimi-k9")
    with pytest.raises(FetchError, match="kimi-k10"):
        scraper.scrape(cfg(), "kimi-k10")


def test_a_row_with_one_empty_price_cell_is_not_listed(monkeypatch):
    # a readable amount beside an empty price cell is neither an unreadable
    # amount nor a second amount, so the row names no rate the scraper reads
    call = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`}],"
        "rows:[[`kimi-k9`,`$3.00 / MTok`,``],[`kimi-k10`,``,`$15.00 / MTok`],"
        "[`kimi-k3`,`$3.00 / MTok`,`$15.00 / MTok`]]})"
    )
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(_manifest(call)))
    assert detector.detect_priced(cfg()) == ["kimi-k3"]


def test_a_row_with_no_amount_is_not_listed(monkeypatch):
    # a heading row with empty price cells, and an id-shaped row with none,
    # list no price: only the priced row reaches the priced set
    call = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`}],"
        "rows:[[`All models (batch)`,``,``],[`kimi-k9`,``,``],"
        "[`kimi-k3`,`$3.00 / MTok`,`$15.00 / MTok`]]})"
    )
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(_manifest(call)))
    assert detector.detect_priced(cfg()) == ["kimi-k3"]


def test_a_malformed_cache_cell_beside_empty_price_cells_is_not_listed(monkeypatch):
    # only the input and output cells decide the listing: an unreadable
    # cached-input cell beside two empty price cells names no rate, and the
    # scrape returns none before reading the cache cell
    call = (
        "_jsx(DocTable,{columns:[{title:`Model`},{title:`Input`},{title:`Output`},"
        "{title:`Cached Input`}],"
        "rows:[[`kimi-k14`,``,``,`$9, 00 / MTok`]]})"
    )
    _serve_rendered(monkeypatch, _EMPTY_SHELL, _manifest_page(_manifest(call)))
    with pytest.raises(FetchError, match="no priced model rows"):
        detector.detect_priced(cfg())
    assert scraper.scrape(cfg(), "kimi-k14") is None

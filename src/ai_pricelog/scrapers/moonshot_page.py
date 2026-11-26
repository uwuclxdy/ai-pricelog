"""scrape per-token pricing for kimi models from the merged pricing page.

page discovery: the scraper url is the docs index (llms.txt). the
model-inference pricing page is the markdown link whose url path sits under
/pricing/ and whose last path segment (minus a .md suffix) is exactly "chat"
(the former per-family pages were merged into that one table; batch, tools
and limits are pricing pages but not model-inference ones). the index is
fetched once per run (lru-cached); no such link, or more than one, is a
FetchError naming the index url, loud enough for the weekly smoke to catch.

the resolved page carries one pricing table per model series (a K3 series
table and a K2 series table since 2026-09-19), written either as a
<DocTable columns={...} rows={...} /> block or, since 2026-10, as a plain
html <table>. a markdown code fence (CommonMark: up to three leading
spaces, a run of three or more backticks or tildes, a backtick fence's
info string holding no backtick, closed by up to three leading spaces
and a run of the same character at least as long followed only by spaces
or tabs) is stripped before the tables are read, so a docs example
contributes no table. DocTable columns are objects with a
`title` key; rows are arrays of strings, price cells written as JSX
fragments (<>{"$"}0.30</>) and the context window as "1,048,576 tokens". an
html table's first own row gives the column titles through web.header_grid,
so a spanned header keeps every later title aligned with its cell, and its
remaining rows give the data, a <tfoot> summary row excepted (a row whose
nearest row group is a tfoot); a table with no data row carrying printable
text is no pricing table, on the export's DocTable blocks as on the rendered
page, so the empty <thead><tr /></thead><tbody /> shell and a DocTable
carrying no rows fall through instead of reading every model absent. since
2026-10-23 the markdown export renders both series tables as that empty
shell, while the rendered page (the resolved url without its .md suffix)
carries them as _jsx(DocTable,{...}) calls: when the export carries no
priced table, the scraper reads them out of the page's Next.js flight
payload (each self.__next_f.push([1,"..."]) chunk's literal decoded and the
chunks concatenated), and when that yields no priced table, out of its
Mintlify manifest's compiled MDX source (the JSON under a
<template data-mint="manifest"> tag, key page.mdx.mdxSource.compiledSource);
the live page has shipped no flight chunk since 2026-11-05 (measured
2026-11-18). a manifest template that does not decode, more than one such
template, or one without a string compiled source raises rather than guess,
and so does a page whose flight payload and manifest both carry a priced
table. both streams feed one reader, which scans every
_jsx(DocTable,{ call, balanced-brace to its closing }. the call head, never
the bare name, is matched, because the DocTable module source in the same
stream spells the name with empty columns/rows defaults and would otherwise
read as a table and hide a dark page. a call carrying neither columns nor
rows is a prop-less shell and contributes no table; a call whose props do
not parse raises. the rendered titles (Model, Input, Output, Cached Input,
5m writes, 1h writes) fold onto the markdown vocabulary before the shared
read, and a cell or title wrapped in _jsx/_jsxs carries its text in a
backtick children string. the fallback fires when the export carries no
table with pricing columns. a non-pricing table the export does carry falls
back the same way; when the rendered surfaces price nothing either, an
export that carried such a table keeps the no Model pricing table raise. a
pricing candidate carries a
Model column plus an input price column (Input Price (Cache Miss), or the
K3 series table's plain "Input Price") and an Output Price column; an
incidental Model-headed table without them names no rate and is skipped,
and an export whose tables are all incidental raises `no Model pricing
table` when the rendered page prices nothing too. the Model column is
matched exactly against the model id and the model is searched across
every candidate table; Input Price (Cache
Miss) -> input_cost, Input Price (Cache Hit) or Cached Input Price (the K3
spelling) -> cache_read_cost_per_token when the column exists, Output Price
-> output_cost, Cache Write Price (TTL 5min) -> cache_write_cost_per_token,
Cache Write Price (TTL 1h) -> cache_write_1h_cost_per_token, USD per 1M ->
/1e6, Context Window digits -> max_tokens_in.

the Pricing url names the page the rate was read from (the resolved chat
page, or the rendered page when the rate came from its flight payload or
manifest; never the index); build_row stamps it as the row's url.

None = no row for the model. FetchError = the fetch failed, the index
resolves no (or an ambiguous) chat page, the page's DocTable props, html
tables, flight payload or manifest do not parse, the flight payload and the
manifest both carry a pricing table, no pricing table (or no Model pricing
table) is on the page, a price cell carries an unreadable amount, or a
context cell carries an oversized digit run. a page whose export and
rendered page both carry no table raises naming both urls.
"""

from __future__ import annotations

import ast
import functools
import json
import math
import re
from typing import NamedTuple
from urllib.parse import urljoin, urlsplit

from ai_pricelog.config import ProviderCfg
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import (
    MAX_COUNT_DIGITS,
    FetchError,
    amount_scan,
    fetch_text,
    header_grid,
    markdown_lines,
    own_cells,
    own_table_rows,
    parse_html,
    unreadable_rate_error,
)

_LINK_PATTERN = re.compile(r"^\s*-\s*\[([^\]]+)\]\(([^)]+)\)")
_FRAGMENT_PATTERN = re.compile(r'<>\{"([^"]*)"\}([^<]*)</>')
_BARE_KEY_PATTERN = re.compile(r'(?<![A-Za-z0-9_"])([A-Za-z_][A-Za-z0-9_]*)(\s*):')
_CONTEXT_PATTERN = re.compile(r"\d[\d,]*")
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}(?!.*`)|~{3,})")
_FLIGHT_PUSH_RE = re.compile(r'<script>self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)</script>')
_MANIFEST_RE = re.compile(r'<template data-mint="manifest">(.*?)</template>', re.S)
_IDENTIFIER_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_JS_SPACE = " \t\r\n"
_RENDERED_TITLES = {
    "Input": "Input Price",
    "Output": "Output Price",
    "Cached Input": "Cached Input Price",
    "5m writes": "Cache Write Price (TTL 5min)",
    "1h writes": "Cache Write Price (TTL 1h)",
}


@functools.lru_cache(maxsize=1)
def _load_index(index_url: str) -> str:
    """the model-inference pricing page url resolved from the llms.txt index."""
    pages: list[str] = []
    for line in fetch_text(index_url).splitlines():
        match = _LINK_PATTERN.match(line)
        if match is None:
            continue
        href = match.group(2)
        path = urlsplit(href).path
        if "/pricing/" not in path:
            continue
        if path.rsplit("/", 1)[-1].removesuffix(".md") != "chat":
            continue
        url = href if href.startswith(("http://", "https://")) else urljoin(index_url, href)
        pages.append(url)
    if len(pages) != 1:
        raise FetchError(
            f"expected one model-inference pricing page in the index {index_url}, "
            f"found {len(pages)}"
        )
    return pages[0]


def _strip_code_fences(text: str) -> str:
    """the page with every CommonMark code-fenced block blanked, so a table
    or DocTable inside one reads as prose, never a pricing table.

    a fence opens on up to three leading spaces and a run of at least three
    backticks or tildes (a backtick fence's info string holds no backtick),
    and closes on up to three leading spaces and a run of the same
    character at least as long followed only by spaces or tabs; an
    unclosed fence runs to the end.
    """
    kept: list[str] = []
    fence = ""
    for line in markdown_lines(text):
        if fence:
            closes = re.fullmatch(rf" {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*", line)
            if closes is not None:
                fence = ""
            kept.append("")
            continue
        opening = _FENCE_OPEN_RE.match(line)
        if opening is not None:
            fence = opening.group(1)
            kept.append("")
            continue
        kept.append(line)
    return "\n".join(kept)


@functools.lru_cache(maxsize=4)
def _page_text(url: str) -> str:
    """fetch a page once per process: the rendered page is ~300 KB and the
    pipeline scrapes one model id at a time, so the fallback would otherwise
    refetch it per model."""
    return fetch_text(url)


def pricing_tables(cfg: ProviderCfg) -> tuple[list[tuple[list[str], list[list[str]]]], str]:
    """the model-inference page's pricing tables and the url they came from.

    the markdown export's tables when it carries one with pricing columns,
    else the rendered page's flight payload, else its manifest's compiled MDX
    source; a page whose flight payload and manifest both carry a pricing
    table raises instead of reading either one silently. when nothing prices,
    an export that carried an incidental table keeps the
    no-Model-pricing-table break, and a page carrying no pricing table
    anywhere raises the no-pricing-table break naming both urls."""
    page_url = _load_index(cfg.scraper_url)
    docs = _doc_tables(_strip_code_fences(_page_text(page_url)))
    if any(_pricing_columns(titles) is not None for titles, _ in docs):
        return docs, page_url
    rendered_url = page_url.removesuffix(".md")
    rendered_page = _page_text(rendered_url)
    flight_docs = _jsx_docs(_flight_stream(rendered_page, rendered_url), rendered_url)
    source = _manifest_source(rendered_page, rendered_url)
    manifest_docs = _jsx_docs(source, rendered_url) if source is not None else []
    if flight_docs and manifest_docs:
        raise FetchError(
            f"pricing tables on both the flight payload and the manifest of {rendered_url}"
        )
    rendered_docs = flight_docs or manifest_docs
    if rendered_docs:
        return rendered_docs, rendered_url
    if docs:
        raise FetchError(f"no Model pricing table on {page_url} or {rendered_url}")
    raise FetchError(
        f"no pricing table (DocTable, html, flight payload or manifest) on"
        f" {page_url} or {rendered_url}"
    )


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    docs, page_url = pricing_tables(cfg)
    return _first_pricing(docs, model_id, page_url)


def _first_pricing(
    docs: list[tuple[list[str], list[list[str]]]], model_id: str, page_url: str
) -> Pricing | None:
    for doc in docs:
        pricing = _pricing(doc, model_id, page_url)
        if pricing is not None:
            return pricing
    return None


def priced_model_ids(cfg: ProviderCfg) -> tuple[list[str], str]:
    """the distinct model cell texts of the page's price rows, page order,
    and the url the rows came from.

    one entry per distinct model cell text: a repeated cell appears once. a
    cell counts as listed when a table's row for it carries an unreadable
    amount in either price cell, whatever the other cell carries, and
    otherwise when both price cells carry an amount; within a table the
    first row long enough to carry every column settles the cell, as in
    `scrape`, and a row too short to carry them is skipped. an unreadable
    amount counts as listed and raises only where that id's own `scrape`
    reads it, while a row carrying no amount at all is unlisted. the chat
    page keeps pricing models the docs index lists as deprecated (the K2
    series, measured 2026-11-19), so this set, not the candidate list, says
    which stored ids stay live.
    """
    docs, page_url = pricing_tables(cfg)
    tables: list[tuple[list[list[str]], _PricingColumns]] = []
    for titles, rows in docs:
        columns = _pricing_columns(titles)
        if columns is not None:
            tables.append((rows, columns))
    cells: dict[str, None] = {}
    for rows, columns in tables:
        for row in rows:
            if len(row) > columns.model:
                cells[str(row[columns.model]).strip()] = None
    ids = [
        cell for cell in cells if any(_priced_row(rows, columns, cell) for rows, columns in tables)
    ]
    return ids, page_url


def _priced_row(rows: list[list[str]], columns: _PricingColumns, model_id: str) -> bool:
    """whether the table lists `model_id` at a price: its row for the id is
    listed when either price cell carries an unreadable amount, whatever the
    other cell carries, and otherwise when both price cells carry an amount.

    a row carrying no amount at all names no price, so it is unlisted; an
    amount the grammar cannot read still counts as listed, and raising on it
    is left to that id's own `scrape`."""
    row = _model_row(rows, columns, model_id)
    if row is None:
        return False
    input_amounts, input_malformed = amount_scan(str(row[columns.input]), before="$")
    output_amounts, output_malformed = amount_scan(str(row[columns.output]), before="$")
    if input_malformed or output_malformed:
        return True
    return bool(input_amounts) and bool(output_amounts)


def _doc_tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    """every pricing table on the page as (column titles, rows) pairs: each
    <DocTable> block's columns/rows props plus each plain html <table>; []
    when the page carries neither. each block's prop scan is bounded at the
    next <DocTable>, so a block missing a prop raises instead of borrowing a
    later block's.

    a block whose rows carry no printable text contributes nothing, the way
    `_html_docs` and `_jsx_docs` drop theirs: the export's priced-columns
    shell falls back to the rendered page instead of pricing every model
    absent."""
    docs: list[tuple[list[str], list[list[str]]]] = []
    start = 0
    while True:
        position = text.find("<DocTable", start)
        if position == -1:
            break
        next_position = text.find("<DocTable", position + 1)
        block = text[position : next_position if next_position != -1 else len(text)]
        start = position + 1
        columns_text = _jsx_prop(block, "columns")
        rows_text = _jsx_prop(block, "rows")
        if columns_text is None or rows_text is None:
            raise FetchError("DocTable block is missing columns or rows props")
        try:
            columns_raw = ast.literal_eval(_quote_keys(columns_text))
            rows = ast.literal_eval(_plain_rows(rows_text))
        except (SyntaxError, ValueError) as exc:
            raise FetchError(f"DocTable props do not parse: {exc}") from exc
        titles = [
            column["title"] if isinstance(column, dict) else str(column) for column in columns_raw
        ]
        if not all(isinstance(row, list) for row in rows):
            raise FetchError("DocTable rows are not arrays")
        if not any(_carries_data([str(cell) for cell in row]) for row in rows):
            continue
        docs.append((titles, rows))
    docs.extend(_html_docs(text))
    return docs


def _html_docs(text: str) -> list[tuple[list[str], list[list[str]]]]:
    """the page's plain html tables as (header titles, data rows) pairs.

    the first own row gives the titles through web.header_grid, so a spanned
    header keeps every later title aligned with its cell; the rest give the
    data, a <tfoot> row excepted (a row whose nearest row group is a tfoot
    is a summary, never a model row). a table whose rows carry no printable
    text contributes nothing, so the empty <thead><tr /></thead><tbody />
    shell the docs platform served on 2026-10-23 stays a page with no
    pricing table instead of a pricing table with zero models."""
    soup = parse_html(text)
    docs: list[tuple[list[str], list[list[str]]]] = []
    for table in soup.find_all("table"):
        if table.find_parent("table") is not None:
            continue
        rows = list(own_table_rows(table))
        if not rows:
            continue
        titles = header_grid(rows[0])
        data: list[list[str]] = []
        for row in rows[1:]:
            group = row.find_parent(["thead", "tbody", "tfoot", "table"])
            if group is not None and group.name == "tfoot":
                continue
            data.append([cell.get_text(" ", strip=True) for cell in own_cells(row)])
        if not any(_carries_data(row) for row in data):
            continue
        docs.append((titles, data))
    return docs


def _carries_data(row: list[str]) -> bool:
    """whether a row holds a printable character; a placeholder row of
    zero-width cells is a shell, not data."""
    return any(char.isprintable() for cell in row for char in cell)


class _JsxElement(NamedTuple):
    """a component call in a rendered page's JSX stream."""

    name: str
    props: dict[str, object]


def _flight_stream(page: str, page_url: str) -> str:
    """the rendered page's flight payload as one stream: each
    self.__next_f.push([1, "<json string>"]) chunk's literal decoded and the
    chunks concatenated, so no json escape survives into the scan. a literal
    that does not decode raises, naming the page and the literal's first 80
    characters."""
    chunks: list[str] = []
    for match in _FLIGHT_PUSH_RE.finditer(page):
        try:
            chunks.append(json.loads(match.group(1)))
        except json.JSONDecodeError as exc:
            raise FetchError(
                f"flight payload on {page_url} does not decode: {match.group(1)[:80]!r}: {exc}"
            ) from exc
    return "".join(chunks)


def _manifest_source(page: str, page_url: str) -> str | None:
    """the rendered page's compiled MDX source, where the DocTable calls ride
    since the 2026-11-05 restructure: the JSON under the page's one
    <template data-mint="manifest"> tag, key page.mdx.mdxSource.compiledSource.
    None when the page carries no such template (the pre-2026-11 shape).

    the manifest is the page's own data, so a template that does not decode,
    more than one template, or a manifest without a string compiled source
    raises instead of reading as a page without tables."""
    templates = _MANIFEST_RE.findall(page)
    if not templates:
        return None
    if len(templates) > 1:
        raise FetchError(f"expected one manifest template on {page_url}, found {len(templates)}")
    try:
        manifest = json.loads(templates[0])
    except json.JSONDecodeError as exc:
        raise FetchError(
            f"manifest template on {page_url} does not decode: {templates[0][:80]!r}: {exc}"
        ) from exc
    node: object = manifest
    path = ""
    for key in ("page", "mdx", "mdxSource", "compiledSource"):
        if not isinstance(node, dict):
            raise FetchError(
                f"manifest on {page_url} carries no compiled MDX source:"
                f" {path or 'the manifest'} is not an object"
            )
        if key not in node:
            raise FetchError(f"manifest on {page_url} carries no compiled MDX source: no {key!r}")
        node = node[key]
        path = f"{path}.{key}" if path else key
    if not isinstance(node, str):
        raise FetchError(
            f"manifest on {page_url} carries no compiled MDX source: {str(node)[:120]!r}"
        )
    return node


def _doc_table_calls(stream: str) -> list[int]:
    """every `_jsx(DocTable,{` call head's position, skipping string literals
    so a documentation sample inside one contributes no table. a quote opens
    a string at any depth and closes on the next same quote, an escaped
    character staying inside it."""
    positions: list[int] = []
    index = 0
    while index < len(stream):
        char = stream[index]
        if char in ('"', "'", "`"):
            index += 1
            while index < len(stream):
                if stream[index] == "\\":
                    index += 2
                    continue
                if stream[index] == char:
                    index += 1
                    break
                index += 1
            continue
        if stream.startswith("_jsx(DocTable,{", index):
            positions.append(index)
        index += 1
    return positions


def _jsx_docs(stream: str, page_url: str) -> list[tuple[list[str], list[list[str]]]]:
    """every priced DocTable call in a rendered page's JSX stream (its flight
    payload, or its manifest's compiled MDX source) as (column titles, rows)
    pairs; [] when the stream carries no priced one.

    the scan keys on the `_jsx(DocTable,{` call head, never the bare name:
    the component's module source in the same stream spells the name with
    empty columns/rows defaults, and reading it as a table would turn a dark
    page into every model absent; the head is matched outside string
    literals, so a docs sample inside one is page text, not a table. a call
    carrying neither columns nor rows is a prop-less shell and contributes no
    table; a table naming no rate is skipped before its cells are read, so an
    incidental one cannot blind the priced calls; a priced table whose rows
    carry no printable text is the shell the platform serves and contributes
    nothing, never every model absent. a call whose props do not parse
    raises."""
    docs: list[tuple[list[str], list[list[str]]]] = []
    for position in _doc_table_calls(stream):
        fragment = stream[position : position + 80]
        try:
            props, _ = _jsx_object(stream, position + len("_jsx(DocTable,"))
            columns = props.get("columns")
            rows = props.get("rows")
            if columns is None and rows is None:
                continue
            if not isinstance(columns, list) or not isinstance(rows, list):
                raise ValueError("missing columns or rows props")
            titles = _jsx_titles(columns)
            if _pricing_columns(titles) is None:
                continue
            data = _jsx_rows(rows)
            if not any(_carries_data(row) for row in data):
                continue
            docs.append((titles, data))
        except (RecursionError, ValueError) as exc:
            raise FetchError(
                f"DocTable call on {page_url} does not parse: {fragment!r}: {exc}"
            ) from exc
    return docs


def _jsx_titles(columns: list[object]) -> list[str]:
    """the rendered column titles folded onto the markdown table's
    vocabulary, so the shared pricing read sees one spelling per column."""
    titles: list[str] = []
    for column in columns:
        if not isinstance(column, dict):
            raise ValueError("a DocTable column is not an object")
        title = _jsx_text(column.get("title"))
        titles.append(_RENDERED_TITLES.get(title, title))
    return titles


def _jsx_rows(rows: list[object]) -> list[list[str]]:
    converted: list[list[str]] = []
    for row in rows:
        if not isinstance(row, list):
            raise ValueError("a DocTable row is not an array")
        converted.append([_jsx_text(cell) for cell in row])
    return converted


def _jsx_text(value: object) -> str:
    """a rendered cell's or column title's text: a plain string, or the
    children string of the _jsx/_jsxs call the page wraps it in."""
    if isinstance(value, str):
        return value
    if isinstance(value, _JsxElement):
        children = value.props.get("children")
        if isinstance(children, str):
            return children
        raise ValueError(f"{value.name} carries no string children")
    raise ValueError(f"unexpected cell value {value!r}")


def _jsx_value(text: str, index: int) -> tuple[object, int]:
    """one JS literal value at `index` and the index past it: an object,
    array, string, number, true/false/null, or an _jsx/_jsxs call. a
    template interpolation raises, never guesses."""
    index = _jsx_skip_space(text, index)
    if index >= len(text):
        raise ValueError("props end early")
    char = text[index]
    if char == "{":
        return _jsx_object(text, index)
    if char == "[":
        return _jsx_array(text, index)
    if char in ('"', "'", "`"):
        return _jsx_string(text, index)
    number = _NUMBER_RE.match(text, index)
    if number is not None:
        token = number.group(0)
        decimal = any(mark in token for mark in ".eE")
        return (float(token) if decimal else int(token)), number.end()
    identifier = _IDENTIFIER_RE.match(text, index)
    if identifier is None:
        raise ValueError(f"unexpected character {char!r}")
    name = identifier.group(0)
    if name == "true":
        return True, identifier.end()
    if name == "false":
        return False, identifier.end()
    if name == "null":
        return None, identifier.end()
    call = _jsx_skip_space(text, identifier.end())
    if call < len(text) and text[call] == "(":
        return _jsx_call(text, index)
    raise ValueError(f"unexpected identifier {name!r}")


def _jsx_call(text: str, index: int) -> tuple[_JsxElement, int]:
    """one `_jsx(Element,{props})` call at `index` and the index past its
    closing paren: the first argument names the element, the second is its
    props object."""
    callee = _IDENTIFIER_RE.match(text, index)
    if callee is None:
        raise ValueError("call has no callee")
    index = _jsx_skip_space(text, callee.end())
    if index >= len(text) or text[index] != "(":
        raise ValueError(f"{callee.group(0)} is not called")
    index = _jsx_skip_space(text, index + 1)
    element = _IDENTIFIER_RE.match(text, index)
    if element is None:
        raise ValueError(f"call of {callee.group(0)} has no element name")
    name = element.group(0)
    index = _jsx_skip_space(text, element.end())
    if index >= len(text) or text[index] != ",":
        raise ValueError(f"call of {name} carries no props")
    props, index = _jsx_value(text, index + 1)
    if not isinstance(props, dict):
        raise ValueError(f"call of {name} props are not an object")
    index = _jsx_skip_space(text, index)
    if index >= len(text) or text[index] != ")":
        raise ValueError(f"call of {name} carries arguments after its props")
    return _JsxElement(name, props), index + 1


def _jsx_object(text: str, index: int) -> tuple[dict[str, object], int]:
    """one `{key: value, ...}` object literal at `index` and the index past
    its closing brace; a key is a bare identifier or a quoted string."""
    props: dict[str, object] = {}
    index = _jsx_skip_space(text, index + 1)
    while index < len(text) and text[index] != "}":
        if text[index] in ('"', "'", "`"):
            key, index = _jsx_string(text, index)
        else:
            identifier = _IDENTIFIER_RE.match(text, index)
            if identifier is None:
                raise ValueError(f"unexpected object key {text[index : index + 20]!r}")
            key = identifier.group(0)
            index = _jsx_skip_space(text, identifier.end())
        if index >= len(text) or text[index] != ":":
            raise ValueError(f"object key {key!r} has no value")
        value, index = _jsx_value(text, index + 1)
        props[key] = value
        index = _jsx_skip_space(text, index)
        if index < len(text) and text[index] == ",":
            index = _jsx_skip_space(text, index + 1)
        elif index >= len(text) or text[index] != "}":
            raise ValueError(f"object key {key!r} is not followed by , or }}")
    if index >= len(text):
        raise ValueError("object ends early")
    return props, index + 1


def _jsx_array(text: str, index: int) -> tuple[list[object], int]:
    """one `[value, ...]` array literal at `index` and the index past its
    closing bracket."""
    values: list[object] = []
    index = _jsx_skip_space(text, index + 1)
    while index < len(text) and text[index] != "]":
        value, index = _jsx_value(text, index)
        values.append(value)
        index = _jsx_skip_space(text, index)
        if index < len(text) and text[index] == ",":
            index = _jsx_skip_space(text, index + 1)
        elif index >= len(text) or text[index] != "]":
            raise ValueError("array value is not followed by , or ]")
    if index >= len(text):
        raise ValueError("array ends early")
    return values, index + 1


def _jsx_string(text: str, index: int) -> tuple[str, int]:
    """one quoted string at `index` and the index past its closing quote; a
    backtick's `${` interpolation raises rather than reads as text."""
    quote = text[index]
    index += 1
    characters: list[str] = []
    while index < len(text):
        char = text[index]
        if char == "\\":
            if index + 1 >= len(text):
                raise ValueError("string ends inside an escape")
            characters.append(text[index + 1])
            index += 2
        elif char == quote:
            return "".join(characters), index + 1
        elif quote == "`" and char == "$" and text.startswith("${", index):
            raise ValueError("template interpolation")
        else:
            characters.append(char)
            index += 1
    raise ValueError("string ends early")


def _jsx_skip_space(text: str, index: int) -> int:
    """the index of the first character at or past `index` that is no JS
    whitespace."""
    while index < len(text) and text[index] in _JS_SPACE:
        index += 1
    return index


def _jsx_prop(block: str, name: str) -> str | None:
    """the balanced-brace value of a <prop={...}> attribute, or None."""
    marker = f"{name}="
    position = block.find(marker)
    if position == -1:
        return None
    position += len(marker)
    if position >= len(block) or block[position] != "{":
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(position, len(block)):
        char = block[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return block[position + 1 : index]
    return None


def _quote_keys(text: str) -> str:
    """quote bare JSX object keys so ast.literal_eval accepts them."""
    return _BARE_KEY_PATTERN.sub(r'"\1"\2:', text)


def _plain_rows(text: str) -> str:
    """turn price-cell JSX fragments (<>{"$"}0.30</>) into plain strings."""
    return _FRAGMENT_PATTERN.sub(r'"\1\2"', text)


class _PricingColumns(NamedTuple):
    """a model-pricing table's column positions: the columns a rate's cells
    are read from."""

    model: int
    input: int
    output: int
    cache_read: int | None
    cache_write: int | None
    cache_write_1h: int | None
    context: int | None


def _pricing_columns(titles: list[str]) -> _PricingColumns | None:
    """the column positions a model-pricing table is read through, or None
    when the table names no per-token rate pair."""
    model_col = _column_index(titles, "Model")
    input_col = _column_index(titles, "Input Price (Cache Miss)")
    if input_col is None:
        input_col = _column_index(titles, "Input Price")
    output_col = _column_index(titles, "Output Price")
    if model_col is None or input_col is None or output_col is None:
        return None
    cache_read_col = _column_index(titles, "Input Price (Cache Hit)")
    if cache_read_col is None:
        cache_read_col = _column_index(titles, "Cached Input Price")
    return _PricingColumns(
        model_col,
        input_col,
        output_col,
        cache_read_col,
        _column_index(titles, "Cache Write Price (TTL 5min)"),
        _column_index(titles, "Cache Write Price (TTL 1h)"),
        _column_index(titles, "Context Window"),
    )


def _model_row(rows: list[list[str]], columns: _PricingColumns, model_id: str) -> list[str] | None:
    """the first row of a model-pricing table whose Model cell names
    `model_id` (case-insensitive), or None: the row `scrape` settles the id
    on.

    a row too short to carry every column the table is read through is
    skipped, so a truncated row prices nothing."""
    needed = max(index for index in columns if index is not None)
    for row in rows:
        if len(row) <= needed:
            continue
        if str(row[columns.model]).strip().lower() != model_id.lower():
            continue
        return row
    return None


def _pricing(
    doc: tuple[list[str], list[list[str]]], model_id: str, page_url: str
) -> Pricing | None:
    titles, rows = doc
    columns = _pricing_columns(titles)
    if columns is None:
        return None  # not a model-pricing table
    row = _model_row(rows, columns, model_id)
    if row is None:
        return None
    input_cost = _dollars(str(row[columns.input]), model_id, page_url)
    output_cost = _dollars(str(row[columns.output]), model_id, page_url)
    if input_cost is None or output_cost is None:
        return None
    cache_cost = (
        _dollars(str(row[columns.cache_read]), model_id, page_url)
        if columns.cache_read is not None
        else None
    )
    write_cost = (
        _dollars(str(row[columns.cache_write]), model_id, page_url)
        if columns.cache_write is not None
        else None
    )
    write_1h_cost = (
        _dollars(str(row[columns.cache_write_1h]), model_id, page_url)
        if columns.cache_write_1h is not None
        else None
    )
    max_tokens_in = (
        _token_count(str(row[columns.context]), model_id, page_url)
        if columns.context is not None
        else 0
    )
    return Pricing(
        input_cost_per_token=input_cost / 1e6,
        output_cost_per_token=output_cost / 1e6,
        mode="chat",
        max_tokens_in=max_tokens_in,
        cache_read_cost_per_token=cache_cost / 1e6 if cache_cost is not None else None,
        cache_write_cost_per_token=write_cost / 1e6 if write_cost is not None else None,
        cache_write_1h_cost_per_token=(write_1h_cost / 1e6 if write_1h_cost is not None else None),
        url=page_url,
    )


def _column_index(titles: list[str], name: str) -> int | None:
    for index, title in enumerate(titles):
        if title == name:
            return index
    return None


def _dollars(text: str, model_id: str, url: str) -> float | None:
    amounts, malformed = amount_scan(text, before="$")
    if malformed:
        raise unreadable_rate_error(text, model_id, url)
    if not amounts:
        return None
    amount = float(amounts[0].replace(",", ""))
    if not math.isfinite(amount):
        raise unreadable_rate_error(text, model_id, url)
    return amount


def _token_count(cell: str, model_id: str, url: str) -> int:
    """a context-window cell's token count; a cell with no digit run is 0.

    a digit run past web.MAX_COUNT_DIGITS is no context length, and the
    bound keeps the conversion far from int()'s 4300-digit limit, so the
    parse fails as a FetchError instead of a raw ValueError."""
    match = _CONTEXT_PATTERN.search(cell)
    if match is None:
        return 0
    digits = match.group(0).replace(",", "")
    if len(digits) > MAX_COUNT_DIGITS:
        raise FetchError(f"unreadable context window {cell!r} for {model_id} on {url}")
    return int(digits)

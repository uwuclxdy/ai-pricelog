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
spaces, a run of three or more backticks or tildes, closed by a run of the
same character at least as long) is stripped before the tables are read, so
a docs example contributes no table. DocTable columns are objects with a
`title` key; rows are arrays of strings, price cells written as JSX
fragments (<>{"$"}0.30</>) and the context window as "1,048,576 tokens". an
html table's first own row gives the column titles through web.header_grid,
so a spanned header keeps every later title aligned with its cell, and its
remaining rows give the data, a <tfoot> summary row excepted (a row whose
nearest row group is a tfoot); a table with no data row carrying printable
text is no pricing table, so the empty <thead><tr /></thead><tbody /> shell
raises instead of reading every model absent. a pricing candidate carries a
Model column plus an input price column (Input Price (Cache Miss), or the
K3 series table's plain "Input Price") and an Output Price column; an
incidental Model-headed table without them names no rate and is skipped,
and a page whose tables are all incidental raises `no Model pricing
table`. the Model column is matched exactly against the model id
and the model is searched across every candidate table; Input Price (Cache
Miss) -> input_cost, Input Price (Cache Hit) or Cached Input Price (the K3
spelling) -> cache_read_cost_per_token when the column exists, Output Price
-> output_cost, Cache Write Price (TTL 5min) -> cache_write_cost_per_token,
Cache Write Price (TTL 1h) -> cache_write_1h_cost_per_token, USD per 1M ->
/1e6, Context Window digits -> max_tokens_in.

the Pricing url names the page the rate was read from (the resolved chat
page, never the index); build_row stamps it as the row's url.

None = no row for the model. FetchError = the fetch failed, the index
resolves no (or an ambiguous) chat page, the page's DocTable props or html
tables do not parse, no pricing table (or no Model pricing table) is on the
page, a price cell carries an unreadable amount, or a context cell carries
an oversized digit run.
"""

from __future__ import annotations

import ast
import functools
import math
import re
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
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


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
    backticks or tildes, and closes on a run of the same character at least
    as long with only spaces after it; an unclosed fence runs to the end.
    """
    kept: list[str] = []
    fence = ""
    for line in markdown_lines(text):
        if fence:
            closes = re.fullmatch(rf" {{0,3}}{re.escape(fence[0])}{{{len(fence)},}} *", line)
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


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    page_url = _load_index(cfg.scraper_url)
    docs = _doc_tables(_strip_code_fences(fetch_text(page_url)))
    if not docs:
        raise FetchError(f"no pricing table (DocTable or html) on {page_url}")
    if not any(_pricing_columns(titles) is not None for titles, _ in docs):
        raise FetchError(f"no Model pricing table on {page_url}")
    for doc in docs:
        pricing = _pricing(doc, model_id, page_url)
        if pricing is not None:
            return pricing
    return None


def _doc_tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    """every pricing table on the page as (column titles, rows) pairs: each
    <DocTable> block's columns/rows props plus each plain html <table>; []
    when the page carries neither. each block's prop scan is bounded at the
    next <DocTable>, so a block missing a prop raises instead of borrowing a
    later block's."""
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


def _pricing_columns(titles: list[str]) -> tuple[int, int, int] | None:
    """the (model, input, output) column positions of a pricing table, or
    None when the table names no per-token rate pair."""
    model_col = _column_index(titles, "Model")
    input_col = _column_index(titles, "Input Price (Cache Miss)")
    if input_col is None:
        input_col = _column_index(titles, "Input Price")
    output_col = _column_index(titles, "Output Price")
    if model_col is None or input_col is None or output_col is None:
        return None
    return model_col, input_col, output_col


def _pricing(
    doc: tuple[list[str], list[list[str]]], model_id: str, page_url: str
) -> Pricing | None:
    titles, rows = doc
    columns = _pricing_columns(titles)
    if columns is None:
        return None  # not a model-pricing table
    model_col, input_col, output_col = columns
    cache_col = _column_index(titles, "Input Price (Cache Hit)")
    if cache_col is None:
        cache_col = _column_index(titles, "Cached Input Price")
    write_col = _column_index(titles, "Cache Write Price (TTL 5min)")
    write_1h_col = _column_index(titles, "Cache Write Price (TTL 1h)")
    context_col = _column_index(titles, "Context Window")
    needed = max(
        model_col,
        input_col,
        output_col,
        cache_col if cache_col is not None else 0,
        write_col if write_col is not None else 0,
        write_1h_col if write_1h_col is not None else 0,
        context_col if context_col is not None else 0,
    )
    for row in rows:
        if len(row) <= needed:
            continue
        if str(row[model_col]).strip().lower() != model_id.lower():
            continue
        input_cost = _dollars(str(row[input_col]), model_id, page_url)
        output_cost = _dollars(str(row[output_col]), model_id, page_url)
        if input_cost is None or output_cost is None:
            return None
        cache_cost = (
            _dollars(str(row[cache_col]), model_id, page_url) if cache_col is not None else None
        )
        write_cost = (
            _dollars(str(row[write_col]), model_id, page_url) if write_col is not None else None
        )
        write_1h_cost = (
            _dollars(str(row[write_1h_col]), model_id, page_url)
            if write_1h_col is not None
            else None
        )
        max_tokens_in = (
            _token_count(str(row[context_col]), model_id, page_url)
            if context_col is not None
            else 0
        )
        return Pricing(
            input_cost_per_token=input_cost / 1e6,
            output_cost_per_token=output_cost / 1e6,
            mode="chat",
            max_tokens_in=max_tokens_in,
            cache_read_cost_per_token=cache_cost / 1e6 if cache_cost is not None else None,
            cache_write_cost_per_token=write_cost / 1e6 if write_cost is not None else None,
            cache_write_1h_cost_per_token=(
                write_1h_cost / 1e6 if write_1h_cost is not None else None
            ),
            url=page_url,
        )
    return None


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

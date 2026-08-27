"""scrape per-token pricing for kimi / moonshot-v1 models.

page discovery: the scraper url is the docs index (llms.txt). every pricing
page is listed as a markdown link. the index is fetched once per run
(lru-cached) and turned into an id -> page map:

- title-derived ids: the part of the page title before "pricing" naming a
  kimi/moonshot family ("Flagship Model Kimi K3 Pricing" -> kimi-k3,
  "Generation Model Moonshot V1 Pricing" -> moonshot-v1); a trailing "model"
  word is dropped ("Kimi K2.6 Model" -> kimi-k2.6).
- slug-derived ids: "chat-k3" -> "kimi-k3" (dots are lost in the slug, so
  dotful ids come from the title match only).

lookup: exact id, else the longest mapped id the model id extends with "-"
(kimi-k2.7-code-highspeed -> kimi-k2.7-code, moonshot-v1-8k -> moonshot-v1).
unmatched ids fall back to "chat-" + the id minus the "kimi-" prefix minus
dots; a failed fetch there (404) means the model has no pricing page -> None.
a transient failure in that fallback fetch reads as the same skip-and-retry,
so it can delay a price, never write a wrong one.

each pricing page is markdown carrying one <DocTable columns={...} rows={...} />
block. columns are objects with a `title` key; rows are arrays of strings,
price cells written as JSX fragments (<>{"$"}0.30</>) and the context window
as "1,048,576 tokens". Input Price (Cache Miss) -> input_cost (the v1 page
has no cache split and titles the column plain "Input Price"), Input Price
(Cache Hit) -> cache_read_cost_per_token when the column exists, Output Price
-> output_cost, USD per 1M -> /1e6, Context Window digits -> max_tokens_in.

the Pricing url names the page the rate was read from (the resolved
per-model page, never the index); build_row stamps it as the row's url.

None = no pricing page or no row for the model. FetchError = the fetch
failed, the index lists no pricing pages, or a page's DocTable does not parse.
"""

from __future__ import annotations

import ast
import functools
import re
from urllib.parse import urljoin, urlsplit

from ai_pricelog.config import ProviderCfg
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_text

_LINK_PATTERN = re.compile(r"^\s*-\s*\[([^\]]+)\]\(([^)]+)\)")
_FAMILY_PATTERN = re.compile(r"(?:kimi|moonshot)(?:\s+[a-z0-9][a-z0-9.]*)+", re.IGNORECASE)
_FRAGMENT_PATTERN = re.compile(r'<>\{"([^"]*)"\}([^<]*)</>')
_BARE_KEY_PATTERN = re.compile(r'(?<![A-Za-z0-9_"])([A-Za-z_][A-Za-z0-9_]*)(\s*):')
_PRICE_PATTERN = re.compile(r"\$(\d+(?:\.\d+)?)")
_CONTEXT_PATTERN = re.compile(r"\d[\d,]*")


@functools.lru_cache(maxsize=1)
def _load_index(index_url: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for line in fetch_text(index_url).splitlines():
        match = _LINK_PATTERN.match(line)
        if match is None:
            continue
        title, href = match.group(1), match.group(2)
        path = urlsplit(href).path
        if "/pricing/" not in path:
            continue
        url = href if href.startswith(("http://", "https://")) else urljoin(index_url, href)
        slug = path.rsplit("/", 1)[-1].removesuffix(".md")
        for candidate in (_title_id(title), _slug_id(slug)):
            if candidate:
                mapping[candidate] = url
    if not mapping:
        raise FetchError(f"no pricing pages listed in the index {index_url}")
    return mapping


def _title_id(title: str) -> str | None:
    before_pricing = re.split(r"\s+pricing\b", title, maxsplit=1, flags=re.IGNORECASE)[0]
    match = _FAMILY_PATTERN.search(before_pricing)
    if match is None:
        return None
    tokens = match.group(0).split()
    if len(tokens) > 1 and tokens[-1].lower() == "model":
        tokens = tokens[:-1]
    return "-".join(tokens).lower()


def _slug_id(slug: str) -> str | None:
    if not slug.startswith("chat-"):
        return None
    return "kimi-" + slug.removeprefix("chat-")


def _page_for(mapping: dict[str, str], model_id: str) -> str | None:
    if model_id in mapping:
        return mapping[model_id]
    prefixes = [
        (candidate, url)
        for candidate, url in mapping.items()
        if model_id.startswith(candidate + "-")
    ]
    if not prefixes:
        return None
    return max(prefixes, key=lambda pair: len(pair[0]))[1]


def _fallback_url(index_url: str, model_id: str) -> str:
    base = index_url.rsplit("/", 1)[0]
    slug = "chat-" + model_id.removeprefix("kimi-").replace(".", "")
    return f"{base}/pricing/{slug}.md"


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    mapping = _load_index(cfg.scraper_url)
    page_url = _page_for(mapping, model_id)
    if page_url is None:
        return _scrape_fallback(cfg.scraper_url, model_id)
    doc = _doc_table(fetch_text(page_url))
    if doc is None:
        raise FetchError(f"no DocTable block on {page_url}")
    return _pricing(doc, model_id, page_url)


def _scrape_fallback(index_url: str, model_id: str) -> Pricing | None:
    fallback_url = _fallback_url(index_url, model_id)
    try:
        text = fetch_text(fallback_url)
    except FetchError:
        return None
    doc = _doc_table(text)
    return _pricing(doc, model_id, fallback_url) if doc is not None else None


def _doc_table(text: str) -> tuple[list[str], list[list[str]]] | None:
    """parse the last <DocTable> block's columns/rows props; None when the
    page carries none."""
    start = text.rfind("<DocTable")
    if start == -1:
        return None
    tail = text[start:]
    columns_text = _jsx_prop(tail, "columns")
    rows_text = _jsx_prop(tail, "rows")
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
    return titles, rows


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


def _pricing(
    doc: tuple[list[str], list[list[str]]], model_id: str, page_url: str
) -> Pricing | None:
    titles, rows = doc
    model_col = _column_index(titles, "Model")
    input_col = _column_index(titles, "Input Price (Cache Miss)")
    if input_col is None:
        input_col = _column_index(titles, "Input Price")
    output_col = _column_index(titles, "Output Price")
    cache_col = _column_index(titles, "Input Price (Cache Hit)")
    context_col = _column_index(titles, "Context Window")
    if model_col is None or input_col is None or output_col is None:
        raise FetchError("pricing table is missing the Model/Input/Output columns")
    needed = max(
        model_col,
        input_col,
        output_col,
        cache_col if cache_col is not None else 0,
        context_col if context_col is not None else 0,
    )
    for row in rows:
        if len(row) <= needed:
            continue
        if str(row[model_col]).strip().lower() != model_id.lower():
            continue
        input_cost = _dollars(str(row[input_col]))
        output_cost = _dollars(str(row[output_col]))
        if input_cost is None or output_cost is None:
            return None
        cache_cost = _dollars(str(row[cache_col])) if cache_col is not None else None
        max_tokens_in = _token_count(str(row[context_col])) if context_col is not None else 0
        return Pricing(
            input_cost_per_token=input_cost / 1e6,
            output_cost_per_token=output_cost / 1e6,
            mode="chat",
            max_tokens_in=max_tokens_in,
            cache_read_cost_per_token=cache_cost / 1e6 if cache_cost is not None else None,
            url=page_url,
        )
    return None


def _column_index(titles: list[str], name: str) -> int | None:
    for index, title in enumerate(titles):
        if title == name:
            return index
    return None


def _dollars(text: str) -> float | None:
    match = _PRICE_PATTERN.search(text)
    return float(match.group(1)) if match else None


def _token_count(cell: str) -> int:
    match = _CONTEXT_PATTERN.search(cell)
    if match is None:
        return 0
    return int(match.group(0).replace(",", ""))

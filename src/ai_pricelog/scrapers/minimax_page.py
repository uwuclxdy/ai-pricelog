"""scrape MiniMax pay-as-you-go pricing.

reads https://platform.minimax.io/docs/guides/pricing-paygo.md (static markdown).
token-priced tables have a header `Model | Input | Output | ...`, matched on
folded headings (case, whitespace, &/and), so a recased header still scrapes
and a `**Model / API**` table stays out. the live page bolds each header name
and appends its unit (`**Input** $ / M tokens`): a unit-suffixed cell folds to
its name with the unit and bold pair dropped, and the first cell drops its bold
pair; a bolded rate cell with no unit does not resolve. MiniMax-M3 rows live in
Standard/Priority tab variants and are split by context size; we take the
first M3 row, which is the Standard tab's <=512k row. price cells like
`~~$0.60~~ $0.30 / M tokens` carry a strikethrough original plus the current
price: we take the LAST readable dollar amount in the cell; a cell with an
amount the grammar cannot read is a page-shape break (FetchError). a folded
`Prompt caching Read` header cell is the cache-read rate, emitted as
cache_read_cost_per_token, and unset when the header names no cache column; a
header naming a cache column the scraper cannot read (folded text holding
`cach`, no `Prompt caching Read`) raises. a table holding the requested
model's `**<model_id>**` row whose header does not resolve a column the
scraper reads - `Input`, `Output`, or `Prompt caching Read` - or whose first
cell does not fold to `Model` is skipped only when its row carries no `$` and
its header names no rate heading (folded text holding `input`, `output`
or `cach`); any other such table raises a FetchError naming the model,
the missing column and the url. when a pricing table holds no readable row
for the requested model, a row whose first non-empty cell - an empty first
cell from a doubled edge pipe shifts the name right - displays the requested
id as a whole id - an unbolded name, a badge before it, an italic name -
raises naming that cell, and a matched row shorter than the resolved columns
raises naming its cell count. that name read takes the cell's visible text
(markdown links reduced to their text, html tags removed, never a link
target) and matches case-insensitively; a markdown emphasis marker is no
part of an id - an `_` at a word edge is a boundary, an `_` between two
word characters is not - so `_MiniMax-M2.7_` names the row while
`MiniMax-M2.7_highspeed` reads as one longer token, never the requested id.
dollars
per 1M tokens -> divided by 1e6. the page carries no context window, so the
max_tokens fields stay 0 (the entry builder omits them).
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.minimax_page import _ID_LEFT_EDGE, _ID_RIGHT_EDGE, _LINK_RE, _TAG_RE
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import (
    FetchError,
    amount_scan,
    extract_markdown_tables,
    fetch_text,
    fold_heading,
    unreadable_rate_error,
)

_MODEL_RE = re.compile(r"\*\*(.+?)\*\*")
_FOLDED_MODEL = fold_heading("Model")
_FOLDED_INPUT = fold_heading("Input")
_FOLDED_OUTPUT = fold_heading("Output")
_FOLDED_CACHE_READ = fold_heading("Prompt caching Read")
_UNIT_SUFFIX_RE = re.compile(r"\s*\\?\$\s*/\s*m tokens$")


def _last_amount(cell: str, model_id: str, url: str) -> float | None:
    """the cell's last readable dollar amount; a cell with an amount the
    grammar cannot read is a page-shape break."""
    amounts, malformed = amount_scan(cell, before="$")
    if malformed:
        raise unreadable_rate_error(cell, model_id, url)
    return float(amounts[-1].replace(",", "")) if amounts else None


def _model_row(table: list[list[str]], model_id: str) -> list[str] | None:
    """the first data row whose first cell is the requested `**<model_id>**`."""
    for row in table[2:]:
        match = _MODEL_RE.search(row[0])
        if match and match.group(1) == model_id:
            return row
    return None


def _name_cell(row: list[str]) -> str:
    """the row's first non-empty cell (a doubled edge pipe shifts the name right)."""
    return next((cell for cell in row if cell), "")


def _names_id(cell: str, model_id: str) -> bool:
    """whether the cell's visible text spells `model_id` whole, never in a link target.

    a markdown emphasis marker is no part of an id: `_MiniMax-M2.7_` spells
    the id, `MiniMax-M2.7_highspeed` is one longer token.
    """
    visible = _TAG_RE.sub(" ", _LINK_RE.sub(r"\1", cell))
    pattern = _ID_LEFT_EDGE + re.escape(model_id) + _ID_RIGHT_EDGE
    return re.search(pattern, visible, re.IGNORECASE) is not None


def _drop_bold_pair(folded: str) -> str:
    """`folded` with one complete `**` pair dropped; an unbalanced marker stays."""
    if len(folded) >= 4 and folded.startswith("**") and folded.endswith("**"):
        return folded[2:-2]
    return folded


def _fold_header(cell: str) -> str:
    """the cell's folded heading; a unit-suffixed cell drops the unit and its bold pair."""
    folded = fold_heading(cell)
    suffix = _UNIT_SUFFIX_RE.search(folded)
    if suffix is None:
        return folded
    return _drop_bold_pair(folded[: suffix.start()].strip())


def _is_model_heading(cell: str) -> bool:
    """whether the first header cell names the model column (the live page bolds it)."""
    return _drop_bold_pair(_fold_header(cell)) == _FOLDED_MODEL


def _missing_column(folded: list[str]) -> str | None:
    """the first column the scraper reads that the header does not resolve."""
    if _FOLDED_INPUT not in folded:
        return "Input"
    if _FOLDED_OUTPUT not in folded:
        return "Output"
    if _FOLDED_CACHE_READ not in folded and any("cach" in cell for cell in folded):
        return "Prompt caching Read"
    return None


def _is_pricing_table(table: list[list[str]]) -> bool:
    """a table the scraper can price from: `Model | Input | Output`."""
    folded = [_fold_header(cell) for cell in table[0]]
    return _is_model_heading(table[0][0]) and _FOLDED_INPUT in folded and _FOLDED_OUTPUT in folded


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    text = fetch_text(cfg.scraper_url)
    url = cfg.scraper_url
    tables = extract_markdown_tables(text)
    for table in tables:
        row = _model_row(table, model_id)
        if row is None:
            if _is_pricing_table(table):
                unreadable = next(
                    (
                        candidate
                        for candidate in table[2:]
                        if _names_id(_name_cell(candidate), model_id)
                    ),
                    None,
                )
                if unreadable is not None:
                    raise FetchError(
                        f"unreadable model row for {model_id} on {url}: {_name_cell(unreadable)!r}"
                    )
            continue
        folded = [_fold_header(cell) for cell in table[0]]
        missing = _missing_column(folded)
        if missing is None and not _is_model_heading(table[0][0]):
            missing = "Model"
        if missing is not None:
            priced = any("$" in cell for cell in row[1:])
            rate_header = any(
                word in cell for cell in folded for word in ("input", "output", "cach")
            )
            if not priced and not rate_header:
                continue
            raise FetchError(
                f"malformed pricing table for {model_id} on {url}: no {missing} column"
            )
        input_idx = folded.index(_FOLDED_INPUT)
        output_idx = folded.index(_FOLDED_OUTPUT)
        cache_idx = folded.index(_FOLDED_CACHE_READ) if _FOLDED_CACHE_READ in folded else None
        resolved_columns = [input_idx, output_idx] + ([cache_idx] if cache_idx is not None else [])
        if len(row) <= max(resolved_columns):
            raise FetchError(f"unreadable model row for {model_id} on {url}: {len(row)} cells")
        input_amount = _last_amount(row[input_idx], model_id, url)
        output_amount = _last_amount(row[output_idx], model_id, url)
        if input_amount is None or output_amount is None:
            return None
        cache_amount = None
        if cache_idx is not None:
            cache_amount = _last_amount(row[cache_idx], model_id, url)
        return Pricing(
            input_amount / 1e6,
            output_amount / 1e6,
            mode="chat",
            cache_read_cost_per_token=(cache_amount / 1e6 if cache_amount is not None else None),
        )
    if not any(_is_pricing_table(table) for table in tables):
        raise FetchError(f"no pricing tables found on {url}")
    return None

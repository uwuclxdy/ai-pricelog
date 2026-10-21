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
the missing column and the url. dollars
per 1M tokens -> divided by 1e6. the page carries no context window, so the
max_tokens fields stay 0 (the entry builder omits them).
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
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
        if len(row) <= max(input_idx, output_idx):
            return None
        input_amount = _last_amount(row[input_idx], model_id, url)
        output_amount = _last_amount(row[output_idx], model_id, url)
        if input_amount is None or output_amount is None:
            return None
        cache_amount = None
        if cache_idx is not None and len(row) > cache_idx:
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

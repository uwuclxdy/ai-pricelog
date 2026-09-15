"""scrape claude per-token pricing from the anthropic pricing markdown twin.

same model table as detection (the header is pinned in the detector).
five rate columns read as USD per 1M tokens: Base Input -> input, 5m
Cache Writes -> the default write tier, 1h Cache Writes -> the 1h write
tier, Cache Hits & Refreshes -> cache read, Output -> output, each /1e6.
every rate cell must carry a dollar amount; an unreadable one is a
page-shape break (FetchError), so a silent misread cannot ship. the page
carries no context window, so the max_tokens fields stay 0 (the entry
builder omits them).

the fast-mode table (folded header Model | Input | Output) prices the
request-body speed:"fast" premium: $ per MTok input/output, first-party
only, full context, stacking with caching and data-residency
multipliers, never batch. a model cell may join two names with " / "
(the row covers both), and a row applying to the requested id attaches
the rates as a window_rates entry keyed on the request mode (the
"mode" lands in the override's `when` at build time), so the standard
rates stay the base row. the fast table absent is additive drift: the
base Pricing still ships, with no entries and a warning. a fast-table
row whose names sit in no model-table row is drift too: skipped with a
warning, never raised. an unreadable rate on a row that does apply is a
page-shape break (FetchError), same as the base table.

None = the model id is not on the page. FetchError = the fetch failed,
the page carries no model pricing table, or a row is outside the shape.
"""

from __future__ import annotations

import logging
import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.anthropic_page import (
    TABLE_HEADER,
    _slug,
    check_row,
    model_table,
)
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, extract_markdown_tables, fetch_text, fold_heading

log = logging.getLogger(__name__)

_AMOUNT_RE = re.compile(r"\$([\d,]+(?:\.\d+)?)")

_FAST_HEADER = ["Model", "Input", "Output"]
_FAST_FOLDED_HEADER = [fold_heading(cell) for cell in _FAST_HEADER]
# the two covered models share one cell, split on the literal separator
_FAST_NAME_SPLIT = " / "
_FAST_MODE = "fast"


def _amount(cell: str, model_id: str, url: str) -> float:
    match = _AMOUNT_RE.search(cell)
    if match is None:
        raise FetchError(f"unreadable rate {cell!r} for {model_id} on {url}")
    return float(match.group(1).replace(",", ""))


def _fast_table(text: str) -> list[list[str]] | None:
    """the fast-mode table among the page's tables; None when absent.

    the folded Model | Input | Output header is what tells it from every
    other two- and three-column table the page carries; a header with no
    data rows reads as absent.
    """
    for table in extract_markdown_tables(text):
        if table and [fold_heading(cell) for cell in table[0]] == _FAST_FOLDED_HEADER:
            return table if len(table) > 2 else None
    return None


def _fast_window_rates(
    text: str, model_id: str, url: str, main_ids: set[str]
) -> tuple[dict[str, object], ...]:
    """the model's fast-mode window_rates entries, () when none apply.

    `main_ids` is every id the model table carries, so a fast-table row
    naming an unknown model is told from a row for other known models:
    the former is drift to skip with a warning, the latter simply does
    not apply here. an unreadable rate raises only on a row that applies.
    """
    table = _fast_table(text)
    if table is None:
        log.warning("fast-mode pricing table absent for %s on %s", model_id, url)
        return ()
    entries: list[dict[str, object]] = []
    for row in table[2:]:
        if len(row) != len(_FAST_HEADER) or not row[0]:
            raise FetchError(f"row outside the fast-mode shape on {url}: {row!r}")
        names = [name.strip() for name in row[0].split(_FAST_NAME_SPLIT)]
        if not any(_slug(name) in main_ids for name in names):
            log.warning("fast-mode row %r names no model in the pricing table on %s", row[0], url)
            continue
        if not any(_slug(name) == model_id for name in names):
            continue
        entries.append(
            {
                "mode": _FAST_MODE,
                "input_mtok": _amount(row[1], model_id, url),
                "output_mtok": _amount(row[2], model_id, url),
            }
        )
    return tuple(entries)


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    text = fetch_text(cfg.scraper_url)
    rows = model_table(text, cfg.scraper_url)[2:]
    # the fast table's names are judged against every id the model table
    # carries, rows past the requested model's included; membership reads
    # tolerantly there, the match itself keeps failing loud
    main_ids = {_slug(row[0]) for row in rows if len(row) == len(TABLE_HEADER) and row[0]}
    for row in rows:
        check_row(row, cfg.scraper_url)
        if _slug(row[0]) != model_id:
            continue
        return Pricing(
            input_cost_per_token=_amount(row[1], model_id, cfg.scraper_url) / 1e6,
            output_cost_per_token=_amount(row[5], model_id, cfg.scraper_url) / 1e6,
            mode="chat",
            cache_read_cost_per_token=_amount(row[4], model_id, cfg.scraper_url) / 1e6,
            cache_write_cost_per_token=_amount(row[2], model_id, cfg.scraper_url) / 1e6,
            cache_write_1h_cost_per_token=_amount(row[3], model_id, cfg.scraper_url) / 1e6,
            window_rates=_fast_window_rates(text, model_id, cfg.scraper_url, main_ids),
        )
    return None

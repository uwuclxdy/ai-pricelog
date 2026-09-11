"""detect model ids on the deepseek api-docs pricing page.

the page (https://api-docs.deepseek.com/quick_start/pricing/) is a docusaurus
static html page with a single table; the trailing slash is required, the
slash-less path serves a JS shell without the table. its header row's first
cell pins as "MODEL" after folding case, whitespace, and &/and
(web.fold_heading), and every remaining header cell is a model id with a
trailing " (n)" footnote marker stripped (the 2026-09-10 page moved the
column ids to "deepseek-flash (1)" spellings). rows keyed by BASE URL /
MODEL VERSION / THINKING MODE / CONTEXT LENGTH / MAX OUTPUT / FEATURES /
PRICING are not model rows. header cells that do not look like model ids are
skipped; a page whose MODEL row carries no id is a parse failure (FetchError).
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, extract_tables, fetch_soup, fold_heading

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
_FOOTNOTE_MARKER = re.compile(r"\s*\(\d+\)$")
_FOLDED_MODEL_HEADER = fold_heading("MODEL")


def header_ids(table: list[list[str]]) -> list[str]:
    """the model table's header ids, a trailing " (n)" footnote marker stripped."""
    return [_FOOTNOTE_MARKER.sub("", cell.strip()) for cell in table[0][1:]]


def detect(cfg: ProviderCfg) -> list[str]:
    tables = extract_tables(fetch_soup(cfg.detector_url))
    table = _model_table(tables, cfg.detector_url)
    ids = [cell for cell in header_ids(table) if _ID_PATTERN.fullmatch(cell)]
    if not ids:
        raise FetchError(f"no model ids in the MODEL header row on {cfg.detector_url}")
    return ids


def _model_table(tables: list[list[list[str]]], url: str) -> list[list[str]]:
    for table in tables:
        if table and table[0] and fold_heading(table[0][0]) == _FOLDED_MODEL_HEADER:
            return table
    raise FetchError(f"no MODEL header table on {url}")

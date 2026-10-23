"""detect model ids on the publicai models page.

https://platform.publicai.co/models serves one static table with the header
Model ID | Context Length | Pricing | Country of Origin, pinned after
folding case, whitespace, and &/and (web.fold_heading). the Model ID cell
spells the api id as an org/model slug; ids are case-folded to fit the
stored id charset (^[a-z0-9][a-z0-9._/-]*$), and rows whose id does not fit
are skipped. the Pricing cell is input / output per 1M tokens ("$0.10 /
$0.20 per 1M tokens"); a row whose pricing cell carries a malformed amount
(a comma-decimal) is skipped with the counter-freezing detect-skip warning;
a row whose pricing cell does not parse as two per-1M-token amounts is not
a per-token model row and is skipped (embeddings, image and audio rows, if
any appear, price differently). a page without the table, or with no usable
ids, is a parse failure (FetchError).
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup, Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import (
    FetchError,
    amount_scan,
    fetch_soup,
    fold_heading,
    header_labels,
    own_rows,
    unreadable_rate_error,
)

log = logging.getLogger(__name__)

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._/-]*$")
_HEADERS = ("model id", "context length", "pricing", "country of origin")
_FOLDED_HEADERS = tuple(fold_heading(cell) for cell in _HEADERS)


def detect(cfg: ProviderCfg) -> list[str]:
    table = _models_table(fetch_soup(cfg.detector_url), cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    for cells in _table_rows(table):
        model_id = _model_id(cells)
        if model_id is None or not _ID_PATTERN.fullmatch(model_id):
            continue
        amounts, malformed = _pricing_cell(cells[2])
        if malformed:
            log.warning(
                "detect skip for %s: %s",
                cfg.key,
                unreadable_rate_error(
                    cells[2].get_text(" ", strip=True), model_id, cfg.detector_url
                ),
            )
            continue
        if len(amounts) != 2:
            continue
        if model_id not in seen:
            seen.add(model_id)
            ids.append(model_id)
    if not ids:
        raise FetchError(f"no model ids in the models table on {cfg.detector_url}")
    return ids


def _models_table(soup: BeautifulSoup, url: str) -> Tag:
    """the Model ID | Context Length | Pricing | Country of Origin table."""
    for table in soup.find_all("table"):
        if table.find_parent("table") is not None:
            continue
        if header_labels(table) == _FOLDED_HEADERS:
            return table
    raise FetchError(f"no models table on {url}")


def _table_rows(table: Tag) -> list[list[Tag]]:
    """the table's own body rows as td cell lists (web.own_rows)."""
    return [row.find_all("td", recursive=False) for row in own_rows(table)]


def _model_id(cells: list[Tag]) -> str | None:
    """the normalized Model ID cell, or None for a short row."""
    if len(cells) < 3:
        return None
    link = cells[0].find("a")
    name = link.get_text(" ", strip=True) if link else cells[0].get_text(" ", strip=True)
    return _normalize_id(name)


def _normalize_id(name: str) -> str:
    """the stored spelling: the page slug, case-folded."""
    return name.strip().lower()


def _pricing_cell(cell: Tag) -> tuple[list[str], bool]:
    """(dollar amounts, malformed) of an input/output per-1M-tokens cell;
    amounts are [] when the cell is not a per-1M-token quote."""
    text = cell.get_text(" ", strip=True)
    if "per 1m tokens" not in text.casefold():
        return [], False
    return amount_scan(text, before="$")

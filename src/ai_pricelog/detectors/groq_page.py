"""detect groq model ids from the supported-models markdown twin.

reads https://console.groq.com/docs/models.md (the machine-readable surface
llms.txt advertises). three tables share the pinned header MODEL ID |
SPEED (T/SEC) | PRICE PER 1M TOKENS | RATE LIMITS (DEVELOPER PLAN) |
CONTEXT WINDOW (TOKENS) | MAX COMPLETION TOKENS | MAX FILE SIZE: production,
systems, and preview. only rows whose price cell reads "$in input $out
output" are emitted, zero rates included so a stored model whose row turns
free stays mapped (the scraper decides); the known unpriced forms
(ContactSales, per-hour "$0.111 per hour", per-character "$40 per 1M
characters", "-") are skipped. rows outside the table shape, price cells
outside the known forms, and model cells outside the link/id shape are
additive drift: detection skips them with a warning (plan #22), and a page
without a per-token pricing table or per-token model rows still raises.
the header pins after folding case, whitespace, and &/and, so wording
drift ("model id", "price per 1m tokens") still matches. the model cell
holds a display-name link followed by the api id; the link path is
authoritative and a badge glued onto the id in any casing strips off
("Enterprisellama-3.1-8b-instant" -> llama-3.1-8b-instant).
"""

from __future__ import annotations

import logging
import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, extract_markdown_tables, fetch_text, fold_heading

log = logging.getLogger(__name__)

TABLE_HEADER = [
    "MODEL ID",
    "SPEED (T/SEC)",
    "PRICE PER 1M TOKENS",
    "RATE LIMITS (DEVELOPER PLAN)",
    "CONTEXT WINDOW (TOKENS)",
    "MAX COMPLETION TOKENS",
    "MAX FILE SIZE",
]

_ID_CHARSET_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*$")
_PRICE_RE = re.compile(r"^\$(\d+(?:\.\d+)?)\s+input\s*\$(\d+(?:\.\d+)?)\s+output$")
_PER_HOUR_RE = re.compile(r"^\$\d+(?:\.\d+)? per hour$")
_PER_CHAR_RE = re.compile(r"^\$\d+(?:\.\d+)? per 1M characters$")
_UNPRICED = ("ContactSales", "-", "\\-")

_FOLDED_HEADER = [fold_heading(cell) for cell in TABLE_HEADER]


def model_tables(text: str, url: str) -> list[list[list[str]]]:
    """the per-token price tables; a page without one is a shape break."""
    tables = [
        table
        for table in extract_markdown_tables(text)
        if table and [fold_heading(cell) for cell in table[0]] == _FOLDED_HEADER
    ]
    if not tables:
        raise FetchError(f"no per-token pricing table on {url}")
    return tables


def check_row(row: list[str], url: str) -> None:
    if len(row) != len(TABLE_HEADER):
        raise FetchError(f"row outside the pricing shape on {url}: {row!r}")


def _price_amounts(cell: str, url: str) -> tuple[float, float] | None:
    """the per-token rates, or None for a known unpriced form.

    a cell outside every known shape is a page-shape break: silently
    skipping it would read a drifted price column as an unpriced row and
    open a phantom delisting.
    """
    match = _PRICE_RE.fullmatch(cell)
    if match is not None:
        return float(match.group(1)), float(match.group(2))
    if cell in _UNPRICED or _PER_HOUR_RE.fullmatch(cell) or _PER_CHAR_RE.fullmatch(cell):
        return None
    raise FetchError(f"unreadable price cell {cell!r} on {url}")


def parse_id(cell: str, url: str) -> str:
    """the row's api id; the link path is authoritative, a badge strips off.

    the cell is [![image](image-url)Display](href)id; the outer link's ](
    delimiter is the LAST one, so the image's own brackets never confuse
    the split. the text after the link must be the link's model id, or a
    badge glued onto it in any casing, which strips off.
    """
    split = cell.rfind("](")
    if split == -1:
        raise FetchError(f"model cell without a model link on {url}: {cell!r}")
    close = cell.find(")", split)
    if close == -1:
        raise FetchError(f"model cell with an unterminated link on {url}: {cell!r}")
    href = cell[split + 2 : close]
    tail = cell[close + 1 :]
    link_id = href.removeprefix("/docs/model/")
    if link_id == href:
        raise FetchError(f"model link outside /docs/model/ on {url}: {href!r}")
    if tail == link_id:
        model_id = tail
    elif tail.endswith(link_id):
        model_id = link_id
    else:
        raise FetchError(f"unreadable model id tail {tail!r} with link {href!r} on {url}")
    if not _ID_CHARSET_RE.fullmatch(model_id):
        raise FetchError(f"model id {model_id!r} outside the id charset on {url}")
    return model_id


def detect(cfg: ProviderCfg) -> list[str]:
    """per-token-priced model ids, page order; unpriced rows are skipped."""
    text = fetch_text(cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    for table in model_tables(text, cfg.detector_url):
        for row in table[2:]:
            try:
                check_row(row, cfg.detector_url)
                if _price_amounts(row[2], cfg.detector_url) is None:
                    continue
                model_id = parse_id(row[0], cfg.detector_url)
            except FetchError as exc:
                log.warning("detect skip for %s: %s", cfg.key, exc)
                continue
            if model_id not in seen:
                seen.add(model_id)
                ids.append(model_id)
    if not ids:
        raise FetchError(f"no per-token model rows on {cfg.detector_url}")
    return ids

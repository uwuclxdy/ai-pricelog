"""detect text-generation model ids from Alibaba's Model Studio CN page.

reads https://help.aliyun.com/zh/model-studio/text-generation-model/ (static
html). every table has a header row whose first cell is the `模型 ID` column
label; each data row's first cell carries one or more model ids. the
detector takes the whitespace tokens of the first cell matching
`^[a-z0-9][a-z0-9.-]*$` case-insensitively and returns them case-preserved
(third-party names like `MiniMax-M3` keep their page spelling). the page
mixes recommended and third-party models; litellm's dashscope namespace
tracks them all. resold first-party ids (models dashscope carries that
another watched source owns) are excluded here, so a dashscope copy never
shadows the owning source's row in a first-match-wins consumer. dedupe
preserves page order.

the CN page lists one official version per model, never its preview names
or dated snapshots, so it seeds candidates but cannot settle absence:
`detect_priced` reads the scraper's international pricing page instead and
returns every id that page prices on an International-scope row (see
`international_rows` for the table shape).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import NamedTuple

from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import (
    FetchError,
    amount_scan,
    extract_tables,
    fetch_soup,
    header_grid,
    own_cells,
    own_table_rows,
)

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$", re.IGNORECASE)

# dashscope resells these ids; the owning source (deepseek / zai / moonshot)
# is the authoritative price, so the resold copy stays out of the store.
_RESOLD_IDS = frozenset(
    {
        "deepseek-v3.2",
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "glm-5.1",
        "glm-5.2",
        "kimi-k2.7-code",
    }
)

# the price columns carry one of these labels (the page renamed `Input price`
# to `Input unit price` by 2026-11-18); a label matches by prefix, so the
# `(per 1 million tokens)` tail may change freely
_INPUT_LABELS = ("Input price", "Input unit price")
_OUTPUT_LABELS = ("Output price", "Output unit price")
_RANGE_LABEL = "Input token"
# the forms a token-range cell takes: `0<Token≤256K`, `256K<Token≤1M`,
# `No tiered pricing`, `flat-rate pricing`
_RANGE_CELL_RE = re.compile(r"Token\s*[<≤]|^No tiered pricing$|^flat-rate pricing$")


class InternationalRow(NamedTuple):
    """one International-scope data row of a pricing table, cells aligned."""

    model_id: str
    input_cell: str
    output_cell: str


def _column(header: list[str], labels: tuple[str, ...]) -> int | None:
    for index, cell in enumerate(header):
        if cell.startswith(labels):
            return index
    return None


def _offset(cells: list[str], range_idx: int | None) -> int:
    """how far a row's cells sit from the header grid.

    some rows omit a grid cell (measured 2026-11-18: the International
    `qwen3.5-flash-2026-02-23` row has no `Pattern` cell and pads an empty
    cell at its end instead), so every later cell sits one position early.
    the token-range cell has a form no other column carries, so its position
    anchors the row.
    """
    if range_idx is None:
        return 0
    for index, cell in enumerate(cells[2:], start=2):
        if _RANGE_CELL_RE.search(cell):
            return index - range_idx
    return 0


def international_rows(soup: BeautifulSoup, url: str) -> Iterator[InternationalRow]:
    """every International-scope data row of the page's pricing tables.

    a pricing table starts with a `Model ID` header cell; its price columns
    are the header cells whose label starts with an `_INPUT_LABELS` /
    `_OUTPUT_LABELS` entry. a multi-column span (the header cell carries a
    colspan, the omni tables split input into text/audio/image and output
    into three modes) expands into one grid position per sub-column; the
    first input position is the text-input rate and the first output
    position the text-output rate (the base rates). a sub-header row names
    the sub-columns and carries no scope cell, so the scope test skips it.
    the row's model id is the first whitespace token of its first cell (the
    rest is a note, and may name another id: `qwen3.7-plus Current
    capabilities are equivalent to qwen3.7-plus-2026-05-26`); tiered
    continuation rows (`256K<Token<=1M`) carry no scope cell and are skipped.
    the `Deployment scope` cell must contain `International`: rows scoped to
    Chinese mainland / Global / Japan / US are skipped. a row too short for
    its aligned price cells is skipped: a later table may carry the same id
    with full columns. a page with no pricing table is a page-shape break.
    """
    tables = [table for table in soup.find_all("table") if table.find_parent("table") is None]
    found_pricing_table = False
    for table in tables:
        rows = list(own_table_rows(table))
        if not rows:
            continue
        grid = header_grid(rows[0])
        if not grid or not grid[0].startswith("Model ID"):
            continue
        found_pricing_table = True
        input_idx = _column(grid, _INPUT_LABELS)
        output_idx = _column(grid, _OUTPUT_LABELS)
        if input_idx is None or output_idx is None:
            continue
        range_idx = _column(grid, (_RANGE_LABEL,))
        for row in rows[1:]:
            cells = [cell.get_text(" ", strip=True) for cell in own_cells(row)]
            if not cells or not cells[0]:
                continue
            if len(cells) <= 1 or "International" not in cells[1]:
                continue
            shift = _offset(cells, range_idx)
            input_at, output_at = input_idx + shift, output_idx + shift
            if min(input_at, output_at) < 2 or len(cells) <= max(input_at, output_at):
                continue
            yield InternationalRow(cells[0].split()[0], cells[input_at], cells[output_at])
    if not found_pricing_table:
        raise FetchError(f"no pricing tables found on {url}")


def detect(cfg: ProviderCfg) -> list[str]:
    tables = extract_tables(fetch_soup(cfg.detector_url))
    if not tables:
        raise FetchError(f"no tables found on {cfg.detector_url}")
    ids: list[str] = []
    seen: set[str] = set()
    for table in tables:
        for row in table[1:]:
            if not row or not row[0]:
                continue
            for token in row[0].split():
                if _ID_RE.fullmatch(token) and token not in _RESOLD_IDS and token not in seen:
                    seen.add(token)
                    ids.append(token)
    if not ids:
        raise FetchError(f"no model ids matched on {cfg.detector_url}")
    return ids


def cell_amounts(cell: str) -> tuple[list[str], bool]:
    """the cell's amount numbers in either currency form the page prints.

    the chat rows print `$0.15` and the audio rows `0.15 USD/million tokens`;
    both scans run on every cell, so a cell carrying both forms reads every
    amount, the same value printed in both included. the second result is
    True when either scan meets an amount-shaped token it cannot read.
    """
    amounts, malformed = amount_scan(cell, before="$")
    suffix, suffix_malformed = amount_scan(cell, after=" USD")
    return amounts + suffix, malformed or suffix_malformed


def _priced(cell: str) -> bool:
    """the cell carries an amount, readable or not: a listed price."""
    amounts, malformed = cell_amounts(cell)
    return bool(amounts) or malformed


def detect_priced(cfg: ProviderCfg) -> list[str]:
    """ids the international pricing page prices: the priced set.

    absence keys on this set. a row counts when both its input and output
    cells carry an amount in either currency form; an amount the scraper
    cannot read still counts (the model is listed, and the scraper raises on
    its cell). a page that prices no id raises, so a page redesign skips the
    absence counters instead of counting every stored id absent.
    """
    ids: list[str] = []
    seen: set[str] = set()
    for row in international_rows(fetch_soup(cfg.scraper_url), cfg.scraper_url):
        if (
            _ID_RE.fullmatch(row.model_id)
            and row.model_id not in _RESOLD_IDS
            and row.model_id not in seen
            and _priced(row.input_cell)
            and _priced(row.output_cell)
        ):
            seen.add(row.model_id)
            ids.append(row.model_id)
    if not ids:
        raise FetchError(f"no priced International rows on {cfg.scraper_url}")
    return ids

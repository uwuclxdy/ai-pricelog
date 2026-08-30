"""scrape Model Studio token pricing from Alibaba's international pricing page.

reads https://www.alibabacloud.com/help/en/model-studio/model-pricing (static
html). pricing tables start with a `Model ID` header cell; the price columns
are the header cells whose label starts with `Input price` / `Output price`.
a multi-column span (the header cell carries a colspan, the omni tables
split input into text/audio/image and output into three modes) expands into
one grid position per sub-column; the first input position is the text-input
rate and the first output position the text-output rate (the base rates).
a sub-header row names the sub-columns and carries no data; it is skipped by
its first cell's prefix. a row matches when the first whitespace token of its
first cell equals the requested id; tiered continuation rows (`256K<Token
<=1M`) carry no id and are skipped. the `Deployment scope` cell must contain
`International`: rows scoped to Chinese mainland / Global / Japan / US are
skipped for now (no entry beats a wrong one; the pipeline retries next run).
price cells like `List price $0.4 Limited-time 20% off` yield the first `$`
float; USD per 1M tokens -> /1e6. the page carries no context window, so the
max_tokens fields stay 0 (the entry builder omits them).
"""

from __future__ import annotations

import re

from bs4 import Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup

_AMOUNT_RE = re.compile(r"\$(\d+(?:\.\d+)?)")

# a sub-header row names the sub-columns of a split span; its first cell
# starts with one of these. data rows start with the model id, which never
# collides with any prefix here.
_SUBHEADER_PREFIXES = ("Non-Thinking mode", "Thinking mode", "Text", "Audio", "Image", "Input:")


def _column(header: list[str], prefix: str) -> int | None:
    for index, cell in enumerate(header):
        if cell.startswith(prefix):
            return index
    return None


def _first_amount(cell: str) -> float | None:
    match = _AMOUNT_RE.search(cell)
    return float(match.group(1)) if match else None


def _grid(header_row: Tag) -> list[str]:
    """one label per grid position: each header cell expands by its colspan."""
    grid: list[str] = []
    for cell in header_row.find_all(["th", "td"]):
        colspan = int(cell.get("colspan", 1) or 1)
        label = cell.get_text(" ", strip=True)
        grid.extend([label] * colspan)
    return grid


def _cells(row: Tag, table: Tag) -> list[Tag]:
    return [cell for cell in row.find_all(["th", "td"]) if cell.find_parent("table") is table]


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    soup = fetch_soup(cfg.scraper_url)
    tables = [table for table in soup.find_all("table") if table.find_parent("table") is None]
    pricing_tables: list[tuple[Tag, list[str]]] = []
    for table in tables:
        rows = table.find_all("tr")
        if not rows:
            continue
        grid = _grid(rows[0])
        if not grid or not grid[0].startswith("Model ID"):
            continue
        pricing_tables.append((table, grid))
    if not pricing_tables:
        raise FetchError(f"no pricing tables found on {cfg.scraper_url}")
    for table, grid in pricing_tables:
        input_idx = _column(grid, "Input price")
        output_idx = _column(grid, "Output price")
        if input_idx is None or output_idx is None:
            continue
        for row in table.find_all("tr")[1:]:
            cells = _cells(row, table)
            if not cells:
                continue
            first = cells[0].get_text(" ", strip=True)
            if first.startswith(_SUBHEADER_PREFIXES):
                continue
            if first.split()[0] != model_id:
                continue
            if len(cells) <= 1 or "International" not in cells[1].get_text(" ", strip=True):
                continue
            if len(cells) <= max(input_idx, output_idx):
                # a short row is not a verdict: a later table may carry the
                # same id with full columns
                continue
            input_amount = _first_amount(cells[input_idx].get_text(" ", strip=True))
            output_amount = _first_amount(cells[output_idx].get_text(" ", strip=True))
            if input_amount is None or output_amount is None:
                # an unpriced row is not a verdict either: a later table may
                # carry the same id with real prices
                continue
            return Pricing(input_amount / 1e6, output_amount / 1e6, mode="chat")
    return None

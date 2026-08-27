"""scrape per-token pricing from the baseten pricing page.

same Model | Input | Cache Input | Output grid as detection; the header
labels are server-rendered on the page itself, and the amounts are USD per
1M tokens -> /1e6. Input -> input_cost, Cache Input -> cache_read, Output
-> output_cost; a cache cell rendering "-" (no cached-input rate for the
model) yields cache_read None. cells render twice (desktop and mobile
duplicates); only the desktop wrapper is read, and a cell with an unexpected
amount count is a page-shape break (FetchError), so a silent misread cannot
ship. rows key by the /library/ slug.

None = the model id is not on the page. FetchError = the fetch failed, the
page has no Model APIs table, or a matched cell carries an unexpected amount
count.
"""

from __future__ import annotations

import re

from bs4 import Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.baseten_page import _desktop, _model_id, _model_rows
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup

_AMOUNT_RE = re.compile(r"\$([\d,]+(?:\.\d+)?)")


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    rows = _model_rows(fetch_soup(cfg.scraper_url), cfg.scraper_url)
    for cells in rows:
        if _model_id(cells[0], cfg.scraper_url) == model_id:
            return _pricing(cells, model_id, cfg.scraper_url)
    return None


def _pricing(cells: list[Tag], model_id: str, url: str) -> Pricing:
    if len(cells) != 4:
        raise FetchError(
            f"malformed pricing row for {model_id} on {url}: {len(cells)} cells, want 4"
        )
    return Pricing(
        input_cost_per_token=_dollars(_desktop(cells[1], url), "input", model_id, url),
        output_cost_per_token=_dollars(_desktop(cells[3], url), "output", model_id, url),
        mode="chat",
        cache_read_cost_per_token=_cache_read(_desktop(cells[2], url), model_id, url),
    )


def _dollars(cell: Tag, column: str, model_id: str, url: str) -> float:
    """per-token dollars of a column cell; an odd amount count -> FetchError."""
    amounts = _AMOUNT_RE.findall(cell.get_text(" ", strip=True))
    if len(amounts) != 1:
        raise FetchError(
            f"malformed {column} cell for {model_id} on {url}: {len(amounts)} amounts, want 1"
        )
    return float(amounts[0].replace(",", "")) / 1e6


def _cache_read(cell: Tag, model_id: str, url: str) -> float | None:
    text = cell.get_text(" ", strip=True)
    amounts = _AMOUNT_RE.findall(text)
    if text == "-" and not amounts:
        return None
    if len(amounts) != 1:
        raise FetchError(
            f"malformed cache input cell for {model_id} on {url}: "
            f"{len(amounts)} amounts, want 1 or '-'"
        )
    # a real $0.00 cell stays 0.0 (free cache reads), never collapses to None
    return float(amounts[0].replace(",", "")) / 1e6

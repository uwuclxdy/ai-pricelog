"""scrape per-token pricing from the sambanova cloud pricing page.

same pricing table as detection: Model | Cached Input Tokens | Input (per 1M
tokens) | Output (per 1M tokens). cached-input cell ->
cache_read_cost_per_token, input -> input_cost_per_token, output ->
output_cost_per_token, USD per 1M -> /1e6. a cached cell reading "N/A"
carries no cached rate -> cache_read_cost_per_token=None. rows match by the
same normalization as detection. a cell whose rate cannot be read is a
page-shape break (FetchError), so a silent misread cannot ship.

None = the model id is not on the page. FetchError = the fetch failed, the
page has no pricing table, or a matched cell carries no readable amount.
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.sambanova_page import _normalize_id, _pricing_table
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup

_AMOUNT_RE = re.compile(r"([\d,]+(?:\.\d+)?) USD")


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    table = _pricing_table(fetch_soup(cfg.scraper_url), cfg.scraper_url)
    for row in table[1:]:
        if not row or _normalize_id(row[0]) != model_id:
            continue
        if len(row) < 4:
            raise FetchError(
                f"malformed pricing row for {model_id} on {cfg.scraper_url}: "
                f"{len(row)} cells, want 4"
            )
        input_cost = _dollars(row[2])
        output_cost = _dollars(row[3])
        if input_cost is None or output_cost is None:
            raise FetchError(
                f"malformed pricing row for {model_id} on {cfg.scraper_url}: "
                f"no per-1M amount in {row[2]!r} / {row[3]!r}"
            )
        return Pricing(
            input_cost_per_token=input_cost / 1e6,
            output_cost_per_token=output_cost / 1e6,
            mode="chat",
            cache_read_cost_per_token=_cached_dollars(row[1], model_id, cfg.scraper_url),
        )
    return None


def _cached_dollars(cell: str, model_id: str, url: str) -> float | None:
    if cell == "N/A":
        return None
    amount = _dollars(cell)
    if amount is None:
        raise FetchError(
            f"malformed pricing row for {model_id} on {url}: unreadable cached-input cell {cell!r}"
        )
    return amount / 1e6


def _dollars(text: str) -> float | None:
    match = _AMOUNT_RE.search(text)
    return float(match.group(1).replace(",", "")) if match else None

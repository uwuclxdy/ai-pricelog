"""scrape together per-token pricing.

same per-token tables as detection. row shape: model | input | cached |
output, the cached amount sitting inside the input cell after the standard
amount ("$0.30 $0.06 (cached)"): first $ amount -> input_cost, second ->
cache_read, both USD per 1M tokens -> /1e6. the page carries no context
windows in these tables, so the max_tokens fields stay 0. a row without dollar
amounts -> None; $0.00 prices as 0.0, since first-party rows may carry it
as a real price.

dedup_keys maps the page spellings to their together api strings
(measured 2026-08-24): the page spells "Llama 3.3 70B" (href
/models/llama-3-3-70b) and "Llama 3 8B Instruct Lite" (href
/models/llama-3-8b-instruct-lite); the api strings are
meta-llama/Llama-3.3-70B-Instruct-Turbo and
meta-llama/Meta-Llama-3-8B-Instruct-Lite. the store holds the page slugs
(verified 2026-08-30), so the mapping is inert today and exists for a
backfill that lands HF-spelled rows. the stored Llama 4 Maverick/Scout
and Mixtral ids have no row on the per-token tables, so nothing maps to
them.
"""

from __future__ import annotations

import re

from bs4 import Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.together_page import (
    _model_name,
    _model_tables,
    _normalize_id,
    _table_rows,
)
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup

_AMOUNT_RE = re.compile(r"\$([\d,]+(?:\.\d+)?)")

_DEDUP_KEYS = {
    "llama-3.3-70b": ("meta-llama/Llama-3.3-70B-Instruct-Turbo",),
    "llama-3-8b-instruct-lite": ("meta-llama/Meta-Llama-3-8B-Instruct-Lite",),
}


def dedup_keys(model_id: str) -> tuple[str, ...]:
    """The stored spelling of a page id, or () when unchanged."""
    return _DEDUP_KEYS.get(_normalize_id(model_id), ())


def _amounts(cell: Tag) -> list[float]:
    text = cell.get_text(" ", strip=True)
    return [float(amount.replace(",", "")) for amount in _AMOUNT_RE.findall(text)]


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    """Pricing for model_id, or None when the page has no usable rates for it."""
    soup = fetch_soup(cfg.scraper_url)
    tables = _model_tables(soup)
    if not tables:
        raise FetchError(f"no per-token model table on {cfg.scraper_url}")
    target = _normalize_id(model_id)
    for table in tables:
        for cells in _table_rows(table):
            if not cells or _normalize_id(_model_name(cells[0])) != target:
                continue
            if len(cells) != 3:
                raise FetchError(f"malformed pricing row for {model_id} on {cfg.scraper_url}")
            input_amounts = _amounts(cells[1])
            output_amounts = _amounts(cells[2])
            if not input_amounts or not output_amounts:
                return None
            input_cost, output_cost = input_amounts[0], output_amounts[0]
            cached = input_amounts[1] if len(input_amounts) > 1 else None
            cache_read = cached / 1e6 if cached is not None and cached > 0 else None
            return Pricing(
                input_cost_per_token=input_cost / 1e6,
                output_cost_per_token=output_cost / 1e6,
                mode="chat",
                cache_read_cost_per_token=cache_read,
            )
    return None

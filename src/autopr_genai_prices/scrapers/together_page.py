"""scrape together per-token pricing.

same per-token tables as detection. row shape: model | input | cached |
output, the cached amount sitting inside the input cell after the standard
amount ("$0.30 $0.06 (cached)"): first $ amount -> input_cost, second ->
cache_read, both USD per 1M tokens -> /1e6. the page carries no context
windows in these tables, so max_tokens stays 0. zero or missing amounts
(free models) -> None.

dedup_keys maps page spellings to the stale HF-style ids the target's
together.yml tracks (measured against that yml, 2026-08-24): the page spells
"Llama 3.3 70B" (href /models/llama-3-3-70b) and "Llama 3 8B Instruct Lite"
(href /models/llama-3-8b-instruct-lite); the yml tracks those endpoints by
their together API strings meta-llama/Llama-3.3-70B-Instruct-Turbo and
meta-llama/Meta-Llama-3-8B-Instruct-Lite. the yml's Llama 4 Maverick/Scout
and Mixtral ids have no row on the per-token tables, so nothing maps to them.
"""

import re

from bs4 import Tag

from autopr_genai_prices.config import ProviderCfg
from autopr_genai_prices.detectors.together_page import (
    _model_name,
    _model_tables,
    _normalize_id,
    _table_rows,
)
from autopr_genai_prices.pricing import Pricing
from autopr_genai_prices.web import FetchError, fetch_soup

_AMOUNT_RE = re.compile(r"\$([\d,]+(?:\.\d+)?)")

_DEDUP_KEYS = {
    "llama-3.3-70b": ("meta-llama/Llama-3.3-70B-Instruct-Turbo",),
    "llama-3-8b-instruct-lite": ("meta-llama/Meta-Llama-3-8B-Instruct-Lite",),
}


def dedup_keys(model_id: str) -> tuple[str, ...]:
    """The target's tracked spelling of a page id, or () when unchanged."""
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
            if input_cost <= 0 or output_cost <= 0:
                return None
            cached = input_amounts[1] if len(input_amounts) > 1 else None
            cache_read = cached / 1e6 if cached is not None and cached > 0 else None
            return Pricing(
                input_cost_per_token=input_cost / 1e6,
                output_cost_per_token=output_cost / 1e6,
                mode="chat",
                max_tokens=0,
                cache_read_cost_per_token=cache_read,
            )
    return None

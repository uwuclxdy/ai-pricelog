"""scrape per-token pricing for perplexity sonar off the agent-api catalog.

same pinned tables as detection. columns Model | Input ($/1M) | Output
($/1M) | Cache read ($/1M) | Service tiers | Docs: Input -> input_cost,
Output -> output_cost, Cache read -> cache_read_cost_per_token, USD per
1M -> /1e6. rows match through the detector's stored-id mapping, so the
page spelling `perplexity/sonar` answers a scrape("sonar") call. Service
tiers holds "-" (no tier distinction), so no peak fields are set; the page
carries no context window -> the max_tokens fields stay 0. other vendors'
tiered long-context cells (`2.00 (<=272k) 4.00 (>272k)`) pass under the
scan un-parsed.

None = the id maps to no watched row, or its input/output cell carries no
number. FetchError = the fetch failed, the page has no pinned table, or
the matched row is shorter than its header.
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.perplexity_page import (
    _FOLDED_CACHE_READ_HEADER,
    _FOLDED_INPUT_HEADER,
    _FOLDED_OUTPUT_HEADER,
    _catalog_tables,
    _stored_id,
)
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, extract_tables, fetch_soup, fold_heading

# the header carries the $; cells are bare per-1M numbers, and a leading $
# stays tolerated
_AMOUNT_PATTERN = re.compile(r"^\$?([\d,]+(?:\.\d+)?)$")


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    tables = _catalog_tables(extract_tables(fetch_soup(cfg.scraper_url)), cfg.scraper_url)
    for table in tables:
        header = table[0]
        row = next(
            (
                candidate
                for candidate in table[1:]
                if candidate and _stored_id(candidate[0]) == model_id
            ),
            None,
        )
        if row is None:
            continue
        if len(row) < len(header):
            raise FetchError(f"malformed pricing row for {model_id} on {cfg.scraper_url}")
        # the columns index through the same folded headers detection pins,
        # so a fold-equal header spelling scrapes instead of crashing on the
        # raw index
        folded = [fold_heading(cell) for cell in header]
        input_cost = _amount(row[folded.index(_FOLDED_INPUT_HEADER)])
        output_cost = _amount(row[folded.index(_FOLDED_OUTPUT_HEADER)])
        if input_cost is None or output_cost is None:
            return None
        cache_read = _amount(row[folded.index(_FOLDED_CACHE_READ_HEADER)])
        return Pricing(
            input_cost_per_token=input_cost / 1e6,
            output_cost_per_token=output_cost / 1e6,
            mode="chat",
            cache_read_cost_per_token=cache_read / 1e6 if cache_read is not None else None,
        )
    return None


def _amount(text: str) -> float | None:
    match = _AMOUNT_PATTERN.fullmatch(text.strip())
    return float(match.group(1).replace(",", "")) if match else None

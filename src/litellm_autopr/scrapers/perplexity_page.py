"""scrape per-token pricing for perplexity sonar models.

same Token Pricing table as detection. columns Model | Input Tokens ($/1M) |
Output Tokens ($/1M) | Citation Tokens ($/1M) | Search Queries ($/1K) |
Reasoning Tokens ($/1M): Input -> input_cost, Output -> output_cost, USD per
1M -> /1e6. citation, search-query and reasoning columns are ignored (not
input/output token rates). the page carries no context window or max output
-> max_tokens stays 0. rows match by the same normalization as detection
(lowercase, whitespace -> "-"), so "Sonar Pro" and "sonar-pro" both match.

None = the model id is not on the page or an input/output cell carries no
dollar amount. FetchError = the fetch failed or the page has no Token Pricing
table.
"""

import re

from litellm_autopr.config import ProviderCfg
from litellm_autopr.detectors.perplexity_page import (
    _INPUT_HEADER,
    _OUTPUT_HEADER,
    _normalize_id,
    _token_pricing_table,
)
from litellm_autopr.pricing import Pricing
from litellm_autopr.web import FetchError, extract_tables, fetch_soup

_PRICE_PATTERN = re.compile(r"\$([\d,]+(?:\.\d+)?)")


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    table = _token_pricing_table(extract_tables(fetch_soup(cfg.scraper_url)), cfg.scraper_url)
    header = table[0]
    row = next(
        (
            candidate
            for candidate in table[1:]
            if candidate and _normalize_id(candidate[0]) == _normalize_id(model_id)
        ),
        None,
    )
    if row is None:
        return None
    if len(row) < len(header):
        raise FetchError(f"malformed pricing row for {model_id} on {cfg.scraper_url}")
    input_cost = _dollars(row[header.index(_INPUT_HEADER)])
    output_cost = _dollars(row[header.index(_OUTPUT_HEADER)])
    if input_cost is None or output_cost is None:
        return None
    return Pricing(
        input_cost_per_token=input_cost / 1e6,
        output_cost_per_token=output_cost / 1e6,
        mode="chat",
    )


def _dollars(text: str) -> float | None:
    match = _PRICE_PATTERN.search(text)
    return float(match.group(1).replace(",", "")) if match else None

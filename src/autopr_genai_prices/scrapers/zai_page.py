"""scrape per-token pricing for z.ai glm models.

same text-models table as detection. columns Model | Input | Cached Input |
Cached Input Storage | Output: Input -> input_cost, Output -> output_cost,
USD per 1M -> /1e6. Cached Input is cache-hit pricing and ignored. cells
without a dollar amount ("Free", "Limited-time Free") -> None (skip until
priced). the page carries no context window -> max_tokens stays 0. rows
match case-insensitively (detection lowercases; the page keeps GLM-4.7-FlashX).

None = the model id is not on the page or a price cell carries no dollar
amount. FetchError = the fetch failed or the page has no text-models table.
"""

import re

from autopr_genai_prices.config import ProviderCfg
from autopr_genai_prices.detectors.zai_page import _text_models_table
from autopr_genai_prices.pricing import Pricing
from autopr_genai_prices.web import FetchError, fetch_soup

_PRICE_PATTERN = re.compile(r"\$(\d+(?:\.\d+)?)")


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    table = _text_models_table(fetch_soup(cfg.scraper_url), cfg.scraper_url)
    header = table[0]
    row = next(
        (
            candidate
            for candidate in table[1:]
            if candidate and candidate[0].strip().lower() == model_id.lower()
        ),
        None,
    )
    if row is None:
        return None
    if len(row) < len(header):
        raise FetchError(f"malformed pricing row for {model_id} on {cfg.scraper_url}")
    input_cost = _dollars(row[header.index("Input")])
    output_cost = _dollars(row[header.index("Output")])
    if input_cost is None or output_cost is None:
        return None
    return Pricing(
        input_cost_per_token=input_cost / 1e6,
        output_cost_per_token=output_cost / 1e6,
        mode="chat",
    )


def _dollars(text: str) -> float | None:
    match = _PRICE_PATTERN.search(text)
    return float(match.group(1)) if match else None

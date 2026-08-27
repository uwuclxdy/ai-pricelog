"""scrape per-token pricing for z.ai glm models.

same per-token tables as detection (Text + Vision Models). columns Model |
Input | Cached Input | Cached Input Storage | Output: Input -> input_cost,
Cached Input -> cache_read_cost_per_token, Output -> output_cost, USD per
1M -> /1e6. cells without a dollar amount ("Free", "Limited-time Free",
"-") -> None (skip until priced). a promo cell renders the struck-through
list price before the charged one (`<del>$0.15</del> $0.075`), so the LAST
dollar amount is the rate in force. the page carries no context window ->
the max_tokens fields stay 0. rows match case-insensitively (detection
lowercases; the page keeps GLM-4.7-FlashX).

a table without the Cached Input column is a page-shape break (FetchError):
silently returning None there reads as a cache-read rate drop in the diff.

None = the model id is not on the page or a price cell carries no dollar
amount. FetchError = the fetch failed, the page has no per-token tables, or
the model's table lacks the Cached Input column.
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.zai_page import _token_model_tables
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup

_PRICE_PATTERN = re.compile(r"\$(\d+(?:\.\d+)?)")


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    tables = _token_model_tables(fetch_soup(cfg.scraper_url), cfg.scraper_url)
    for table in tables:
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
            continue
        if "Cached Input" not in header:
            raise FetchError(
                f"malformed pricing table for {model_id} on {cfg.scraper_url}: "
                "no Cached Input column"
            )
        if len(row) < len(header):
            raise FetchError(f"malformed pricing row for {model_id} on {cfg.scraper_url}")
        input_cost = _dollars(row[header.index("Input")])
        output_cost = _dollars(row[header.index("Output")])
        if input_cost is None or output_cost is None:
            return None
        cache_read = _dollars(row[header.index("Cached Input")])
        return Pricing(
            input_cost_per_token=input_cost / 1e6,
            output_cost_per_token=output_cost / 1e6,
            mode="chat",
            cache_read_cost_per_token=cache_read / 1e6 if cache_read is not None else None,
        )
    return None


def _dollars(text: str) -> float | None:
    matches = _PRICE_PATTERN.findall(text)
    return float(matches[-1]) if matches else None

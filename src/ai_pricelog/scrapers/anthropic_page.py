"""scrape claude per-token pricing from the anthropic pricing markdown twin.

same model table as detection (the header is pinned in the detector).
five rate columns read as USD per 1M tokens: Base Input -> input, 5m
Cache Writes -> the default write tier, 1h Cache Writes -> the 1h write
tier, Cache Hits & Refreshes -> cache read, Output -> output, each /1e6.
every rate cell must carry a dollar amount; an unreadable one is a
page-shape break (FetchError), so a silent misread cannot ship. the page
carries no context window, so the max_tokens fields stay 0 (the entry
builder omits them).

None = the model id is not on the page. FetchError = the fetch failed,
the page carries no model pricing table, or a row is outside the shape.
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.anthropic_page import _slug, check_row, model_table
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_text

_AMOUNT_RE = re.compile(r"\$([\d,]+(?:\.\d+)?)")


def _amount(cell: str, model_id: str, url: str) -> float:
    match = _AMOUNT_RE.search(cell)
    if match is None:
        raise FetchError(f"unreadable rate {cell!r} for {model_id} on {url}")
    return float(match.group(1).replace(",", ""))


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    text = fetch_text(cfg.scraper_url)
    for row in model_table(text, cfg.scraper_url)[2:]:
        check_row(row, cfg.scraper_url)
        if _slug(row[0]) != model_id:
            continue
        return Pricing(
            input_cost_per_token=_amount(row[1], model_id, cfg.scraper_url) / 1e6,
            output_cost_per_token=_amount(row[5], model_id, cfg.scraper_url) / 1e6,
            mode="chat",
            cache_read_cost_per_token=_amount(row[4], model_id, cfg.scraper_url) / 1e6,
            cache_write_cost_per_token=_amount(row[2], model_id, cfg.scraper_url) / 1e6,
            cache_write_1h_cost_per_token=_amount(row[3], model_id, cfg.scraper_url) / 1e6,
        )
    return None

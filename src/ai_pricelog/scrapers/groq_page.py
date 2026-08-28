"""scrape groq per-token pricing from the supported-models markdown twin.

same tables as detection (the header is pinned in the detector). the price
cell reads "$in input $out output" in USD per 1M tokens, so each amount
divides by 1e6. rows key by the detector's parse_id (badge-stripped), so a
priced badge row resolves under its clean id. the context-window cell reads
max_tokens_in and the max-completion cell max_tokens_out; a dash cell
carries none (0, the entry builder omits it). the page has no cached-input
column, so the cache fields stay unset. a matched row with an unreadable
token count is a page-shape break (FetchError), so a silent misread cannot
ship.

None = the model id is not on the page, its row carries no per-token rate
(ContactSales, per-hour, per-character), or both its rates are zero (a
free row carries no price row; skip-and-retry re-candidates it next run,
and the detector still emits the id so a stored model never counts
absent). a zero input beside a priced output scrapes normally (the google
embeddings convention). FetchError = the fetch failed, the page carries no
per-token pricing table, or a row is outside the shape.
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.groq_page import _PRICE_RE, check_row, model_tables, parse_id
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_text

_COUNT_RE = re.compile(r"^[\d,]+$")
_ABSENT_COUNTS = ("-", "\\-")


def _token_count(cell: str, model_id: str, url: str) -> int:
    """a token-count cell; a dash means none (0)."""
    if cell in _ABSENT_COUNTS:
        return 0
    if _COUNT_RE.fullmatch(cell):
        return int(cell.replace(",", ""))
    raise FetchError(f"unreadable token count {cell!r} for {model_id} on {url}")


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    text = fetch_text(cfg.scraper_url)
    for table in model_tables(text, cfg.scraper_url):
        for row in table[2:]:
            check_row(row, cfg.scraper_url)
            match = _PRICE_RE.fullmatch(row[2])
            if match is None:
                continue
            if parse_id(row[0], cfg.scraper_url) != model_id:
                continue
            input_rate, output_rate = float(match.group(1)), float(match.group(2))
            if input_rate == 0 and output_rate == 0:
                return None
            return Pricing(
                input_cost_per_token=input_rate / 1e6,
                output_cost_per_token=output_rate / 1e6,
                mode="chat",
                max_tokens_in=_token_count(row[4], model_id, cfg.scraper_url),
                max_tokens_out=_token_count(row[5], model_id, cfg.scraper_url),
                url=cfg.scraper_url,
            )
    return None

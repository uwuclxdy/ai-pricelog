"""scrape groq per-token pricing from the supported-models markdown twin.

same tables as detection (the header is pinned in the detector). the price
cell reads "$in input $out output" in USD per 1M tokens, so each amount
divides by 1e6. rows key by the detector's parse_id (badge-stripped), so a
priced badge row resolves under its clean id. the context-window cell reads
max_tokens_in and the max-completion cell max_tokens_out; a dash cell
carries none (0, the entry builder omits it). the page has no cached-input
column, so the cache fields stay unset. the matched row's cells are
strict: a price cell outside the known shapes or an unreadable token
count raises (plan #22), never reads as unpriced, so a drifted price
column cannot read as a missing model. rows the match scan passes over
(odd cell counts, malformed model cells) are additive drift detection
already reported.

None = the model id is not on the page, or its row carries no per-token
rate (ContactSales, per-hour, per-character). zero rates scrape as 0.0
(free is a price), so a fully free row lands a 0.0 price row; the
detector still emits the id, so a stored model whose row turns free stays
mapped. FetchError = the fetch failed, the page carries no per-token
pricing table, or the matched row's cells are outside the known shapes.
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.groq_page import _price_amounts, check_row, model_tables, parse_id
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
            try:
                check_row(row, cfg.scraper_url)
                if parse_id(row[0], cfg.scraper_url) != model_id:
                    continue
            except FetchError:
                continue  # additive drift; detect already reported the row
            amounts = _price_amounts(row[2], cfg.scraper_url)
            if amounts is None:
                return None  # the row carries no per-token rate for this model
            input_rate, output_rate = amounts
            return Pricing(
                input_cost_per_token=input_rate / 1e6,
                output_cost_per_token=output_rate / 1e6,
                mode="chat",
                max_tokens_in=_token_count(row[4], model_id, cfg.scraper_url),
                max_tokens_out=_token_count(row[5], model_id, cfg.scraper_url),
                url=cfg.scraper_url,
            )
    return None

"""scrape per-token pricing for avian models.

same pricing grid as detection. per card: Input -> input_cost_per_token,
Output -> output_cost_per_token, Cache -> cache_read_cost_per_token, USD per
1M tokens -> /1e6. a card with no Cache block keeps the cache field None.
context from the card meta -> max_tokens_in ("262K context · ..." -> 262000;
K = 1000, M = 1000000: the page abbreviates and the exact token count is not
shown, the human verifier reconciles it). mode is chat; no peak fields.

None = the model id is not on the page, or its Input/Output cells carry no
amount (a row without usable rates is never a candidate). zero rates scrape
as 0.0 (free is a price). FetchError = the fetch failed, the page has no
pricing grid, or a cell carries an unreadable amount or context count.

no dedup_keys hook: the page models (deepseek, minimax, glm, kimi, mimo
cards) map to none of the stored avian ids (four stale Meta-Llama
entries), so nothing to normalize.
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.avian_page import _cards, _slug
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, amount_scan, fetch_soup, unreadable_rate_error

_CONTEXT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*([KM])\s*context")
_MAX_COUNT_DIGITS = 12

_CONTEXT_FACTORS = {"K": 1_000, "M": 1_000_000}


def _dollars(text: str, model_id: str, url: str) -> float | None:
    amounts, malformed = amount_scan(text, before="$")
    if malformed:
        raise unreadable_rate_error(text, model_id, url)
    return float(amounts[0].replace(",", "")) if amounts else None


def _context_tokens(meta: str) -> int:
    match = _CONTEXT_PATTERN.search(meta)
    if match is None:
        return 0
    count = match.group(1)
    if len(count.replace(".", "")) > _MAX_COUNT_DIGITS:
        raise FetchError(f"unreadable context {meta!r}")
    return int(float(count) * _CONTEXT_FACTORS[match.group(2)])


def _rate(prices: dict[str, str], name: str, model_id: str, url: str) -> float | None:
    """per-token dollars for one price block, or None when unusable."""
    text = prices.get(name)
    if text is None:
        return None
    amount = _dollars(text, model_id, url)
    if amount is None or amount < 0:
        return None
    return amount / 1e6


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    """Pricing for model_id, or None when the page has no usable rates for it."""
    for card in _cards(fetch_soup(cfg.scraper_url), cfg.scraper_url):
        if _slug(card.label) != _slug(model_id):
            continue
        input_cost = _rate(card.prices, "Input", model_id, cfg.scraper_url)
        output_cost = _rate(card.prices, "Output", model_id, cfg.scraper_url)
        if input_cost is None or output_cost is None:
            return None
        return Pricing(
            input_cost_per_token=input_cost,
            output_cost_per_token=output_cost,
            mode="chat",
            max_tokens_in=_context_tokens(card.meta),
            cache_read_cost_per_token=_rate(card.prices, "Cache", model_id, cfg.scraper_url),
        )
    return None

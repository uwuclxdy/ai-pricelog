"""scrape per-token pricing for novita models.

same model cards as detection, matched by the same canonical ids. each card
holds a <dl> of Context / Input / Output rows; amounts sit in span title
attributes as exact dollars per 1M tokens. Input -> input_cost, Output ->
output_cost, /1e6. the input row's ``[data-pricing-key="cache-read"]``
wrapper carries a second titled span for the cache-read rate ->
cache_read_cost_per_token. the context row's span title is the exact token
count -> max_tokens_in (0 when absent or unreadable, the entry builder omits
it). cards with tiered or omnimodal pricing ("-" input, "Tiered pricing"
button) or zero amounts carry no usable rates -> None. mode is chat.

None = the model id is not on the page or its card carries no usable rates.
FetchError = the fetch failed or the page has no model cards.
"""

from __future__ import annotations

import math

from bs4 import Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.novita_page import (
    _card_slug,
    _model_cards,
    _page,
    _page_id,
)
from ai_pricelog.pricing import Pricing

# deepseek dated snapshots: the store holds the base ids
# (deepseek/deepseek-r1, and deepseek_v3 with an underscore), measured
# 2026-08-24.
_DEDUP: dict[str, tuple[str, ...]] = {
    "deepseek/deepseek-r1-0528": ("deepseek/deepseek-r1",),
    "deepseek/deepseek-v3-0324": ("deepseek/deepseek_v3",),
}


def dedup_keys(model_id: str) -> tuple[str, ...]:
    """The stored spelling this page id is tracked under, or () when unchanged."""
    return _DEDUP.get(model_id, ())


def _amount(element: Tag | None) -> float | None:
    """the element's title as a positive dollar amount, or None when unusable."""
    if element is None:
        return None
    title = element.get("title")
    if not title:
        return None
    try:
        value = float(title.strip())
    except ValueError:
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def _cell_amount(cell: Tag | None) -> float | None:
    if cell is None:
        return None
    return _amount(cell.find("span", title=True))


def _cache_amount(cell: Tag | None) -> float | None:
    """the cache-read span amount, or None when the cell has no cache-read rate."""
    if cell is None:
        return None
    wrapper = cell.find(attrs={"data-pricing-key": "cache-read"})
    if wrapper is None:
        return None
    spans = wrapper.find_all("span", title=True)
    if len(spans) < 2:
        return None
    return _amount(spans[-1])


def _dl_cell(card: Tag, key: str) -> Tag | None:
    """the <dd> paired with the <dt> whose text is key, or None without one."""
    for dt in card.find_all("dt"):
        if dt.get_text(strip=True) == key:
            return dt.find_next_sibling("dd")
    return None


def _context_tokens(card: Tag) -> int:
    span = None
    cell = _dl_cell(card, "Context")
    if cell is not None:
        span = cell.find("span", title=True)
    if span is None:
        return 0
    try:
        value = int(span["title"].strip())
    except ValueError:
        return 0
    return value if value > 0 else 0


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    """Pricing for model_id, or None when the page carries no usable rates for it."""
    soup, canonical = _page(cfg.scraper_url)
    cards = _model_cards(soup, cfg.scraper_url)
    card: Tag | None = None
    for candidate in cards:
        slug = _card_slug(candidate)
        if slug is not None and _page_id(slug, canonical) == model_id:
            card = candidate
            break
    if card is None:
        return None
    input_cell = _dl_cell(card, "Input")
    input_amount = _cell_amount(input_cell)
    output_amount = _cell_amount(_dl_cell(card, "Output"))
    if input_amount is None or output_amount is None:
        return None
    cache_amount = _cache_amount(input_cell)
    return Pricing(
        input_cost_per_token=input_amount / 1e6,
        output_cost_per_token=output_amount / 1e6,
        mode="chat",
        max_tokens_in=_context_tokens(card),
        cache_read_cost_per_token=cache_amount / 1e6 if cache_amount is not None else None,
    )

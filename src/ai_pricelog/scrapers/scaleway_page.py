"""scrape scaleway per-token pricing from the model-as-a-service page.

same table as detection (caption and headers pinned in the detector). rates
read "€X / million tokens" in EUR, so each amount divides by 1e6 and
Pricing quotes currency="EUR" (store.build_row converts through the dated
fx table). an input cell carrying a cached amount parses into
cache_read_cost_per_token; "Free" cells are zero rates. rows priced per
audio minute are known unpriced and scrape as None. the matched row's
cells are strict: a cell outside the known shapes raises (plan #22),
never reads as unpriced, so a drifted price column cannot read as a
missing model. rows the match scan passes over (odd cell counts, id
disagreements) are additive drift detection already reported. the page
carries no context/max-tokens column and no peak tier, so those fields
stay unset. mode is chat.

None = the model id is not on the page, or its row carries no per-token
rate. zero rates scrape as 0.0 (free is a price), so a fully free row
lands a 0.0 price row; the detector still emits the id, so a stored model
whose row turns free stays mapped. FetchError = the fetch failed, the page
has no generative-api table, or the matched row's cells are outside the
known shapes.
"""

from __future__ import annotations

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.scaleway_page import (
    _input_amounts,
    _model_table,
    _output_amount,
    _page,
    _row_cells,
    parse_id,
)
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError

# dated slug spellings map to the base id the store holds (the xai
# convention): openrouter carries deepseek/deepseek-v4-flash as a base id,
# and its canonical_slug facts name mistralai/mistral-small-3.2-24b-
# instruct-2506 as the dated variant of
# mistralai/mistral-small-3.2-24b-instruct, measured 2026-08-29. the qwen
# spelling stays out: no source stores a qwen3-235b-a22b-instruct base
# (openrouter holds qwen3-235b-a22b / -2507 / -thinking-2507 only), so the
# page spelling stores directly. pixtral-12b-2409 keeps its suffix too: it
# is mistral's canonical release name, not a snapshot of a pixtral-12b
# base.
_DEDUP: dict[str, tuple[str, ...]] = {
    "deepseek-v4-flash-0731": ("deepseek-v4-flash",),
    "mistral-small-3.2-24b-instruct-2506": ("mistral-small-3.2-24b-instruct",),
}


def dedup_keys(model_id: str) -> tuple[str, ...]:
    """The base slug this dated page spelling is tracked under, or () when unchanged."""
    return _DEDUP.get(model_id, ())


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    soup = _page(cfg.scraper_url)
    table = _model_table(soup, cfg.scraper_url)
    for row in table.find("tbody").find_all("tr", recursive=False):
        try:
            cells = _row_cells(row, cfg.scraper_url)
            if parse_id(cells[0], cells[4], cfg.scraper_url) != model_id:
                continue
        except FetchError:
            continue  # additive drift; detect already reported the row
        amounts = _input_amounts(cells[2], cfg.scraper_url)
        if amounts is None:
            return None  # per audio minute, a known unpriced form
        input_rate, cache_rate = amounts
        output_rate = _output_amount(cells[3], cfg.scraper_url)
        return Pricing(
            input_cost_per_token=input_rate / 1e6,
            output_cost_per_token=output_rate / 1e6,
            mode="chat",
            cache_read_cost_per_token=cache_rate / 1e6 if cache_rate is not None else None,
            currency="EUR",
        )
    return None

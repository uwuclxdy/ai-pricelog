"""scrape databricks foundation-model-serving pricing from the pricing page.

same table as detection (headers pinned in the detector), rows matched by
the detector's display-name ids. rates read DBU per 1M tokens, so each
amount divides by 1e6 and Pricing quotes currency="DBU"
(store.build_row converts through the provider's configured dbu->usd
rate). the cache-read cell parses into cache_read_cost_per_token when it
carries a rate; "n/a" output reads as a zero output rate (embedding rows
bill input only). a cell outside the known shapes reads as unpriced
(input) or zero (output) here (the detector gates the run loudly
instead). the page carries no context/max-tokens column and no peak tier,
so those fields stay unset. mode is chat.

None = the model id is not on the page, its row carries no per-token
input rate, or both its rates are zero (a free row carries no price row;
skip-and-retry re-candidates it next run, and the detector still emits the
id so a stored model never counts absent). FetchError = the fetch failed,
the page has no dbu table, a row is outside the row shape, or a priced
row's display name is unmapped.
"""

from __future__ import annotations

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.databricks_page import (
    _model_table,
    _page,
    _row_cells,
    _try_rate,
    parse_id,
)
from ai_pricelog.pricing import Pricing

# dated display spellings map to the base id (the xai convention):
# openrouter holds both the base ids (deepseek/deepseek-v4-pro,
# deepseek/deepseek-v4-flash) and the dated variants, measured against the
# stored openrouter id set 2026-08-29. the "(Priority)" tiers are tiers,
# not snapshots, and dedup to nothing.
_DEDUP: dict[str, tuple[str, ...]] = {
    "deepseek-v4-pro-0813": ("deepseek-v4-pro",),
    "deepseek-v4-flash-0731": ("deepseek-v4-flash",),
}


def dedup_keys(model_id: str) -> tuple[str, ...]:
    """The base id this dated page spelling is tracked under, or () when unchanged."""
    return _DEDUP.get(model_id, ())


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    soup = _page(cfg.scraper_url)
    table = _model_table(soup, cfg.scraper_url)
    for row in table.find("tbody").find_all("tr", recursive=False):
        cells = _row_cells(row, cfg.scraper_url)
        input_rate = _try_rate(cells[1])
        if input_rate is None:
            continue
        output_rate = _try_rate(cells[2])
        if output_rate is None:
            output_rate = 0.0  # n/a output: embedding rows bill input only
        cache_rate = _try_rate(cells[3])
        if parse_id(cells[0], cfg.scraper_url) != model_id:
            continue
        if input_rate == 0 and output_rate == 0:
            return None
        return Pricing(
            input_cost_per_token=input_rate / 1e6,
            output_cost_per_token=output_rate / 1e6,
            mode="chat",
            cache_read_cost_per_token=cache_rate / 1e6 if cache_rate is not None else None,
            currency="DBU",
        )
    return None

"""scrape databricks foundation-model-serving pricing from the pricing page.

same tables as detection (headers pinned in the detector), rows matched by
the detector's display-name ids: a base id's row lives in the standard
table, its "-priority" twin in the priority table, and a merged display
row ("GLM-5.2, 5.3") carries one rate pair for every id it maps to. rates
read DBU per 1M tokens, so each amount divides by 1e6 and Pricing quotes
currency="DBU" (store.build_row converts through the provider's configured
dbu->usd rate). the cache-read cell parses into cache_read_cost_per_token
when it carries a rate; "-" output reads as a zero output rate (embedding
rows bill input only). the matched row's cells are strict: an unknown
rate-cell shape raises (plan #22), never reads as unpriced. rows the match
scan passes over (odd cell counts, unmapped names) are additive drift
detection already reported. the page carries no context/max-tokens column
and no peak tier, so those fields stay unset. mode is chat.

None = the model id is not on the page, or its row carries no per-token
input rate. zero rates scrape as 0.0 (free is a price), so a fully free
row lands a 0.0 price row; the detector still emits the id, so a stored
model whose row turns free stays mapped. FetchError = the fetch failed,
the page has no per-token table, or the matched row's rate cells are
outside the known shapes.
"""

from __future__ import annotations

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.databricks_page import (
    _is_priority_table,
    _model_tables,
    _page,
    _rate,
    _row_cells,
    parse_id,
)
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError

# the page's display names dropped the deepseek snapshot dates in the
# 2026-09-05 restructure, while the store still tracks the dated spellings
# from the era page: a PAGE spelling maps to the STORED spelling its rows
# live under (the pipeline calls dedup_keys with page ids only), so the
# era track continues instead of forking under the base spelling. the
# "-priority" tiers are tiers, not snapshots, and dedup to nothing.
_DEDUP: dict[str, tuple[str, ...]] = {
    "deepseek-v4-pro": ("deepseek-v4-pro-0813",),
    "deepseek-v4-flash": ("deepseek-v4-flash-0731",),
}


def dedup_keys(model_id: str) -> tuple[str, ...]:
    """The stored spellings this page id is tracked under, or () when unchanged."""
    return _DEDUP.get(model_id, ())


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    soup = _page(cfg.scraper_url)
    for table in _model_tables(soup, cfg.scraper_url):
        priority = _is_priority_table(table, cfg.scraper_url)
        for row in table.find("tbody").find_all("tr", recursive=False):
            try:
                cells = _row_cells(row, cfg.scraper_url)
                if model_id not in parse_id(cells[0], cfg.scraper_url, priority=priority):
                    continue
            except FetchError:
                continue  # additive drift; detect already reported the row
            input_rate = _rate(cells[1], cfg.scraper_url)
            if input_rate is None:
                return None  # the row carries no per-token input rate
            output_rate = _rate(cells[2], cfg.scraper_url)
            if output_rate is None:
                output_rate = 0.0  # "-" output: embedding rows bill input only
            cache_rate = _rate(cells[3], cfg.scraper_url)
            return Pricing(
                input_cost_per_token=input_rate / 1e6,
                output_cost_per_token=output_rate / 1e6,
                mode="chat",
                cache_read_cost_per_token=cache_rate / 1e6 if cache_rate is not None else None,
                currency="DBU",
            )
    return None

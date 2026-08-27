"""scrape per-token pricing from the ibm watsonx pricing page.

same per-model components as detection. the pay-as-you-go cell holds the
rate text: "USD <in> per 1M tokens input USD <out> per 1M tokens output"
(input then output), or one bare "USD <x>" amount, the watsonx convention
where a single rate bills both directions (stored input=output=x). amounts
are USD per 1M tokens -> /1e6. "Not available" and empty cells carry no
rate -> None. more than two amounts in a matched cell is a page-shape break
(FetchError), so a silent misread cannot ship.

None = the model id is not on the page or its row carries no amount.
FetchError = the fetch failed, the page has no per-model token table, or a
matched row or cell carries an unexpected shape.
"""

from __future__ import annotations

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.watsonx_page import (
    _AMOUNT_RE,
    _comp_rows,
    _normalize_id,
    _per_model_comps,
)
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    soup = fetch_soup(cfg.scraper_url)
    comps = _per_model_comps(soup, cfg.scraper_url)
    target = _normalize_id(model_id)
    for comp, headers, price_col in comps:
        for cells in _comp_rows(comp):
            if not cells:
                continue
            if len(cells) < len(headers):
                raise FetchError(f"malformed pricing row on {cfg.scraper_url}")
            if _normalize_id(cells[0]) != target:
                continue
            amounts = _AMOUNT_RE.findall(cells[price_col])
            if not amounts:
                return None
            if len(amounts) > 2:
                raise FetchError(
                    f"malformed pricing cell for {model_id} on {cfg.scraper_url}: "
                    f"{len(amounts)} amounts, want 1 or 2"
                )
            input_cost = float(amounts[0].replace(",", ""))
            output_cost = float(amounts[-1].replace(",", ""))
            return Pricing(
                input_cost_per_token=input_cost / 1e6,
                output_cost_per_token=output_cost / 1e6,
                mode="chat",
            )
    return None

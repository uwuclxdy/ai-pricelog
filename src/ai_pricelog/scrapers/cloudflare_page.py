"""scrape per-token pricing from the cloudflare workers ai pricing page.

the LLM and other pricing tables price each model per 1M tokens: the Price
in Tokens cell carries one line per rate - "$X per M input tokens", "$X per
M cached input tokens" on some models, "$X per M output tokens" - and each
line's label decides its slot, so the cached line's position between input
and output carries no weight. the Price in Neurons cell is an equivalent
unit the index has no slot for and is dropped (known gap). ids key by the
page spelling of the api id. a matched cell with an unknown line, a
duplicate label, or no input/output pair is a page-shape break
(FetchError), so a silent misread cannot ship.

None = the model id is not on the page. FetchError = the fetch failed, the
page has no pricing table for a section, or a matched pricing cell has an
unexpected shape.
"""

from __future__ import annotations

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.cloudflare_page import (
    _model_id,
    _section_tables,
    _table_rows,
    _token_rates,
)
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    tables = _section_tables(fetch_soup(cfg.scraper_url), cfg.scraper_url)
    target = model_id.lower()
    for table in tables:
        for cells in _table_rows(table):
            if not cells or _model_id(cells[0]) != target:
                continue
            if len(cells) < 2:
                raise FetchError(
                    f"malformed row for {model_id} on {cfg.scraper_url}: no token cell"
                )
            input_cost, output_cost, cache_read = _token_rates(cells[1], model_id, cfg.scraper_url)
            return Pricing(
                input_cost / 1e6,
                output_cost / 1e6,
                mode="chat",
                cache_read_cost_per_token=cache_read / 1e6 if cache_read is not None else None,
            )
    return None

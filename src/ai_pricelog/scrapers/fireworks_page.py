"""scrape per-token serverless pricing from the fireworks docs page.

the Model | Standard | Priority table prices each model per 1M tokens, one
cell per tier, three dollar amounts per cell in input / cached-input /
output order. the row stores the Standard tier, the default serving path;
the Priority column is a tier the index has no slot for and is dropped
(known gap in docs/domain-knowledge.md). a "—" cell (fast skus have no
priority tier) carries no amounts. rows key by the normalized page spelling
of the sku. a cell with a different amount count is a page-shape break
(FetchError), so a silent misread cannot ship.

None = the model id is not on the page. FetchError = the fetch failed, the
page has no serverless table, or a matched cell carries an unexpected
amount count.
"""

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.fireworks_page import _normalize_id, _serverless_table
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup

_AMOUNT_RE = re.compile(r"\$(\d+(?:\.\d+)?)")


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    table = _serverless_table(fetch_soup(cfg.scraper_url), cfg.scraper_url)
    for row in table[1:]:
        if not row or _normalize_id(row[0]) != model_id:
            continue
        amounts = _AMOUNT_RE.findall(row[1])
        if len(amounts) != 3:
            raise FetchError(
                f"malformed pricing cell for {model_id} on {cfg.scraper_url}: "
                f"{len(amounts)} amounts, want 3"
            )
        input_cost, cache_read, output_cost = (float(amount) for amount in amounts)
        return Pricing(
            input_cost / 1e6,
            output_cost / 1e6,
            mode="chat",
            cache_read_cost_per_token=cache_read / 1e6,
        )
    return None

"""scrape per-token chat pricing from the ai21 pricing page.

each Foundation Models card carries its rates in the footer as two lines:
"$0.2 / 1M input tokens" and "$0.4 / 1M output tokens". the two amounts
parse into input/output per 1M tokens; the page carries no cached-read or
context rates, so cache_read_cost_per_token and max_tokens stay unset. a
matched card whose footer does not hold exactly one input and one output
rate is a page-shape break (FetchError), so a silent misread cannot ship.

None = the model id is not on the page or a needed price is missing.
FetchError = the fetch failed, the page has no model cards, or a matched
card carries a malformed footer.
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.ai21_page import _model_cards, _slug
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup

_PRICE_LINE = re.compile(
    r"\$(\d+(?:\.\d+)?) / 1M input tokens\s*\$(\d+(?:\.\d+)?) / 1M output tokens"
)


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    soup = fetch_soup(cfg.scraper_url)
    for title, footer in _model_cards(soup):
        if _slug(title, cfg.scraper_url) != model_id:
            continue
        matches = _PRICE_LINE.findall(footer)
        if len(matches) != 1:
            raise FetchError(
                f"malformed price line for {model_id} on {cfg.scraper_url}: "
                f"{len(matches)} price lines, want 1"
            )
        input_cost, output_cost = (float(value) for value in matches[0])
        return Pricing(input_cost / 1e6, output_cost / 1e6, mode="chat")
    return None

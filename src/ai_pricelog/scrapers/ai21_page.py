"""scrape per-token chat pricing from the ai21 pricing page.

each Foundation Models card carries its rates in the footer as two lines:
"$0.2 / 1M input tokens" and "$0.4 / 1M output tokens". the two amounts
parse into input/output per 1M tokens; the page carries no cached-read or
context rates, so cache_read_cost_per_token and max_tokens stay unset. the
matched card's footer must hold exactly one input and one output rate; a
malformed one is a page-shape break (FetchError), so a silent misread
cannot ship. cards the match scan passes over (no title, no footer, an
out-of-charset title) are additive drift detection already reported.

None = the model id is not on the page or a needed price is missing.
FetchError = the fetch failed or the matched card carries a malformed
footer.
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.ai21_page import _UA, _card_parts, _slug
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup

_PRICE_LINE = re.compile(
    r"\$(\d+(?:\.\d+)?) / 1M input tokens\s*\$(\d+(?:\.\d+)?) / 1M output tokens"
)


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    soup = fetch_soup(cfg.scraper_url, headers=_UA)
    for title, footer in _card_parts(soup):
        if title is None:
            continue
        title_text = title.get_text(" ", strip=True)
        try:
            if _slug(title_text, cfg.scraper_url) != model_id:
                continue
        except FetchError:
            continue  # additive drift; detect already reported the card
        if footer is None:
            raise FetchError(f"model card {model_id} without a footer on {cfg.scraper_url}")
        matches = _PRICE_LINE.findall(footer.get_text(" ", strip=True))
        if len(matches) != 1:
            raise FetchError(
                f"malformed price line for {model_id} on {cfg.scraper_url}: "
                f"{len(matches)} price lines, want 1"
            )
        input_cost, output_cost = (float(value) for value in matches[0])
        return Pricing(input_cost / 1e6, output_cost / 1e6, mode="chat")
    return None

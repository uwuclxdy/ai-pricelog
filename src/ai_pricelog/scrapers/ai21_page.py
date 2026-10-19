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
from ai_pricelog.web import FetchError, amount_scan, fetch_soup, unreadable_rate_error

# the input and output amounts read from their own spans, so an amount
# elsewhere in the footer cannot shift the rates
_PRICE_LINE = re.compile(r"(\$\S+) / 1M input tokens\s*(\$\S+) / 1M output tokens")


def _price_amount(span: str, footer_text: str, model_id: str, url: str) -> float:
    """one price-line amount through the shared grammar; not exactly one
    readable amount is a page-shape break naming the whole footer (a
    malformed span already failed the footer's own scan in scrape)."""
    amounts, _ = amount_scan(span, before="$")
    if len(amounts) != 1:
        raise unreadable_rate_error(footer_text, model_id, url)
    return float(amounts[0].replace(",", ""))


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
        footer_text = footer.get_text(" ", strip=True)
        _, malformed = amount_scan(footer_text, before="$")
        if malformed:
            raise unreadable_rate_error(footer_text, model_id, cfg.scraper_url)
        pairs = _PRICE_LINE.findall(footer_text)
        if len(pairs) != 1:
            raise FetchError(
                f"malformed price line for {model_id} on {cfg.scraper_url}: "
                f"{len(pairs)} price lines, want 1"
            )
        input_span, output_span = pairs[0]
        input_cost = _price_amount(input_span, footer_text, model_id, cfg.scraper_url)
        output_cost = _price_amount(output_span, footer_text, model_id, cfg.scraper_url)
        return Pricing(input_cost / 1e6, output_cost / 1e6, mode="chat")
    return None

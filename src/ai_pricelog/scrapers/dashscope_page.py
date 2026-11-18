"""scrape Model Studio token pricing from Alibaba's international pricing page.

reads https://www.alibabacloud.com/help/en/model-studio/model-pricing (static
html). the detector's `international_rows` walks the pricing tables (header
labels, split spans, row alignment, the International scope); the scraper
prices the first such row whose id equals the requested one and whose cells
both read an amount. an unpriced row is not a verdict: a later table may
carry the same id with real prices, and a page with no such row returns None
(no entry beats a wrong one; the pipeline retries next run).

a price cell records the rate in force. a plain cell yields its first
amount (`$`, or the `USD` suffix the audio rows print). a promo cell
carries an `NN% off` marker: when it prints two amounts and the list label
(`Original`, `List price`) attaches to one, the other is the charged rate
(the zai and minimax precedent); a second amount with no list label, or one
on another priced axis (cache, peak), names no single charged rate and
raises; when it prints only the labelled list amount (`Original$0.4 (20% off
for a limited time)`, `List price $0.4 Limited-time 20% off`), the rate is
list x (100 - NN) / 100. the percent runs to the whole token, so `1000%` and
`1,000%` are past the cap; a percent split across elements (`1 000%`) is never
read as its trailing fragment, and a percent glued to its amount (`$0.420%`)
is never read as the percent. a list-labelled amount with no discount marker
names no charged rate; a promo cell naming two different discounts
(`Original$0.276 (limited-time 60% off for off-peak usage) 20% off during
peak hours`), two different list amounts, a list label that places no
amount, or an amount the grammar cannot read is a page-shape break
(FetchError). USD per 1M tokens -> /1e6. the page carries no context
window, so the max_tokens fields stay 0 (the entry builder omits them).
"""

from __future__ import annotations

import re
from decimal import Decimal

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.dashscope_page import cell_amounts, international_rows
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup, unreadable_rate_error

_DISCOUNT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*%\s*off", re.IGNORECASE)
_LIST_LABEL_RE = re.compile(r"Original|List price", re.IGNORECASE)
_LIST_AMOUNT_RE = re.compile(
    r"(?:Original|List price)\s*\$([0-9][0-9,]*(?:\.[0-9]+)?)", re.IGNORECASE
)
_LIST_SUFFIX_RE = re.compile(
    r"(?:Original|List price)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*USD", re.IGNORECASE
)
# a price cell naming another priced axis beside the marker leaves which
# amount the discount applies to unknown
_SECOND_AXIS_RE = re.compile(r"\b(?:Cached?|Peak|Off-peak)\b", re.IGNORECASE)
# the cell text joins element boundaries with a space, so a percent token
# split across elements sits right behind a whitespace-separated number
_SPLIT_DIGITS_RE = re.compile(r"(?<![\d,.])[\d,.]+\s+$")
# a `$`-led decimal amount directly before the percent is the complete list
# amount, not the leading half of a split number
_CURRENCY_AMOUNT_RE = re.compile(r"\$[\d,]*\.\d+\s+$")


def _split_percent(cell: str) -> bool:
    """whether an `NN% off` token continues a whitespace-separated number."""
    for match in _DISCOUNT_RE.finditer(cell):
        prefix = cell[: match.start(1)]
        if _SPLIT_DIGITS_RE.search(prefix) and not _CURRENCY_AMOUNT_RE.search(prefix):
            return True
    return False


def _glued_percent(cell: str) -> bool:
    """whether an `NN% off` token starts inside an amount (`$0.420% off`)."""
    return any(
        match.start(1) > 0 and cell[match.start(1) - 1] in "$.0123456789"
        for match in _DISCOUNT_RE.finditer(cell)
    )


def _rate_in_force(cell: str, model_id: str, url: str) -> float | None:
    """the cell's charged per-1M amount; None when the cell holds no amount."""
    amounts, malformed = cell_amounts(cell)
    if malformed:
        raise unreadable_rate_error(cell, model_id, url)
    if not amounts:
        return None
    values = [Decimal(amount.replace(",", "")) for amount in amounts]
    list_values = [
        Decimal(text.replace(",", ""))
        for text in _LIST_AMOUNT_RE.findall(cell) + _LIST_SUFFIX_RE.findall(cell)
    ]
    labelled = _LIST_LABEL_RE.search(cell) is not None
    discounts = set(_DISCOUNT_RE.findall(cell))
    if not discounts:
        # the label says the amount is not what the page charges, and no
        # marker gives the discount
        if labelled:
            raise unreadable_rate_error(cell, model_id, url)
        return float(values[0])
    if _split_percent(cell) or _glued_percent(cell):
        raise unreadable_rate_error(cell, model_id, url)
    if len(discounts) > 1:
        raise FetchError(f"promo cell {cell!r} names more than one rate for {model_id} on {url}")
    if len(values) == 2:
        if not list_values:
            # no list label or a label that places no amount: neither amount
            # is known to be the charged one
            raise unreadable_rate_error(cell, model_id, url)
        if len(set(list_values)) > 1 or list_values[0] not in values:
            raise unreadable_rate_error(cell, model_id, url)
        others = [value for value in values if value != list_values[0]]
        if not others or _SECOND_AXIS_RE.search(cell):
            raise unreadable_rate_error(cell, model_id, url)
        return float(others[-1])
    percent = Decimal(discounts.pop().replace(",", ""))
    if len(values) == 1 and list_values == values and percent <= 100:
        return float(values[0] * (100 - percent) / 100)
    raise unreadable_rate_error(cell, model_id, url)


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    for row in international_rows(fetch_soup(cfg.scraper_url), cfg.scraper_url):
        if row.model_id != model_id:
            continue
        input_amount = _rate_in_force(row.input_cell, model_id, cfg.scraper_url)
        output_amount = _rate_in_force(row.output_cell, model_id, cfg.scraper_url)
        if input_amount is None or output_amount is None:
            continue
        return Pricing(input_amount / 1e6, output_amount / 1e6, mode="chat")
    return None

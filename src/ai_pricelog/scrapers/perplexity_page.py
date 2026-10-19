"""scrape per-token pricing for perplexity sonar off the agent-api catalog.

same pinned tables as detection. columns Model | Input ($/1M) | Output
($/1M) | Cache read ($/1M) | Service tiers | Docs: Input -> input_cost,
Output -> output_cost, Cache read -> cache_read_cost_per_token, USD per
1M -> /1e6. rows match through the detector's stored-id mapping, so the
page spelling `perplexity/sonar` answers a scrape("sonar") call. Service
tiers holds "-" (no tier distinction), so no peak fields are set; the page
carries no context window -> the max_tokens fields stay 0. other vendors'
tiered long-context cells (`2.00 (<=272k) 4.00 (>272k)`) pass under the
scan un-parsed.

the web-search tool page (docs/agent-api/tools/web-search) supplies the
per-request web_search fee: the standard rate in the "instead of $X"
sentence, per the sentence's N invocations (1,000 on the live page), never
the $1.00 fast tier; a missing or unreadable fee, or an unrecognized unit,
is a scrape failure.

None = the id maps to no watched row, or its input/output cell carries no
number. FetchError = the fetch failed, the page has no pinned table, the
matched row is shorter than its header, a cell carries an unreadable
amount, or the web_search fee or its unit is missing or unreadable.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.perplexity_page import (
    _FOLDED_CACHE_READ_HEADER,
    _FOLDED_INPUT_HEADER,
    _FOLDED_OUTPUT_HEADER,
    _catalog_tables,
    _stored_id,
)
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import (
    FetchError,
    amount_scan,
    extract_tables,
    fetch_soup,
    fold_heading,
    unreadable_rate_error,
)

_WEB_SEARCH_URL = "https://docs.perplexity.ai/docs/agent-api/tools/web-search"


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    tables = _catalog_tables(extract_tables(fetch_soup(cfg.scraper_url)), cfg.scraper_url)
    for table in tables:
        header = table[0]
        row = next(
            (
                candidate
                for candidate in table[1:]
                if candidate and _stored_id(candidate[0]) == model_id
            ),
            None,
        )
        if row is None:
            continue
        if len(row) < len(header):
            raise FetchError(f"malformed pricing row for {model_id} on {cfg.scraper_url}")
        # the columns index through the same folded headers detection pins,
        # so a fold-equal header spelling scrapes instead of crashing on the
        # raw index
        folded = [fold_heading(cell) for cell in header]
        input_cost = _amount(row[folded.index(_FOLDED_INPUT_HEADER)], model_id, cfg.scraper_url)
        output_cost = _amount(row[folded.index(_FOLDED_OUTPUT_HEADER)], model_id, cfg.scraper_url)
        if input_cost is None or output_cost is None:
            return None
        cache_read = _amount(
            row[folded.index(_FOLDED_CACHE_READ_HEADER)], model_id, cfg.scraper_url
        )
        return Pricing(
            input_cost_per_token=input_cost / 1e6,
            output_cost_per_token=output_cost / 1e6,
            mode="chat",
            cache_read_cost_per_token=cache_read / 1e6 if cache_read is not None else None,
            fees={"web_search": _web_search_fee(fetch_soup(_WEB_SEARCH_URL), _WEB_SEARCH_URL)},
        )
    return None


def _amount(cell: str, model_id: str, url: str) -> float | None:
    """the cell's per-1M amount; the header carries the $ and cells are bare
    numbers, but a leading "$" stays tolerated. only a cell that is exactly
    one amount returns a value."""
    amounts, malformed = amount_scan(cell)
    if malformed:
        raise unreadable_rate_error(cell, model_id, url)
    if len(amounts) != 1:
        return None
    amount = amounts[0]
    if cell.strip() not in (amount, "$" + amount):
        return None
    return float(amount.replace(",", ""))


_INSTEAD_OF_RE = re.compile(r"instead of\s*\$", re.IGNORECASE)


def _web_search_fee(soup: BeautifulSoup, url: str) -> float:
    """the standard web_search fee from the page's "instead of $X" sentence.

    the standard rate is the amount after "instead of", never the $1.00 fast
    tier named before it. USD per the standard clause's "per N invocations"
    unit, falling back to the shared sentence unit (per 1,000 -> /1000 per
    request on the live page).
    """
    node = soup.find(string=_INSTEAD_OF_RE)
    if node is None:
        raise FetchError(f"web_search standard fee missing on {url}")
    text = str(node)
    marker = _INSTEAD_OF_RE.search(text)
    clause = text[marker.start() :]
    amounts, malformed = amount_scan(clause, before="$")
    if malformed or not amounts:
        raise unreadable_rate_error(clause, "web_search", url)
    divisor = _web_search_divisor(clause, text, url)
    return float(amounts[0].replace(",", "")) / divisor


_WEB_SEARCH_UNIT_RE = re.compile(r"\bper\s+([\d,.]*)\s+invocations\b", re.IGNORECASE)


def _web_search_divisor(clause: str, sentence: str, url: str) -> float:
    """the per-N invocations divisor the standard clause states, else the sentence's.

    the standard clause's own unit wins; a clause without one falls back to
    the shared sentence unit. a sentence carrying no "per <N> invocations"
    clause anywhere, or whose N the amount grammar cannot read, is a shape
    break.
    """
    match = _WEB_SEARCH_UNIT_RE.search(clause) or _WEB_SEARCH_UNIT_RE.search(sentence)
    if match is None:
        raise FetchError(f"unrecognized web_search unit in {sentence!r} on {url}")
    amounts, malformed = amount_scan(match.group(1))
    if malformed or len(amounts) != 1:
        raise FetchError(f"unrecognized web_search unit in {sentence!r} on {url}")
    return float(amounts[0].replace(",", ""))

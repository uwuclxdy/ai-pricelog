"""scrape per-token pricing from the publicai models page.

same models table as detection: Model ID | Context Length | Pricing |
Country of Origin. the Pricing cell prices input / output per 1M tokens
("$0.10 / $0.20 per 1M tokens"), USD per 1M -> /1e6. max_tokens_in comes
from the Context Length cell ("262K" -> 262000; the page spells decimal-K
labels). rows key by the page Model ID case-folded (the ids already carry
org/model slugs, so case is the only folding). the page carries no
cache-read or peak rates. a row too short to carry a model id is additive
drift: detection already skips it, so the match scan tolerates it
(plan #22); the matched row's pricing and context cells stay strict, so a
drifted cell cannot read as a missing or wrong rate.

None = the model id is not on the page, or a drifted short row carries no
id and reads as absent. FetchError = the fetch failed, the page has no
models table, or a matched row's pricing or context cell does not parse.
"""

from __future__ import annotations

import re

from bs4 import Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.publicai_page import (
    _model_id,
    _models_table,
    _normalize_id,
    _pricing_amounts,
    _table_rows,
)
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup

_CONTEXT_RE = re.compile(r"^(\d+)K$", re.IGNORECASE)


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    table = _models_table(fetch_soup(cfg.scraper_url), cfg.scraper_url)
    target = _normalize_id(model_id)
    for cells in _table_rows(table):
        if not cells:
            continue
        if len(cells) < 3:
            continue  # additive drift; detection already skips the short row
        if _model_id(cells) != target:
            continue
        amounts = _pricing_amounts(cells[2])
        if len(amounts) != 2:
            raise FetchError(
                f"malformed pricing cell for {model_id} on {cfg.scraper_url}: "
                f"{len(amounts)} amounts, want 2"
            )
        input_cost, output_cost = (float(amount.replace(",", "")) for amount in amounts)
        return Pricing(
            input_cost / 1e6,
            output_cost / 1e6,
            mode="chat",
            max_tokens_in=_context_tokens(cells[1], model_id, cfg.scraper_url),
        )
    return None


def _context_tokens(cell: Tag, model_id: str, url: str) -> int:
    text = cell.get_text(" ", strip=True)
    match = _CONTEXT_RE.fullmatch(text)
    if match is None:
        raise FetchError(f"malformed context cell for {model_id} on {url}: {text!r}")
    return int(match.group(1)) * 1000

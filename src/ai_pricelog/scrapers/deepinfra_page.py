"""scrape per-token chat pricing from the deepinfra pricing page.

the per-token tables (Model | Context | $ per 1M input tokens | $ per 1M
output tokens | Actions) price each model per 1M tokens. the input cell
holds one amount, or two as "$base / $cached cached" when the model bills
cache reads; the output cell holds exactly one. the context cell ("1024k")
-> max_tokens_in, k counted as 1024 (the repo convention). rows key by the
model-cell link's last path segment, lowercased, the detector's id. a
matched cell with an unexpected amount count, or an unreadable context, is
a page-shape break (FetchError), so a silent misread cannot ship. rows the
match scan passes over with a link-less or out-of-charset model cell are
additive drift detection already reported.

None = the model id is not on the page. FetchError = the fetch failed, the
page has no per-token model table, or a matched cell carries an unexpected
shape.
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.deepinfra_page import _model_tables, _row_id, _table_rows
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup

_AMOUNT_RE = re.compile(r"\$(\d+(?:\.\d+)?)")
_CONTEXT_RE = re.compile(r"^(\d+)k$")


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    soup = fetch_soup(cfg.scraper_url)
    tables = _model_tables(soup)
    if not tables:
        raise FetchError(f"no per-token model table on {cfg.scraper_url}")
    for table in tables:
        for row in _table_rows(table):
            if not row:
                continue
            try:
                if _row_id(row[0], cfg.scraper_url) != model_id:
                    continue
            except FetchError:
                continue  # additive drift; detect already reported the row
            if len(row) < 4:
                raise FetchError(f"malformed row for {model_id} on {cfg.scraper_url}")
            input_amounts = _AMOUNT_RE.findall(row[2].get_text(" ", strip=True))
            output_amounts = _AMOUNT_RE.findall(row[3].get_text(" ", strip=True))
            if len(input_amounts) == 2:
                input_cost, cache_read = (float(amount) for amount in input_amounts)
            elif len(input_amounts) == 1:
                input_cost, cache_read = float(input_amounts[0]), None
            else:
                raise FetchError(
                    f"malformed input cell for {model_id} on {cfg.scraper_url}: "
                    f"{len(input_amounts)} amounts, want 1 or 2"
                )
            if len(output_amounts) != 1:
                raise FetchError(
                    f"malformed output cell for {model_id} on {cfg.scraper_url}: "
                    f"{len(output_amounts)} amounts, want 1"
                )
            context = row[1].get_text(" ", strip=True)
            context_match = _CONTEXT_RE.fullmatch(context)
            if context_match is None:
                raise FetchError(
                    f"unreadable context {context!r} for {model_id} on {cfg.scraper_url}"
                )
            return Pricing(
                input_cost / 1e6,
                float(output_amounts[0]) / 1e6,
                mode="chat",
                max_tokens_in=int(context_match.group(1)) * 1024,
                cache_read_cost_per_token=(cache_read / 1e6 if cache_read is not None else None),
            )
    return None

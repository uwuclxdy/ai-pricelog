"""scrape per-token chat pricing from the openai platform pricing page.

rows come from the standard tier island (see the detector for the shape):
[model, input, cached read, cache write?, output], dollars per 1M tokens.
input, cached read, cache write (the default 5m tier on five-column rows)
and output parse into Pricing. "null" and "-" cells mean the model has no
such rate. max_tokens stays unset: the rows carry no context column (the
page prints context as a name annotation, not a field). rows the match
scan passes over (odd shapes, unreadable names) are additive drift
detection already reported; the matched row's cells are strict, so an
unreadable rate raises (plan #22) and never reads as unpriced.

None = the model id is not on the page, or its row carries no input or
output rate. FetchError = the fetch failed, the page has no standard
pricing table, or the matched row carries an unreadable rate.
"""

from __future__ import annotations

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.openai_page import _row_id, _standard_rows
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup


def _rate(value, model_id: str, url: str) -> float | None:
    """the cell's per-1M-token rate; null/"-" means the model has no such rate."""
    if value is None or value == "-":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raise FetchError(f"unreadable rate {value!r} for {model_id} on {url}")


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    soup = fetch_soup(cfg.scraper_url)
    for row in _standard_rows(soup, cfg.scraper_url):
        try:
            if _row_id(row, cfg.scraper_url) != model_id:
                continue
        except FetchError:
            continue  # additive drift; detect already reported the row
        input_cost = _rate(row[1], model_id, cfg.scraper_url)
        cache_read = _rate(row[2], model_id, cfg.scraper_url)
        cache_write = _rate(row[3], model_id, cfg.scraper_url) if len(row) == 5 else None
        output_cost = _rate(row[-1], model_id, cfg.scraper_url)
        if input_cost is None or output_cost is None:
            return None
        return Pricing(
            input_cost / 1e6,
            output_cost / 1e6,
            mode="chat",
            cache_read_cost_per_token=(cache_read / 1e6 if cache_read is not None else None),
            cache_write_cost_per_token=(cache_write / 1e6 if cache_write is not None else None),
        )
    return None

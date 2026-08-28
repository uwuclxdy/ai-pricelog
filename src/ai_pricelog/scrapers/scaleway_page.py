"""scrape scaleway per-token pricing from the model-as-a-service page.

same table as detection (caption and headers pinned in the detector). rates
read "€X / million tokens" in EUR, so each amount divides by 1e6 and
Pricing quotes currency="EUR" (store.build_row converts through the dated
fx table). an input cell carrying a cached amount parses into
cache_read_cost_per_token; "Free" cells are zero rates. rows priced per
audio minute are known unpriced and scrape as None, and a cell outside the
known shapes reads as an unpriced row here (the detector gates the run
loudly instead). the page carries no context/max-tokens column and no peak
tier, so those fields stay unset. mode is chat.

None = the model id is not on the page, its row carries no per-token rate,
or both its rates are zero (a free row carries no price row; skip-and-retry
re-candidates it next run, and the detector still emits the id so a stored
model never counts absent). FetchError = the fetch failed, the page has no
generative-api table, a row is outside the row shape, or the row's id
sources disagree.
"""

from __future__ import annotations

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.scaleway_page import (
    _CACHED_RE,
    _FREE,
    _RATE_RE,
    _model_table,
    _page,
    _row_cells,
    parse_id,
)
from ai_pricelog.pricing import Pricing

# dated slug spellings map to the base id the store holds (the xai
# convention): openrouter carries deepseek/deepseek-v4-flash as a base id,
# and its canonical_slug facts name mistralai/mistral-small-3.2-24b-
# instruct-2506 as the dated variant of
# mistralai/mistral-small-3.2-24b-instruct, measured 2026-08-29. the qwen
# spelling stays out: no source stores a qwen3-235b-a22b-instruct base
# (openrouter holds qwen3-235b-a22b / -2507 / -thinking-2507 only), so the
# page spelling stores directly. pixtral-12b-2409 keeps its suffix too: it
# is mistral's canonical release name, not a snapshot of a pixtral-12b
# base.
_DEDUP: dict[str, tuple[str, ...]] = {
    "deepseek-v4-flash-0731": ("deepseek-v4-flash",),
    "mistral-small-3.2-24b-instruct-2506": ("mistral-small-3.2-24b-instruct",),
}


def dedup_keys(model_id: str) -> tuple[str, ...]:
    """The base slug this dated page spelling is tracked under, or () when unchanged."""
    return _DEDUP.get(model_id, ())


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    soup = _page(cfg.scraper_url)
    table = _model_table(soup, cfg.scraper_url)
    for row in table.find("tbody").find_all("tr", recursive=False):
        cells = _row_cells(row, cfg.scraper_url)
        input_text = cells[2].get_text(" ", strip=True)
        if (match := _CACHED_RE.fullmatch(input_text)) is not None:
            input_rate, cache_rate = float(match.group(1)), float(match.group(2))
        elif (match := _RATE_RE.fullmatch(input_text)) is not None:
            input_rate, cache_rate = float(match.group(1)), None
        elif input_text == _FREE:
            input_rate, cache_rate = 0.0, None
        else:
            continue  # per audio minute, or a shape the detector gates on
        output_text = cells[3].get_text(" ", strip=True)
        if (match := _RATE_RE.fullmatch(output_text)) is not None:
            output_rate = float(match.group(1))
        elif output_text == _FREE:
            output_rate = 0.0
        else:
            continue
        if parse_id(cells[0], cells[4], cfg.scraper_url) != model_id:
            continue
        if input_rate == 0 and output_rate == 0:
            return None
        return Pricing(
            input_cost_per_token=input_rate / 1e6,
            output_cost_per_token=output_rate / 1e6,
            mode="chat",
            cache_read_cost_per_token=cache_rate / 1e6 if cache_rate is not None else None,
            currency="EUR",
        )
    return None

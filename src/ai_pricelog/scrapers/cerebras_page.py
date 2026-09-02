"""scrape cerebras per-token pricing from the public models api.

same payload as detection. pricing.prompt / pricing.completion are
per-token dollar strings -> per-token floats; zero strings are zero rates
(free is a price), negative strings read as no price. an entry without
both carries no usable rates (None, skip-and-retry: decision 8). the api
serves no context window, so the max_tokens fields stay 0 (the entry
builder omits them). entries the match scan passes over (no id string,
non-object pricing) are additive drift detection already reported; the
matched entry's non-object pricing raises.

None = the id is not on the page or its entry carries no usable rates.
FetchError = the fetch failed, the payload root is outside the shape, the
matched entry's pricing is not an object, or a rate string is unreadable.
"""

from __future__ import annotations

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.cerebras_page import _entry_id, _entry_pricing, payload_entries
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_text


def _per_token(entry: dict, key: str, model_id: str, url: str) -> float | None:
    value = (entry.get("pricing") or {}).get(key)
    if value is None:
        return None
    try:
        rate = float(value)
    except (TypeError, ValueError) as exc:
        raise FetchError(f"unreadable {key} rate for {model_id} on {url}: {value!r}") from exc
    return rate if rate >= 0 else None


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    entries = payload_entries(fetch_text(cfg.scraper_url), cfg.scraper_url)
    for entry in entries:
        try:
            if _entry_id(entry, cfg.scraper_url) != model_id:
                continue
        except FetchError:
            continue  # additive drift; detect already reported the entry
        _entry_pricing(entry, cfg.scraper_url)
        input_cost = _per_token(entry, "prompt", model_id, cfg.scraper_url)
        output_cost = _per_token(entry, "completion", model_id, cfg.scraper_url)
        if input_cost is None or output_cost is None:
            return None
        return Pricing(input_cost, output_cost, mode="chat")
    return None

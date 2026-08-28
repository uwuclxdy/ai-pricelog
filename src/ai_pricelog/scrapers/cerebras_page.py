"""scrape cerebras per-token pricing from the public models api.

same payload as detection. pricing.prompt / pricing.completion are
per-token dollar strings -> per-token floats; an entry without both
carries no usable rates (None, skip-and-retry: decision 8). the api
serves no context window, so the max_tokens fields stay 0 (the entry
builder omits them).

None = the id is not on the page or its entry carries no usable rates.
FetchError = the fetch failed or the payload is outside the shape.
"""

from __future__ import annotations

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.cerebras_page import payload_entries
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
    return rate if rate > 0 else None


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    entries = payload_entries(fetch_text(cfg.scraper_url), cfg.scraper_url)
    for entry in entries:
        if entry["id"] != model_id:
            continue
        input_cost = _per_token(entry, "prompt", model_id, cfg.scraper_url)
        output_cost = _per_token(entry, "completion", model_id, cfg.scraper_url)
        if input_cost is None or output_cost is None:
            return None
        return Pricing(input_cost, output_cost, mode="chat")
    return None

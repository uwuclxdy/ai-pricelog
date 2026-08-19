"""xAI pricing from the docs.x.ai models page blob.

prices live in the same embedded blob the detector reads. the blob price fields are
USD per 1M tokens scaled by 1e4 (20000 -> $2.00/1M, measured 2026-08-19), so a
per-token cost is ``float(field) * 1e-4 / 1e6``. cached-input fields are ignored.
max_tokens comes from ``maxOutputTokens`` when present (absent on the live page ->
0, the entry builder omits it). mode is chat.
"""

from litellm_autopr.config import ProviderCfg
from litellm_autopr.detectors.xai_page import _blob, _language_models
from litellm_autopr.pricing import Pricing

_PER_1M_SCALE = 1e-4
_PER_TOKEN = _PER_1M_SCALE / 1e6


def _price(value: object) -> float | None:
    try:
        return float(value) * _PER_TOKEN
    except (TypeError, ValueError):
        return None


def _max_output_tokens(entry: dict) -> int:
    value = entry.get("maxOutputTokens")
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    """Pricing for model_id, or None when the page carries no pricing for it."""
    blob = _blob(cfg.scraper_url)
    for entry in _language_models(blob, cfg.scraper_url):
        if entry["name"] != model_id:
            continue
        if "promptTextTokenPrice" not in entry or "completionTextTokenPrice" not in entry:
            return None
        input_cost = _price(entry["promptTextTokenPrice"])
        output_cost = _price(entry["completionTextTokenPrice"])
        if input_cost is None or output_cost is None:
            return None
        return Pricing(
            input_cost_per_token=input_cost,
            output_cost_per_token=output_cost,
            mode="chat",
            max_tokens=_max_output_tokens(entry),
        )
    return None

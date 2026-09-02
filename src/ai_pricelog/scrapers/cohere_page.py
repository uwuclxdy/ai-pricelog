"""scrape cohere per-token pricing.

same page as detection. three rate shapes:

- model cards: per-token dollars from the flight state, USD per 1M
  tokens ("Command R" -> 0.15/0.60 -> 1.5e-7 / 6e-7). a card whose
  output rate is not a token rate ("Embed 4"'s "Image cost" is per
  image) prices with output 0: embedding models bill no output tokens
  (litellm stores cohere/embed-v4.0 as 0.12/1M input, 0 output,
  measured 2026-08-26).
- faq prose: per-token dollars ("Command pricing is $1.00/1M tokens
  for input and $2.00/1M tokens for output" -> 1e-6 / 2e-6).
- Model Vault table: per instance (hourly or monthly), never per token,
  so those models scrape to None until the page publishes token rates.

none of the shapes carries a context window or max output -> the max_tokens
fields stay 0. mode is chat; cohere lists no cache-read rates, so
cache_read_cost_per_token stays None, and there are no peak fields.

None = the model id is not on the page, or the page has no per-token
rate for it (model vault rows, and cards the shared parse skipped as
malformed: additive drift detection already reported). FetchError = the
fetch failed or the page carries no pricing content at all.

the faq's dated release spellings are the stored ids themselves (the
store re-keyed onto them 2026-08-30), so page ids map straight to their
rows and no dedup is needed.
"""

from __future__ import annotations

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.cohere_page import _page, _slug
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    """Pricing for model_id, or None when the page has no usable rates for it."""
    models = _page(cfg.scraper_url, cfg.key)
    if not models:
        raise FetchError(f"no priced models found on {cfg.scraper_url}")
    for model in models:
        if model.id != _slug(model_id):
            continue
        if model.input_cost_per_token is None or model.output_cost_per_token is None:
            return None
        return Pricing(
            input_cost_per_token=model.input_cost_per_token,
            output_cost_per_token=model.output_cost_per_token,
            mode="chat",
        )
    return None

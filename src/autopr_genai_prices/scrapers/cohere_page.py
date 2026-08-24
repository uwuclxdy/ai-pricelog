"""scrape cohere per-token pricing.

same page as detection. the faq prose rates are per-token dollars:
"Command pricing is $1.00/1M tokens for input and $2.00/1M tokens for
output" -> 1e-6 / 2e-6. the Model Vault table rates are per instance
(hourly or monthly), never per token, so those models scrape to None
until the page publishes token rates. neither shape carries a context
window or max output -> max_tokens stays 0. mode is chat; cohere lists
no cache-read rates, so cache_read_cost_per_token stays None, and there
are no peak fields.

None = the model id is not on the page, or the page has no per-token
rate for it (model vault rows). FetchError = the fetch failed or the
page carries no pricing content at all.

dedup_keys maps the faq's dated release spellings to the target's
tracked ids, measured against pydantic/genai-prices cohere.yml
(2026-08-24). cohere names its releases by date; the page's legacy faq
spells "Command R 03-2024" and "Command R+ 04-2024"/"Command R+
08-2024", and the yml tracks those models as command-r and
command-r-plus (its own match clauses alias the 08-2024 spellings).
"""

from autopr_genai_prices.config import ProviderCfg
from autopr_genai_prices.detectors.cohere_page import _page, _slug
from autopr_genai_prices.pricing import Pricing
from autopr_genai_prices.web import FetchError

_DEDUP_BY_PAGE_ID = {
    "command-r-03-2024": ("command-r",),
    "command-r-plus-04-2024": ("command-r-plus",),
    "command-r-plus-08-2024": ("command-r-plus",),
}


def dedup_keys(model_id: str) -> tuple[str, ...]:
    """tracked spellings for a dated release page id, or () when unchanged."""
    return _DEDUP_BY_PAGE_ID.get(model_id, ())


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    """Pricing for model_id, or None when the page has no usable rates for it."""
    models = _page(cfg.scraper_url)
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

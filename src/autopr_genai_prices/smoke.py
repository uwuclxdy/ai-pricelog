"""live smoke probe for the moonshot .md endpoints.

kimi's pricing HTML is JS-rendered; the pipeline runs entirely on the static
.md twins (models.md for detection, llms.txt + per-page <DocTable> blocks for
scraping). the fixture tests pin saved copies and cannot catch the upstream
pages changing shape or disappearing, so the cron workflow runs this probe
against the live endpoints. exit 0 = every endpoint still serves what the
pipeline expects.

checks are small pure functions over fetched text so the offline tests cover
them; main() owns the network, which flows through the moonshot modules'
fetch_text (web.fetch_text, one retry layer) exactly like the pipeline does.
"""

import sys
from pathlib import Path

from autopr_genai_prices.config import ConfigError, ProviderCfg, load_providers
from autopr_genai_prices.detectors import moonshot_page as detector
from autopr_genai_prices.pricing import Pricing
from autopr_genai_prices.scrapers import moonshot_page as scraper
from autopr_genai_prices.web import FetchError


def pick_model(ids: list[str]) -> str:
    """the id to scrape: kimi-k3 when detected, else the first kimi- id."""
    if not ids:
        raise ValueError("models.md carries no detected model ids")
    if "kimi-k3" in ids:
        return "kimi-k3"
    for model_id in ids:
        if model_id.startswith("kimi-"):
            return model_id
    raise ValueError("models.md carries no kimi-* model id")


def check_pricing(pricing: Pricing | None, model_id: str) -> Pricing:
    """the scraped pricing for the model is present and positive."""
    if pricing is None:
        raise ValueError(f"{model_id} has no pricing row on its pricing page")
    if pricing.input_cost_per_token <= 0 or pricing.output_cost_per_token <= 0:
        raise ValueError(
            f"{model_id} pricing is non-positive: "
            f"input ${pricing.input_cost_per_token * 1e6:.2f}, "
            f"output ${pricing.output_cost_per_token * 1e6:.2f} per 1M tokens"
        )
    return pricing


def check_pricing_pages(mapping: dict[str, str]) -> int:
    """every indexed pricing page fetches and carries a DocTable; page count."""
    if not mapping:
        raise ValueError("llms.txt resolves to no pricing pages")
    count = 0
    for url in mapping.values():
        doc = scraper._doc_table(scraper.fetch_text(url))
        if doc is None:
            raise ValueError(f"no DocTable block on pricing page {url}")
        count += 1
    return count


def main() -> int:
    try:
        cfg = _moonshot_cfg()
        ids = detector.detect(cfg)
        model_id = pick_model(ids)
        pricing = check_pricing(scraper.scrape(cfg, model_id), model_id)
        mapping = scraper._load_index(cfg.scraper_url)
        pages = check_pricing_pages(mapping)
    except (ConfigError, FetchError, ValueError) as exc:
        print(f"moonshot smoke failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"moonshot smoke ok: models.md + llms.txt + {pages} pricing pages; "
        f"{model_id} ${pricing.input_cost_per_token * 1e6:.2f}/"
        f"${pricing.output_cost_per_token * 1e6:.2f} per 1M tokens"
    )
    return 0


def _moonshot_cfg() -> ProviderCfg:
    for provider in load_providers(Path("providers.toml")):
        if provider.key == "moonshot":
            return provider
    raise ConfigError("providers.toml has no [moonshot] section; nothing to probe")


if __name__ == "__main__":
    sys.exit(main())

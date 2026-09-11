"""live smoke probe for the moonshot .md endpoints.

kimi's pricing HTML is JS-rendered; the pipeline runs entirely on the static
.md twins (models.md for detection, llms.txt resolving the merged pricing
chat page and its <DocTable> block for scraping). the fixture tests pin saved
copies and cannot catch the upstream pages changing shape or disappearing,
so the cron workflow runs this probe against the live endpoints. exit 0 =
every endpoint still serves what the pipeline expects.

checks are small functions over fetched text so the offline tests cover them
with a monkeypatched fetch_text; live runs flow through the moonshot
modules' fetch_text (web.fetch_text, one retry layer) exactly like the
pipeline does.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ai_pricelog.config import ConfigError, ProviderCfg, load_providers
from ai_pricelog.detectors import moonshot_page as detector
from ai_pricelog.pricing import Pricing
from ai_pricelog.scrapers import moonshot_page as scraper
from ai_pricelog.web import FetchError


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


def check_pricing_pages(index_url: str) -> str:
    """the resolved chat page fetches and carries a DocTable; its url."""
    page_url = scraper._load_index(index_url)
    if scraper._doc_table(scraper.fetch_text(page_url)) is None:
        raise ValueError(f"no DocTable block on pricing page {page_url}")
    return page_url


def main() -> int:
    try:
        cfg = _moonshot_cfg()
        ids = detector.detect(cfg)
        model_id = pick_model(ids)
        pricing = check_pricing(scraper.scrape(cfg, model_id), model_id)
        page_url = check_pricing_pages(cfg.scraper_url)
    except (ConfigError, FetchError, ValueError) as exc:
        print(f"moonshot smoke failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"moonshot smoke ok: models.md + llms.txt + pricing page {page_url}; "
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

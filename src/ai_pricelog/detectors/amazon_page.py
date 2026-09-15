"""detect nova model ids from the aws bulk price-list api (amazon bedrock).

the detector url is the region index
(.../AmazonBedrock/current/region_index.json): 36 regions, each pinning a
currentVersionUrl. the watched region's pinned url is the per-region versioned
file (~1.4MB, 1032 products) — never the 16MB global current/index.json, which
is 11x larger and holds every region's rows. the region index is fetched once
per run (lru-cached) so detect and scrape read one pinned version per run,
matching the probe's snapshot-`current` history model (older versions are
reachable only through version ids already recorded).

the api's model key is a display name ("Nova Lite"), not the canonical model
id; the carded names join through NAME_TO_ID to the `amazon.nova-*` ids the
aws docs model cards carry. every other product skips, by mechanism: a
nova-family chat name with no card (today nova 2.0 lite and nova pro latency
optimized) is additive drift and skips with a warning (plan #22); a nova
name whose products carry only non-chat inferenceTypes (canvas, reel, sonic,
MME, the 2.0 omni/pro audio-image rows) never passes the axis filter; a
third-party chat model (the file serves dozens: claude, llama, mistral) is
another provider's coverage and skips silently; a product with no model
attribute at all (titan keys on titanModel) skips at the name check. a page
with no carded nova name is structural absence and raises, so the provider
goes loud instead of reading every stored nova id absent and faking
delistings. invalid json, a non-object root, a missing regions map, or a
watched region with no pinned
url raises.
"""

from __future__ import annotations

import functools
import json
import logging
import urllib.parse

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_text

log = logging.getLogger(__name__)

REGION = "us-east-1"

ON_DEMAND_FEATURE = "On-demand Inference"

# display name -> canonical model id, joined from the aws docs model cards'
# "Model ID" rows (static markdown, 0 price numbers):
# https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-lite.md
# (the {pro,micro,premier} twins hold the same table). only carded names join;
# every other nova name in the api is drift to skip with a warning.
NAME_TO_ID = {
    "Nova Lite": "amazon.nova-lite-v1:0",
    "Nova Micro": "amazon.nova-micro-v1:0",
    "Nova Pro": "amazon.nova-pro-v1:0",
    "Nova Premier": "amazon.nova-premier-v1:0",
}

ID_TO_NAME = {model_id: name for name, model_id in NAME_TO_ID.items()}

# the chat price axes: on-demand inferenceType -> axis
AXIS_INFERENCE_TYPES = {
    "input": "Input tokens",
    "output": "Output tokens",
    "cache_read": "Prompt cache read input tokens",
}


@functools.lru_cache(maxsize=1)
def region_file_url(region_index_url: str) -> str:
    """the watched region's pinned currentVersionUrl, as an absolute url.

    amazon republishes under a new version id, so this pins the region's own
    snapshot instead of the global file.
    """
    url = region_index_url
    try:
        data = json.loads(fetch_text(url))
    except json.JSONDecodeError as exc:
        raise FetchError(f"fetch for {url}: invalid json: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise FetchError(f"region index must be an object on {url}")
    regions = data.get("regions")
    if not isinstance(regions, dict):
        raise FetchError(f"region index carries no 'regions' object on {url}")
    entry = regions.get(REGION)
    if not isinstance(entry, dict) or not isinstance(entry.get("currentVersionUrl"), str):
        raise FetchError(f"region index has no '{REGION}' entry with a currentVersionUrl on {url}")
    return urllib.parse.urljoin(url, entry["currentVersionUrl"])


def offer_payload(url: str) -> dict:
    """the per-region offer file's json object; invalid json or a non-object
    root is a shape break."""
    try:
        data = json.loads(fetch_text(url))
    except json.JSONDecodeError as exc:
        raise FetchError(f"fetch for {url}: invalid json: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise FetchError(f"offer file must be an object on {url}")
    return data


def parse_index(products: dict, url: str) -> list[dict]:
    """every chat-shaped on-demand product's attributes.

    a product outside the dict shape raises; a chat-shaped one matching an
    already-seen (model, inferenceType) pair raises too: an ambiguity must
    never pick silently.
    """
    matched: dict[tuple[str, str], dict] = {}
    for product in products.values():
        if not isinstance(product, dict):
            raise FetchError(f"product entry must be an object on {url}")
        attributes = product.get("attributes")
        if not isinstance(attributes, dict):
            raise FetchError(f"product without an attributes object on {url}")
        inference_type = attributes.get("inferenceType")
        if attributes.get("feature") != ON_DEMAND_FEATURE or inference_type not in (
            AXIS_INFERENCE_TYPES.values()
        ):
            continue
        name = attributes.get("model")
        if not isinstance(name, str) or not name:
            continue
        key = (name, inference_type)
        if key in matched:
            raise FetchError(f"two on-demand {inference_type!r} products for {name!r} on {url}")
        matched[key] = attributes
    return list(matched.values())


def detect(cfg: ProviderCfg) -> list[str]:
    url = region_file_url(cfg.detector_url)
    data = offer_payload(url)
    products = data.get("products")
    if not isinstance(products, dict):
        raise FetchError(f"offer file carries no 'products' object on {url}")
    ids: list[str] = []
    seen: set[str] = set()
    unjoined: set[str] = set()
    for attributes in parse_index(products, url):
        name = attributes["model"]
        model_id = NAME_TO_ID.get(name)
        if model_id is None:
            # only the nova family is this provider's watch scope: a nova
            # name with no card is drift to report, a third-party bedrock
            # model (the file serves dozens) is another provider's coverage
            # and skips silently
            if name.startswith("Nova"):
                unjoined.add(name)
            continue
        if model_id not in seen:
            seen.add(model_id)
            ids.append(model_id)
    for name in sorted(unjoined):
        log.warning(
            "detect skip for %s: nova name %r has no model-card id join",
            cfg.key,
            name,
        )
    if not ids:
        raise FetchError(
            f"no carded nova model names on {url}: saw {sorted(unjoined)!r}; fix: extend"
            " NAME_TO_ID from the aws docs model cards"
        )
    return ids

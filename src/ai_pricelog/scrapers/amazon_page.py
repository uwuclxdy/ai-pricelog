"""scrape nova per-token pricing from the aws bulk price-list api (bedrock).

same payload as detection: the region index pins the watched region's
currentVersionUrl, and the versioned per-region file carries the products and
their on-demand terms. the chat axes join by exact (model display name,
feature "On-demand Inference", inferenceType): input/output/prompt-cache-read
token rows are the price axes; the tier variants (priority, flex) and the
batch/customization/provisioned-throughput features never join, so they cannot
smuggle a wrong rate into a standard row.

every rate is quoted USD per 1K tokens: the per-1K value /1000 is the
per-token cost build_row converts to the per-1M rate axes. a non-"1K tokens"
unit on a joined row is a shape break, never a silent conversion (build_row
refuses non-token units; a misconverting skip here would misstate the billing
axis). the row's effective date is the latest on-demand offer effectiveDate
among the axes it carries: a row prices a day only once every axis it names
has its price, so a later-dated axis never backdates the row. cache write is
dropped: the api reads $0.0000 per 1K on the standard cache-write rows the
carded models carry (lite, micro, pro; premier has none, only tier variants)
and the docs model cards corroborate no write price — the caveat's rule.

a joined product with two on-demand terms, two price dimensions, or no terms
at all is a shape break (FetchError): wrong data must stay impossible. an
unreadable USD value or effectiveDate raises too. a carded model whose input
or output row is gone carries no usable rates: None (skip-and-retry,
decision 8), never a partial row. an id with no carded name is not on this
page: None.
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.amazon_page import (
    AXIS_INFERENCE_TYPES,
    ID_TO_NAME,
    ON_DEMAND_FEATURE,
    offer_payload,
    region_file_url,
)
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError

_UNIT = "1K tokens"
_TOKENS_PER_K = 1000
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T")


def _rate(product_sku: str, on_demand: dict, url: str) -> tuple[float, str]:
    """the product's per-1K-token USD rate and its offer's effective date.

    one on-demand offer carrying exactly one price dimension: anything else
    on a joined product is a shape break, never a silent pick.
    """
    offers = on_demand.get(product_sku)
    if not isinstance(offers, dict) or not offers:
        raise FetchError(f"product {product_sku} carries no on-demand terms in {url}")
    if len(offers) > 1:
        raise FetchError(f"two on-demand terms for product {product_sku} in {url}")
    offer = next(iter(offers.values()))
    if not isinstance(offer, dict):
        raise FetchError(f"on-demand offer for product {product_sku} must be an object in {url}")
    dimensions = offer.get("priceDimensions")
    if not isinstance(dimensions, dict) or len(dimensions) != 1:
        raise FetchError(f"product {product_sku} must carry exactly one price dimension in {url}")
    dimension = next(iter(dimensions.values()))
    if not isinstance(dimension, dict) or not isinstance(dimension.get("pricePerUnit"), dict):
        raise FetchError(f"unreadable price dimensions for product {product_sku} in {url}")
    unit = dimension.get("unit")
    if unit != _UNIT:
        raise FetchError(f"product {product_sku} unit is {unit!r}, expected {_UNIT!r} in {url}")
    usd = dimension["pricePerUnit"].get("USD")
    try:
        rate = float(usd)
    except (TypeError, ValueError) as exc:
        raise FetchError(f"unreadable USD rate {usd!r} for product {product_sku} on {url}") from exc
    if rate < 0:
        raise FetchError(f"negative USD rate {usd!r} for product {product_sku} on {url}")
    effective = offer.get("effectiveDate")
    if not isinstance(effective, str) or _DATE.match(effective) is None:
        raise FetchError(f"unreadable effectiveDate {effective!r} on offer {product_sku} in {url}")
    return rate, effective[:10]


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    name = ID_TO_NAME.get(model_id)
    if name is None:
        return None
    url = region_file_url(cfg.scraper_url)
    data = offer_payload(url)
    products = data.get("products")
    on_demand = (data.get("terms") or {}).get("OnDemand")
    if not isinstance(products, dict) or not isinstance(on_demand, dict):
        raise FetchError(f"offer file carries no 'products'/'terms' objects on {url}")
    axis_skus: dict[str, str] = {}
    for sku, product in products.items():
        if not isinstance(product, dict):
            continue  # detection's parse_index reports the drift
        attributes = product.get("attributes")
        if not isinstance(attributes, dict) or attributes.get("model") != name:
            continue
        if attributes.get("feature") != ON_DEMAND_FEATURE:
            continue
        inference_type = attributes.get("inferenceType")
        axis = next((a for a, t in AXIS_INFERENCE_TYPES.items() if t == inference_type), None)
        if axis is None:
            continue
        if axis in axis_skus:
            raise FetchError(f"two on-demand {inference_type!r} products for {name!r} on {url}")
        axis_skus[axis] = sku
    if "input" not in axis_skus or "output" not in axis_skus:
        return None
    rates: dict[str, float] = {}
    effective: str | None = None
    # AXIS_INFERENCE_TYPES is the single axis list: dict order is the read
    # order, so a new axis joins by entering the map, never a second copy here
    for axis in AXIS_INFERENCE_TYPES:
        if axis not in axis_skus:
            continue
        rate, axis_effective = _rate(axis_skus[axis], on_demand, url)
        rates[axis] = rate
        if effective is None or axis_effective > effective:
            effective = axis_effective
    return Pricing(
        input_cost_per_token=rates["input"] / _TOKENS_PER_K,
        output_cost_per_token=rates["output"] / _TOKENS_PER_K,
        mode="chat",
        cache_read_cost_per_token=(
            rates["cache_read"] / _TOKENS_PER_K if "cache_read" in rates else None
        ),
        url=url,
        effective_at=effective,
    )

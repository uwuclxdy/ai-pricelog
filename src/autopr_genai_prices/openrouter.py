"""OpenRouter public models API: fetch and parse model entries.

https://openrouter.ai/api/v1/models is keyless. Per-token price strings are
converted to per-megatoken floats with the same rounding as yml.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from autopr_genai_prices.web import FetchError, fetch_text
from autopr_genai_prices.yml import to_mtok

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


@dataclass(frozen=True)
class OpenrouterModel:
    id: str
    name: str
    input_mtok: float | None
    output_mtok: float | None
    cache_read_mtok: float | None


def fetch_models(url: str | None = None) -> list[OpenrouterModel]:
    url = url or OPENROUTER_MODELS_URL
    text = fetch_text(url)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FetchError(f"fetch for {url}: invalid json: {exc.msg}") from exc
    return _parse_models(data, f"url '{url}'")


def find(models: list[OpenrouterModel], prefix: str, model_id: str) -> OpenrouterModel | None:
    slug = f"{prefix}/{model_id.lower()}"
    for model in models:
        if model.id == slug:
            return model
    return None


def _parse_models(data: object, source: str) -> list[OpenrouterModel]:
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise ValueError(f"{source}: root must be an object with a 'data' list")
    models: list[OpenrouterModel] = []
    for entry in data["data"]:
        if not isinstance(entry, dict):
            raise ValueError(f"{source}: model entries must be objects")
        if entry.get("alias_target"):
            continue
        pricing = entry.get("pricing") or {}
        if not isinstance(pricing, dict):
            raise ValueError(f"{source}: pricing of {entry.get('id')!r} must be an object")
        models.append(
            OpenrouterModel(
                id=entry["id"],
                name=entry.get("name") or entry["id"],
                input_mtok=_price(pricing.get("prompt"), entry["id"]),
                output_mtok=_price(pricing.get("completion"), entry["id"]),
                cache_read_mtok=_price(pricing.get("input_cache_read"), entry["id"]),
            )
        )
    return models


def _price(value: object, model_id: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(
            f"model {model_id!r}: pricing values must be per-token strings, "
            f"got {type(value).__name__}"
        )
    return to_mtok(float(value))

"""OpenRouter public models API: fetch and parse model entries, map them to store rows.

https://openrouter.ai/api/v1/models is keyless. Per-token price strings are
converted to per-megatoken floats with the same rounding as yml.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ai_pricelog.web import FetchError, fetch_text
from ai_pricelog.yml import to_mtok

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


@dataclass(frozen=True)
class OpenrouterModel:
    id: str
    name: str
    input_mtok: float | None
    output_mtok: float | None
    cache_read_mtok: float | None
    # build_row-only payload; compare=False keeps the existing mtok-focused equality
    alias_target: object | None = field(default=None, compare=False)
    canonical_slug: str | None = field(default=None, compare=False)
    context_length: int = field(default=0, compare=False)
    pricing: dict[str, object] = field(default_factory=dict, compare=False)


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


OBSERVED_KEYS = frozenset({"prompt", "completion", "input_cache_read"})


def build_row(model: OpenrouterModel, observed_at: str) -> dict[str, object] | None:
    if model.alias_target or (
        model.canonical_slug is not None and model.canonical_slug != model.id
    ):
        return None
    row: dict[str, object] = {
        "source": "openrouter",
        "model_id": model.id,
        "observed_at": observed_at,
    }
    if model.name:
        row["name"] = model.name
    for key, field_name in (
        ("prompt", "input_mtok"),
        ("completion", "output_mtok"),
        ("input_cache_read", "cache_read_mtok"),
    ):
        value = model.pricing.get(key)
        if value is not None:
            row[field_name] = to_mtok(float(value))
    if model.context_length > 0:
        row["max_tokens"] = model.context_length
    extra = {key: value for key, value in model.pricing.items() if key not in OBSERVED_KEYS}
    if extra:
        row["extra"] = extra
    return row


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
                name=_display_name(entry),
                input_mtok=_price(pricing.get("prompt"), entry["id"]),
                output_mtok=_price(pricing.get("completion"), entry["id"]),
                cache_read_mtok=_price(pricing.get("input_cache_read"), entry["id"]),
                canonical_slug=entry.get("canonical_slug"),
                context_length=entry.get("context_length") or 0,
                pricing=pricing,
            )
        )
    return models


def _display_name(entry: dict) -> str:
    name = entry.get("name") or entry["id"]
    # API names carry a vendor prefix ("SpaceXAI: Grok 4.6"); the target's
    # openrouter.yml entries use the bare model name
    return name.split(": ", 1)[1] if ": " in name else name


def _price(value: object, model_id: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(
            f"model {model_id!r}: pricing values must be per-token strings, "
            f"got {type(value).__name__}"
        )
    per_token = float(value)
    if per_token == 0:
        # free models ship all-zero pricing strings; the target represents
        # them as an empty prices mapping, and its schema forbids zero prices
        return None
    return to_mtok(per_token)

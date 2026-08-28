"""OpenRouter public models API: fetch and parse model entries, map them to store rows.

https://openrouter.ai/api/v1/models is keyless. Per-token price strings are
converted to per-megatoken floats with the same rounding as pricing.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ai_pricelog.pricing import to_mtok
from ai_pricelog.web import FetchError, fetch_text

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
    variant_snapshot: bool = field(default=False, compare=False)
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


OBSERVED_KEYS = frozenset(
    {"prompt", "completion", "input_cache_read", "input_cache_write", "input_cache_write_1h"}
)


def build_row(model: OpenrouterModel, observed_at: str) -> dict[str, object] | None:
    if model.alias_target or model.variant_snapshot:
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
        ("input_cache_write", "cache_write_mtok"),
        ("input_cache_write_1h", "cache_write_1h_mtok"),
    ):
        value = model.pricing.get(key)
        if value is None:
            continue
        try:
            rate = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"model {model.id!r}: pricing value for {key} must be a"
                f" per-token string, got {type(value).__name__}"
            ) from exc
        if rate >= 0:
            row[field_name] = to_mtok(rate)
    if model.context_length > 0:
        row["max_tokens_in"] = model.context_length
    extra = {key: value for key, value in model.pricing.items() if key not in OBSERVED_KEYS}
    if extra:
        row["extra"] = extra
    return row


def _parse_models(data: object, source: str) -> list[OpenrouterModel]:
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise ValueError(f"{source}: root must be an object with a 'data' list")
    entries = data["data"]
    listed_ids = {entry["id"] for entry in entries if isinstance(entry, dict)}
    models: list[OpenrouterModel] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"{source}: model entries must be objects")
        if entry.get("alias_target"):
            continue
        pricing = entry.get("pricing") or {}
        if not isinstance(pricing, dict):
            raise ValueError(f"{source}: pricing of {entry.get('id')!r} must be an object")
        canonical_slug = entry.get("canonical_slug")
        models.append(
            OpenrouterModel(
                id=entry["id"],
                name=_display_name(entry),
                input_mtok=_price(pricing.get("prompt"), entry["id"]),
                output_mtok=_price(pricing.get("completion"), entry["id"]),
                cache_read_mtok=_price(pricing.get("input_cache_read"), entry["id"]),
                canonical_slug=canonical_slug,
                # a variant entry redirects to another listed id (":batch"
                # spellings pointing at the plain model); the plain id keys
                # the row, so the redirect is not a priced row of its own
                variant_snapshot=bool(
                    canonical_slug is not None
                    and canonical_slug != entry["id"]
                    and canonical_slug in listed_ids
                ),
                context_length=entry.get("context_length") or 0,
                pricing=pricing,
            )
        )
    return models


def _display_name(entry: dict) -> str:
    name = entry.get("name") or entry["id"]
    # API names carry a vendor prefix ("SpaceXAI: Grok 4.6"); rows use the
    # bare model name
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
    if per_token <= 0:
        # zero (free models) and negative ("no fixed price" router models)
        # strings parse as no price
        return None
    return to_mtok(per_token)

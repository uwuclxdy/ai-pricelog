"""OpenRouter public models API: fetch and parse model entries, map them to v4 store rows.

https://openrouter.ai/api/v1/models is keyless. Per-token price strings are
converted to per-megatoken floats with the same rounding as pricing.py.
Scheduled overrides (utc_days / utc_start / utc_end) and volume-threshold
overrides (min_prompt_tokens) both map to v4 `overrides` entries; unmapped
pricing keys stay verbatim under `unmapped`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
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

# source pricing key -> v4 rate axis; the one table shared by the base
# mapping, window overrides and volume overrides so the three can never
# drift apart
_PRICE_KEYS = (
    ("prompt", "input"),
    ("completion", "output"),
    ("input_cache_read", "cache_read"),
    ("input_cache_write", "cache_write"),
    ("input_cache_write_1h", "cache_write_1h"),
)

# source modality key -> v4 rate axis, promoted out of `unmapped` so consumers
# can query and validate them. web_search stays out: it prices per request (a
# flat USD fee), not per token, and lands in the fees dict below
_MODALITY_KEYS = (
    ("image", "image"),
    ("audio", "audio"),
    ("input_audio_cache", "input_audio_cache"),
    ("internal_reasoning", "internal_reasoning"),
    ("image_output", "image_output"),
    ("audio_output", "audio_output"),
)
_MODALITY_SOURCE_KEYS = frozenset(key for key, _ in _MODALITY_KEYS)
# per-request fee keys, typed as plain USD fields (never per-token)
_FEE_SOURCE_KEYS = frozenset({"web_search"})

# every source pricing key the typed mapping consumes; the migration splits
# v3 `extra` rows on this set so a known pricing key re-maps and everything
# else stays unmapped
SOURCE_KEYS = frozenset(
    {*(key for key, _ in _PRICE_KEYS), *_MODALITY_SOURCE_KEYS, *_FEE_SOURCE_KEYS}
)

# the override keys that make an override a schedule rather than a threshold;
# any override carrying one of them maps to a scheduled override entry
_SCHEDULE_KEYS = frozenset({"utc_days", "utc_start", "utc_end"})

# override keys recognized in a volume-threshold override: the threshold plus
# every price key the volume mapper maps
_VOLUME_SOURCE_KEYS = frozenset({*(key for key, _ in _PRICE_KEYS), *_MODALITY_SOURCE_KEYS})

_WINDOW_ENTRY_KEYS = frozenset({*_SCHEDULE_KEYS, *(key for key, _ in _PRICE_KEYS)})

_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def map_typed_fields(
    source_pricing: Mapping[str, object], label: str
) -> tuple[dict[str, object], dict[str, object]]:
    """source pricing keys -> (rates, fees), via the one shared mapping.

    per-token strings convert to mtok (round 6); web_search is a per-request
    USD fee and lands verbatim. zero (free) keys stay; negative ("no fixed
    price") keys drop. a non-numeric value is a shape break.
    """
    rates: dict[str, object] = {}
    for key, axis in (*_PRICE_KEYS, *_MODALITY_KEYS):
        value = source_pricing.get(key)
        if value is None:
            continue
        try:
            rate = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"model {label!r}: pricing value for {key} must be a"
                f" per-token string, got {type(value).__name__}"
            ) from exc
        if rate >= 0:
            rates[axis] = to_mtok(rate)
    fees: dict[str, object] = {}
    web_search = source_pricing.get("web_search")
    if web_search is not None:
        try:
            fee = float(web_search)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"model {label!r}: pricing value for web_search must be a"
                f" per-request dollar string, got {type(web_search).__name__}"
            ) from exc
        if fee >= 0:
            fees["web_search"] = fee
    return rates, fees


def build_row(
    model: OpenrouterModel, observed_at: str, schema_version: int
) -> dict[str, object] | None:
    if model.alias_target or model.variant_snapshot:
        return None
    rates, fees = map_typed_fields(model.pricing, model.id)
    schedule_entries: list[dict[str, object]] = []
    volume_entries: list[dict[str, object]] = []
    leftover_overrides: list[dict[str, object]] = []
    overrides = model.pricing.get("overrides")
    if overrides is not None:
        if not isinstance(overrides, list) or not all(
            isinstance(override, dict) for override in overrides
        ):
            raise ValueError(f"model {model.id!r}: pricing 'overrides' must be a list of objects")
        for override in overrides:
            if not _SCHEDULE_KEYS.isdisjoint(override):
                schedule_entries.extend(_window_entry(model.id, override))
            elif "min_prompt_tokens" in override:
                volume_entries.append(_volume_entry(model.id, override))
            else:
                leftover_overrides.append(override)
    unmapped = {
        key: value
        for key, value in model.pricing.items()
        if key not in OBSERVED_KEYS
        and key not in _MODALITY_SOURCE_KEYS
        and key not in _FEE_SOURCE_KEYS
        and key != "overrides"
    }
    if leftover_overrides:
        unmapped["overrides"] = leftover_overrides
    row: dict[str, object] = {
        "schema": schema_version,
        "source": "openrouter",
        "model_id": model.id,
        "observed_at": observed_at,
    }
    if rates:
        row["rates"] = rates
    if schedule_entries or volume_entries:
        row["overrides"] = [*schedule_entries, *volume_entries]
    if fees:
        row["fees"] = fees
    limits: dict[str, object] = {}
    if model.context_length > 0:
        limits["context"] = model.context_length
    if limits:
        row["limits"] = limits
    if unmapped:
        row["unmapped"] = unmapped
    provenance: dict[str, object] = {}
    if model.name:
        provenance["name"] = model.name
    if provenance:
        row["provenance"] = provenance
    return row


def _window_entry(model_id: str, override: dict[str, object]) -> list[dict[str, object]]:
    """One scheduled override as v4 override entries (a wrap window splits into two).

    The entries keep the source encoding: days are the lowercase weekday
    names in calendar order, the window is the [utc_start, utc_end] HHMM
    clock pair with a utc_end of 0 normalized to 2400 (midnight as the END
    of the day). Absent utc_days (every day) and absent bounds (whole day)
    stay absent. The source spells its windows in UTC, so every entry's when
    carries "timezone": "UTC".
    """
    when: dict[str, object] = {}
    days = override.get("utc_days")
    if days is not None:
        if not isinstance(days, list) or not days or not all(isinstance(day, str) for day in days):
            raise ValueError(
                f"model {model_id!r}: override utc_days must be a non-empty list of"
                f" weekday names, got {days!r}"
            )
        unknown = [day for day in days if day not in _WEEKDAYS]
        if unknown:
            raise ValueError(
                f"model {model_id!r}: override utc_days weekday(s) {unknown!r} unknown;"
                " fix: use names like 'monday'"
            )
        # calendar order, deduped: a repeated day adds no information, and
        # the order is stable across source reorderings
        when["days"] = sorted(set(days), key=_WEEKDAYS.index)
    start = override.get("utc_start")
    end = override.get("utc_end")
    if (start is None) != (end is None):
        raise ValueError(
            f"model {model_id!r}: override utc_start without utc_end (or the reverse)"
            " is not a time window; fix: ship both bounds or neither"
        )
    windows: list[list[int]] | None = None
    if start is not None:
        start_clock = _clock(model_id, "utc_start", start)
        end_clock = _clock(model_id, "utc_end", end)
        if start_clock > end_clock:
            # the source window is half-open and may wrap past midnight; a
            # wrap splits into two plain same-day windows so validation
            # never sees a start-after-end pair
            windows = [[start_clock, 2400], [0, end_clock]]
        else:
            windows = [[start_clock, end_clock]]
    rates: dict[str, object] = {}
    for key, axis in _PRICE_KEYS:
        value = override.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(
                f"model {model_id!r}: override pricing value for {key} must be a"
                f" per-token string, got {type(value).__name__}"
            )
        try:
            rate = float(value)
        except ValueError as exc:
            raise ValueError(
                f"model {model_id!r}: override pricing value for {key} must be a"
                f" per-token number string, got {value!r}"
            ) from exc
        if rate > 0:
            # zero (free) and negative ("no fixed price") keys inherit the
            # base price, mirroring _price: the key drops from the entry
            rates[axis] = to_mtok(rate)
    unknown = set(override) - _WINDOW_ENTRY_KEYS
    if unknown:
        raise ValueError(
            f"model {model_id!r}: scheduled override key(s) {sorted(unknown)!r} are"
            " not mapped; fix: extend the window mapping or drop the key"
        )
    if windows is None:
        when["timezone"] = "UTC"
        return [{"when": when, "rates": rates}]
    return [
        {"when": {**when, "window": window, "timezone": "UTC"}, "rates": dict(rates)}
        for window in windows
    ]


def _volume_entry(model_id: str, override: dict[str, object]) -> dict[str, object]:
    """One volume-threshold override as a v4 override entry.

    min_prompt_tokens lands as when.min_tokens; the price keys map to their
    rate axes with the same zero/negative inherit-base rule as window entries.
    A key outside the known volume set is a shape break.
    """
    min_tokens = override.get("min_prompt_tokens")
    if (
        isinstance(min_tokens, bool)
        or not isinstance(min_tokens, (int, float))
        or not float(min_tokens).is_integer()
        or min_tokens <= 0
    ):
        raise ValueError(
            f"model {model_id!r}: override min_prompt_tokens must be a positive"
            f" integer, got {min_tokens!r}"
        )
    rates: dict[str, object] = {}
    for key, axis in (*_PRICE_KEYS, *_MODALITY_KEYS):
        value = override.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(
                f"model {model_id!r}: override pricing value for {key} must be a"
                f" per-token string, got {type(value).__name__}"
            )
        try:
            rate = float(value)
        except ValueError as exc:
            raise ValueError(
                f"model {model_id!r}: override pricing value for {key} must be a"
                f" per-token number string, got {value!r}"
            ) from exc
        if rate > 0:
            rates[axis] = to_mtok(rate)
    unknown = set(override) - _VOLUME_SOURCE_KEYS - {"min_prompt_tokens"}
    if unknown:
        raise ValueError(
            f"model {model_id!r}: volume override key(s) {sorted(unknown)!r} are"
            " not mapped; fix: extend the volume mapping or drop the key"
        )
    return {"when": {"min_tokens": int(min_tokens)}, "rates": rates}


def _clock(model_id: str, key: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"model {model_id!r}: override {key} must be an HHMM clock number, got {value!r}"
        )
    number = float(value)
    if not number.is_integer() or not 0 <= number <= 2400:
        raise ValueError(
            f"model {model_id!r}: override {key} must be a whole HHMM clock number"
            f" between 0 and 2400, got {value!r}"
        )
    clock = int(number)
    if clock % 100 > 59:
        raise ValueError(
            f"model {model_id!r}: override {key} {clock} is not a clock time;"
            " fix: HHMM with minutes under 60"
        )
    if key == "utc_start" and clock == 2400:
        raise ValueError(
            f"model {model_id!r}: override utc_start 2400 is past the day;"
            " fix: use a start before 2400"
        )
    if key == "utc_end" and clock == 0:
        return 2400
    return clock


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

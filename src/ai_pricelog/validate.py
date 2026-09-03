"""Row-level checks that run before a v4 price row is appended to the history.

The history is append-only, so a bad row lands forever. validate_row checks the
shape our own emission could corrupt: the top-level key set and required keys,
the schema stamp, source and model_id, the dates, the removal flag, the currency
code, the base rates, fees, limits, unmapped and provenance containers, the fx
pair, and each conditional override. Every key set comes from the committed
data/schema/row.v4.json contract via load_schema_keys, so validate_row resolves
no repo root and never hardcodes a key.
"""

from __future__ import annotations

import functools
import json
import math
import re
from pathlib import Path
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ValidationError(ValueError):
    """a row failed validation; the message names the field, bad value, fix."""


def validate_row(row: dict[str, Any], keys: SchemaKeys) -> None:
    unknown = set(row) - keys.row
    if unknown:
        raise ValidationError(
            f"row field(s) {sorted(unknown)!r} are not part of the row schema;"
            " fix: drop them, or extend the schema and bump the version"
        )
    missing = keys.required - set(row)
    if missing:
        raise ValidationError(
            f"row is missing required field(s) {sorted(missing)!r}; fix: emit them"
        )
    schema = row["schema"]
    if schema != keys.version:
        raise ValidationError(
            f"row field 'schema' has bad value {schema!r}; fix: use {keys.version}"
        )
    for field in ("source", "model_id"):
        value = row[field]
        if not isinstance(value, str) or not value:
            raise ValidationError(f"row field '{field}' must be a non-empty string")
    observed = row["observed_at"]
    if not isinstance(observed, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", observed) is None:
        raise ValidationError(
            f"row field 'observed_at' has bad value {observed!r}; fix: YYYY-MM-DD"
        )
    effective = row.get("effective_at")
    if effective is not None and (
        not isinstance(effective, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", effective) is None
    ):
        raise ValidationError(
            f"row field 'effective_at' has bad value {effective!r}; fix: YYYY-MM-DD"
        )
    if "removed" in row:
        removed = row["removed"]
        if not isinstance(removed, bool) or removed is not True:
            raise ValidationError(
                f"row field 'removed' has bad value {removed!r}; fix: only true is valid"
            )
    currency = row.get("currency")
    if currency is not None and (
        not isinstance(currency, str) or re.fullmatch(r"[A-Z]{3}", currency) is None
    ):
        raise ValidationError(
            f"row field 'currency' has bad value {currency!r}; fix: a 3-letter uppercase code"
        )
    rates = row.get("rates")
    if rates is not None:
        if not isinstance(rates, dict) or not rates:
            raise ValidationError("row field 'rates' must be a non-empty dict")
        unknown = set(rates) - keys.rate_axes
        if unknown:
            raise ValidationError(
                f"row field 'rates' has unknown axis(es) {sorted(unknown)!r};"
                " fix: drop them or extend the schema"
            )
        for axis, value in rates.items():
            _check_price(f"rates.{axis}", value)
    fees = row.get("fees")
    if fees is not None:
        if not isinstance(fees, dict) or not fees:
            raise ValidationError("row field 'fees' must be a non-empty dict")
        unknown = set(fees) - keys.fees
        if unknown:
            raise ValidationError(
                f"row field 'fees' has unknown fee(s) {sorted(unknown)!r};"
                " fix: drop them or extend the schema"
            )
        for fee, value in fees.items():
            _check_price(f"fees.{fee}", value)
    limits = row.get("limits")
    if limits is not None:
        if not isinstance(limits, dict) or not limits:
            raise ValidationError("row field 'limits' must be a non-empty dict")
        unknown = set(limits) - keys.limits
        if unknown:
            raise ValidationError(
                f"row field 'limits' has unknown limit(s) {sorted(unknown)!r};"
                " fix: drop them or extend the schema"
            )
        for limit, value in limits.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValidationError(
                    f"row field 'limits' limit '{limit}' has bad value {value!r};"
                    " fix: use a positive integer"
                )
    unmapped = row.get("unmapped")
    if unmapped is not None and (not isinstance(unmapped, dict) or not unmapped):
        raise ValidationError("row field 'unmapped' must be a non-empty dict")
    provenance = row.get("provenance")
    if provenance is not None:
        _check_provenance(provenance, currency, keys)
    elif currency is not None and currency != "USD":
        # the rate is what makes a non-USD quote convertible, and the store is
        # append-only: a row without it is unpriceable forever
        raise ValidationError(
            f"row field 'currency' is {currency!r} but the row carries no"
            " 'provenance.fx_rate'; fix: add the rate the quote converted at"
        )
    overrides = row.get("overrides")
    if overrides is not None:
        if not isinstance(overrides, list) or not overrides:
            raise ValidationError(
                "row field 'overrides' must be a non-empty list of override entries"
            )
        for entry in overrides:
            _check_override(entry, keys)


def _check_override(entry: Any, keys: SchemaKeys) -> None:
    if not isinstance(entry, dict):
        raise ValidationError(f"row field 'overrides' has bad entry {entry!r}; fix: use an object")
    unknown = set(entry) - keys.override
    if unknown:
        raise ValidationError(
            f"row field 'overrides' has unknown key(s) {sorted(unknown)!r};"
            " fix: drop them or extend the schema"
        )
    if not entry:
        raise ValidationError(
            "row field 'overrides' has an empty entry; fix: map a rate, a when,"
            " or a quota_multiplier"
        )
    has_rates = "rates" in entry
    has_multiplier = "quota_multiplier" in entry
    if not has_rates and not has_multiplier:
        raise ValidationError(
            "row field 'overrides' entry carries neither 'rates' nor"
            " 'quota_multiplier'; fix: map at least one override price key or a multiplier"
        )
    multiplier = entry.get("quota_multiplier")
    if multiplier is not None and (
        isinstance(multiplier, bool)
        or not isinstance(multiplier, (int, float))
        or not math.isfinite(multiplier)
        or multiplier <= 0
    ):
        raise ValidationError(
            f"row field 'overrides' entry has bad quota_multiplier {multiplier!r};"
            " fix: a finite float > 0"
        )
    when = entry.get("when")
    if when is not None:
        if not isinstance(when, dict) or not when:
            raise ValidationError("row field 'overrides' entry 'when' must be a non-empty dict")
        unknown = set(when) - keys.when
        if unknown:
            raise ValidationError(
                f"row field 'overrides' entry 'when' has unknown key(s) {sorted(unknown)!r};"
                " fix: drop them or extend the schema"
            )
        days = when.get("days")
        if days is not None and (
            not isinstance(days, list)
            or not days
            or not all(isinstance(day, str) and day in keys.days for day in days)
            or len(set(days)) != len(days)
        ):
            raise ValidationError(
                f"row field 'overrides' entry 'when' has bad day-set {days!r};"
                " fix: lowercase weekday names like ['monday', 'saturday'], no duplicates"
            )
        window = when.get("window")
        if window is not None and (
            not isinstance(window, list)
            or len(window) != 2
            or any(isinstance(part, bool) or not isinstance(part, int) for part in window)
            or not 0 <= window[0] < window[1] <= 2400
            or window[0] % 100 > 59
            or window[1] % 100 > 59
        ):
            raise ValidationError(
                f"row field 'overrides' entry 'when' has bad window {window!r};"
                " fix: [start, end] HHMM clock numbers with minutes under 60,"
                " start < end, end at most 2400"
            )
        min_tokens = when.get("min_tokens")
        if min_tokens is not None and (
            isinstance(min_tokens, bool) or not isinstance(min_tokens, int) or min_tokens <= 0
        ):
            raise ValidationError(
                f"row field 'overrides' entry 'when' has bad min_tokens {min_tokens!r};"
                " fix: a positive integer"
            )
        timezone = when.get("timezone")
        if timezone is not None:
            if not isinstance(timezone, str):
                raise ValidationError(
                    f"row field 'overrides' entry 'when' has bad timezone {timezone!r};"
                    " fix: an IANA zone name"
                )
            try:
                ZoneInfo(timezone)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValidationError(
                    f"row field 'overrides' entry 'when' has unknown zone {timezone!r};"
                    " fix: an IANA zone name"
                ) from exc
            if "days" not in when and "window" not in when:
                raise ValidationError(
                    "row field 'overrides' entry 'when' carries 'timezone' with no"
                    " 'days' or 'window'; fix: drop it or add a schedule"
                )
    if has_rates:
        if not isinstance(when, dict) or not any(
            key in when for key in ("days", "window", "min_tokens")
        ):
            raise ValidationError(
                "row field 'overrides' entry with 'rates' needs a 'when' holding"
                " 'days', 'window', or 'min_tokens'; fix: make the override conditional"
            )
        rates = entry["rates"]
        if not isinstance(rates, dict) or not rates:
            raise ValidationError("row field 'overrides' entry 'rates' must be a non-empty dict")
        unknown = set(rates) - keys.rate_axes
        if unknown:
            raise ValidationError(
                f"row field 'overrides' entry 'rates' has unknown axis(es)"
                f" {sorted(unknown)!r}; fix: drop them or extend the schema"
            )
        for axis, value in rates.items():
            _check_container_rate("overrides", axis, value)


def _check_provenance(provenance: Any, currency: Any, keys: SchemaKeys) -> None:
    if not isinstance(provenance, dict) or not provenance:
        raise ValidationError("row field 'provenance' must be a non-empty dict")
    unknown = set(provenance) - keys.provenance
    if unknown:
        raise ValidationError(
            f"row field 'provenance' has unknown key(s) {sorted(unknown)!r};"
            " fix: drop them or extend the schema"
        )
    for field in ("url", "name"):
        value = provenance.get(field)
        if value is not None and (not isinstance(value, str) or not value):
            raise ValidationError(f"row field 'provenance.{field}' must be a non-empty string")
    non_usd = currency is not None and currency != "USD"
    fx_rate = provenance.get("fx_rate")
    fx_rate_date = provenance.get("fx_rate_date")
    if non_usd:
        if fx_rate is None or (
            isinstance(fx_rate, bool)
            or not isinstance(fx_rate, (int, float))
            or not math.isfinite(fx_rate)
            or fx_rate <= 0
        ):
            raise ValidationError(
                f"row field 'provenance.fx_rate' has bad value {fx_rate!r} for currency"
                f" {currency!r}; fix: a finite float > 0"
            )
    elif fx_rate is not None or fx_rate_date is not None:
        raise ValidationError(
            "row field 'provenance.fx_rate' and 'provenance.fx_rate_date' are only valid"
            " with a non-USD 'currency'; fix: drop them or set currency"
        )
    if fx_rate_date is not None and (
        not isinstance(fx_rate_date, str)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}", fx_rate_date) is None
    ):
        raise ValidationError(
            f"row field 'provenance.fx_rate_date' has bad value {fx_rate_date!r}; fix: YYYY-MM-DD"
        )


def _check_container_rate(container: str, field: str, value: Any) -> None:
    # an override rate of zero is indistinguishable from inheriting the base
    # rate, so it is refused here while base rates allow zero
    if (
        isinstance(value, bool)
        or not isinstance(value, float)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValidationError(
            f"row field '{container}' entry rate '{field}' has bad value {value!r};"
            " fix: use a finite float > 0"
        )


def _check_price(field: str, value: Any) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, float)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValidationError(
            f"row field '{field}' has bad value {value!r}; fix: use a finite float >= 0"
        )


# the v4 row contract, keyed by the committed schema file. load_schema_keys
# derives every key set (and the weekday enum) from here so the validator cannot
# drift from the published contract.
SCHEMA_PATH = "data/schema/row.v4.json"


class SchemaKeys(NamedTuple):
    """What a v4 row is built from, derived from row.v4.json."""

    version: int
    required: frozenset[str]
    row: frozenset[str]
    rate_axes: frozenset[str]
    fees: frozenset[str]
    limits: frozenset[str]
    provenance: frozenset[str]
    when: frozenset[str]
    override: frozenset[str]
    days: frozenset[str]


# keyed by root, and a process sees one or two of those; an unbounded cache
# cannot evict the repo's own entry to serve a test's temp copy
@functools.cache
def load_schema_keys(root: Path) -> SchemaKeys:
    """Derive the v4 key sets from the committed schema, cached.

    Every key name comes from the schema's ``properties`` / ``$defs``; none is
    hardcoded. The weekday enum rides ``$defs/when/properties/days/items/enum``.
    ``root`` is the repo root, passed the way every other data path in this
    package reaches its caller.
    """
    path = root / SCHEMA_PATH
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValidationError(
            f"schema file '{path}' is missing; fix: restore {SCHEMA_PATH}"
        ) from None
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"schema file '{path}' is invalid json: {exc.msg}; fix: repair the file"
        ) from exc
    if not isinstance(schema, dict):
        raise ValidationError(f"schema file '{path}' must be a json object; fix: restore the file")
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise ValidationError(
            f"schema file '{path}' has no 'properties' object; fix: restore the file"
        )
    defs = schema.get("$defs")
    if not isinstance(defs, dict):
        raise ValidationError(f"schema file '{path}' has no '$defs' object; fix: restore the file")

    def key_set(node: object, what: str) -> frozenset[str]:
        if not isinstance(node, dict) or not isinstance(node.get("properties"), dict):
            raise ValidationError(
                f"schema file '{path}': '{what}' must carry a 'properties' object;"
                " fix: restore the file"
            )
        return frozenset(node["properties"])

    version = (properties.get("schema") or {}).get("const")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValidationError(
            f"schema file '{path}': 'properties.schema.const' must be an integer,"
            f" got {version!r}; fix: restore the file"
        )
    required = schema.get("required")
    if not isinstance(required, list) or not all(isinstance(key, str) for key in required):
        raise ValidationError(
            f"schema file '{path}': 'required' must be a list of key names; fix: restore the file"
        )
    when_node = defs.get("when")
    when_keys = key_set(when_node, "$defs/when")
    days_node = when_node["properties"].get("days")
    days_enum: Any = None
    if isinstance(days_node, dict):
        items = days_node.get("items")
        if isinstance(items, dict):
            days_enum = items.get("enum")
    if (
        not isinstance(days_enum, list)
        or not days_enum
        or not all(isinstance(day, str) for day in days_enum)
    ):
        raise ValidationError(
            f"schema file '{path}': '$defs/when/properties/days/items/enum' must be a"
            " non-empty list of weekday names; fix: restore the file"
        )
    return SchemaKeys(
        version=version,
        required=frozenset(required),
        row=frozenset(properties),
        rate_axes=key_set(defs.get("axes"), "$defs/axes"),
        fees=key_set(properties.get("fees"), "properties/fees"),
        limits=key_set(properties.get("limits"), "properties/limits"),
        provenance=key_set(properties.get("provenance"), "properties/provenance"),
        when=when_keys,
        override=key_set(defs.get("override"), "$defs/override"),
        days=frozenset(days_enum),
    )

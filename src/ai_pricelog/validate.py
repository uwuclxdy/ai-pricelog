"""Row-level checks that run before a price row is appended to the history.

The history is append-only, so a bad row lands forever. Only what our own
emission could corrupt is checked here: the model id (rows are keyed by
(source, model_id)), the price values, the quote provenance (currency, unit,
currency_rate), the peak-pricing shape, the scheduled window-rate shape, the
volume-threshold shape, the schedule timezone, and the removal-row shape
(removed=true only, never alongside price fields). The producers are the
store's build_row, build_removal_row, and openrouter.build_row.
"""

from __future__ import annotations

import math
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ValidationError(ValueError):
    """a row failed validation; the message names the field, bad value, fix."""


# the row-format version, mirrored by the committed data/schema.json (pinned by
# a test). a top-level key change bumps both: consumers detect the format change
# by version instead of by surprise.
SCHEMA_VERSION = 3

# every top-level key a produced row may carry; validate_row rejects anything
# else, so a new key cannot slide past without the version bump. the legacy
# `max_tokens` key is not producible (pre-split rows only) and stays out.
ROW_KEYS = frozenset(
    {
        "source",
        "model_id",
        "observed_at",
        "effective_at",
        "removed",
        "input_mtok",
        "output_mtok",
        "cache_read_mtok",
        "cache_write_mtok",
        "cache_write_1h_mtok",
        "max_tokens_in",
        "max_tokens_out",
        "peak_windows",
        "peak_input_mtok",
        "peak_output_mtok",
        "peak_cache_read_mtok",
        "window_rates",
        "volume_rates",
        "web_search_usd",
        "image_mtok",
        "audio_mtok",
        "input_audio_cache_mtok",
        "internal_reasoning_mtok",
        "image_output_mtok",
        "audio_output_mtok",
        "timezone",
        "name",
        "extra",
        "url",
        "currency",
        "unit",
        "currency_rate",
        "currency_rate_date",
    }
)

_PRICE_FIELDS = (
    "input_mtok",
    "output_mtok",
    "cache_read_mtok",
    "cache_write_mtok",
    "cache_write_1h_mtok",
    "image_mtok",
    "audio_mtok",
    "input_audio_cache_mtok",
    "internal_reasoning_mtok",
    "image_output_mtok",
    "audio_output_mtok",
)
_PEAK_PRICE_FIELDS = ("peak_input_mtok", "peak_output_mtok", "peak_cache_read_mtok")
_WINDOW_DAYS = frozenset(
    {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
)
_WINDOW_ENTRY_KEYS = frozenset({*_PRICE_FIELDS, "days", "window", "quota_multiplier"})
_VOLUME_ENTRY_KEYS = frozenset({*_PRICE_FIELDS, "min_tokens"})


def validate_row(row: dict[str, Any]) -> None:
    unknown = set(row) - ROW_KEYS
    if unknown:
        raise ValidationError(
            f"row field(s) {sorted(unknown)!r} are not part of the row schema;"
            " fix: drop them, or extend the schema and bump the version in"
            " validate.py and data/schema.json"
        )
    model_id = row.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        raise ValidationError("row field 'model_id' must be a non-empty string")
    if "removed" in row:
        removed = row["removed"]
        if not isinstance(removed, bool) or removed is not True:
            raise ValidationError(
                f"row field 'removed' has bad value {removed!r}; fix: only true is valid"
            )
        # a removal row carries the final price snapshot; every price field
        # it does carry must still be a valid one, so fall through
    currency = row.get("currency")
    if currency is not None and (
        not isinstance(currency, str) or re.fullmatch(r"[A-Z]{3}", currency) is None
    ):
        raise ValidationError(
            f"row field 'currency' has bad value {currency!r}; fix: a 3-letter uppercase code"
        )
    unit = row.get("unit")
    if unit is not None and (not isinstance(unit, str) or re.fullmatch(r"[a-z-]+", unit) is None):
        raise ValidationError(
            f"row field 'unit' has bad value {unit!r}; fix: lowercase letters and dashes"
        )
    non_usd = currency is not None and currency != "USD"
    rate = row.get("currency_rate")
    rate_date = row.get("currency_rate_date")
    if non_usd:
        if (
            isinstance(rate, bool)
            or not isinstance(rate, (int, float))
            or not math.isfinite(rate)
            or rate <= 0
        ):
            raise ValidationError(
                f"row field 'currency_rate' has bad value {rate!r} for currency"
                f" {currency!r}; fix: a finite float > 0"
            )
    elif rate is not None or rate_date is not None:
        raise ValidationError(
            "row field 'currency_rate' and 'currency_rate_date' are only valid"
            " with a non-USD 'currency'; fix: drop them or set currency"
        )
    if rate_date is not None and (
        not isinstance(rate_date, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", rate_date) is None
    ):
        raise ValidationError(
            f"row field 'currency_rate_date' has bad value {rate_date!r}; fix: YYYY-MM-DD"
        )
    effective = row.get("effective_at")
    if effective is not None and (
        not isinstance(effective, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", effective) is None
    ):
        raise ValidationError(
            f"row field 'effective_at' has bad value {effective!r}; fix: YYYY-MM-DD"
        )
    for field in _PRICE_FIELDS:
        value = row.get(field)
        if value is None:
            continue  # openrouter free rows carry no input/output prices
        _check_price(row, field, value)
    search_fee = row.get("web_search_usd")
    if search_fee is not None:
        _check_price(row, "web_search_usd", search_fee)
    if any(field in row for field in _PEAK_PRICE_FIELDS) or "peak_windows" in row:
        windows = row.get("peak_windows")
        if not isinstance(windows, list) or not windows:
            raise ValidationError(
                "row field 'peak_windows' must be a non-empty list when peak prices are set"
            )
        for window in windows:
            if (
                not isinstance(window, list)
                or len(window) != 2
                or not all(isinstance(part, str) and part for part in window)
            ):
                raise ValidationError(
                    f"row field 'peak_windows' has bad window {window!r}; "
                    "fix: use [start, end] string pairs"
                )
        for field in _PEAK_PRICE_FIELDS:
            value = row.get(field)
            if value is not None:
                _check_price(row, field, value)
    if "window_rates" in row:
        _check_window_rates(row)
    if "volume_rates" in row:
        _check_volume_rates(row)
    timezone = row.get("timezone")
    if timezone is not None:
        if "window_rates" not in row:
            raise ValidationError(
                "row field 'timezone' is only valid beside 'window_rates';"
                " fix: drop it or add a schedule"
            )
        if not isinstance(timezone, str):
            raise ValidationError(
                f"row field 'timezone' has bad value {timezone!r}; fix: an IANA zone name"
            )
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValidationError(
                f"row field 'timezone' has unknown zone {timezone!r}; fix: an IANA zone name"
            ) from exc


def _check_window_rates(row: dict[str, Any]) -> None:
    entries = row.get("window_rates")
    if not isinstance(entries, list) or not entries:
        raise ValidationError(
            "row field 'window_rates' must be a non-empty list of schedule entries"
        )
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValidationError(
                f"row field 'window_rates' has bad entry {entry!r}; fix: use an object"
            )
        unknown = set(entry) - _WINDOW_ENTRY_KEYS
        if unknown:
            raise ValidationError(
                f"row field 'window_rates' has unknown key(s) {sorted(unknown)!r};"
                " fix: drop them or extend the schema"
            )
        days = entry.get("days")
        if days is not None and (
            not isinstance(days, list)
            or not days
            or not all(isinstance(day, str) and day in _WINDOW_DAYS for day in days)
        ):
            raise ValidationError(
                f"row field 'window_rates' has bad day-set {days!r};"
                " fix: weekday names like ['monday', 'saturday']"
            )
        window = entry.get("window")
        if window is not None and (
            not isinstance(window, list)
            or len(window) != 2
            or any(isinstance(part, bool) or not isinstance(part, int) for part in window)
            or not 0 <= window[0] < window[1] <= 2400
            or window[0] % 100 > 59
            or window[1] % 100 > 59
        ):
            raise ValidationError(
                f"row field 'window_rates' has bad window {window!r};"
                " fix: [start, end] HHMM clock numbers with minutes under 60,"
                " start < end, end at most 2400"
            )
        multiplier = entry.get("quota_multiplier")
        if multiplier is not None and (
            isinstance(multiplier, bool)
            or not isinstance(multiplier, (int, float))
            or not math.isfinite(multiplier)
            or multiplier <= 0
        ):
            raise ValidationError(
                f"row field 'window_rates' entry has bad quota_multiplier"
                f" {multiplier!r}; fix: a finite float > 0"
            )
        rates = {field: entry[field] for field in _PRICE_FIELDS if field in entry}
        if rates and days is None and window is None:
            # a rate override must be scheduled; a multiplier-only entry may
            # cover the whole day by design (zai's whole-day quota weight)
            raise ValidationError(
                "row field 'window_rates' entry needs a 'days' set or a 'window';"
                " fix: keep at least one schedule condition"
            )
        if not rates and "quota_multiplier" not in entry:
            raise ValidationError(
                "row field 'window_rates' entry carries no rates and no"
                " quota_multiplier; fix: map at least one override price key"
                " or a multiplier"
            )
        for field, value in rates.items():
            _check_container_rate(row, "window_rates", field, value)


def _check_volume_rates(row: dict[str, Any]) -> None:
    """volume threshold overrides: min_tokens + per-rate mtok keys."""
    entries = row.get("volume_rates")
    if not isinstance(entries, list) or not entries:
        raise ValidationError(
            "row field 'volume_rates' must be a non-empty list of threshold entries"
        )
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValidationError(
                f"row field 'volume_rates' has bad entry {entry!r}; fix: use an object"
            )
        unknown = set(entry) - _VOLUME_ENTRY_KEYS
        if unknown:
            raise ValidationError(
                f"row field 'volume_rates' has unknown key(s) {sorted(unknown)!r};"
                " fix: drop them or extend the schema"
            )
        min_tokens = entry.get("min_tokens")
        if isinstance(min_tokens, bool) or not isinstance(min_tokens, int) or min_tokens <= 0:
            raise ValidationError(
                f"row field 'volume_rates' entry has bad min_tokens {min_tokens!r};"
                " fix: a positive integer"
            )
        rates = {field: entry[field] for field in _PRICE_FIELDS if field in entry}
        if not rates:
            raise ValidationError(
                "row field 'volume_rates' entry carries no rates;"
                " fix: map at least one override price key"
            )
        for field, value in rates.items():
            _check_container_rate(row, "volume_rates", field, value)


def _check_container_rate(row: dict[str, Any], container: str, field: str, value: Any) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, float)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValidationError(
            f"row field '{container}' entry rate '{field}' has bad value"
            f" {value!r}; fix: use a finite float > 0"
        )


def _check_price(row: dict[str, Any], field: str, value: Any) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, float)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValidationError(
            f"row field '{field}' has bad value {value!r}; fix: use a finite float >= 0"
        )

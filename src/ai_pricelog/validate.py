"""Row-level checks that run before a price row is appended to the history.

The history is append-only, so a bad row lands forever. Only what our own
emission could corrupt is checked here: the model id (rows are keyed by
(source, model_id)), the price values, the quote provenance (currency, unit,
currency_rate), the peak-pricing shape, and the removal-row shape
(removed=true only, never alongside price fields). The producers are the
store's build_row, build_removal_row, and openrouter.build_row.
"""

from __future__ import annotations

import math
import re
from typing import Any


class ValidationError(ValueError):
    """a row failed validation; the message names the field, bad value, fix."""


_PRICE_FIELDS = (
    "input_mtok",
    "output_mtok",
    "cache_read_mtok",
    "cache_write_mtok",
    "cache_write_1h_mtok",
)
_PEAK_PRICE_FIELDS = ("peak_input_mtok", "peak_output_mtok", "peak_cache_read_mtok")
# a removal row is provenance only: any pricing data beside it is junk
_REMOVAL_FORBIDDEN = (
    "input_mtok",
    "output_mtok",
    "cache_read_mtok",
    "cache_write_mtok",
    "cache_write_1h_mtok",
    "peak_windows",
    "peak_input_mtok",
    "peak_output_mtok",
    "peak_cache_read_mtok",
    "currency",
    "unit",
    "currency_rate",
    "currency_rate_date",
)


def validate_row(row: dict[str, Any]) -> None:
    model_id = row.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        raise ValidationError("row field 'model_id' must be a non-empty string")
    if "removed" in row:
        removed = row["removed"]
        if not isinstance(removed, bool) or removed is not True:
            raise ValidationError(
                f"row field 'removed' has bad value {removed!r}; fix: only true is valid"
            )
        for field in _REMOVAL_FORBIDDEN:
            if field in row:
                raise ValidationError(
                    f"row field '{field}' is not allowed on a removed row; fix: drop it"
                )
        return
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
    for field in _PRICE_FIELDS:
        value = row.get(field)
        if value is None:
            continue  # openrouter free rows carry no input/output prices
        _check_price(row, field, value)
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

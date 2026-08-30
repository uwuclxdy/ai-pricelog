"""the Pricing dataclass scrapers return, and per-token conversion helpers.

The per-token costs are quoted in `currency` per `unit`; store.build_row
converts non-USD quotes into the USD mtok row fields.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pricing:
    # max_tokens_in keeps the slot the legacy max_tokens held, so positional
    # constructions keep their meaning; max_tokens_out is keyword-only
    input_cost_per_token: float
    output_cost_per_token: float
    mode: str
    max_tokens_in: int = 0
    cache_read_cost_per_token: float | None = None
    peak_input_cost_per_token: float | None = None
    peak_output_cost_per_token: float | None = None
    peak_windows: tuple[tuple[int, int], ...] = ()
    peak_cache_read_cost_per_token: float | None = None
    max_tokens_out: int = 0
    # the page the rate was read from, when it is not the scraper's own url
    # (moonshot reads the index to resolve a per-model page); build_row stamps
    # it as the row's provenance url
    url: str | None = None
    # cache-write tiers (5m default + 1h); appended after url so positional
    # constructions of the pre-existing prefix keep their meaning
    cache_write_cost_per_token: float | None = None
    cache_write_1h_cost_per_token: float | None = None
    currency: str = "USD"
    unit: str = "tokens"
    # the date the quote becomes effective, when the source announces one
    # ahead of time; None = valid at observation. consumers clamp rows to
    # effective <= the query date
    effective_at: str | None = None
    # weekday days of the peak windows (lowercase names, calendar order);
    # empty = every day
    peak_days: tuple[str, ...] = ()
    # pre-built window_rates entries (e.g. zai's quota multipliers); build_row
    # appends them after the peak-derived entries. entries carry rate keys, a
    # quota_multiplier, or both
    window_rates: tuple[dict[str, object], ...] = ()


def to_mtok(per_token: float) -> float:
    """Per-token dollars -> per-megatoken dollars, rounded to 6 decimals."""
    return round(per_token * 1_000_000, 6)

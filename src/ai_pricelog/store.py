"""Append-only model history: one compact ndjson row per line plus a generated index.

Price rows carry the pricing fields; a removal row marks a model delisted
from its source. The index entry keeps the last priced row's fields and gains
a removed_at stamp while the newest row for the key is a removal. Non-USD
quotes convert to USD at row build through an fx resolver backed by the
committed fx table and the provider's configured rate.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path

from ai_pricelog.pricing import Pricing, to_mtok
from ai_pricelog.validate import SCHEMA_VERSION


class FxError(ValueError):
    """an fx rate needed to convert a quote is missing or malformed."""


def load(path: Path) -> list[dict[str, object]]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    return parse(text, str(path))


def parse(text: str, label: str) -> list[dict[str, object]]:
    """Parse ndjson rows from text; errors name the label and the line."""
    rows: list[dict[str, object]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"history file '{label}': line {number}: invalid json: {exc.msg}"
            ) from exc
        if not isinstance(row, dict):
            raise ValueError(f"history file '{label}': line {number}: must be an object")
        rows.append(row)
    return rows


def save(rows: list[dict[str, object]], path: Path) -> None:
    payload = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows
    )
    _atomic_write(payload, path)


def union(rows: list[dict[str, object]], extra: list[dict[str, object]]) -> list[dict[str, object]]:
    """rows plus the extra rows not already present, keyed by (source, model_id, observed_at).

    Pending PR branches each carry a full store snapshot, so their union over
    the loaded store repeats every load-time row; the key dedupe collapses
    those while keeping the rows unique to a pending branch. a removal row
    dedupes against removal rows only: it must survive a same-day landed price
    row sharing its key (the price row must not hide the removal), but a
    carried copy of an already-union'd removal appends nothing, since one
    removal row per key ever is the store's invariant.
    """
    seen = {(row.get("source"), row.get("model_id"), row.get("observed_at")) for row in rows}
    removed_keys = {
        (row.get("source"), row.get("model_id"), row.get("observed_at"))
        for row in rows
        if row.get("removed") is True
    }
    merged = list(rows)
    for row in extra:
        key = (row.get("source"), row.get("model_id"), row.get("observed_at"))
        if row.get("removed") is True:
            if key in removed_keys:
                continue
            removed_keys.add(key)
            seen.add(key)
            merged.append(row)
            continue
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def last(rows: list[dict[str, object]], source: str, model_id: str) -> dict[str, object] | None:
    """The last priced row for the key: removal rows never feed price diffs."""
    for row in reversed(rows):
        if (
            row["source"] == source
            and row["model_id"] == model_id
            and row.get("removed") is not True
        ):
            return row
    return None


def load_fx(path: Path) -> dict[str, dict[str, float]]:
    """Committed per-currency dated USD rates; a missing file is an empty table."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FxError(f"fx file '{path}': invalid json: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise FxError(f"fx file '{path}': must be an object of currency -> date -> rate")
    fx: dict[str, dict[str, float]] = {}
    for currency, dated in data.items():
        if not isinstance(dated, dict):
            raise FxError(f"fx file '{path}': currency '{currency}' must map dates to rates")
        rates: dict[str, float] = {}
        for day, rate in dated.items():
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) is None:
                raise FxError(
                    f"fx file '{path}': date '{day}' for currency '{currency}' must be YYYY-MM-DD"
                )
            if (
                isinstance(rate, bool)
                or not isinstance(rate, (int, float))
                or not math.isfinite(rate)
                or rate <= 0
            ):
                raise FxError(
                    f"fx file '{path}': rate for '{currency}' on {day} must be a finite float > 0"
                )
            rates[day] = float(rate)
        fx[currency] = rates
    return fx


def resolve_rate(
    fx: dict[str, dict[str, float]],
    provider_rate: float | None,
    currency: str,
    observed_at: str,
) -> tuple[float, str] | None:
    """The USD-per-unit rate and its date for a non-USD quote, None for USD.

    FX currencies resolve to the latest dated entry on or before the
    observation; DBU resolves to the provider's configured rate, dated with
    the observation itself, and never consults the fx table.
    """
    if currency == "USD":
        return None
    if currency == "DBU":
        if provider_rate is None:
            raise FxError(
                f"no fx rate for currency {currency!r}; fix: set currency_rate in providers.toml"
            )
        return provider_rate, observed_at[:10]
    dated = fx.get(currency)
    if dated is not None:
        day = max((d for d in dated if d <= observed_at[:10]), default="")
        if not day:
            raise FxError(
                f"no fx rate for {currency!r} on or before {observed_at[:10]};"
                " fix: add a dated entry to data/fx-rates.json"
            )
        return dated[day], day
    raise FxError(f"no fx rate for currency {currency!r}; fix: add it to data/fx-rates.json")


def newest(rows: list[dict[str, object]], source: str, model_id: str) -> dict[str, object] | None:
    """The newest row for the key, removal rows included."""
    for row in reversed(rows):
        if row["source"] == source and row["model_id"] == model_id:
            return row
    return None


# provenance fields describe where a row came from, never what it costs; a
# difference in them alone is not an observed price change. currency_rate /
# currency_rate_date are conversion provenance: a rate refresh with unchanged
# USD prices must not append a row
_PROVENANCE_FIELDS = frozenset(
    {"observed_at", "url", "name", "currency_rate", "currency_rate_date"}
)


def _comparable(row: dict[str, object]) -> dict[str, object]:
    """The row minus provenance, with the legacy max_tokens key renamed.

    rows before 2026-08-27 store the context window (deepseek: max output)
    under `max_tokens`; the split into `max_tokens_in` / `max_tokens_out`
    renamed the field. treating the legacy key as `max_tokens_in` keeps the
    rename from reading as a price change on the next re-scrape of every
    still-legacy row.
    """
    fields = {k: v for k, v in row.items() if k not in _PROVENANCE_FIELDS}
    if "max_tokens" in fields and "max_tokens_in" not in fields:
        fields["max_tokens_in"] = fields.pop("max_tokens")
    return fields


def changed(row: dict[str, object], last_row: dict[str, object] | None) -> bool:
    if last_row is None or last_row.get("removed") is True:
        return True
    return _comparable(row) != _comparable(last_row)


def write_index(rows: list[dict[str, object]], path: Path) -> None:
    first_seen: dict[tuple[str, str], str] = {}
    priced: dict[tuple[str, str], dict[str, object]] = {}
    newest: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        key = (row["source"], row["model_id"])
        observed_at = row["observed_at"]
        # rows are appended in observation order, but a backfill can land an
        # older timestamp later; keep the earliest seen rather than the first
        if key not in first_seen or observed_at < first_seen[key]:
            first_seen[key] = observed_at
        # pick the newest observed_at; ties resolve to the later row in the
        # file, so the index never depends on the file's global sort. a
        # removal row competes for newest (it stamps removed_at) but never
        # for the entry's own fields
        if row.get("removed") is True:
            if key not in newest or observed_at >= newest[key]["observed_at"]:
                newest[key] = row
        else:
            if key not in priced or observed_at >= priced[key]["observed_at"]:
                priced[key] = row
            if key not in newest or observed_at >= newest[key]["observed_at"]:
                newest[key] = row
    sources: dict[str, dict[str, dict[str, object]]] = {}
    for (source, model_id), row in sorted(newest.items()):
        base = priced.get((source, model_id))
        if base is None:
            # removal rows only ever follow a priced row for the key; fall
            # back to the removal's own provenance fields if one sneaks in
            base = {k: v for k, v in row.items() if k != "removed"}
        entry = dict(base)
        entry["first_seen"] = first_seen[(source, model_id)]
        if row.get("removed") is True:
            entry["removed_at"] = row["observed_at"]
        sources.setdefault(source, {})[model_id] = entry
    _atomic_write(
        json.dumps({"sources": sources, "version": SCHEMA_VERSION}, ensure_ascii=False) + "\n",
        path,
    )


def build_row(
    source: str,
    model_id: str,
    pricing: Pricing,
    observed_at: str,
    url: str,
    resolve: Callable[[str, str], tuple[float, str] | None] | None = None,
) -> dict[str, object]:
    """Build one price row: every mtok price field holds USD.

    `resolve` maps a non-USD quote currency to its USD rate and the rate's
    date; without one, a non-USD quote is refused instead of passing through
    unconverted. max_tokens fields are never converted. a non-token unit
    (per-minute, per-character) is refused: the mtok fields price tokens,
    and a converted non-token price would misstate the billing axis.
    """
    if pricing.unit != "tokens":
        raise ValueError(
            f"cannot build a row for unit {pricing.unit!r}: non-token units stay"
            " out of the index; fix: drop the model in the scraper instead of"
            " converting a non-token price into mtok fields"
        )
    conversion = None
    if pricing.currency != "USD":
        if resolve is None:
            raise FxError(
                f"cannot convert {pricing.currency!r} quote to USD without an fx"
                " resolver; fix: pass one to build_row"
            )
        conversion = resolve(pricing.currency, observed_at)
    factor = 1.0 if conversion is None else conversion[0]
    row: dict[str, object] = {
        "source": source,
        "model_id": model_id,
        "observed_at": observed_at,
    }
    if pricing.currency != "USD":
        row["currency"] = pricing.currency
    if pricing.effective_at is not None:
        row["effective_at"] = pricing.effective_at
    if conversion is not None:
        row["currency_rate"] = conversion[0]
        row["currency_rate_date"] = conversion[1]
    row["input_mtok"] = to_mtok(pricing.input_cost_per_token * factor)
    row["output_mtok"] = to_mtok(pricing.output_cost_per_token * factor)
    if pricing.cache_read_cost_per_token is not None:
        row["cache_read_mtok"] = to_mtok(pricing.cache_read_cost_per_token * factor)
    if pricing.cache_write_cost_per_token is not None:
        row["cache_write_mtok"] = to_mtok(pricing.cache_write_cost_per_token * factor)
    if pricing.cache_write_1h_cost_per_token is not None:
        row["cache_write_1h_mtok"] = to_mtok(pricing.cache_write_1h_cost_per_token * factor)
    if pricing.max_tokens_in > 0:
        row["max_tokens_in"] = pricing.max_tokens_in
    if pricing.max_tokens_out > 0:
        row["max_tokens_out"] = pricing.max_tokens_out
    peak_rates = {
        field: to_mtok(cost * factor)
        for field, cost in (
            ("input_mtok", pricing.peak_input_cost_per_token),
            ("output_mtok", pricing.peak_output_cost_per_token),
            ("cache_read_mtok", pricing.peak_cache_read_cost_per_token),
        )
        if cost is not None
    }
    if peak_rates:
        # the peak schedule lands as window_rates entries: the base mtok
        # fields stay the off-peak default, one entry per window overrides
        # them. no assert on peak_windows here: the row must build even when
        # the scrape left the windows empty, so validate.validate_row rejects
        # THIS row instead of an AssertionError killing the whole run
        entries: list[dict[str, object]] = []
        for window in pricing.peak_windows or (None,):
            entry: dict[str, object] = {}
            if window is not None:
                entry["window"] = list(window)
            if pricing.peak_days:
                entry["days"] = list(pricing.peak_days)
            entry.update(peak_rates)
            entries.append(entry)
        row["window_rates"] = entries
    row["url"] = pricing.url or url
    return row


def build_removal_row(source: str, model_id: str, observed_at: str) -> dict[str, object]:
    """The removal row: one per (source, model_id) ever, no price fields."""
    return {"source": source, "model_id": model_id, "observed_at": observed_at, "removed": True}


def _atomic_write(payload: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, path)
        tmp_name = None
    finally:
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)

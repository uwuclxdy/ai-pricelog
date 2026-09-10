"""Append-only model history: one compact ndjson shard per source plus a generated index.

Price rows carry the v4 pricing shape; a removal row marks a model delisted
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
from typing import TypedDict

from ai_pricelog.pricing import Pricing, to_mtok


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


SHARD_DIR = "data/history"

# a source names a shard file, so it must be one plain path segment
_SAFE_SOURCE = re.compile(r"[a-z0-9][a-z0-9_-]*")


def shard_name(source: object) -> str:
    """The shard filename for a source, refusing anything but one path segment.

    A source reaches a filesystem path here and _atomic_write creates parent
    directories, so an unchecked value writes wherever it points.
    """
    if not isinstance(source, str) or _SAFE_SOURCE.fullmatch(source) is None:
        raise ValueError(
            f"source {source!r} cannot name a shard file;"
            " fix: lowercase letters, digits, '_' and '-', starting alphanumeric"
        )
    return f"{source}.ndjson"


def load_shards(directory: Path) -> list[dict[str, object]]:
    """Every shard row, in filename order, concatenated."""
    rows: list[dict[str, object]] = []
    for path in sorted(directory.glob("*.ndjson")):
        rows.extend(load(path))
    return rows


def load_shard(directory: Path, source: str) -> list[dict[str, object]]:
    """The rows of one source's shard."""
    return load(directory / shard_name(source))


def _shard_order(row: dict[str, object]) -> tuple[str, str]:
    """Shard sort key: a new row lands beside its siblings in the review diff."""
    return (str(row["model_id"]), str(row["observed_at"]))


def save_shard(rows: list[dict[str, object]], directory: Path, source: str) -> None:
    """Write one source's shard, sorted by (model_id, observed_at)."""
    save(sorted(rows, key=_shard_order), directory / shard_name(source))


def union(rows: list[dict[str, object]], extra: list[dict[str, object]]) -> list[dict[str, object]]:
    """rows plus the extra rows not already present, keyed by (source, model_id, observed_at).

    The key dedupe collapses repeated rows across the two inputs while keeping
    the rows unique to `extra`. a removal row dedupes against removal rows
    only: it must survive a same-day landed price row sharing its key (the
    price row must not hide the removal), but a carried copy of an
    already-union'd removal appends nothing, since one removal row per key
    ever is the store's invariant.
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
                " fix: add a dated entry to data/catalog/fx-rates.json"
            )
        return dated[day], day
    raise FxError(
        f"no fx rate for currency {currency!r}; fix: add it to data/catalog/fx-rates.json"
    )


def newest(rows: list[dict[str, object]], source: str, model_id: str) -> dict[str, object] | None:
    """The newest row for the key, removal rows included."""
    for row in reversed(rows):
        if row["source"] == source and row["model_id"] == model_id:
            return row
    return None


# three names, not a maintained field list: a new pricing key lands inside
# `rates`, so it joins the comparable diff without anyone remembering to add
# it here.
_PROVENANCE_KEYS = frozenset({"schema", "observed_at", "provenance"})


def _comparable(row: dict[str, object]) -> dict[str, object]:
    """The row minus the version stamp, the observation date, and provenance."""
    return {k: v for k, v in row.items() if k not in _PROVENANCE_KEYS}


def changed(row: dict[str, object], last_row: dict[str, object] | None) -> bool:
    if last_row is None or last_row.get("removed") is True:
        return True
    return _comparable(row) != _comparable(last_row)


class Partition(TypedDict):
    """The published view's per-key partition, one consumer for every view."""

    first_seen: dict[tuple[str, str], str]
    priced: dict[tuple[str, str], dict[str, object]]
    newest: dict[tuple[str, str], dict[str, object]]
    intervals: dict[tuple[str, str], list[dict[str, object]]]
    # row object identity -> its chain item; resolves an entry's own interval
    # exactly where a (observed_at, removed) filter is ambiguous
    row_items: dict[tuple[str, str], dict[int, dict[str, object]]]


# the interval item emits the pair, the observation stamp, then the row's own
# pricing fields when present; provenance and the key's identity stay out, the
# same surface rule as the flat export's row fields, minus the removal row's
# copied effective_at: it is a snapshot artifact and would contradict the
# item's own valid_from (the delisting starts at the removal's observed_at).
_INTERVAL_ROW_FIELDS = ("currency", "rates", "overrides", "limits", "fees")


def _derive_intervals(
    rows: list[dict[str, object]], source: str, model_id: str
) -> tuple[list[dict[str, object]], dict[int, dict[str, object]]]:
    """The validity chain for one key's rows, input order, sorted by valid_from,
    plus an id(row) -> that row's own item side index.

    A row starts at (effective_at ?? observed_at) — a removal row at its own
    observed_at, its copied effective_at is a snapshot artifact — and ends at
    the earliest start among the rows dominating it (greater observed_at, or
    equal observed_at and later input position); the open end stays null. A
    dominated row whose end lands on or before its start clamps to an empty
    interval, which prices no day. The removal item closes like any other:
    open-ended only when the removal is the key's newest row, closed at the
    revival row's start when a later-observed price row reopens the key.

    The side index is the identity the published views match their entry's
    own interval through — exact where a (observed_at, removed) filter is
    not, since same-day priced peers can clamp to different ends. it MUST be
    built before the sort reorders the chain, or a row maps to a peer's item.
    """
    starts: list[str] = []
    for position, row in enumerate(rows):
        observed_at = row.get("observed_at")
        effective_at = row.get("effective_at")
        if not isinstance(observed_at, str) or (
            effective_at is not None and not isinstance(effective_at, str)
        ):
            raise ValueError(
                f"cannot derive validity intervals for ({source!r}, {model_id!r}):"
                f" row {position} has an unorderable observed_at/effective_at: {row!r};"
                " fix: every row carries a YYYY-MM-DD observed_at and an optional"
                " YYYY-MM-DD effective_at"
            )
        if row.get("removed") is True:
            starts.append(observed_at)
        else:
            starts.append(observed_at if effective_at is None else effective_at)
    items: list[dict[str, object]] = []
    for position, row in enumerate(rows):
        valid_from = starts[position]
        valid_to: str | None = None
        for other_position, other in enumerate(rows):
            if other_position == position:
                continue
            dominates = other["observed_at"] > row["observed_at"] or (
                other["observed_at"] == row["observed_at"] and other_position > position
            )
            if dominates and (valid_to is None or starts[other_position] < valid_to):
                valid_to = starts[other_position]
        if valid_to is not None and valid_to <= valid_from:
            valid_to = valid_from
        item: dict[str, object] = {
            "valid_from": valid_from,
            "valid_to": valid_to,
            "observed_at": row["observed_at"],
        }
        for field in _INTERVAL_ROW_FIELDS:
            if field in row:
                item[field] = row[field]
        if row.get("removed") is True:
            item["removed"] = True
        items.append(item)
    row_items = {id(row): item for row, item in zip(rows, items, strict=True)}
    items.sort(key=lambda item: item["valid_from"])
    return items, row_items


def _interval_of(
    row_items: dict[int, dict[str, object]], row: dict[str, object]
) -> dict[str, object]:
    """The chain item whose source row is `row`, matched by object identity.

    A (observed_at, removed) filter plus a max would pair one row's rates
    with a same-observed_at peer's window when the peers clamp to different
    ends, so the match runs on the row object itself. the entry row is
    always a member of the chain; a miss is a derivation bug and raises
    rather than guessing.
    """
    try:
        return row_items[id(row)]
    except KeyError:
        raise ValueError(f"no interval item matches the entry row: {row!r}") from None


def current(rows: list[dict[str, object]]) -> Partition:
    """The published view's partition: per (source, model_id), the newest
    priced row, the newest row overall (removals included), first_seen, and
    the validity interval chain.

    Ties resolve to the later row in the input, so the view never depends on
    the caller's sort order. Every consumer of "the current price of a key"
    reads this one partition: `write_index` builds the nested index from it,
    the flat export resolves names, rates and intervals from it, and no second
    implementation of the rule can drift from it.
    """
    first_seen: dict[tuple[str, str], str] = {}
    priced: dict[tuple[str, str], dict[str, object]] = {}
    newest: dict[tuple[str, str], dict[str, object]] = {}
    key_rows: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        key = (row["source"], row["model_id"])
        observed_at = row["observed_at"]
        key_rows.setdefault(key, []).append(row)
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
    derived = {key: _derive_intervals(group, key[0], key[1]) for key, group in key_rows.items()}
    return {
        "first_seen": first_seen,
        "priced": priced,
        "newest": newest,
        "intervals": {key: chain for key, (chain, _) in derived.items()},
        "row_items": {key: index for key, (_, index) in derived.items()},
    }


def write_index(rows: list[dict[str, object]], path: Path, schema_version: int) -> None:
    """Build the published index: the newest priced row per key plus first_seen
    and the entry's own validity interval."""
    partition = current(rows)
    first_seen = partition["first_seen"]
    priced = partition["priced"]
    newest = partition["newest"]
    row_items = partition["row_items"]
    sources: dict[str, dict[str, dict[str, object]]] = {}
    for (source, model_id), row in sorted(newest.items()):
        base = priced.get((source, model_id))
        # the entry's own row: the newest priced row, or the removal itself
        # when one sneaks in without a priced row before it
        entry_row = base if base is not None else row
        if base is None:
            # removal rows only ever follow a priced row for the key; fall
            # back to the removal's own comparable fields if one sneaks in
            base = {k: v for k, v in row.items() if k != "removed"}
        entry = dict(base)
        entry["first_seen"] = first_seen[(source, model_id)]
        item = _interval_of(row_items[(source, model_id)], entry_row)
        entry["valid_from"] = item["valid_from"]
        entry["valid_to"] = item["valid_to"]
        if row.get("removed") is True:
            entry["removed_at"] = row["observed_at"]
        sources.setdefault(source, {})[model_id] = entry
    _atomic_write(
        json.dumps({"sources": sources, "version": schema_version}, ensure_ascii=False) + "\n",
        path,
    )


_RATE_SUFFIX = "_mtok"


def build_row(
    source: str,
    model_id: str,
    pricing: Pricing,
    observed_at: str,
    url: str,
    schema_version: int,
    resolve: Callable[[str, str], tuple[float, str] | None] | None = None,
) -> dict[str, object]:
    """Build one v4 price row: every rate axis holds USD.

    `resolve` maps a non-USD quote currency to its USD rate and the rate's
    date; without one, a non-USD quote is refused instead of passing through
    unconverted. limit fields are never converted. a non-token unit
    (per-minute, per-character) is refused: the rate axes price tokens, and a
    converted non-token price would misstate the billing axis.
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

    rates: dict[str, object] = {
        "input": to_mtok(pricing.input_cost_per_token * factor),
        "output": to_mtok(pricing.output_cost_per_token * factor),
    }
    if pricing.cache_read_cost_per_token is not None:
        rates["cache_read"] = to_mtok(pricing.cache_read_cost_per_token * factor)
    if pricing.cache_write_cost_per_token is not None:
        rates["cache_write"] = to_mtok(pricing.cache_write_cost_per_token * factor)
    if pricing.cache_write_1h_cost_per_token is not None:
        rates["cache_write_1h"] = to_mtok(pricing.cache_write_1h_cost_per_token * factor)

    limits: dict[str, object] = {}
    if pricing.max_tokens_in > 0:
        limits["context"] = pricing.max_tokens_in
    if pricing.max_tokens_out > 0:
        limits["output"] = pricing.max_tokens_out

    overrides: list[dict[str, object]] = []
    peak_rates = {
        axis: to_mtok(cost * factor)
        for axis, cost in (
            ("input", pricing.peak_input_cost_per_token),
            ("output", pricing.peak_output_cost_per_token),
            ("cache_read", pricing.peak_cache_read_cost_per_token),
        )
        if cost is not None
    }
    if peak_rates:
        for window in pricing.peak_windows or (None,):
            when: dict[str, object] = {}
            if window is not None:
                when["window"] = list(window)
            if pricing.peak_days:
                when["days"] = list(pricing.peak_days)
            if when and pricing.timezone is not None:
                when["timezone"] = pricing.timezone
            override: dict[str, object] = {"rates": dict(peak_rates)}
            if when:
                override["when"] = when
            # no assert on an empty `when`: a scrape that found peak costs but
            # no schedule must still BUILD, so validate_row rejects this one
            # row and the run skips the model, instead of an error killing it
            overrides.append(override)
    for entry in pricing.window_rates:
        when = {}
        if "days" in entry:
            when["days"] = entry["days"]
        if "window" in entry:
            when["window"] = entry["window"]
        if when and pricing.timezone is not None:
            when["timezone"] = pricing.timezone
        # the scraper hands these already per-million, so they take the fx
        # factor the same way the base rates do; without it a non-USD provider
        # with a scheduled rate would store source-currency values as USD
        entry_rates = {
            key[: -len(_RATE_SUFFIX)]: round(value * factor, 6)
            for key, value in entry.items()
            if key.endswith(_RATE_SUFFIX) and isinstance(value, (int, float))
        }
        override = {}
        if when:
            override["when"] = when
        if entry_rates:
            override["rates"] = entry_rates
        if "quota_multiplier" in entry:
            override["quota_multiplier"] = entry["quota_multiplier"]
        overrides.append(override)

    row: dict[str, object] = {
        "schema": schema_version,
        "source": source,
        "model_id": model_id,
        "observed_at": observed_at,
    }
    if pricing.effective_at is not None:
        row["effective_at"] = pricing.effective_at
    if pricing.currency != "USD":
        row["currency"] = pricing.currency
    row["rates"] = rates
    if overrides:
        row["overrides"] = overrides
    if limits:
        row["limits"] = limits
    provenance: dict[str, object] = {"url": pricing.url or url}
    if conversion is not None:
        provenance["fx_rate"] = conversion[0]
        provenance["fx_rate_date"] = conversion[1]
    row["provenance"] = provenance
    return row


def build_removal_row(
    source: str,
    model_id: str,
    observed_at: str,
    schema_version: int,
    last_row: dict[str, object] | None = None,
) -> dict[str, object]:
    """The removal row: one per (source, model_id) ever, carrying the final
    price snapshot so the closing record stays self-contained.

    `last_row` is the last priced row for the key (store.last); its comparable
    fields ride the removal row. the fx pair is conversion provenance but
    rides along when the snapshot quotes non-USD, so the row still validates.
    a missing last row builds the bare removal row.
    """
    row: dict[str, object] = {
        "schema": schema_version,
        "source": source,
        "model_id": model_id,
        "observed_at": observed_at,
    }
    comparable = _comparable(last_row) if last_row is not None else {}
    if "effective_at" in comparable:
        row["effective_at"] = comparable["effective_at"]
    row["removed"] = True
    if "currency" in comparable:
        row["currency"] = comparable["currency"]
    if "rates" in comparable:
        row["rates"] = comparable["rates"]
    if "overrides" in comparable:
        row["overrides"] = comparable["overrides"]
    if "fees" in comparable:
        row["fees"] = comparable["fees"]
    if "limits" in comparable:
        row["limits"] = comparable["limits"]
    if "unmapped" in comparable:
        row["unmapped"] = comparable["unmapped"]
    if last_row is not None and last_row.get("currency") not in (None, "USD"):
        provenance = last_row.get("provenance") or {}
        fx = {key: provenance[key] for key in ("fx_rate", "fx_rate_date") if key in provenance}
        if fx:
            row["provenance"] = fx
    return row


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

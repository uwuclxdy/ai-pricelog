"""v3 history row -> v4 row migration, plus the per-source shard writer.

The migration is a pure transform: a v3 history row becomes a v4 row with the
nested rates/fees/limits/provenance containers and one overrides list. It
never touches the live store; the orchestrator runs main() once and deletes
the v3 file afterwards.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from pathlib import Path

from ai_pricelog import openrouter, store, validate

HISTORY_FILE = "data/history.ndjson"
SHARD_DIR = "data/history"

# this module is now the last owner of the v3 vocabulary: validate.py describes
# the v4 row, so the migration keeps its own literal v3 field tuples here.
_RATE_FIELDS = (
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
_PEAK_FIELDS = ("peak_input_mtok", "peak_output_mtok", "peak_cache_read_mtok")

_TOP_KEYS = ("source", "model_id", "observed_at", "effective_at", "removed", "currency")

# every v3 key this migration PLACES. a key outside this set raises instead of
# migrating silently, so an unmapped v3 key cannot drop out of the history.
_RECOGNIZED = frozenset(
    {
        *_TOP_KEYS,
        *_RATE_FIELDS,
        "web_search_usd",
        "max_tokens_in",
        "max_tokens_out",
        "max_tokens",
        "window_rates",
        "volume_rates",
        "peak_windows",
        *_PEAK_FIELDS,
        "timezone",
        "name",
        "url",
        "currency_rate",
        "currency_rate_date",
        "extra",
    }
)

_MT = "_mtok"

# store no longer reads the v3 window-string shape, so this migration keeps
# its own copy, as the last owner of the v3 vocabulary.
_WINDOW_STR_RE = re.compile(r"^(\d{2}):(\d{2}):\d{2}Z$")


def _window_hhmm(window: object, model_id: str) -> list[int]:
    """a legacy `["HH:MM:SSZ", "HH:MM:SSZ"]` pair -> `[start, end]` HHMM ints."""
    if (
        not isinstance(window, list)
        or len(window) != 2
        or not all(isinstance(part, str) for part in window)
    ):
        raise ValueError(
            f"row {model_id!r}: peak window {window!r} outside the [start, end]"
            " string-pair shape; fix: the row or extend the normalization"
        )
    parts: list[int] = []
    for part in window:
        match = _WINDOW_STR_RE.fullmatch(part)
        if match is None or int(match.group(1)) > 23 or int(match.group(2)) > 59:
            raise ValueError(
                f"row {model_id!r}: peak window {part!r} outside the HH:MM:SSZ shape;"
                " fix: the row or extend the normalization"
            )
        parts.append(int(match.group(1)) * 100 + int(match.group(2)))
    if parts[0] >= parts[1]:
        raise ValueError(
            f"row {model_id!r}: peak window start must precede its end;"
            " fix: the row or extend the normalization"
        )
    return parts


def migrate_row(row: dict[str, object], schema_version: int) -> dict[str, object]:
    """Convert one v3 history row into a v4 row; raises on an unplaceable key.

    `schema_version` comes from the contract's own `properties.schema.const`,
    so the stamp every migrated row carries cannot drift from the file that
    declares it.
    """
    source = row.get("source")
    model_id = row.get("model_id")
    observed_at = row.get("observed_at")
    label = (source, model_id, observed_at)

    unknown = set(row) - _RECOGNIZED
    if unknown:
        raise ValueError(
            f"row {label!r}: cannot place key(s) {sorted(unknown)!r};"
            " fix: extend the migration or drop the keys"
        )

    rates: dict[str, object] = {}
    for field in _RATE_FIELDS:
        if field in row:
            rates[field[: -len(_MT)]] = row[field]

    fees: dict[str, object] = {}
    if "web_search_usd" in row:
        fees["web_search"] = row["web_search_usd"]

    limits: dict[str, object] = {}
    if "max_tokens_in" in row:
        limits["context"] = row["max_tokens_in"]
    if "max_tokens_out" in row:
        limits["output"] = row["max_tokens_out"]
    if "max_tokens" in row:
        # deepseek's pre-split rows stored max output under max_tokens;
        # everyone else stored the context window. setdefault so an already
        # split row keeps its newer typed value, matching _normalize_entry
        limits.setdefault("output" if source == "deepseek" else "context", row["max_tokens"])

    provenance: dict[str, object] = {}
    if "url" in row:
        provenance["url"] = row["url"]
    if "name" in row:
        provenance["name"] = row["name"]
    if "currency_rate" in row:
        provenance["fx_rate"] = row["currency_rate"]
    if "currency_rate_date" in row:
        provenance["fx_rate_date"] = row["currency_rate_date"]

    timezone = row.get("timezone")
    overrides: list[dict[str, object]] = []
    for entry in row.get("window_rates") or []:
        overrides.append(_window_override(entry, timezone))
    if any(field in row for field in _PEAK_FIELDS):
        peak_rates = {
            name.removeprefix("peak_")[: -len(_MT)]: row[name]
            for name in _PEAK_FIELDS
            if name in row
        }
        windows = row.get("peak_windows") or []
        if not windows:
            raise ValueError(
                f"row {label!r}: peak rates with no peak_windows have no schedule"
                " to land on; fix: the row, or extend the migration"
            )
        for window in windows:
            when: dict[str, object] = {"window": _window_hhmm(window, str(model_id))}
            if timezone:
                when["timezone"] = timezone
            overrides.append({"when": when, "rates": dict(peak_rates)})
    for entry in row.get("volume_rates") or []:
        overrides.append(_volume_override(entry, label))

    if timezone is not None and not any(
        "timezone" in (override.get("when") or {}) for override in overrides
    ):
        # v3 hangs the zone off the row; v4 hangs it off the condition it
        # describes, and an unconditional entry has no condition. a row whose
        # every entry is unconditional would lose the zone with no trace
        raise ValueError(
            f"row {label!r}: timezone {timezone!r} has no scheduled override to"
            " describe; fix: the row, or extend the migration"
        )

    unmapped: dict[str, object] = {}
    extra = row.get("extra")
    if extra is not None:
        if not isinstance(extra, dict):
            raise ValueError(
                f"row {label!r}: 'extra' is a {type(extra).__name__}, not an object;"
                " fix: the row, or extend the migration"
            )
        source_pricing = {key: extra[key] for key in extra if key in openrouter.SOURCE_KEYS}
        if source_pricing:
            typed_rates, typed_fees = openrouter.map_typed_fields(source_pricing, str(model_id))
            for axis, value in typed_rates.items():
                rates.setdefault(axis, value)
            for fee, value in typed_fees.items():
                fees.setdefault(fee, value)
        unmapped = {key: value for key, value in extra.items() if key not in openrouter.SOURCE_KEYS}

    out: dict[str, object] = {"schema": schema_version}
    for key in _TOP_KEYS:
        if key in row:
            out[key] = row[key]
    if rates:
        out["rates"] = rates
    if overrides:
        out["overrides"] = overrides
    if fees:
        out["fees"] = fees
    if limits:
        out["limits"] = limits
    if unmapped:
        out["unmapped"] = unmapped
    if provenance:
        out["provenance"] = provenance
    return out


def _window_override(entry: dict[str, object], timezone: object) -> dict[str, object]:
    """a v3 window_rates entry -> a v4 override entry."""
    when: dict[str, object] = {}
    if "days" in entry:
        when["days"] = entry["days"]
    if "window" in entry:
        when["window"] = entry["window"]
    # a zone describes a schedule, and an unconditional entry has none
    if when and timezone:
        when["timezone"] = timezone
    rates = {field[: -len(_MT)]: entry[field] for field in _RATE_FIELDS if field in entry}
    override: dict[str, object] = {}
    if when:
        override["when"] = when
    if rates:
        override["rates"] = rates
    if "quota_multiplier" in entry:
        override["quota_multiplier"] = entry["quota_multiplier"]
    return override


def _volume_override(entry: dict[str, object], label: tuple[object, ...]) -> dict[str, object]:
    """a v3 volume_rates entry -> a v4 override entry."""
    if "min_tokens" not in entry:
        raise ValueError(
            f"row {label!r}: volume_rates entry {entry!r} carries no min_tokens,"
            " so it names no threshold to apply from; fix: the row, or extend"
            " the migration"
        )
    when: dict[str, object] = {"min_tokens": entry["min_tokens"]}
    rates = {field[: -len(_MT)]: entry[field] for field in _RATE_FIELDS if field in entry}
    return {"when": when, "rates": rates}


def _shard_order(row: dict[str, object]) -> tuple[str, str]:
    """Shard sort key: a new row lands beside its siblings in the review diff."""
    return (str(row["model_id"]), str(row["observed_at"]))


def run_migration(input_path: Path, output_dir: Path, root: Path, overwrite: bool = False) -> None:
    """Migrate an ndjson history file into one v4 shard per source."""
    version = validate.load_schema_keys(root).version
    existing = sorted(output_dir.glob("*.ndjson")) if output_dir.exists() else []
    if existing and not overwrite:
        raise RuntimeError(
            f"output dir '{output_dir}' already holds shard(s)"
            f" {[path.name for path in existing]!r};"
            " fix: pass --overwrite or use an empty directory"
        )
    try:
        text = input_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"history file '{input_path}' does not exist; fix: name the v3 history file to migrate"
        ) from exc
    rows = store.parse(text, str(input_path))
    by_shard: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        migrated = migrate_row(row, version)
        by_shard.setdefault(store.shard_name(migrated.get("source")), []).append(migrated)
    output_dir.mkdir(parents=True, exist_ok=True)
    # a stale shard from an earlier run would otherwise survive --overwrite and
    # leave the store carrying a source nothing produced
    for path in existing:
        path.unlink()
    for name in sorted(by_shard):
        store.save(sorted(by_shard[name], key=_shard_order), output_dir / name)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="migrate v3 history to v4 shards")
    parser.add_argument("input", nargs="?", default=HISTORY_FILE)
    parser.add_argument("output_dir", nargs="?", default=SHARD_DIR)
    parser.add_argument("--root", default=".", help="repo root holding the v4 schema file")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    run_migration(
        Path(args.input), Path(args.output_dir), Path(args.root), overwrite=args.overwrite
    )


if __name__ == "__main__":
    main()

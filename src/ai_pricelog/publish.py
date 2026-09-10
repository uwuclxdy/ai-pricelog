"""Rebuild the dist branch tree and refresh the committed README stats.

`build_dist` emits every derived view a consumer of the `dist` branch reads;
`refresh_committed` rewrites the README stats blocks that stay on the mommy
branch. The CI publish job runs both from the committed store.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Mapping
from pathlib import Path

from ai_pricelog import models, stats, store, validate
from ai_pricelog.store import _atomic_write

_ORDER_KEYS = ("source", "model_id", "observed_at")

# the flat export's own shape version, stamped inside the file: a shape
# change ships a -v2 file beside the current one instead of breaking
# readers of the -v1 file. v2 (2026-09-10) adds the entry's `intervals`
# chain. the `version` field beside it stays the row schema version, same
# as index.json.
FLAT_VERSION = 2

# the flat entry's own fields, in emit order, from the row the partition
# picked: the row's pricing fields, then the view stamps. provenance and
# unmapped stay out: the export is the price surface, not the observation
# record; unmapped would let one moved source key reshape a versioned
# consumer file, which is a flat_version bump, not a silent emit.
_FLAT_ROW_FIELDS = (
    "schema",
    "effective_at",
    "rates",
    "overrides",
    "limits",
    "fees",
    "currency",
    "observed_at",
)


def _history_order(row: dict[str, object]) -> tuple[str, str, str]:
    """The merged-history sort: source, then model, then observation.

    Leading with the source is what lets a consumer stream one provider out of
    the merged file; `store._shard_order` drops it because a shard already is
    one source.
    """
    return (
        _row_field(row, "source"),
        _row_field(row, "model_id"),
        _row_field(row, "observed_at"),
    )


def _row_field(row: dict[str, object], key: str) -> str:
    """One required row field, naming the row when it is missing.

    A human push to mommy can commit a row no gate ever saw (the merge
    validates only pipeline branches), and a bare KeyError here names neither
    the shard nor the line.
    """
    try:
        return str(row[key])
    except KeyError:
        raise ValueError(
            f"history row is missing '{key}': {row!r};"
            f" fix: the offending line in data/history/, every row carries {list(_ORDER_KEYS)}"
        ) from None


def _group_by_source(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    """Rows keyed by their own source field, each source passing the shard guard."""
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        # every field the build reads is checked here, before any write: this
        # walk is the only pass that precedes all of them, and `write_index`
        # would otherwise reach `model_id` first with a bare KeyError
        for key in _ORDER_KEYS:
            _row_field(row, key)
        source = _row_field(row, "source")
        # a source that cannot name a file refuses the whole build, not half
        store.shard_name(source)
        grouped.setdefault(source, []).append(row)
    return grouped


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def _name(entry: Mapping[str, object] | None, row: dict[str, object], model_id: str) -> str:
    """The display name: catalog name, then the source's own name for the
    model, then the raw id. An entry with no `name` key and a row whose
    provenance carries none still yields a non-empty string, never a missing
    field.
    """
    catalog_name = entry.get("name") if entry is not None else None
    if isinstance(catalog_name, str) and catalog_name:
        return catalog_name
    provenance = row.get("provenance")
    if isinstance(provenance, dict):
        source_name = provenance.get("name")
        if isinstance(source_name, str) and source_name:
            return source_name
    return model_id


def build_flat(
    rows: list[dict[str, object]],
    root: Path,
    out: Path,
    schema_version: int,
) -> None:
    """Write the flat export beside index.json plus one twin per source.

    One entry per (source, model_id), built from the same `store.current`
    partition index.json reads, so the two views cannot disagree on which
    row is current. The removal rule is index.json's own: last prices kept,
    `removed_at` stamped. Each entry carries the key's full `intervals`
    chain, so pricing any past day is a containment test.
    """
    partition = store.current(rows)
    first_seen = partition["first_seen"]
    priced = partition["priced"]
    newest = partition["newest"]
    intervals = partition["intervals"]
    mapping = models.load_models(root / models.MODELS_FILE, allow_missing=False)
    # one reverse index: (source, model_id) -> catalog entry, shared by the
    # root file and every twin, so each entry of the tree resolves through
    # one lookup
    catalog_by_key: dict[tuple[str, str], dict[str, object]] = {}
    for entry in mapping.values():
        for source, model_ids in entry["sources"].items():
            if isinstance(model_ids, str):
                model_ids = [model_ids]
            for model_id in model_ids:
                if isinstance(model_id, str):
                    catalog_by_key[(source, model_id)] = entry

    def _entries(keys: list[tuple[str, str]]) -> list[dict[str, object]]:
        built = []
        for key in keys:
            source, model_id = key
            row = newest[key]
            base = priced.get(key)
            if base is None:
                base = {k: v for k, v in row.items() if k != "removed"}
            catalog_entry = catalog_by_key.get(key)
            entry: dict[str, object] = {
                "source": source,
                "model_id": model_id,
                "vendor": catalog_entry.get("vendor") if catalog_entry is not None else None,
                "name": _name(catalog_entry, base, model_id),
            }
            for field in _FLAT_ROW_FIELDS:
                if field in base:
                    entry[field] = base[field]
            entry["first_seen"] = first_seen[key]
            entry["intervals"] = intervals[key]
            if row.get("removed") is True:
                entry["removed_at"] = row["observed_at"]
            built.append(entry)
        return built

    all_keys = sorted(newest)
    _atomic_write(
        json.dumps(
            {
                "version": schema_version,
                "flat_version": FLAT_VERSION,
                "updated_at": max((newest[key]["observed_at"] for key in all_keys), default=""),
                "entries": _entries(all_keys),
            },
            ensure_ascii=False,
        )
        + "\n",
        out / f"flat-v{FLAT_VERSION}.json",
    )
    for source in sorted({key[0] for key in all_keys}):
        source_keys = [key for key in all_keys if key[0] == source]
        # the twin path runs through the same shard guard the index twins do,
        # so the two twin sets can never disagree on what a source names
        twin = Path(store.shard_name(source)).with_suffix(".json")
        _atomic_write(
            json.dumps(
                {
                    "version": schema_version,
                    "flat_version": FLAT_VERSION,
                    "updated_at": max(
                        (newest[key]["observed_at"] for key in source_keys), default=""
                    ),
                    "entries": _entries(source_keys),
                },
                ensure_ascii=False,
            )
            + "\n",
            out / "flat" / twin,
        )


def build_dist(
    rows: list[dict[str, object]],
    root: Path,
    out: Path,
    schema_version: int,
) -> None:
    """Write the whole dist tree under `out`, copies byte-identical to the store.

    `out` is emptied first: the tree is force-pushed whole, so a file left by an
    earlier build would publish a delisted source's index and history forever.
    """
    grouped = _group_by_source(rows)
    shards = sorted((root / store.SHARD_DIR).glob("*.ndjson"))
    # the per-source index groups by the row's own source and the history copy
    # by the shard filename; nothing upstream asserts the two agree, and a
    # disagreement would publish an index file with no history file beside it
    stems = {shard.stem for shard in shards}
    if stems != set(grouped):
        raise ValueError(
            f"history rows and shard files disagree on the source set:"
            f" rows-only {sorted(set(grouped) - stems)}, files-only {sorted(stems - set(grouped))};"
            " fix: the offending row's 'source' or the shard it sits in"
        )
    if out.exists():
        shutil.rmtree(out)
    store.write_index(rows, out / "index.json", schema_version)
    build_flat(rows, root, out, schema_version)
    for source, source_rows in grouped.items():
        shard = Path(store.shard_name(source))
        store.write_index(source_rows, out / "index" / shard.with_suffix(".json"), schema_version)
    store.save(sorted(rows, key=_history_order), out / "history.ndjson")
    for shard in shards:
        _copy(shard, out / "history" / shard.name)
    for catalog_file in sorted((root / Path(models.MODELS_FILE).parent).glob("*.json")):
        _copy(catalog_file, out / "catalog" / catalog_file.name)
    _copy(root / validate.SCHEMA_PATH, out / "schema" / Path(validate.SCHEMA_PATH).name)


def refresh_committed(rows: list[dict[str, object]], root: Path) -> None:
    """Rewrite both README stats blocks from the store rows."""
    mapping = models.load_models(root / models.MODELS_FILE, allow_missing=False)
    readme_path = root / "README.md"
    rendered = stats.render(readme_path.read_text(encoding="utf-8"), stats.compute(rows, mapping))
    # the README is a committed file the workflow's drift gate diffs; a torn
    # write would commit half a file
    _atomic_write(rendered, readme_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="ai-pricelog-publish",
        description="rebuild the dist tree and refresh the committed README stats",
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    root = Path(args.root)
    schema_version = validate.load_schema_keys(root).version
    rows = store.load_shards(root / store.SHARD_DIR)
    build_dist(rows, root, Path(args.out), schema_version)
    refresh_committed(rows, root)
    return 0

"""Rebuild the dist branch tree and refresh the two committed derived files.

`build_dist` emits every derived view a consumer of the `dist` branch reads;
`refresh_committed` rewrites data/index.json and the README stats blocks that
stay on the mommy branch. The CI publish job runs both from the committed
store.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from ai_pricelog import models, stats, store, validate
from ai_pricelog.store import _atomic_write

_ORDER_KEYS = ("source", "model_id", "observed_at")


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

    The publish job fires on a push to mommy, the one path that reaches the
    store without `validate_row`: a hand-edited branch row rides `automerge`'s
    line union unvalidated, so a bare KeyError here names neither the shard nor
    the line.
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
    for source, source_rows in grouped.items():
        shard = Path(store.shard_name(source))
        store.write_index(source_rows, out / "index" / shard.with_suffix(".json"), schema_version)
    store.save(sorted(rows, key=_history_order), out / "history.ndjson")
    for shard in shards:
        _copy(shard, out / "history" / shard.name)
    for catalog_file in sorted((root / Path(models.MODELS_FILE).parent).glob("*.json")):
        _copy(catalog_file, out / "catalog" / catalog_file.name)
    _copy(root / validate.SCHEMA_PATH, out / "schema" / Path(validate.SCHEMA_PATH).name)


def refresh_committed(
    rows: list[dict[str, object]],
    root: Path,
    schema_version: int,
) -> None:
    """Rewrite data/index.json and both README stats blocks from the store rows."""
    mapping = models.load_models(root / models.MODELS_FILE, allow_missing=False)
    readme_path = root / "README.md"
    rendered = stats.render(readme_path.read_text(encoding="utf-8"), stats.compute(rows, mapping))
    store.write_index(rows, root / store.INDEX_FILE, schema_version)
    # the README is a committed file the workflow's drift gate diffs; a torn
    # write would commit half a file, so it lands the way the index does
    _atomic_write(rendered, readme_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="ai-pricelog-publish",
        description="rebuild the dist tree and refresh the committed derived files",
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    root = Path(args.root)
    schema_version = validate.load_schema_keys(root).version
    rows = store.load_shards(root / store.SHARD_DIR)
    build_dist(rows, root, Path(args.out), schema_version)
    refresh_committed(rows, root, schema_version)
    return 0

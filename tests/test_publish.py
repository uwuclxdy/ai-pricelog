"""The publish module rebuilds the dist tree and refreshes the committed derived files."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from ai_pricelog import publish, store, validate

ROOT = Path(__file__).resolve().parents[1]

CATALOG_NAMES = (
    "models.json",
    "aliases.json",
    "providers.json",
    "billing-rules.json",
    "fx-rates.json",
)

MODELS_JSON = json.dumps(
    {
        "version": 4,
        "models": {
            "alpha-m1": {"vendor": "alpha", "curated": True, "sources": {"alpha": ["m1"]}},
            "alpha-m3": {"vendor": "alpha", "curated": True, "sources": {"alpha": ["m3"]}},
            "beta-m2": {"vendor": "beta", "curated": False, "sources": {"beta": ["m2"]}},
        },
    }
)

README = (
    "<!-- stats:start -->OLD TABLE<!-- stats:end -->\n"
    "\n"
    "<!-- stats-row:start -->OLD ROW<!-- stats-row:end -->\n"
)


def _row(source: str, model_id: str, observed_at: str) -> dict[str, object]:
    return {"source": source, "model_id": model_id, "observed_at": observed_at}


def _rows() -> list[dict[str, object]]:
    """Model ids deliberately NOT source-prefixed.

    `(source, model_id, ...)` and `(model_id, source, ...)` order these rows
    differently, so the merged-history test binds the ruled key rather than
    passing under any permutation of it.
    """
    return [
        _row("alpha", "m1", "2026-08-01"),
        _row("alpha", "m3", "2026-08-02"),
        _row("alpha", "m1", "2026-08-03"),
        _row("beta", "m2", "2026-08-01"),
    ]


def _fixture_root(base: Path, readme: str | None = None) -> Path:
    root = base / "root"
    history_dir = root / "data" / "history"
    catalog_dir = root / "data" / "catalog"
    schema_dir = root / "data" / "schema"
    history_dir.mkdir(parents=True)
    catalog_dir.mkdir(parents=True)
    schema_dir.mkdir(parents=True)
    rows = _rows()
    for source, source_rows in {"alpha": rows[:3], "beta": rows[3:]}.items():
        store.save_shard(source_rows, history_dir, source)
    (catalog_dir / "models.json").write_text(MODELS_JSON, encoding="utf-8")
    for name in CATALOG_NAMES[1:]:
        (catalog_dir / name).write_text(f'{{"fixture": "{name}"}}\n', encoding="utf-8")
    (schema_dir / "row.v4.json").write_text('{"fixture": true}\n', encoding="utf-8")
    if readme is not None:
        (root / "README.md").write_text(readme, encoding="utf-8")
    return root


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _relpaths(out: Path) -> list[str]:
    return sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())


DIST_PATHS = sorted(
    [
        "index.json",
        "index/alpha.json",
        "index/beta.json",
        "history.ndjson",
        "history/alpha.ndjson",
        "history/beta.ndjson",
        *(f"catalog/{name}" for name in CATALOG_NAMES),
        "schema/row.v4.json",
    ]
)


def test_dist_tree_carries_the_exact_path_set(tmp_path):
    root = _fixture_root(tmp_path)
    out = tmp_path / "out"
    publish.build_dist(_rows(), root, out, 4)
    assert _relpaths(out) == DIST_PATHS


def test_a_rebuild_drops_what_the_previous_build_left(tmp_path):
    """The tree is force-pushed whole, so a stale file would publish forever."""
    root = _fixture_root(tmp_path)
    out = tmp_path / "out"
    publish.build_dist(_rows(), root, out, 4)
    (out / "index" / "gone.json").write_text("{}", encoding="utf-8")
    (out / "history" / "gone.ndjson").write_text("", encoding="utf-8")

    publish.build_dist(_rows(), root, out, 4)

    assert _relpaths(out) == DIST_PATHS


def test_per_source_index_equals_the_whole_tree_slice(tmp_path):
    root = _fixture_root(tmp_path)
    out = tmp_path / "out"
    publish.build_dist(_rows(), root, out, 4)
    whole = json.loads((out / "index.json").read_text())
    assert set(whole["sources"]) == {"alpha", "beta"}
    for source in ("alpha", "beta"):
        per = json.loads((out / "index" / f"{source}.json").read_text())
        assert set(per) == {"sources", "version"}
        assert per["version"] == 4
        # equality, never a subset walk: a per-source file that DROPS a model
        # still satisfies every entry it does carry
        assert per["sources"] == {source: whole["sources"][source]}


def test_merged_history_is_the_source_first_ordering_of_the_shard_lines(tmp_path):
    root = _fixture_root(tmp_path)
    out = tmp_path / "out"
    shuffled = list(reversed(_rows()))
    publish.build_dist(shuffled, root, out, 4)

    merged = _lines(out / "history.ndjson")
    keys = [
        (row["source"], row["model_id"], row["observed_at"])
        for row in (json.loads(line) for line in merged)
    ]
    # spelled out, not re-derived from the function under test: sorting by
    # (model_id, source, observed_at) instead swaps the last two entries
    assert keys == [
        ("alpha", "m1", "2026-08-01"),
        ("alpha", "m1", "2026-08-03"),
        ("alpha", "m3", "2026-08-02"),
        ("beta", "m2", "2026-08-01"),
    ]
    # a multiset, since the real store holds a removal row and a same-day price
    # row under one (source, model_id, observed_at) key
    shard_lines: Counter[str] = Counter()
    for source in ("alpha", "beta"):
        shard_lines.update(_lines(root / "data" / "history" / f"{source}.ndjson"))
    assert Counter(merged) == shard_lines


def test_copies_are_byte_identical(tmp_path):
    root = _fixture_root(tmp_path)
    out = tmp_path / "out"
    publish.build_dist(_rows(), root, out, 4)
    for name in CATALOG_NAMES:
        assert (out / "catalog" / name).read_bytes() == (
            root / "data" / "catalog" / name
        ).read_bytes()
    assert (out / "schema" / "row.v4.json").read_bytes() == (
        root / "data" / "schema" / "row.v4.json"
    ).read_bytes()
    for source in ("alpha", "beta"):
        assert (out / "history" / f"{source}.ndjson").read_bytes() == (
            root / "data" / "history" / f"{source}.ndjson"
        ).read_bytes()


def test_a_source_that_cannot_name_a_file_raises(tmp_path):
    root = _fixture_root(tmp_path)
    out = tmp_path / "out"
    rows = _rows() + [_row("../evil", "x", "2026-08-01")]
    with pytest.raises(ValueError, match="cannot name a shard file"):
        publish.build_dist(rows, root, out, 4)
    assert not out.exists()


def test_a_row_missing_a_required_field_names_it(tmp_path):
    root = _fixture_root(tmp_path)
    out = tmp_path / "out"
    rows = _rows() + [{"source": "alpha", "observed_at": "2026-08-04"}]
    with pytest.raises(ValueError, match="missing 'model_id'"):
        publish.build_dist(rows, root, out, 4)


def test_rows_and_shard_files_must_agree_on_the_source_set(tmp_path):
    root = _fixture_root(tmp_path)
    out = tmp_path / "out"
    (root / "data" / "history" / "gamma.ndjson").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="disagree on the source set"):
        publish.build_dist(_rows(), root, out, 4)


def test_refresh_committed_rewrites_index_and_readme(tmp_path):
    root = _fixture_root(tmp_path, readme=README)
    rows = _rows()
    publish.refresh_committed(rows, root, 4)
    expected_index = tmp_path / "expected-index.json"
    store.write_index(rows, expected_index, 4)
    assert (root / "data" / "index.json").read_bytes() == expected_index.read_bytes()
    readme = (root / "README.md").read_text()
    assert "| models tracked | **3** |" in readme
    assert "| sources | 2 |" in readme
    assert "| dated rows | 4 |" in readme
    assert "| canonical models | 2 |" in readme
    assert "history | since 2026-08-01 (3 days) |" in readme
    assert "| models | **3** tracked across 2 sources, history back to 2026-08-01 |" in readme
    assert "OLD" not in readme


def test_refresh_committed_raises_when_a_readme_marker_is_missing(tmp_path):
    root = _fixture_root(tmp_path, readme="<!-- stats:start -->x<!-- stats:end -->\n")
    with pytest.raises(ValueError):
        publish.refresh_committed(_rows(), root, 4)


def test_main_builds_the_tree_and_refreshes_the_committed_files(tmp_path, monkeypatch):
    root = _fixture_root(tmp_path, readme=README)
    (root / "data" / "schema" / "row.v4.json").write_bytes(
        (ROOT / "data" / "schema" / "row.v4.json").read_bytes()
    )
    out = tmp_path / "out"
    loads: list[Path] = []
    real_load_shards = store.load_shards
    monkeypatch.setattr(
        publish.store,
        "load_shards",
        lambda directory: (loads.append(directory), real_load_shards(directory))[1],
    )

    monkeypatch.setattr("sys.argv", ["ai-pricelog-publish", "--root", str(root), "--out", str(out)])
    assert publish.main() == 0

    assert _relpaths(out) == DIST_PATHS
    assert "OLD" not in (root / "README.md").read_text()
    assert (root / "data" / "index.json").read_bytes() == (out / "index.json").read_bytes()
    # one read feeds both writers: two reads could see different trees and
    # publish an index the committed one disagrees with
    assert loads == [root / store.SHARD_DIR]


def test_build_dist_index_matches_the_committed_index(tmp_path):
    rows = store.load_shards(ROOT / "data" / "history")
    schema_version = validate.load_schema_keys(ROOT).version
    out = tmp_path / "out"
    publish.build_dist(rows, ROOT, out, schema_version)
    # bytes, not parsed dicts: the workflow's drift gate is `git diff`, so a
    # serialization change would commit a no-op refresh on every push
    assert (out / "index.json").read_bytes() == (ROOT / "data" / "index.json").read_bytes()

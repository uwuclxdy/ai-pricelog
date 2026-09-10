"""The publish module rebuilds the dist tree and refreshes the committed derived files."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from ai_pricelog import models, publish, store, validate
from ai_pricelog.testing import default_branch_test

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
            "alpha-m1": {
                "name": "Alpha One",
                "vendor": "alpha",
                "curated": True,
                "sources": {"alpha": ["m1"]},
            },
            "alpha-m3": {"vendor": "alpha", "curated": True, "sources": {"alpha": ["m3"]}},
            "beta-m2": {"vendor": "beta", "curated": False, "sources": {"beta": ["m2"]}},
            "beta-m4": {"vendor": None, "curated": False, "sources": {"beta": ["m4"]}},
            "beta-m5": {
                "name": "Beta Five",
                "vendor": "beta",
                "curated": True,
                "sources": {"beta": ["m5"]},
            },
            "beta-m6": {"vendor": "beta", "curated": False, "sources": {"beta": ["m6"]}},
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


def _flat_rows() -> list[dict[str, object]]:
    """Rows for the flat export: priced, nameless, null-vendor, removal and a
    provenance-name fallback all present, so the assertions bind each rung.
    """
    return [
        _row("alpha", "m1", "2026-08-01"),
        _row("alpha", "m3", "2026-08-02"),
        _row("alpha", "m1", "2026-08-03"),
        _row("beta", "m2", "2026-08-01"),
        _row("beta", "m4", "2026-08-02"),
        {
            "schema": 4,
            "source": "beta",
            "model_id": "m5",
            "observed_at": "2026-08-01",
            "rates": {"input": 1.0},
            "provenance": {"url": "u1"},
        },
        {
            "schema": 4,
            "source": "beta",
            "model_id": "m6",
            "observed_at": "2026-08-05",
            "rates": {"input": 2.0},
            "provenance": {"name": "Beta Six", "url": "u2"},
        },
        {
            "schema": 4,
            "source": "beta",
            "model_id": "m5",
            "observed_at": "2026-08-06",
            "removed": True,
        },
    ]


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


def _fixture_root(
    base: Path, readme: str | None = None, rows: list[dict[str, object]] | None = None
) -> Path:
    root = base / "root"
    history_dir = root / "data" / "history"
    catalog_dir = root / "data" / "catalog"
    schema_dir = root / "data" / "schema"
    history_dir.mkdir(parents=True)
    catalog_dir.mkdir(parents=True)
    schema_dir.mkdir(parents=True)
    by_source: dict[str, list[dict[str, object]]] = {}
    for row in rows if rows is not None else _rows():
        by_source.setdefault(str(row["source"]), []).append(row)
    for source, source_rows in by_source.items():
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
        "flat-v1.json",
        "flat/alpha.json",
        "flat/beta.json",
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


def test_refresh_committed_rewrites_only_the_readme(tmp_path):
    root = _fixture_root(tmp_path, readme=README)
    stale = root / "data" / "index.json"
    stale.write_text("stale\n", encoding="utf-8")
    publish.refresh_committed(_rows(), root)
    assert stale.read_text(encoding="utf-8") == "stale\n"
    stale.unlink()
    publish.refresh_committed(_rows(), root)
    assert not stale.exists()
    readme = (root / "README.md").read_text()
    assert "| models tracked | **3** |" in readme
    assert "| sources | 2 |" in readme
    assert "| dated rows | 4 |" in readme
    assert "| canonical models | 3 |" in readme
    assert "history | since 2026-08-01 (3 days) |" in readme
    assert "| models | **3** tracked across 2 sources, history back to 2026-08-01 |" in readme
    assert "OLD" not in readme


def test_refresh_committed_raises_when_a_readme_marker_is_missing(tmp_path):
    root = _fixture_root(tmp_path, readme="<!-- stats:start -->x<!-- stats:end -->\n")
    with pytest.raises(ValueError):
        publish.refresh_committed(_rows(), root)


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
    # one read feeds both writers: two reads could see different trees and
    # publish README stats the dist tree disagrees with
    assert loads == [root / store.SHARD_DIR]


# the flat export: one entry per (source, model_id), built from the same
# partition index.json reads. these fixtures exercise every rung the verify
# clauses name: entry-count parity, the name chain, the vendor resolution,
# updated_at, and rates parity against index.json.


def _build_flat(tmp_path, rows):
    root = _fixture_root(tmp_path, rows=rows)
    out = tmp_path / "out"
    publish.build_dist(rows, root, out, 4)
    return (
        json.loads((out / "flat-v1.json").read_text()),
        json.loads((out / "flat" / "alpha.json").read_text()),
        json.loads((out / "flat" / "beta.json").read_text()),
        json.loads((out / "index.json").read_text()),
    )


def test_flat_export_entry_counts_match_the_index(tmp_path):
    flat, _, _, index = _build_flat(tmp_path, _flat_rows())
    index_keys = {
        (source, model_id) for source, models in index["sources"].items() for model_id in models
    }
    flat_keys = {(entry["source"], entry["model_id"]) for entry in flat["entries"]}
    assert flat_keys == index_keys
    # one entry per (source, model_id), never one per row: m1 has two rows
    assert len(flat["entries"]) == len(flat_keys) == 6


def test_flat_export_names_resolve_the_chain(tmp_path):
    flat, _, _, _ = _build_flat(tmp_path, _flat_rows())
    names = {(e["source"], e["model_id"]): e["name"] for e in flat["entries"]}
    # catalog name wins
    assert names[("alpha", "m1")] == "Alpha One"
    assert names[("beta", "m5")] == "Beta Five"
    # provenance.name on the row is the middle rung (m6: no catalog name)
    assert names[("beta", "m6")] == "Beta Six"
    # raw model id is the last rung (m3, m2, m4 carry neither)
    assert names[("alpha", "m3")] == "m3"
    assert names[("beta", "m2")] == "m2"
    assert names[("beta", "m4")] == "m4"
    # the removal-row entry (m5) keeps the priced row's name chain: its
    # provenance is gone but the catalog still names it
    assert names[("beta", "m5")] == "Beta Five"


def test_flat_export_carries_vendor_and_row_fields(tmp_path):
    flat, _, _, index = _build_flat(tmp_path, _flat_rows())
    entries = {(e["source"], e["model_id"]): e for e in flat["entries"]}
    # vendor resolves through the catalog, null seeds included verbatim
    assert entries[("alpha", "m1")]["vendor"] == "alpha"
    assert entries[("beta", "m4")]["vendor"] is None
    # a removal keeps last prices and gains removed_at, the index.json rule
    m5 = entries[("beta", "m5")]
    assert m5["rates"] == {"input": 1.0}
    assert m5["removed_at"] == "2026-08-06"
    assert "removed" not in m5
    assert m5["first_seen"] == "2026-08-01"
    # first_seen on a single-row key
    assert entries[("beta", "m6")]["first_seen"] == "2026-08-05"
    # the field set is exactly the contract, no provenance leaks
    assert list(entries[("beta", "m6")]) == [
        "source",
        "model_id",
        "vendor",
        "name",
        "schema",
        "rates",
        "observed_at",
        "first_seen",
    ]


def test_flat_export_rates_equal_the_index_entry_rates(tmp_path):
    flat, _, _, index = _build_flat(tmp_path, _flat_rows())
    for entry in flat["entries"]:
        index_entry = index["sources"][entry["source"]][entry["model_id"]]
        # every key present in both: a rateless row (an openrouter router)
        # exports no rates key in either view
        for axis in entry.get("rates", {}):
            assert entry["rates"][axis] == index_entry["rates"][axis]


def test_flat_export_updated_at_is_the_newest_observed_at(tmp_path):
    flat, alpha_flat, beta_flat, _ = _build_flat(tmp_path, _flat_rows())
    # the whole tree's newest observed_at, including removal rows
    assert flat["updated_at"] == "2026-08-06"
    assert flat["version"] == 4
    assert flat["flat_version"] == 1
    # the per-source twin carries its own source's newest observed_at
    assert alpha_flat["updated_at"] == "2026-08-03"
    assert beta_flat["updated_at"] == "2026-08-06"
    # the twin holds exactly its source's entries, same shape as the root
    beta_keys = {(e["source"], e["model_id"]) for e in beta_flat["entries"]}
    assert beta_keys == {
        k for k in {(e["source"], e["model_id"]) for e in flat["entries"]} if k[0] == "beta"
    }
    assert list(alpha_flat) == ["version", "flat_version", "updated_at", "entries"]


def test_flat_export_is_sorted_deterministically(tmp_path):
    flat, _, _, _ = _build_flat(tmp_path, _flat_rows())
    keys = [(e["source"], e["model_id"]) for e in flat["entries"]]
    assert keys == sorted(keys)


@pytest.mark.skipif(not default_branch_test, reason=default_branch_test.skip_reason)
def test_flat_export_over_the_real_tree(tmp_path):
    """The verify clauses against the committed store: counts, names, updated_at."""
    rows = store.load_shards(ROOT / "data" / "history")
    out = tmp_path / "out"
    publish.build_dist(rows, ROOT, out, validate.load_schema_keys(ROOT).version)
    flat = json.loads((out / "flat-v1.json").read_text())
    index = json.loads((out / "index.json").read_text())
    index_keys = {
        (source, model_id) for source, models in index["sources"].items() for model_id in models
    }
    flat_keys = {(e["source"], e["model_id"]) for e in flat["entries"]}
    assert flat_keys == index_keys
    assert len(flat["entries"]) == len(index_keys)
    for entry in flat["entries"]:
        assert isinstance(entry["name"], str) and entry["name"]
        assert "vendor" in entry
        # the todo's parity clause: every rate key present in both views
        for axis in entry.get("rates", {}):
            assert (
                entry["rates"][axis]
                == index["sources"][entry["source"]][entry["model_id"]]["rates"][axis]
            )
    assert flat["updated_at"] == max(str(r["observed_at"]) for r in rows)
    # a null vendor only ever comes from a catalog seed pending curation
    nulls = [e for e in flat["entries"] if e["vendor"] is None]
    catalog = models.load_models(ROOT / models.MODELS_FILE)
    by_key = {}
    for entry in catalog.values():
        for source, ids in entry["sources"].items():
            for model_id in ids:
                by_key[(source, model_id)] = entry
    for e in nulls:
        assert by_key[(e["source"], e["model_id"])]["curated"] is False

"""The committed catalog holds the coverage, resold, and curated invariants."""

from __future__ import annotations

import json
from pathlib import Path

from ai_pricelog import models, store

ROOT = Path(__file__).resolve().parents[1]


def _catalog() -> dict[str, dict[str, object]]:
    return models.load_models(ROOT / "data" / "catalog" / "models.json")


def _providers() -> dict[str, dict[str, str]]:
    return json.loads((ROOT / "data" / "catalog" / "providers.json").read_text())["providers"]


def test_coverage_invariant_over_the_real_tree():
    rows = store.load_shards(ROOT / "data" / "history")
    keys = {(row["source"], row["model_id"]) for row in rows}
    claims: dict[tuple[str, str], list[str]] = {}
    for canonical, entry in _catalog().items():
        for source, ids in entry["sources"].items():
            for model_id in ids:
                claims.setdefault((source, model_id), []).append(canonical)
    assert set(claims) == keys
    assert all(len(canonicals) == 1 for canonicals in claims.values())


def test_resold_is_the_vendor_comparison():
    catalog = _catalog()
    providers = _providers()

    # a first-party row: anthropic serving its own claude model
    assert models.is_resold(catalog["claude-fable-5"], providers["anthropic"]) is False
    # a resold row on a mixed provider, sampled from a SEEDED entry: watsonx
    # serves llama (meta), not an ibm model
    assert models.is_resold(catalog["watsonx/llama-3-3-70b-instruct"], providers["watsonx"]) is True
    # any row on a vendorless reseller: deepinfra has no vendor
    assert models.is_resold(catalog["claude-fable-5"], providers["deepinfra"]) is True
    # every null-vendor entry the seeding left behind sits on a vendorless
    # reseller, so equality alone would hand a consumer 17 first-party rows
    nulls = [c for c, e in catalog.items() if e["vendor"] is None]
    assert nulls
    for canonical in nulls:
        for source in catalog[canonical]["sources"]:
            assert models.is_resold(catalog[canonical], providers[source]) is True


def test_seeded_entries_are_machine_seeds():
    catalog = _catalog()
    seeded = {k: e for k, e in catalog.items() if e["curated"] is False}
    assert seeded
    for canonical, entry in seeded.items():
        sources = entry["sources"]
        assert len(sources) == 1
        ((source, ids),) = sources.items()
        assert len(ids) == 1
        assert canonical == f"{source}/{ids[0]}"
        assert "name" not in entry
        assert "vendor" in entry


def test_curated_entries_carry_a_vendor_key():
    catalog = _catalog()
    for entry in catalog.values():
        if entry["curated"] is True:
            assert "vendor" in entry

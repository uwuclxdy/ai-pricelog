"""Round-trip guard for the v3 -> v4 migration.

The inverse mapping here is written from the v4 contract, not from the
migration's code, so a bug shared with the tool cannot hide behind the guard.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from ai_pricelog import migrate_v4, openrouter, store, validate
from ai_pricelog.validate import ValidationError

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "tests" / "fixtures" / "history-v3-frozen.ndjson"
# store._normalize_entry produced these, row for row, at 318266c. it was the
# v3 index normalizer and the v4 switch deleted it, so the guard freezes its
# output instead of chasing the function through every later refactor
NORMALIZED = ROOT / "tests" / "fixtures" / "normalized-v3-frozen.ndjson"
VERSION = validate.load_schema_keys(ROOT).version

EXPECTED_SOURCE_COUNTS = {
    "openrouter": 1112,
    "novita": 155,
    "together": 77,
    "dashscope": 72,
    "deepinfra": 70,
    "google": 60,
    "digitalocean": 60,
    "zai": 49,
    "mistral": 44,
    "cloudflare": 40,
    "openai": 36,
    "deepseek": 35,
    "avian": 34,
    "fireworks": 32,
    "moonshot": 28,
    "databricks": 21,
    "perplexity": 20,
    "minimax": 20,
    "anthropic": 17,
    "cohere": 16,
    "xai": 16,
    "baseten": 15,
    "scaleway": 14,
    "publicai": 13,
    "watsonx": 11,
    "sambanova": 7,
    "groq": 7,
    "cerebras": 2,
    "ai21": 2,
}

CONTEXT_MOVERS = {
    ("openrouter", "google/gemma-3-27b-it"),
    ("openrouter", "mistralai/voxtral-small-24b-2507"),
    ("openrouter", "kwaipilot/kat-coder-pro-v2.5"),
    ("openrouter", "nvidia/nemotron-3-ultra-550b-a55b"),
    ("openrouter", "z-ai/glm-5.3"),
}

_LIMIT_TO_FIELD = {"context": "max_tokens_in", "output": "max_tokens_out"}
_PROVENANCE_TO_FIELD = {
    "url": "url",
    "name": "name",
    "fx_rate": "currency_rate",
    "fx_rate_date": "currency_rate_date",
}


def v4_to_v3(v4: dict[str, object]) -> dict[str, object]:
    """The inverse of the migration, written from the v4 schema alone."""
    out: dict[str, object] = {}
    for key in ("source", "model_id", "observed_at", "effective_at", "removed", "currency"):
        if key in v4:
            out[key] = v4[key]
    for axis, value in v4.get("rates", {}).items():
        out[axis + "_mtok"] = value
    for fee, value in v4.get("fees", {}).items():
        out[fee + "_usd"] = value
    for limit, value in v4.get("limits", {}).items():
        out[_LIMIT_TO_FIELD[limit]] = value
    for key, value in v4.get("provenance", {}).items():
        out[_PROVENANCE_TO_FIELD[key]] = value
    timezone = None
    window_rates: list[dict[str, object]] = []
    volume_rates: list[dict[str, object]] = []
    for override in v4.get("overrides", []):
        when = override.get("when", {})
        if "timezone" in when:
            timezone = when["timezone"]
        rates = {axis + "_mtok": value for axis, value in override.get("rates", {}).items()}
        if "min_tokens" in when:
            volume_rates.append({"min_tokens": when["min_tokens"], **rates})
        else:
            entry = dict(rates)
            if "days" in when:
                entry["days"] = when["days"]
            if "window" in when:
                entry["window"] = when["window"]
            if "quota_multiplier" in override:
                entry["quota_multiplier"] = override["quota_multiplier"]
            window_rates.append(entry)
    if window_rates:
        out["window_rates"] = window_rates
    if volume_rates:
        out["volume_rates"] = volume_rates
    if timezone is not None:
        out["timezone"] = timezone
    if "unmapped" in v4:
        out["extra"] = dict(v4["unmapped"])
    return out


@pytest.fixture(scope="module")
def frozen_rows() -> list[dict[str, object]]:
    return store.parse(FROZEN.read_text(encoding="utf-8"), str(FROZEN))


def _shard_bytes(output_dir: Path) -> bytes:
    return b"".join(path.read_bytes() for path in sorted(output_dir.glob("*.ndjson")))


def test_rows_survive_and_carry_the_contract_stamp(frozen_rows: list[dict[str, object]]) -> None:
    assert len(frozen_rows) == 2085
    migrated = [migrate_v4.migrate_row(row, VERSION) for row in frozen_rows]
    # the contract lists `schema` as required and pins its value; the tool
    # is the only place that value is invented
    keys = validate.load_schema_keys(ROOT)
    assert {row["schema"] for row in migrated} == {keys.version}
    assert all(keys.required <= set(row) for row in migrated)


def test_legacy_max_tokens_facts(frozen_rows: list[dict[str, object]]) -> None:
    legacy = [row for row in frozen_rows if "max_tokens" in row]
    assert len(legacy) == 806
    deepseek_legacy = [row for row in legacy if row["source"] == "deepseek"]
    assert len(deepseek_legacy) == 10
    assert {row["max_tokens"] for row in deepseek_legacy} == {393216}
    assert not any(
        "max_tokens" in row and ("max_tokens_in" in row or "max_tokens_out" in row)
        for row in frozen_rows
    )
    legacy_keys = {(row["source"], row["model_id"]) for row in legacy}
    split_keys = {
        (row["source"], row["model_id"])
        for row in frozen_rows
        if "max_tokens_in" in row or "max_tokens_out" in row
    }
    both = legacy_keys & split_keys
    assert len(both) == 212
    eq_in = eq_out = neither = 0
    for key in both:
        legacy_rows = [
            row
            for row in frozen_rows
            if row["source"] == key[0] and row["model_id"] == key[1] and "max_tokens" in row
        ]
        split_rows = [
            row
            for row in frozen_rows
            if row["source"] == key[0]
            and row["model_id"] == key[1]
            and ("max_tokens_in" in row or "max_tokens_out" in row)
        ]
        last_legacy = max(legacy_rows, key=lambda row: row["observed_at"])
        last_split = max(split_rows, key=lambda row: row["observed_at"])
        if last_legacy["max_tokens"] == last_split.get("max_tokens_in"):
            eq_in += 1
        elif last_legacy["max_tokens"] == last_split.get("max_tokens_out"):
            eq_out += 1
        else:
            neither += 1
    assert eq_in == 204
    assert eq_out == 3
    assert neither == 5


def test_round_trip_matches_normalize_except_deepseek_legacy(
    frozen_rows: list[dict[str, object]],
) -> None:
    expected = {
        (row["source"], row["model_id"], row["observed_at"])
        for row in frozen_rows
        if row["source"] == "deepseek" and "max_tokens" in row
    }
    assert len(expected) == 10
    oracle = [json.loads(line) for line in NORMALIZED.read_text(encoding="utf-8").splitlines()]
    assert len(oracle) == len(frozen_rows)
    diverged = []
    for row, normalized in zip(frozen_rows, oracle, strict=True):
        back = v4_to_v3(migrate_v4.migrate_row(row, VERSION))
        if back != normalized:
            diverged.append((row["source"], row["model_id"], row["observed_at"]))
    assert set(diverged) == expected
    legacy_deepseek = [
        (row, normalized)
        for row, normalized in zip(frozen_rows, oracle, strict=True)
        if row["source"] == "deepseek" and "max_tokens" in row
    ]
    assert len(legacy_deepseek) == 10
    for row, normalized in legacy_deepseek:
        back = v4_to_v3(migrate_v4.migrate_row(row, VERSION))
        assert back["max_tokens_out"] == 393216
        assert normalized["max_tokens_in"] == 393216
        assert {k: v for k, v in back.items() if k != "max_tokens_out"} == {
            k: v for k, v in normalized.items() if k != "max_tokens_in"
        }


def test_migrated_keys_fit_schema(frozen_rows: list[dict[str, object]]) -> None:
    keys = validate.load_schema_keys(ROOT)
    for row in frozen_rows:
        migrated = migrate_v4.migrate_row(row, VERSION)
        assert set(migrated) <= keys.row
        if "rates" in migrated:
            assert set(migrated["rates"]) <= keys.rate_axes
        if "fees" in migrated:
            assert set(migrated["fees"]) <= keys.fees
        if "limits" in migrated:
            assert set(migrated["limits"]) <= keys.limits
        if "provenance" in migrated:
            assert set(migrated["provenance"]) <= keys.provenance
        if "unmapped" in migrated:
            assert isinstance(migrated["unmapped"], dict)
        for override in migrated.get("overrides", []):
            assert set(override) <= keys.override
            if "when" in override:
                assert set(override["when"]) <= keys.when
            if "rates" in override:
                assert set(override["rates"]) <= keys.rate_axes


def test_distinct_keys_and_triples_survive(frozen_rows: list[dict[str, object]]) -> None:
    keys = {(row["source"], row["model_id"]) for row in frozen_rows}
    assert len(keys) == 1106
    triples = Counter((row["source"], row["model_id"], row["observed_at"]) for row in frozen_rows)
    assert sum(1 for count in triples.values() if count > 1) == 26
    migrated = [migrate_v4.migrate_row(row, VERSION) for row in frozen_rows]
    assert {(row["source"], row["model_id"]) for row in migrated} == keys
    migrated_triples = Counter(
        (row["source"], row["model_id"], row["observed_at"]) for row in migrated
    )
    assert migrated_triples == triples


def test_source_counts(frozen_rows: list[dict[str, object]]) -> None:
    counts = Counter(row["source"] for row in frozen_rows)
    assert dict(counts) == EXPECTED_SOURCE_COUNTS
    assert len(EXPECTED_SOURCE_COUNTS) == 29
    assert sum(EXPECTED_SOURCE_COUNTS.values()) == 2085


def test_no_window_and_volume_together(frozen_rows: list[dict[str, object]]) -> None:
    assert not any("window_rates" in row and "volume_rates" in row for row in frozen_rows)


def test_extra_rows_are_openrouter_only(frozen_rows: list[dict[str, object]]) -> None:
    extra_rows = [row for row in frozen_rows if "extra" in row]
    assert len(extra_rows) == 233
    assert {row["source"] for row in extra_rows} == {"openrouter"}
    unconsumed = {
        key for row in extra_rows for key in row["extra"] if key not in openrouter.SOURCE_KEYS
    }
    assert unconsumed == {"overrides"}
    assert sum(1 for row in extra_rows if "overrides" in row["extra"]) == 81


def test_extra_never_shadows_a_typed_field(frozen_rows: list[dict[str, object]]) -> None:
    for row in frozen_rows:
        extra = row.get("extra")
        if not isinstance(extra, dict):
            continue
        for key in extra:
            if key not in openrouter.SOURCE_KEYS:
                continue
            rates, fees = openrouter.map_typed_fields({key: extra[key]}, row["model_id"])
            for axis in rates:
                assert f"{axis}_mtok" not in row
            for fee in fees:
                assert f"{fee}_usd" not in row


def test_context_movers_keep_legacy_as_context(frozen_rows: list[dict[str, object]]) -> None:
    seen = set()
    for row in frozen_rows:
        key = (row["source"], row["model_id"])
        if key in CONTEXT_MOVERS and "max_tokens" in row:
            migrated = migrate_v4.migrate_row(row, VERSION)
            assert migrated["limits"]["context"] == row["max_tokens"]
            assert "output" not in migrated["limits"]
            seen.add(key)
    assert seen == CONTEXT_MOVERS


def test_main_shards_are_compact_and_byte_identical(tmp_path: Path) -> None:
    out = tmp_path / "shards"
    migrate_v4.main([str(FROZEN), str(out), "--root", str(ROOT)])
    snapshot = _shard_bytes(out)
    assert b'", "' not in snapshot
    counts = {
        path.stem: sum(1 for _ in path.read_text(encoding="utf-8").splitlines())
        for path in sorted(out.glob("*.ndjson"))
    }
    assert counts == EXPECTED_SOURCE_COUNTS
    migrate_v4.main(["--overwrite", str(FROZEN), str(out), "--root", str(ROOT)])
    assert _shard_bytes(out) == snapshot


def test_main_refuses_a_partial_output_dir(tmp_path: Path) -> None:
    out = tmp_path / "shards"
    out.mkdir()
    (out / "openrouter.ndjson").write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="already holds shard"):
        migrate_v4.main([str(FROZEN), str(out), "--root", str(ROOT)])
    migrate_v4.main(["--overwrite", str(FROZEN), str(out), "--root", str(ROOT)])


def test_overwrite_clears_a_shard_no_source_produces(tmp_path: Path) -> None:
    # a survivor would give the v4 store a source nothing writes any more
    out = tmp_path / "shards"
    out.mkdir()
    (out / "ghostprovider.ndjson").write_text("{}\n", encoding="utf-8")
    migrate_v4.main(["--overwrite", str(FROZEN), str(out), "--root", str(ROOT)])
    assert not (out / "ghostprovider.ndjson").exists()
    assert {path.stem for path in out.glob("*.ndjson")} == set(EXPECTED_SOURCE_COUNTS)


def test_a_non_shard_file_does_not_trip_the_guard(tmp_path: Path) -> None:
    out = tmp_path / "shards"
    out.mkdir()
    (out / ".gitkeep").write_text("", encoding="utf-8")
    migrate_v4.main([str(FROZEN), str(out), "--root", str(ROOT)])
    assert (out / ".gitkeep").exists()


def test_load_schema_keys_derives_from_file() -> None:
    keys = validate.load_schema_keys(ROOT)
    assert keys.row == {
        "schema",
        "source",
        "model_id",
        "observed_at",
        "effective_at",
        "removed",
        "currency",
        "rates",
        "overrides",
        "fees",
        "limits",
        "unmapped",
        "provenance",
    }
    assert keys.rate_axes == {
        "input",
        "output",
        "cache_read",
        "cache_write",
        "cache_write_1h",
        "image",
        "audio",
        "input_audio_cache",
        "internal_reasoning",
        "image_output",
        "audio_output",
    }
    assert keys.fees == {"web_search"}
    assert keys.limits == {"context", "output"}
    assert keys.provenance == {"url", "name", "fx_rate", "fx_rate_date"}
    assert keys.when == {"days", "window", "timezone", "min_tokens"}
    assert keys.override == {"when", "rates", "quota_multiplier"}


def test_rate_field_list_matches_the_contract_both_ways() -> None:
    # a subset check alone lets a dropped axis pass: the migration would
    # silently leave that rate out of every row it touches
    axes = {field.removesuffix("_mtok") for field in migrate_v4._RATE_FIELDS}
    assert axes == validate.load_schema_keys(ROOT).rate_axes


def test_load_schema_keys_points_at_a_copy(tmp_path: Path) -> None:
    copy_root = tmp_path / "repo"
    (copy_root / "data" / "schema").mkdir(parents=True)
    (copy_root / "data" / "schema" / "row.v4.json").write_text(
        (ROOT / "data" / "schema" / "row.v4.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    assert validate.load_schema_keys(copy_root) == validate.load_schema_keys(ROOT)


def test_load_schema_keys_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="is missing"):
        validate.load_schema_keys(tmp_path)


def test_load_schema_keys_malformed_raises(tmp_path: Path) -> None:
    (tmp_path / "data" / "schema").mkdir(parents=True)
    (tmp_path / "data" / "schema" / "row.v4.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValidationError, match="invalid json"):
        validate.load_schema_keys(tmp_path)


def test_shards_sort_by_model_then_date(tmp_path: Path) -> None:
    # the sort is what puts a new row beside its siblings in the review diff,
    # and byte-identity across runs holds under any deterministic order
    out = tmp_path / "shards"
    migrate_v4.main([str(FROZEN), str(out), "--root", str(ROOT)])
    for path in sorted(out.glob("*.ndjson")):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        order = [(row["model_id"], row["observed_at"]) for row in rows]
        assert order == sorted(order), f"{path.name} is not sorted"


def test_a_source_cannot_escape_the_shard_directory(tmp_path: Path) -> None:
    history = tmp_path / "history.ndjson"
    history.write_text(
        json.dumps({"source": "../escaped", "model_id": "m", "observed_at": "2026-09-03"}) + "\n",
        encoding="utf-8",
    )
    shards = tmp_path / "shards"
    with pytest.raises(ValueError, match="cannot name a shard file"):
        migrate_v4.main([str(history), str(shards), "--root", str(ROOT)])
    # the traversal would have landed one level above the shard dir
    assert not (tmp_path / "escaped.ndjson").exists()
    assert not shards.exists() or not list(shards.iterdir())


def test_timezone_rides_the_override_it_describes() -> None:
    row = {
        "source": "deepseek",
        "model_id": "m",
        "observed_at": "2026-09-03",
        "input_mtok": 0.66,
        "peak_windows": [["01:00:00Z", "04:00:00Z"]],
        "peak_input_mtok": 1.32,
        "window_rates": [{"days": ["monday"], "input_mtok": 0.9}],
        "timezone": "Asia/Shanghai",
    }
    # a shape v3's validator accepted; nothing validates v3 any more, so the
    # migration is the only thing left that reads it
    overrides = migrate_v4.migrate_row(row, VERSION)["overrides"]
    # v4_to_v3 collapses every zone into one top-level key, so it cannot see
    # WHICH override carries it; this reads the placement directly
    assert [override["when"].get("timezone") for override in overrides] == [
        "Asia/Shanghai",
        "Asia/Shanghai",
    ]


def test_a_timezone_with_no_schedule_to_describe_refuses() -> None:
    # v3 lets a zone sit beside a whole-day quota weight; v4 has nowhere to put
    # it, and dropping it silently is the one loss the round-trip cannot see
    row = {
        "source": "zai",
        "model_id": "m",
        "observed_at": "2026-09-03",
        "input_mtok": 0.075,
        "window_rates": [{"quota_multiplier": 0.4}],
        "timezone": "Asia/Singapore",
    }
    with pytest.raises(ValueError, match="no scheduled override to describe"):
        migrate_v4.migrate_row(row, VERSION)

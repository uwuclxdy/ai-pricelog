from __future__ import annotations

import json
from collections.abc import Callable
from functools import partial

import pytest

from ai_pricelog.pricing import Pricing
from ai_pricelog.store import (
    SHARD_DIR,
    FxError,
    build_removal_row,
    build_row,
    changed,
    last,
    load,
    load_fx,
    load_shard,
    load_shards,
    newest,
    resolve_rate,
    save,
    save_shard,
    shard_name,
    union,
    write_index,
)

VERSION = 4

EUR_FX: dict[str, dict[str, float]] = {
    "EUR": {"2026-08-20": 1.05, "2026-08-26": 1.1, "2026-08-28": 1.1643}
}


def eur_resolve(
    fx: dict[str, dict[str, float]] = EUR_FX,
) -> Callable[[str, str], tuple[float, str] | None]:
    return partial(resolve_rate, fx, None)


def test_load_missing_file_returns_empty(tmp_path):
    assert load(tmp_path / "nope.ndjson") == []


def test_load_invalid_json_line_names_file_and_line(tmp_path):
    path = tmp_path / "history.ndjson"
    path.write_text('{"source": "a", "model_id": "m", "observed_at": "t", "url": "u"}\n{oops\n')
    with pytest.raises(ValueError) as excinfo:
        load(path)
    message = str(excinfo.value)
    assert str(path) in message
    assert "line 2" in message


def test_load_non_object_line_names_file_and_line(tmp_path):
    path = tmp_path / "history.ndjson"
    path.write_text('{"source": "a"}\n[1, 2]\n')
    with pytest.raises(ValueError) as excinfo:
        load(path)
    message = str(excinfo.value)
    assert str(path) in message
    assert "line 2" in message


def test_save_load_roundtrip_preserves_order_and_trailing_newline(tmp_path):
    rows = [
        {"schema": 4, "source": "a", "model_id": "m", "observed_at": "t1", "rates": {"input": 1.5}},
        {"schema": 4, "source": "b", "model_id": "n", "observed_at": "t2", "rates": {"input": 2.5}},
    ]
    path = tmp_path / "history.ndjson"
    save(rows, path)
    assert load(path) == rows
    expected = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows
    )
    assert path.read_text(encoding="utf-8") == expected


def test_shard_dir_constant():
    assert SHARD_DIR == "data/history"


def test_shard_name_appends_ndjson():
    assert shard_name("deepseek") == "deepseek.ndjson"


def test_shard_name_refuses_a_non_segment_source():
    for bad in ("../escaped", "a/b", "a b", "", ".", "UPPER"):
        with pytest.raises(ValueError, match="cannot name a shard file"):
            shard_name(bad)


def test_save_shard_sorts_by_model_then_date(tmp_path):
    rows = [
        {"schema": 4, "source": "a", "model_id": "b", "observed_at": "2026-08-20"},
        {"schema": 4, "source": "a", "model_id": "a", "observed_at": "2026-08-22"},
        {"schema": 4, "source": "a", "model_id": "b", "observed_at": "2026-08-19"},
    ]
    save_shard(rows, tmp_path, "a")
    loaded = load_shard(tmp_path, "a")
    assert [(r["model_id"], r["observed_at"]) for r in loaded] == [
        ("a", "2026-08-22"),
        ("b", "2026-08-19"),
        ("b", "2026-08-20"),
    ]
    text = (tmp_path / "a.ndjson").read_text(encoding="utf-8")
    assert '", "' not in text
    assert ": " not in text


def test_save_shard_refuses_a_source_that_escapes(tmp_path):
    with pytest.raises(ValueError, match="cannot name a shard file"):
        save_shard([], tmp_path, "../escaped")
    assert not (tmp_path.parent / "escaped.ndjson").exists()


def test_load_shard_reads_one_source(tmp_path):
    save_shard([{"schema": 4, "source": "a", "model_id": "m", "observed_at": "t1"}], tmp_path, "a")
    save_shard([{"schema": 4, "source": "b", "model_id": "m", "observed_at": "t2"}], tmp_path, "b")
    assert [r["source"] for r in load_shard(tmp_path, "a")] == ["a"]
    assert load_shard(tmp_path, "missing") == []


def test_load_shards_concatenates_in_filename_order(tmp_path):
    (tmp_path / "a.ndjson").write_text(
        '{"schema":4,"source":"a","model_id":"m","observed_at":"t1"}\n', encoding="utf-8"
    )
    (tmp_path / "b.ndjson").write_text(
        '{"schema":4,"source":"b","model_id":"m","observed_at":"t2"}\n', encoding="utf-8"
    )
    (tmp_path / "z.ndjson").write_text(
        '{"schema":4,"source":"z","model_id":"m","observed_at":"t3"}\n', encoding="utf-8"
    )
    assert [r["source"] for r in load_shards(tmp_path)] == ["a", "b", "z"]


def test_union_dedupes_by_source_model_observed_at():
    base = [
        {"source": "a", "model_id": "m", "observed_at": "t1"},
        {"source": "a", "model_id": "n", "observed_at": "t2"},
    ]
    extra = [
        {"source": "a", "model_id": "m", "observed_at": "t1"},  # duplicate of base[0]
        {"source": "a", "model_id": "m", "observed_at": "t3"},
    ]
    assert union(base, extra) == base + [extra[1]]


def test_union_preserves_base_rows_and_order():
    base = [{"source": "a", "model_id": "m", "observed_at": "t1"}]
    assert union(base, []) is not base
    assert union(base, []) == base


def test_union_keeps_removal_row_sharing_a_landed_price_key():
    base = [
        {"source": "a", "model_id": "m", "observed_at": "t1", "rates": {"input": 1.0}},
    ]
    extra = [
        {"source": "a", "model_id": "m", "observed_at": "t1", "removed": True},
    ]
    assert union(base, extra) == base + extra


def test_union_dedupes_carried_removal_copy():
    base = [
        {"source": "a", "model_id": "m", "observed_at": "t1", "removed": True},
        {"source": "a", "model_id": "n", "observed_at": "t2", "rates": {"input": 1.0}},
    ]
    extra = [
        {"source": "a", "model_id": "m", "observed_at": "t1", "removed": True},
        {"source": "a", "model_id": "o", "observed_at": "t2", "removed": True},
    ]
    assert union(base, extra) == base + [extra[1]]


def test_last_returns_latest_row_per_source_and_model():
    rows = [
        {"source": "a", "model_id": "m1", "observed_at": "t1"},
        {"source": "a", "model_id": "m2", "observed_at": "t2"},
        {"source": "b", "model_id": "m1", "observed_at": "t3"},
        {"source": "a", "model_id": "m1", "observed_at": "t4"},
    ]
    assert last(rows, "a", "m1")["observed_at"] == "t4"
    assert last(rows, "a", "m2")["observed_at"] == "t2"
    assert last(rows, "b", "m1")["observed_at"] == "t3"
    assert last(rows, "a", "missing") is None


def test_last_skips_removed_rows():
    rows = [
        {"source": "a", "model_id": "m", "observed_at": "t1", "rates": {"input": 1.0}},
        {"source": "a", "model_id": "m", "observed_at": "t2", "removed": True},
    ]
    assert last(rows, "a", "m")["observed_at"] == "t1"
    assert last([rows[1]], "a", "m") is None


def test_newest_returns_the_newest_row_removal_included():
    rows = [
        {"source": "a", "model_id": "m", "observed_at": "t1", "rates": {"input": 1.0}},
        {"source": "a", "model_id": "m", "observed_at": "t2", "removed": True},
    ]
    assert newest(rows, "a", "m")["observed_at"] == "t2"
    assert newest(rows, "a", "m")["removed"] is True
    assert newest(rows, "a", "n") is None


def test_changed_is_true_for_first_row():
    row = {"schema": 4, "source": "a", "model_id": "m", "observed_at": "t", "rates": {"input": 1.0}}
    assert changed(row, None) is True


def test_changed_ignores_observed_at_only_difference():
    row = {
        "schema": 4,
        "source": "a",
        "model_id": "m",
        "observed_at": "t2",
        "rates": {"input": 1.0},
    }
    prev = {
        "schema": 4,
        "source": "a",
        "model_id": "m",
        "observed_at": "t1",
        "rates": {"input": 1.0},
    }
    assert changed(row, prev) is False


def test_changed_ignores_schema_stamp_only_difference():
    row = {
        "schema": 5,
        "source": "a",
        "model_id": "m",
        "observed_at": "t1",
        "rates": {"input": 1.0},
    }
    prev = {
        "schema": 4,
        "source": "a",
        "model_id": "m",
        "observed_at": "t1",
        "rates": {"input": 1.0},
    }
    assert changed(row, prev) is False


def test_changed_ignores_provenance_only_difference():
    row = {
        "schema": 4,
        "source": "a",
        "model_id": "m",
        "observed_at": "t2",
        "rates": {"input": 1.0},
        "provenance": {"url": "v2"},
    }
    prev = {
        "schema": 4,
        "source": "a",
        "model_id": "m",
        "observed_at": "t1",
        "rates": {"input": 1.0},
        "provenance": {"url": "v1"},
    }
    assert changed(row, prev) is False


def test_changed_ignores_fx_refresh_only_difference():
    row = {
        "schema": 4,
        "source": "scaleway",
        "model_id": "m",
        "observed_at": "t2",
        "rates": {"input": 1.1643},
        "currency": "EUR",
        "provenance": {"fx_rate": 1.1643, "fx_rate_date": "2026-08-28"},
    }
    prev = {
        "schema": 4,
        "source": "scaleway",
        "model_id": "m",
        "observed_at": "t1",
        "rates": {"input": 1.1643},
        "currency": "EUR",
        "provenance": {"fx_rate": 1.1, "fx_rate_date": "2026-08-26"},
    }
    assert changed(row, prev) is False


def test_changed_detects_rates_difference():
    row = {
        "schema": 4,
        "source": "a",
        "model_id": "m",
        "observed_at": "t2",
        "rates": {"input": 2.0},
    }
    prev = {
        "schema": 4,
        "source": "a",
        "model_id": "m",
        "observed_at": "t1",
        "rates": {"input": 1.0},
    }
    assert changed(row, prev) is True


def test_changed_detects_added_field_difference():
    row = {
        "schema": 4,
        "source": "a",
        "model_id": "m",
        "observed_at": "t2",
        "rates": {"input": 1.0},
        "limits": {"context": 4096},
    }
    prev = {
        "schema": 4,
        "source": "a",
        "model_id": "m",
        "observed_at": "t1",
        "rates": {"input": 1.0},
    }
    assert changed(row, prev) is True


def test_changed_detects_dropped_field():
    row = {
        "schema": 4,
        "source": "a",
        "model_id": "m",
        "observed_at": "t2",
        "rates": {"input": 1.0},
    }
    prev = {
        "schema": 4,
        "source": "a",
        "model_id": "m",
        "observed_at": "t1",
        "rates": {"input": 1.0, "output": 0.5},
    }
    assert changed(row, prev) is True


def test_changed_detects_currency_difference():
    row = {
        "schema": 4,
        "source": "a",
        "model_id": "m",
        "observed_at": "t2",
        "rates": {"input": 1.0},
        "currency": "EUR",
    }
    prev = {
        "schema": 4,
        "source": "a",
        "model_id": "m",
        "observed_at": "t1",
        "rates": {"input": 1.0},
    }
    assert changed(row, prev) is True


def test_changed_treats_a_removed_last_row_as_first():
    row = {
        "schema": 4,
        "source": "a",
        "model_id": "m",
        "observed_at": "t2",
        "rates": {"input": 1.0},
    }
    removed = {"schema": 4, "source": "a", "model_id": "m", "observed_at": "t1", "removed": True}
    assert changed(row, removed) is True


def test_build_row_maps_per_token_to_mtok_and_rounds():
    pricing = Pricing(input_cost_per_token=0.000000435, output_cost_per_token=0.000001, mode="flex")
    row = build_row(
        "deepseek", "deepseek/model", pricing, "2026-08-26T00:00:00Z", "https://x", VERSION
    )
    assert list(row) == ["schema", "source", "model_id", "observed_at", "rates", "provenance"]
    assert row["schema"] == VERSION
    assert row["source"] == "deepseek"
    assert row["model_id"] == "deepseek/model"
    assert row["observed_at"] == "2026-08-26T00:00:00Z"
    assert row["rates"] == {"input": 0.435, "output": 1.0}
    assert row["provenance"] == {"url": "https://x"}


def test_build_row_omits_empty_containers():
    pricing = Pricing(input_cost_per_token=1e-6, output_cost_per_token=2e-6, mode="flex")
    row = build_row("a", "m", pricing, "t", "u", VERSION)
    assert "overrides" not in row
    assert "fees" not in row
    assert "limits" not in row
    assert "unmapped" not in row
    assert "currency" not in row
    assert "effective_at" not in row


def test_build_row_copies_effective_at():
    pricing = Pricing(1e-6, 2e-6, "flex", effective_at="2026-08-23")
    row = build_row("deepseek", "m", pricing, "2026-08-30", "u", VERSION)
    assert row["effective_at"] == "2026-08-23"


def test_build_row_includes_cache_read_and_limits():
    pricing = Pricing(
        input_cost_per_token=1e-6,
        output_cost_per_token=2e-6,
        mode="flex",
        cache_read_cost_per_token=0.0000001,
        max_tokens_in=200000,
        max_tokens_out=8192,
    )
    row = build_row("a", "m", pricing, "t", "u", VERSION)
    assert row["rates"]["cache_read"] == 0.1
    assert row["limits"] == {"context": 200000, "output": 8192}


def test_build_row_includes_cache_write_tiers():
    pricing = Pricing(
        input_cost_per_token=1e-6,
        output_cost_per_token=2e-6,
        mode="chat",
        cache_write_cost_per_token=1.25e-6,
        cache_write_1h_cost_per_token=2e-6,
    )
    row = build_row("a", "m", pricing, "t", "u", VERSION)
    assert row["rates"]["cache_write"] == 1.25
    assert row["rates"]["cache_write_1h"] == 2.0


def test_build_row_maps_peak_fields_to_overrides():
    pricing = Pricing(
        input_cost_per_token=1e-6,
        output_cost_per_token=2e-6,
        mode="flex",
        peak_input_cost_per_token=0.000002,
        peak_output_cost_per_token=0.000004,
        peak_cache_read_cost_per_token=0.0000005,
        peak_windows=((0, 400), (600, 1000)),
    )
    row = build_row("a", "m", pricing, "t", "u", VERSION)
    assert row["overrides"] == [
        {"when": {"window": [0, 400]}, "rates": {"input": 2.0, "output": 4.0, "cache_read": 0.5}},
        {
            "when": {"window": [600, 1000]},
            "rates": {"input": 2.0, "output": 4.0, "cache_read": 0.5},
        },
    ]
    assert "peak_windows" not in row
    assert "peak_input_mtok" not in row


def test_build_row_peak_cache_read_alone_triggers_peak_block():
    pricing = Pricing(
        input_cost_per_token=1e-6,
        output_cost_per_token=2e-6,
        mode="flex",
        peak_cache_read_cost_per_token=0.0000005,
        peak_windows=((0, 400),),
    )
    row = build_row("a", "m", pricing, "t", "u", VERSION)
    assert row["overrides"] == [{"when": {"window": [0, 400]}, "rates": {"cache_read": 0.5}}]


def test_build_row_peak_days_without_windows_builds_day_only_entry():
    pricing = Pricing(
        input_cost_per_token=1e-6,
        output_cost_per_token=2e-6,
        mode="flex",
        peak_input_cost_per_token=0.000002,
        peak_days=("monday", "tuesday", "wednesday", "thursday", "friday"),
    )
    row = build_row("a", "m", pricing, "t", "u", VERSION)
    assert row["overrides"] == [
        {
            "when": {"days": ["monday", "tuesday", "wednesday", "thursday", "friday"]},
            "rates": {"input": 2.0},
        }
    ]


def test_build_row_peak_prices_without_windows_or_days_builds_rates_only_override():
    pricing = Pricing(
        input_cost_per_token=1e-6,
        output_cost_per_token=2e-6,
        mode="flex",
        peak_input_cost_per_token=0.000002,
    )
    row = build_row("a", "m", pricing, "t", "u", VERSION)
    # the row still builds; the schedule-less override is validate's to reject
    assert row["overrides"] == [{"rates": {"input": 2.0}}]


def test_build_row_appends_converted_window_rates_entries():
    pricing = Pricing(
        input_cost_per_token=1e-6,
        output_cost_per_token=2e-6,
        mode="flex",
        window_rates=(
            {"quota_multiplier": 0.4},
            {"days": ["monday", "tuesday"], "window": [600, 1000], "quota_multiplier": 1.2},
            {"days": ["saturday"], "input_mtok": 0.9, "output_mtok": 1.8},
        ),
    )
    row = build_row("a", "m", pricing, "t", "u", VERSION)
    assert row["overrides"] == [
        {"quota_multiplier": 0.4},
        {
            "when": {"days": ["monday", "tuesday"], "window": [600, 1000]},
            "quota_multiplier": 1.2,
        },
        {"when": {"days": ["saturday"]}, "rates": {"input": 0.9, "output": 1.8}},
    ]


def test_build_row_stamps_timezone_inside_scheduled_override_when():
    pricing = Pricing(
        input_cost_per_token=1e-6,
        output_cost_per_token=2e-6,
        mode="flex",
        window_rates=(
            {"quota_multiplier": 0.4},
            {"days": ["monday"], "window": [600, 1000], "quota_multiplier": 1.2},
        ),
        timezone="Asia/Singapore",
    )
    row = build_row("a", "m", pricing, "t", "u", VERSION)
    assert row["overrides"] == [
        {"quota_multiplier": 0.4},
        {
            "when": {"days": ["monday"], "window": [600, 1000], "timezone": "Asia/Singapore"},
            "quota_multiplier": 1.2,
        },
    ]


def test_build_row_stamps_the_page_the_scraper_read():
    pricing = Pricing(input_cost_per_token=1e-6, output_cost_per_token=2e-6, mode="flex")
    row = build_row("a", "m", pricing, "t", "https://index", VERSION)
    assert row["provenance"]["url"] == "https://index"
    pricing = Pricing(
        input_cost_per_token=1e-6,
        output_cost_per_token=2e-6,
        mode="flex",
        url="https://resolved-page",
    )
    row = build_row("a", "m", pricing, "t", "https://index", VERSION)
    assert row["provenance"]["url"] == "https://resolved-page"


def test_build_row_converts_eur_quote_to_usd():
    pricing = Pricing(
        input_cost_per_token=1e-6,
        output_cost_per_token=2e-6,
        mode="flex",
        currency="EUR",
    )
    row = build_row("scaleway", "m", pricing, "2026-08-28", "u", VERSION, resolve=eur_resolve())
    assert list(row) == [
        "schema",
        "source",
        "model_id",
        "observed_at",
        "currency",
        "rates",
        "provenance",
    ]
    assert row["currency"] == "EUR"
    assert row["rates"] == {"input": 1.1643, "output": 2.3286}
    assert row["provenance"] == {"url": "u", "fx_rate": 1.1643, "fx_rate_date": "2026-08-28"}


def test_build_row_converts_a_scheduled_rate_too():
    # the scheduled rates arrive already per-million, so they scale by the fx
    # factor rather than re-converting. without the factor a non-USD provider
    # with a schedule would store source-currency values under USD axes
    pricing = Pricing(
        input_cost_per_token=1e-6,
        output_cost_per_token=2e-6,
        mode="flex",
        currency="EUR",
        window_rates=({"days": ["saturday"], "input_mtok": 0.9},),
    )
    row = build_row("scaleway", "m", pricing, "2026-08-28", "u", VERSION, resolve=eur_resolve())
    assert row["rates"]["input"] == 1.1643
    assert row["overrides"] == [
        {"when": {"days": ["saturday"]}, "rates": {"input": round(0.9 * 1.1643, 6)}}
    ]


def test_build_row_picks_latest_rate_on_or_before_observation():
    pricing = Pricing(1e-6, 2e-6, "flex", currency="EUR")
    row = build_row("scaleway", "m", pricing, "2026-08-27", "u", VERSION, resolve=eur_resolve())
    assert row["provenance"]["fx_rate"] == 1.1
    assert row["provenance"]["fx_rate_date"] == "2026-08-26"
    assert row["rates"]["input"] == 1.1


def test_build_row_converts_every_price_field_but_not_limits():
    pricing = Pricing(
        input_cost_per_token=1e-6,
        output_cost_per_token=2e-6,
        mode="flex",
        cache_read_cost_per_token=5e-7,
        cache_write_cost_per_token=1.25e-6,
        cache_write_1h_cost_per_token=2e-6,
        peak_input_cost_per_token=2e-6,
        peak_output_cost_per_token=4e-6,
        peak_cache_read_cost_per_token=5e-7,
        peak_windows=((0, 400),),
        max_tokens_in=200000,
        max_tokens_out=8192,
        currency="EUR",
    )
    row = build_row("scaleway", "m", pricing, "2026-08-26", "u", VERSION, resolve=eur_resolve())
    assert row["rates"]["input"] == 1.1
    assert row["rates"]["output"] == 2.2
    assert row["rates"]["cache_read"] == 0.55
    assert row["rates"]["cache_write"] == 1.375
    assert row["rates"]["cache_write_1h"] == 2.2
    assert row["overrides"] == [
        {"when": {"window": [0, 400]}, "rates": {"input": 2.2, "output": 4.4, "cache_read": 0.55}}
    ]
    assert row["limits"] == {"context": 200000, "output": 8192}


def test_build_row_requires_resolver_for_non_usd_quote():
    pricing = Pricing(1e-6, 2e-6, "flex", currency="EUR")
    with pytest.raises(FxError, match="resolver"):
        build_row("scaleway", "m", pricing, "2026-08-28", "u", VERSION)


def test_build_row_dbu_quote_converts_via_provider_rate():
    pricing = Pricing(7e-8, 1.4e-7, "chat", currency="DBU")
    row = build_row(
        "databricks",
        "m",
        pricing,
        "2026-08-28",
        "u",
        VERSION,
        resolve=partial(resolve_rate, {}, 0.55),
    )
    assert row["currency"] == "DBU"
    assert row["provenance"]["fx_rate"] == 0.55
    assert row["provenance"]["fx_rate_date"] == "2026-08-28"
    assert row["rates"]["input"] == 0.0385
    assert row["rates"]["output"] == 0.077


def test_build_row_refuses_non_token_units():
    pricing = Pricing(1e-6, 2e-6, "flex", unit="minutes")
    with pytest.raises(ValueError, match="non-token"):
        build_row("a", "m", pricing, "2026-08-28", "u", VERSION)


def test_build_removal_row_shape():
    assert build_removal_row("deepseek", "deepseek-chat", "2026-08-26", VERSION) == {
        "schema": 4,
        "source": "deepseek",
        "model_id": "deepseek-chat",
        "observed_at": "2026-08-26",
        "removed": True,
    }


def test_build_removal_row_copies_the_final_price_snapshot():
    last_row = {
        "schema": 4,
        "source": "a",
        "model_id": "m",
        "observed_at": "t1",
        "effective_at": "2026-08-23",
        "currency": "EUR",
        "rates": {"input": 1.0, "output": 2.0},
        "overrides": [{"when": {"days": ["saturday"]}, "rates": {"input": 0.5}}],
        "limits": {"context": 4096},
        "provenance": {
            "url": "https://example.com/pricing",
            "fx_rate": 1.1643,
            "fx_rate_date": "2026-08-28",
        },
    }
    removal = build_removal_row("a", "m", "t2", VERSION, last_row)
    assert list(removal) == [
        "schema",
        "source",
        "model_id",
        "observed_at",
        "effective_at",
        "removed",
        "currency",
        "rates",
        "overrides",
        "limits",
        "provenance",
    ]
    assert removal == {
        "schema": 4,
        "source": "a",
        "model_id": "m",
        "observed_at": "t2",
        "effective_at": "2026-08-23",
        "removed": True,
        "currency": "EUR",
        "rates": {"input": 1.0, "output": 2.0},
        "overrides": [{"when": {"days": ["saturday"]}, "rates": {"input": 0.5}}],
        "limits": {"context": 4096},
        "provenance": {"fx_rate": 1.1643, "fx_rate_date": "2026-08-28"},
    }


def test_build_removal_row_without_a_last_row_stays_bare():
    assert build_removal_row("a", "m", "t2", VERSION) == {
        "schema": 4,
        "source": "a",
        "model_id": "m",
        "observed_at": "t2",
        "removed": True,
    }


def test_write_index_first_seen_earliest_and_latest_fields_win(tmp_path):
    rows = [
        {
            "schema": 4,
            "source": "z",
            "model_id": "m1",
            "observed_at": "2026-08-20",
            "rates": {"input": 1.0},
            "provenance": {"url": "z1"},
        },
        {
            "schema": 4,
            "source": "a",
            "model_id": "m2",
            "observed_at": "2026-08-21",
            "rates": {"input": 2.0},
            "provenance": {"url": "a1"},
        },
        {
            "schema": 4,
            "source": "a",
            "model_id": "m1",
            "observed_at": "2026-08-22",
            "rates": {"input": 3.0, "output": 0.5},
            "provenance": {"url": "a2"},
        },
        {
            "schema": 4,
            "source": "a",
            "model_id": "m1",
            "observed_at": "2026-08-19",
            "rates": {"input": 4.0},
            "provenance": {"url": "a0"},
        },
        {
            "schema": 4,
            "source": "a",
            "model_id": "m1",
            "observed_at": "2026-08-23",
            "rates": {"input": 5.0},
            "provenance": {"url": "a3"},
        },
    ]
    path = tmp_path / "index.json"
    write_index(rows, path, VERSION)
    index = json.loads(path.read_text(encoding="utf-8"))
    assert index["version"] == VERSION
    sources = index["sources"]
    assert list(sources) == ["a", "z"]
    assert list(sources["a"]) == ["m1", "m2"]
    m1 = sources["a"]["m1"]
    # latest row fields win: input from the last row, output dropped
    assert m1["rates"] == {"input": 5.0}
    assert m1["provenance"] == {"url": "a3"}
    # first_seen is the earliest observed_at even when appended out of order
    assert m1["observed_at"] == "2026-08-23"
    assert m1["first_seen"] == "2026-08-19"
    assert list(m1) == [
        "schema",
        "source",
        "model_id",
        "observed_at",
        "rates",
        "provenance",
        "first_seen",
    ]
    assert sources["a"]["m2"]["first_seen"] == "2026-08-21"
    assert sources["z"]["m1"]["first_seen"] == "2026-08-20"


def test_write_index_picks_max_observed_at_not_last_row(tmp_path):
    rows = [
        {
            "schema": 4,
            "source": "a",
            "model_id": "m",
            "observed_at": "2026-08-23",
            "rates": {"input": 5.0},
            "provenance": {"url": "new"},
        },
        {
            "schema": 4,
            "source": "a",
            "model_id": "m",
            "observed_at": "2026-08-19",
            "rates": {"input": 4.0},
            "provenance": {"url": "old"},
        },
    ]
    path = tmp_path / "index.json"
    write_index(rows, path, VERSION)
    entry = json.loads(path.read_text(encoding="utf-8"))["sources"]["a"]["m"]
    assert entry["rates"]["input"] == 5.0
    assert entry["observed_at"] == "2026-08-23"
    assert entry["first_seen"] == "2026-08-19"


def test_write_index_removed_at_stamps_and_clears(tmp_path):
    rows = [
        {
            "schema": 4,
            "source": "a",
            "model_id": "m",
            "observed_at": "2026-08-20",
            "rates": {"input": 1.0},
            "provenance": {"url": "u1"},
        },
        {"schema": 4, "source": "a", "model_id": "m", "observed_at": "2026-08-22", "removed": True},
    ]
    path = tmp_path / "index.json"
    write_index(rows, path, VERSION)
    entry = json.loads(path.read_text(encoding="utf-8"))["sources"]["a"]["m"]
    assert entry["rates"] == {"input": 1.0}
    assert entry["provenance"] == {"url": "u1"}
    assert entry["removed_at"] == "2026-08-22"
    assert "removed" not in entry
    rows.append(
        {
            "schema": 4,
            "source": "a",
            "model_id": "m",
            "observed_at": "2026-08-24",
            "rates": {"input": 1.0},
            "provenance": {"url": "u2"},
        }
    )
    write_index(rows, path, VERSION)
    entry = json.loads(path.read_text(encoding="utf-8"))["sources"]["a"]["m"]
    assert "removed_at" not in entry
    assert entry["observed_at"] == "2026-08-24"
    assert entry["provenance"] == {"url": "u2"}


def test_write_index_tie_resolves_to_later_row_in_file(tmp_path):
    rows = [
        {
            "schema": 4,
            "source": "a",
            "model_id": "m",
            "observed_at": "2026-08-23",
            "rates": {"input": 4.0},
            "provenance": {"url": "first"},
        },
        {
            "schema": 4,
            "source": "a",
            "model_id": "m",
            "observed_at": "2026-08-23",
            "rates": {"input": 5.0},
            "provenance": {"url": "second"},
        },
    ]
    path = tmp_path / "index.json"
    write_index(rows, path, VERSION)
    entry = json.loads(path.read_text(encoding="utf-8"))["sources"]["a"]["m"]
    assert entry["rates"]["input"] == 5.0
    assert entry["provenance"] == {"url": "second"}


def test_resolve_rate_returns_none_for_usd():
    assert resolve_rate(EUR_FX, 0.55, "USD", "2026-08-28") is None


def test_resolve_rate_missing_currency_names_the_fix():
    with pytest.raises(FxError, match="GBP"):
        resolve_rate(EUR_FX, None, "GBP", "2026-08-28")


def test_resolve_rate_missing_date_names_the_fix():
    with pytest.raises(FxError, match="2026-08-27"):
        resolve_rate({"EUR": {"2026-08-28": 1.2}}, None, "EUR", "2026-08-27")


def test_resolve_rate_missing_dbu_config_names_the_fix():
    with pytest.raises(FxError, match="DBU"):
        resolve_rate({}, None, "DBU", "2026-08-28")


def test_resolve_rate_dbu_uses_provider_rate_with_observation_date():
    assert resolve_rate({}, 0.55, "DBU", "2026-08-28T00:00:00Z") == (0.55, "2026-08-28")


def test_resolve_rate_dbu_ignores_an_fx_table_dbu_key():
    assert resolve_rate({"DBU": {"2026-08-20": 9.99}}, 0.55, "DBU", "2026-08-28") == (
        0.55,
        "2026-08-28",
    )


def test_load_fx_reads_the_committed_table(tmp_path):
    path = tmp_path / "fx-rates.json"
    path.write_text('{"EUR": {"2026-08-28": 1.1643}}\n', encoding="utf-8")
    assert load_fx(path) == {"EUR": {"2026-08-28": 1.1643}}


def test_load_fx_missing_file_is_an_empty_table(tmp_path):
    assert load_fx(tmp_path / "nope.json") == {}


def test_load_fx_bad_shapes_name_the_file(tmp_path):
    path = tmp_path / "fx-rates.json"
    path.write_text("{oops\n", encoding="utf-8")
    with pytest.raises(FxError, match="invalid json"):
        load_fx(path)
    path.write_text("[1]\n", encoding="utf-8")
    with pytest.raises(FxError, match="must be an object"):
        load_fx(path)
    path.write_text('{"EUR": {"2026-08-28": -1.0}}\n', encoding="utf-8")
    with pytest.raises(FxError, match="2026-08-28"):
        load_fx(path)
    path.write_text('{"EUR": []}\n', encoding="utf-8")
    with pytest.raises(FxError, match="EUR"):
        load_fx(path)


def test_load_fx_rejects_bad_date_key(tmp_path):
    path = tmp_path / "fx-rates.json"
    path.write_text('{"EUR": {"2026-8-28": 1.1643}}\n', encoding="utf-8")
    with pytest.raises(FxError, match="2026-8-28"):
        load_fx(path)

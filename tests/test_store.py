from __future__ import annotations

import json

import pytest

from ai_pricelog import validate
from ai_pricelog.pricing import Pricing
from ai_pricelog.store import (
    build_removal_row,
    build_row,
    changed,
    last,
    load,
    newest,
    save,
    union,
    write_index,
)


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
        {"source": "a", "model_id": "m", "observed_at": "t1", "input_mtok": 1.5, "url": "u"},
        {"source": "b", "model_id": "n", "observed_at": "t2", "input_mtok": 2.5, "url": "ü"},
    ]
    path = tmp_path / "history.ndjson"
    save(rows, path)
    assert load(path) == rows
    expected = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows
    )
    assert path.read_text(encoding="utf-8") == expected


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
    # a same-day landed price row and a pending removal row share the
    # (source, model_id, observed_at) key; the removal must survive the dedupe
    base = [
        {"source": "a", "model_id": "m", "observed_at": "t1", "input_mtok": 1.0},
    ]
    extra = [
        {"source": "a", "model_id": "m", "observed_at": "t1", "removed": True},
    ]
    assert union(base, extra) == base + extra


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


def test_changed_is_true_for_first_row():
    row = {"source": "a", "model_id": "m", "observed_at": "t", "input_mtok": 1.0}
    assert changed(row, None) is True


def test_changed_ignores_observed_at_only_difference():
    row = {"source": "a", "model_id": "m", "observed_at": "t2", "input_mtok": 1.0}
    prev = {"source": "a", "model_id": "m", "observed_at": "t1", "input_mtok": 1.0}
    assert changed(row, prev) is False


def test_changed_detects_value_and_added_field_differences():
    row = {"source": "a", "model_id": "m", "observed_at": "t2", "input_mtok": 2.0}
    prev = {"source": "a", "model_id": "m", "observed_at": "t1", "input_mtok": 1.0}
    assert changed(row, prev) is True


def test_changed_ignores_url_only_difference():
    row = {"source": "a", "model_id": "m", "observed_at": "t2", "input_mtok": 1.0, "url": "v2"}
    prev = {"source": "a", "model_id": "m", "observed_at": "t1", "input_mtok": 1.0, "url": "v1"}
    assert changed(row, prev) is False


def test_changed_ignores_name_only_difference():
    row = {"source": "a", "model_id": "m", "observed_at": "t2", "input_mtok": 1.0, "name": "n2"}
    prev = {"source": "a", "model_id": "m", "observed_at": "t1", "input_mtok": 1.0}
    assert changed(row, prev) is False


def test_changed_treats_legacy_max_tokens_as_max_tokens_in():
    # pre-split rows store the context under max_tokens; the rename alone is
    # not a change
    row = {"source": "a", "model_id": "m", "observed_at": "t2", "max_tokens_in": 131072}
    prev = {"source": "a", "model_id": "m", "observed_at": "t1", "max_tokens": 131072}
    assert changed(row, prev) is False


def test_changed_detects_legacy_max_tokens_value_difference():
    row = {"source": "a", "model_id": "m", "observed_at": "t2", "max_tokens_in": 1048576}
    prev = {"source": "a", "model_id": "m", "observed_at": "t1", "max_tokens": 393216}
    assert changed(row, prev) is True


def test_changed_detects_dropped_field():
    row = {"source": "a", "model_id": "m", "observed_at": "t2", "input_mtok": 1.0}
    prev = {
        "source": "a",
        "model_id": "m",
        "observed_at": "t1",
        "input_mtok": 1.0,
        "output_mtok": 0.5,
    }
    assert changed(row, prev) is True


def test_build_row_maps_per_token_to_mtok_and_rounds():
    pricing = Pricing(input_cost_per_token=0.000000435, output_cost_per_token=0.000001, mode="flex")
    row = build_row("deepseek", "deepseek/model", pricing, "2026-08-26T00:00:00Z", "https://x")
    assert list(row) == ["source", "model_id", "observed_at", "input_mtok", "output_mtok", "url"]
    assert row["source"] == "deepseek"
    assert row["model_id"] == "deepseek/model"
    assert row["observed_at"] == "2026-08-26T00:00:00Z"
    assert row["input_mtok"] == 0.435
    assert row["output_mtok"] == 1.0
    assert row["url"] == "https://x"


def test_build_row_omits_optional_fields_when_absent():
    pricing = Pricing(input_cost_per_token=1e-6, output_cost_per_token=2e-6, mode="flex")
    row = build_row("a", "m", pricing, "t", "u")
    assert "cache_read_mtok" not in row
    assert "max_tokens_in" not in row
    assert "max_tokens_out" not in row
    assert "peak_windows" not in row
    assert "peak_input_mtok" not in row
    assert "peak_output_mtok" not in row
    assert "peak_cache_read_mtok" not in row


def test_build_row_includes_cache_read_and_max_tokens():
    pricing = Pricing(
        input_cost_per_token=1e-6,
        output_cost_per_token=2e-6,
        mode="flex",
        cache_read_cost_per_token=0.0000001,
        max_tokens_in=200000,
        max_tokens_out=8192,
    )
    row = build_row("a", "m", pricing, "t", "u")
    assert row["cache_read_mtok"] == 0.1
    assert row["max_tokens_in"] == 200000
    assert row["max_tokens_out"] == 8192


def test_build_row_emits_peak_fields_together():
    pricing = Pricing(
        input_cost_per_token=1e-6,
        output_cost_per_token=2e-6,
        mode="flex",
        peak_input_cost_per_token=0.000002,
        peak_output_cost_per_token=0.000004,
        peak_cache_read_cost_per_token=0.0000005,
        peak_windows=(("00:00", "04:00"), ("06:00", "10:00")),
    )
    row = build_row("a", "m", pricing, "t", "u")
    assert row["peak_windows"] == [["00:00", "04:00"], ["06:00", "10:00"]]
    assert row["peak_input_mtok"] == 2.0
    assert row["peak_output_mtok"] == 4.0
    assert row["peak_cache_read_mtok"] == 0.5


def test_build_row_stamps_the_page_the_scraper_read():
    # the scraper's own url names the row unless the scrape resolved another
    # page (moonshot reads the index to find the per-model page)
    pricing = Pricing(input_cost_per_token=1e-6, output_cost_per_token=2e-6, mode="flex")
    row = build_row("a", "m", pricing, "t", "https://index")
    assert row["url"] == "https://index"
    pricing = Pricing(
        input_cost_per_token=1e-6,
        output_cost_per_token=2e-6,
        mode="flex",
        url="https://resolved-page",
    )
    row = build_row("a", "m", pricing, "t", "https://index")
    assert row["url"] == "https://resolved-page"


def test_build_row_peak_cache_read_alone_triggers_peak_block():
    pricing = Pricing(
        input_cost_per_token=1e-6,
        output_cost_per_token=2e-6,
        mode="flex",
        peak_cache_read_cost_per_token=0.0000005,
        peak_windows=(("00:00", "04:00"),),
    )
    row = build_row("a", "m", pricing, "t", "u")
    assert row["peak_windows"] == [["00:00", "04:00"]]
    assert row["peak_cache_read_mtok"] == 0.5
    assert "peak_input_mtok" not in row
    assert "peak_output_mtok" not in row


def test_build_row_peak_prices_without_windows_builds_and_validation_rejects():
    pricing = Pricing(
        input_cost_per_token=1e-6,
        output_cost_per_token=2e-6,
        mode="flex",
        peak_input_cost_per_token=0.000002,
    )
    row = build_row("a", "m", pricing, "t", "u")
    assert row["peak_windows"] == []
    assert row["peak_input_mtok"] == 2.0
    # one malformed scrape must fail only its own row, not the whole run
    with pytest.raises(validate.ValidationError, match="peak_windows"):
        validate.validate_row(row)


def test_write_index_first_seen_earliest_and_latest_fields_win(tmp_path):
    rows = [
        {
            "source": "z",
            "model_id": "m1",
            "observed_at": "2026-08-20",
            "input_mtok": 1.0,
            "url": "z1",
        },
        {
            "source": "a",
            "model_id": "m2",
            "observed_at": "2026-08-21",
            "input_mtok": 2.0,
            "url": "a1",
        },
        {
            "source": "a",
            "model_id": "m1",
            "observed_at": "2026-08-22",
            "input_mtok": 3.0,
            "output_mtok": 0.5,
            "url": "a2",
        },
        {
            "source": "a",
            "model_id": "m1",
            "observed_at": "2026-08-19",
            "input_mtok": 4.0,
            "url": "a0",
        },
        {
            "source": "a",
            "model_id": "m1",
            "observed_at": "2026-08-23",
            "input_mtok": 5.0,
            "url": "a3",
        },
    ]
    path = tmp_path / "index.json"
    write_index(rows, path)
    index = json.loads(path.read_text(encoding="utf-8"))
    sources = index["sources"]
    assert list(sources) == ["a", "z"]
    assert list(sources["a"]) == ["m1", "m2"]
    m1 = sources["a"]["m1"]
    # latest row fields win: input_mtok from the last row, output_mtok dropped
    assert m1["input_mtok"] == 5.0
    assert m1["url"] == "a3"
    assert "output_mtok" not in m1
    # first_seen is the earliest observed_at even when appended out of order
    assert m1["observed_at"] == "2026-08-23"
    assert m1["first_seen"] == "2026-08-19"
    assert list(m1) == ["source", "model_id", "observed_at", "input_mtok", "url", "first_seen"]
    assert sources["a"]["m2"]["first_seen"] == "2026-08-21"
    assert sources["z"]["m1"]["first_seen"] == "2026-08-20"


def test_write_index_picks_max_observed_at_not_last_row(tmp_path):
    rows = [
        {
            "source": "a",
            "model_id": "m",
            "observed_at": "2026-08-23",
            "input_mtok": 5.0,
            "url": "new",
        },
        {
            "source": "a",
            "model_id": "m",
            "observed_at": "2026-08-19",
            "input_mtok": 4.0,
            "url": "old",
        },
    ]
    path = tmp_path / "index.json"
    write_index(rows, path)
    entry = json.loads(path.read_text(encoding="utf-8"))["sources"]["a"]["m"]
    assert entry["input_mtok"] == 5.0
    assert entry["observed_at"] == "2026-08-23"
    assert entry["first_seen"] == "2026-08-19"


def test_last_skips_removed_rows():
    rows = [
        {"source": "a", "model_id": "m", "observed_at": "t1", "input_mtok": 1.0},
        {"source": "a", "model_id": "m", "observed_at": "t2", "removed": True},
    ]
    assert last(rows, "a", "m")["observed_at"] == "t1"
    assert last([rows[1]], "a", "m") is None


def test_newest_returns_the_newest_row_removal_included():
    rows = [
        {"source": "a", "model_id": "m", "observed_at": "t1", "input_mtok": 1.0},
        {"source": "a", "model_id": "m", "observed_at": "t2", "removed": True},
    ]
    assert newest(rows, "a", "m")["observed_at"] == "t2"
    assert newest(rows, "a", "m")["removed"] is True
    assert newest(rows, "a", "n") is None


def test_changed_treats_a_removed_last_row_as_first():
    row = {"source": "a", "model_id": "m", "observed_at": "t2", "input_mtok": 1.0}
    removed = {"source": "a", "model_id": "m", "observed_at": "t1", "removed": True}
    assert changed(row, removed) is True


def test_build_removal_row_shape():
    assert build_removal_row("deepseek", "deepseek-chat", "2026-08-26") == {
        "source": "deepseek",
        "model_id": "deepseek-chat",
        "observed_at": "2026-08-26",
        "removed": True,
    }


def test_write_index_removed_at_stamps_and_clears(tmp_path):
    rows = [
        {
            "source": "a",
            "model_id": "m",
            "observed_at": "2026-08-20",
            "input_mtok": 1.0,
            "url": "u1",
        },
        {"source": "a", "model_id": "m", "observed_at": "2026-08-22", "removed": True},
    ]
    path = tmp_path / "index.json"
    write_index(rows, path)
    entry = json.loads(path.read_text(encoding="utf-8"))["sources"]["a"]["m"]
    # the entry keeps the last priced row's fields, stamped removed_at
    assert entry["input_mtok"] == 1.0
    assert entry["url"] == "u1"
    assert entry["removed_at"] == "2026-08-22"
    assert "removed" not in entry
    rows.append(
        {
            "source": "a",
            "model_id": "m",
            "observed_at": "2026-08-24",
            "input_mtok": 1.0,
            "url": "u2",
        }
    )
    write_index(rows, path)
    entry = json.loads(path.read_text(encoding="utf-8"))["sources"]["a"]["m"]
    assert "removed_at" not in entry
    assert entry["observed_at"] == "2026-08-24"
    assert entry["url"] == "u2"


def test_write_index_tie_resolves_to_later_row_in_file(tmp_path):
    rows = [
        {
            "source": "a",
            "model_id": "m",
            "observed_at": "2026-08-23",
            "input_mtok": 4.0,
            "url": "first",
        },
        {
            "source": "a",
            "model_id": "m",
            "observed_at": "2026-08-23",
            "input_mtok": 5.0,
            "url": "second",
        },
    ]
    path = tmp_path / "index.json"
    write_index(rows, path)
    entry = json.loads(path.read_text(encoding="utf-8"))["sources"]["a"]["m"]
    assert entry["input_mtok"] == 5.0
    assert entry["url"] == "second"

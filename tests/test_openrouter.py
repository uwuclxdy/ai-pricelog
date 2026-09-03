from __future__ import annotations

from pathlib import Path

import pytest

from ai_pricelog import openrouter, validate
from ai_pricelog.openrouter import (
    OBSERVED_KEYS,
    OpenrouterModel,
    build_row,
    fetch_models,
    map_typed_fields,
)

FIXTURE = Path(__file__).parent / "fixtures" / "openrouter_models.json"
ROOT = Path(__file__).resolve().parents[1]
VERSION = validate.load_schema_keys(ROOT).version


@pytest.fixture()
def fake_fetch(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def fake(url: str) -> str:
        calls.append(url)
        return FIXTURE.read_text()

    monkeypatch.setattr(openrouter, "fetch_text", fake)
    return calls


def test_fetch_models_parses_fixture(fake_fetch: list[str]) -> None:
    models = fetch_models()
    by_id = {m.id: m for m in models}
    glm53 = by_id["z-ai/glm-5.3"]
    assert glm53 == OpenrouterModel("z-ai/glm-5.3", "GLM 5.3", 1.4, 4.4, 0.26)
    v4pro = by_id["deepseek/deepseek-v4-pro"]
    assert v4pro.input_mtok == 0.741588
    assert v4pro.cache_read_mtok == 0.061799
    assert v4pro.output_mtok == 1.483176
    assert by_id["minimax/minimax-m3"].cache_read_mtok == 0.06
    # unconsumed pricing keys (web_search) do not leak into the price fields
    assert by_id["x-ai/grok-4.5"].input_mtok == 2.0


def test_fetch_models_skips_alias_entries(fake_fetch: list[str]) -> None:
    ids = [m.id for m in fetch_models()]
    assert "~z-ai/glm-latest" not in ids
    assert len(ids) == 386


def test_fetch_models_free_model_and_missing_cache_read(fake_fetch: list[str]) -> None:
    by_id = {m.id: m for m in fetch_models()}
    free = by_id["dots-studio/dots-3-note-preview:free"]
    # free models ship all-zero pricing strings; the fetch layer parses
    # zero as None
    assert free.input_mtok is None
    assert free.output_mtok is None
    assert free.cache_read_mtok is None
    seed = by_id["bytedance-seed/seed-2-1-turbo"]
    assert seed.input_mtok == 0.5
    assert seed.output_mtok == 2.5
    assert seed.cache_read_mtok is None


def test_fetch_models_empty_pricing_mapping_is_all_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(url: str) -> str:
        return '{"data": [{"id": "x/y", "name": "X", "pricing": {}}]}'

    monkeypatch.setattr(openrouter, "fetch_text", fake)
    assert fetch_models() == [OpenrouterModel("x/y", "X", None, None, None)]


def test_fetch_models_uses_default_url_and_passes_custom_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def fake(url: str) -> str:
        seen.append(url)
        return FIXTURE.read_text()

    monkeypatch.setattr(openrouter, "fetch_text", fake)
    fetch_models()
    assert seen == ["https://openrouter.ai/api/v1/models"]
    fetch_models("https://example.test/models")
    assert seen[-1] == "https://example.test/models"


def test_fetch_models_rounds_to_six_decimals(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(url: str) -> str:
        return '{"data": [{"id": "a/b", "name": "A", "pricing": {"prompt": "0.0000001234567"}}]}'

    monkeypatch.setattr(openrouter, "fetch_text", fake)
    (model,) = fetch_models()
    assert model.input_mtok == 0.123457


def test_fetch_models_root_shape_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openrouter, "fetch_text", lambda url: "[1, 2]")
    with pytest.raises(ValueError, match="data"):
        fetch_models()
    monkeypatch.setattr(
        openrouter,
        "fetch_text",
        lambda url: '{"data": [{"id": "a/b", "name": "A", "pricing": {"prompt": 5}}]}',
    )
    with pytest.raises(ValueError, match="per-token strings"):
        fetch_models()


def test_openrouter_fixture_is_valid_json() -> None:
    import json

    data = json.loads(FIXTURE.read_text())
    assert isinstance(data, dict)
    assert isinstance(data["data"], list)


def test_fetch_models_strips_vendor_name_prefix(fake_fetch: list[str]) -> None:
    by_id = {m.id: m for m in fetch_models()}
    assert by_id["x-ai/grok-4.5"].name == "Grok 4.5"
    assert by_id["deepseek/deepseek-v4-pro"].name == "DeepSeek V4 Pro 0423"
    assert by_id["dots-studio/dots-3-note-preview:free"].name == "Dots3-Note Preview (free)"


def test_build_row_skips_alias_entries():
    model = OpenrouterModel("~x/y", "X", 1.0, 2.0, None, alias_target={"slug": "x/y"})
    assert build_row(model, "2026-08-26", VERSION) is None


def test_build_row_keeps_stable_ids_with_dated_canonical():
    # the api's stable ids carry a dated canonical spelling; the stable id
    # keys the row, the dated spelling is not a listed entry
    stable = OpenrouterModel("a/b", "A", 1.0, 2.0, None, canonical_slug="a/b-20260101")
    assert build_row(stable, "2026-08-26", VERSION) is not None


def test_build_row_skips_variant_ids_that_redirect_to_a_listed_id():
    variant = OpenrouterModel(
        "a/b:batch", "A Batch", 1.0, 2.0, None, canonical_slug="a/b", variant_snapshot=True
    )
    assert build_row(variant, "2026-08-26", VERSION) is None


def test_build_row_maps_pricing_keys_and_rounds():
    model = OpenrouterModel(
        "a/b",
        "A",
        None,
        None,
        None,
        context_length=131072,
        pricing={
            "prompt": "0.000000435",
            "completion": "0.0000012",
            "input_cache_read": "0.0000001",
            "input_cache_write": "0.0000025",
            "input_cache_write_1h": "0.000004",
        },
    )
    row = build_row(model, "2026-08-26", VERSION)
    assert row is not None
    assert list(row) == [
        "schema",
        "source",
        "model_id",
        "observed_at",
        "rates",
        "limits",
        "provenance",
    ]
    assert row["schema"] == VERSION
    assert row["source"] == "openrouter"
    assert row["model_id"] == "a/b"
    assert row["observed_at"] == "2026-08-26"
    assert row["rates"] == {
        "input": 0.435,
        "output": 1.2,
        "cache_read": 0.1,
        "cache_write": 2.5,
        "cache_write_1h": 4.0,
    }
    assert row["limits"] == {"context": 131072}
    assert row["provenance"] == {"name": "A"}


def test_build_row_omits_missing_prompt_and_empty_name():
    model = OpenrouterModel("a/b", "", None, None, None, pricing={"completion": "0.0000012"})
    row = build_row(model, "2026-08-26", VERSION)
    assert row is not None
    assert "provenance" not in row
    assert "input" not in row["rates"]
    assert row["rates"] == {"output": 1.2}


def test_build_row_promotes_fee_and_volume_overrides():
    # web_search prices per request and lands as a plain USD fee; a
    # volume-threshold override lands as a typed overrides entry
    model = OpenrouterModel(
        "x/y",
        "X",
        None,
        None,
        None,
        pricing={
            "prompt": "0.000001",
            "completion": "0.000002",
            "web_search": "0.005",
            "overrides": [{"min_prompt_tokens": 200000, "prompt": "0.000004"}],
        },
    )
    row = build_row(model, "2026-08-26", VERSION)
    assert row is not None
    assert row["fees"] == {"web_search": 0.005}
    assert row["overrides"] == [{"when": {"min_tokens": 200000}, "rates": {"input": 4.0}}]
    assert "unmapped" not in row


def test_build_row_passes_truly_unknown_pricing_keys_through_unmapped():
    model = OpenrouterModel(
        "x/y",
        "X",
        None,
        None,
        None,
        pricing={
            "prompt": "0.000001",
            "completion": "0.000002",
            "some_new_key": "0.005",
            "overrides": [{"some_new_override": 1}],
        },
    )
    row = build_row(model, "2026-08-26", VERSION)
    assert row is not None
    assert row["unmapped"] == {
        "some_new_key": "0.005",
        "overrides": [{"some_new_override": 1}],
    }


def test_build_row_omits_unmapped_when_all_pricing_keys_consumed():
    model = OpenrouterModel(
        "x/y", "X", None, None, None, pricing={"prompt": "0.000001", "completion": "0.000002"}
    )
    row = build_row(model, "2026-08-26", VERSION)
    assert row is not None
    assert "unmapped" not in row


def test_build_row_keeps_zero_pricing_strings():
    model = OpenrouterModel(
        "x/y", "X", None, None, None, pricing={"prompt": "0", "completion": "0"}
    )
    row = build_row(model, "2026-08-26", VERSION)
    assert row is not None
    assert row["rates"]["input"] == 0.0
    assert row["rates"]["output"] == 0.0


@pytest.mark.parametrize("bad", [{"x": 1}, "abc"])
def test_build_row_names_non_string_pricing_values(bad):
    # the read keys get _price's type check at parse; the write keys go
    # through the build loop only, so a shape change must name itself
    model = OpenrouterModel("a/b", "A", None, None, None, pricing={"input_cache_write": bad})
    with pytest.raises(ValueError, match="per-token string"):
        build_row(model, "2026-08-26", VERSION)


def test_build_row_skips_negative_pricing_strings():
    # router models ship "-1" pricing strings ("no fixed price"); a row must
    # not carry a negative price
    model = OpenrouterModel(
        "openrouter/auto",
        "Auto Router",
        None,
        None,
        None,
        pricing={
            "prompt": "-1",
            "completion": "-1",
            "input_cache_read": "-1",
            "input_cache_write": "-1",
            "input_cache_write_1h": "-1",
        },
    )
    row = build_row(model, "2026-08-26", VERSION)
    assert row is not None
    assert "rates" not in row
    assert "unmapped" not in row


def test_fetch_models_parses_negative_pricing_as_none(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = (
        '{"data": [{"id": "openrouter/auto", "name": "Auto",'
        ' "pricing": {"prompt": "-1", "completion": "-1"}}]}'
    )
    monkeypatch.setattr(openrouter, "fetch_text", lambda url: payload)
    (model,) = fetch_models()
    assert model.input_mtok is None
    assert model.output_mtok is None


def test_fetch_models_marks_variants_that_redirect_to_a_listed_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        '{"data": ['
        '{"id": "a/b", "name": "A", "pricing": {"prompt": "0.000001", "completion": "0.000002"}},'
        '{"id": "a/b:batch", "name": "A Batch",'
        ' "pricing": {"prompt": "0.0000005", "completion": "0.000001"},'
        ' "canonical_slug": "a/b"}'
        "]}"
    )
    monkeypatch.setattr(openrouter, "fetch_text", lambda url: payload)
    models = fetch_models()
    by_id = {m.id: m for m in models}
    assert by_id["a/b"].variant_snapshot is False
    assert by_id["a/b:batch"].variant_snapshot is True
    rows = [row for row in (build_row(m, "2026-08-26", VERSION) for m in models) if row is not None]
    assert [row["model_id"] for row in rows] == ["a/b"]


def test_observed_keys_lists_the_consumed_pricing_keys():
    assert (
        frozenset(
            {
                "prompt",
                "completion",
                "input_cache_read",
                "input_cache_write",
                "input_cache_write_1h",
            }
        )
        == OBSERVED_KEYS
    )


def test_map_typed_fields_rate_keys_match_the_contract_axes():
    keys = validate.load_schema_keys(ROOT)
    pricing = {
        "prompt": "0.000001",
        "completion": "0.000002",
        "input_cache_read": "0.000003",
        "input_cache_write": "0.000004",
        "input_cache_write_1h": "0.000005",
        "image": "0.000006",
        "audio": "0.000007",
        "input_audio_cache": "0.000008",
        "internal_reasoning": "0.000009",
        "image_output": "0.000010",
        "audio_output": "0.000011",
        "web_search": "0.005",
    }
    rates, fees = map_typed_fields(pricing, "x/y")
    assert set(rates) == keys.rate_axes
    assert set(fees) == keys.fees == {"web_search"}


def test_build_row_maps_fixture_cache_write_tiers(fake_fetch: list[str]) -> None:
    by_id = {m.id: m for m in fetch_models()}
    row = build_row(by_id["anthropic/claude-opus-5-fast"], "2026-08-28", VERSION)
    assert row is not None
    assert row["rates"] == {
        "input": 10.0,
        "output": 50.0,
        "cache_read": 1.0,
        "cache_write": 12.5,
        "cache_write_1h": 20.0,
    }
    assert row["limits"] == {"context": 1000000}
    # the write keys ride rate axes, and web_search rides the typed fee;
    # nothing is left for unmapped
    assert row["fees"] == {"web_search": 0.01}
    assert "unmapped" not in row


def test_build_row_keeps_every_non_alias_fixture_model(fake_fetch: list[str]) -> None:
    models = fetch_models()
    rows = []
    for model in models:
        row = build_row(model, "2026-08-26", VERSION)
        if row is not None:
            rows.append(row)
    # 398 listed minus 12 alias entries minus 10 dated-canonical variants
    assert len(rows) == 376
    by_id = {row["model_id"]: row for row in rows}
    sonar = by_id["perplexity/sonar-pro"]
    assert sonar["provenance"] == {"name": "Sonar Pro"}
    assert sonar["fees"] == {"web_search": 0.005}
    assert "unmapped" not in sonar
    assert len(by_id["deepseek/deepseek-v4-flash-vision-exp"]["overrides"]) == 6
    # every rowable model ships a context window in this capture
    assert all("context" in (row.get("limits") or {}) for row in rows)


def test_build_row_maps_scheduled_overrides_to_overrides(fake_fetch: list[str]) -> None:
    by_id = {m.id: m for m in fetch_models()}
    row = build_row(by_id["deepseek/deepseek-v4-pro-0813"], "2026-08-28", VERSION)
    assert row is not None
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    assert row["overrides"] == [
        {
            "when": {"days": ["saturday", "sunday"], "timezone": "UTC"},
            "rates": {"input": 0.66, "output": 1.98, "cache_read": 0.022},
        },
        {
            "when": {"days": weekdays, "window": [0, 100], "timezone": "UTC"},
            "rates": {"input": 0.66, "output": 1.98, "cache_read": 0.022},
        },
        {
            "when": {"days": weekdays, "window": [100, 400], "timezone": "UTC"},
            "rates": {"input": 1.32, "output": 3.96, "cache_read": 0.044},
        },
        {
            "when": {"days": weekdays, "window": [400, 600], "timezone": "UTC"},
            "rates": {"input": 0.66, "output": 1.98, "cache_read": 0.022},
        },
        {
            "when": {"days": weekdays, "window": [600, 1000], "timezone": "UTC"},
            "rates": {"input": 1.32, "output": 3.96, "cache_read": 0.044},
        },
        {
            "when": {"days": weekdays, "window": [1000, 2400], "timezone": "UTC"},
            "rates": {"input": 0.66, "output": 1.98, "cache_read": 0.022},
        },
    ]
    # the override key is consumed: nothing rides unmapped on this model
    assert "unmapped" not in row


def test_build_row_maps_window_only_override_and_wraps_midnight_end(
    fake_fetch: list[str],
) -> None:
    by_id = {m.id: m for m in fetch_models()}
    row = build_row(by_id["tencent/hy3"], "2026-08-28", VERSION)
    assert row is not None
    # utc_end 0 means midnight as the END of the day: normalized to 2400,
    # and an override without utc_days applies every day (no days key)
    assert row["overrides"] == [
        {
            "when": {"window": [0, 1600], "timezone": "UTC"},
            "rates": {"input": 0.132, "output": 0.528, "cache_read": 0.033},
        },
        {
            "when": {"window": [1600, 2400], "timezone": "UTC"},
            "rates": {"input": 0.0825, "output": 0.33, "cache_read": 0.020625},
        },
    ]
    assert "unmapped" not in row


def test_build_row_maps_volume_overrides_to_overrides(fake_fetch: list[str]) -> None:
    by_id = {m.id: m for m in fetch_models()}
    row = build_row(by_id["qwen/qwen3.7-flash"], "2026-08-28", VERSION)
    assert row is not None
    # min_prompt_tokens is a volume threshold, not a schedule: it lands as a
    # typed overrides entry with the rate keys mapped to rate axes
    assert row["overrides"] == [
        {
            "when": {"min_tokens": 32000},
            "rates": {"input": 0.1, "output": 0.4, "cache_read": 0.02, "cache_write": 0.125},
        },
        {
            "when": {"min_tokens": 256000},
            "rates": {"input": 0.2, "output": 0.8, "cache_read": 0.04, "cache_write": 0.25},
        },
    ]


def test_build_row_promotes_modality_keys_to_rate_axes():
    model = OpenrouterModel(
        "a/b",
        "A",
        None,
        None,
        None,
        pricing={
            "prompt": "0.000001",
            "completion": "0.000002",
            "image": "0.0000005",
            "audio": "0.000002",
            "input_audio_cache": "0.0000002",
            "internal_reasoning": "0.000012",
            "image_output": "0.00003",
            "audio_output": "0.000064",
        },
    )
    row = build_row(model, "2026-08-26", VERSION)
    assert row is not None
    assert row["rates"] == {
        "input": 1.0,
        "output": 2.0,
        "image": 0.5,
        "audio": 2.0,
        "input_audio_cache": 0.2,
        "internal_reasoning": 12.0,
        "image_output": 30.0,
        "audio_output": 64.0,
    }
    assert "unmapped" not in row


def test_build_row_rounds_window_rates_to_six_decimals():
    model = OpenrouterModel(
        "a/b",
        "A",
        None,
        None,
        None,
        pricing={
            "prompt": "0.000001",
            "completion": "0.000002",
            "overrides": [{"utc_start": 100, "utc_end": 400, "prompt": "0.0000001234567"}],
        },
    )
    row = build_row(model, "2026-08-26", VERSION)
    assert row is not None
    assert row["overrides"] == [
        {"when": {"window": [100, 400], "timezone": "UTC"}, "rates": {"input": 0.123457}}
    ]


def test_build_row_sorts_window_days():
    model = OpenrouterModel(
        "a/b",
        "A",
        None,
        None,
        None,
        pricing={
            "prompt": "0.000001",
            "overrides": [
                {"utc_days": ["sunday", "saturday"], "prompt": "0.000002"},
            ],
        },
    )
    row = build_row(model, "2026-08-26", VERSION)
    assert row is not None
    assert row["overrides"][0]["when"]["days"] == ["saturday", "sunday"]


def test_build_row_splits_wrap_window_into_two_entries():
    model = OpenrouterModel(
        "a/b",
        "A",
        None,
        None,
        None,
        pricing={
            "prompt": "0.000001",
            "overrides": [
                {
                    "utc_start": 1600,
                    "utc_end": 800,
                    "prompt": "0.000002",
                    "completion": "0.000004",
                }
            ],
        },
    )
    row = build_row(model, "2026-08-26", VERSION)
    assert row is not None
    # a window wrapping past midnight splits into two plain same-day halves
    assert row["overrides"] == [
        {
            "when": {"window": [1600, 2400], "timezone": "UTC"},
            "rates": {"input": 2.0, "output": 4.0},
        },
        {
            "when": {"window": [0, 800], "timezone": "UTC"},
            "rates": {"input": 2.0, "output": 4.0},
        },
    ]


def test_build_row_drops_zero_window_rate_keys():
    model = OpenrouterModel(
        "a/b",
        "A",
        None,
        None,
        None,
        pricing={
            "prompt": "0.000001",
            "overrides": [
                {"utc_start": 100, "utc_end": 400, "prompt": "0", "completion": "0.000002"}
            ],
        },
    )
    row = build_row(model, "2026-08-26", VERSION)
    assert row is not None
    # a zero (free) key inherits the base price: it drops from the entry
    assert row["overrides"] == [
        {"when": {"window": [100, 400], "timezone": "UTC"}, "rates": {"output": 2.0}}
    ]


def test_build_row_drops_negative_window_rate_keys():
    model = OpenrouterModel(
        "a/b",
        "A",
        None,
        None,
        None,
        pricing={
            "prompt": "0.000001",
            "overrides": [
                {"utc_start": 100, "utc_end": 400, "prompt": "-1", "completion": "0.000002"}
            ],
        },
    )
    row = build_row(model, "2026-08-26", VERSION)
    assert row is not None
    # a negative ("no fixed price") key inherits the base price, like _price
    assert row["overrides"] == [
        {"when": {"window": [100, 400], "timezone": "UTC"}, "rates": {"output": 2.0}}
    ]


def test_build_row_dedupes_window_days():
    model = OpenrouterModel(
        "a/b",
        "A",
        None,
        None,
        None,
        pricing={
            "prompt": "0.000001",
            "overrides": [
                {"utc_days": ["monday", "monday", "sunday"], "prompt": "0.000002"},
            ],
        },
    )
    row = build_row(model, "2026-08-26", VERSION)
    assert row is not None
    assert row["overrides"][0]["when"]["days"] == ["monday", "sunday"]


@pytest.mark.parametrize("bad", [100.5, 2401, "100", True, 199])
def test_build_row_rejects_bad_clock_values(bad):
    model = OpenrouterModel(
        "a/b",
        "A",
        None,
        None,
        None,
        pricing={
            "prompt": "0.000001",
            "overrides": [{"utc_start": bad, "utc_end": 400, "prompt": "0.000002"}],
        },
    )
    with pytest.raises(ValueError, match="HHMM"):
        build_row(model, "2026-08-26", VERSION)


def test_build_row_rejects_utc_start_2400():
    model = OpenrouterModel(
        "a/b",
        "A",
        None,
        None,
        None,
        pricing={
            "prompt": "0.000001",
            "overrides": [{"utc_start": 2400, "utc_end": 100, "prompt": "0.000002"}],
        },
    )
    with pytest.raises(ValueError, match="2400"):
        build_row(model, "2026-08-26", VERSION)


def test_build_row_rejects_bool_window_rate_value():
    model = OpenrouterModel(
        "a/b",
        "A",
        None,
        None,
        None,
        pricing={
            "prompt": "0.000001",
            "overrides": [{"utc_start": 0, "utc_end": 100, "prompt": True}],
        },
    )
    with pytest.raises(ValueError, match="per-token string"):
        build_row(model, "2026-08-26", VERSION)


def test_build_row_maps_flash_vision_exp_schedule_exactly(fake_fetch: list[str]) -> None:
    by_id = {m.id: m for m in fetch_models()}
    row = build_row(by_id["deepseek/deepseek-v4-flash-vision-exp"], "2026-08-28", VERSION)
    assert row is not None
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    assert row["overrides"] == [
        {
            "when": {"days": ["saturday", "sunday"], "timezone": "UTC"},
            "rates": {"input": 0.22, "output": 0.66, "cache_read": 0.007},
        },
        {
            "when": {"days": weekdays, "window": [0, 100], "timezone": "UTC"},
            "rates": {"input": 0.22, "output": 0.66, "cache_read": 0.007},
        },
        {
            "when": {"days": weekdays, "window": [100, 400], "timezone": "UTC"},
            "rates": {"input": 0.44, "output": 1.32, "cache_read": 0.014},
        },
        {
            "when": {"days": weekdays, "window": [400, 600], "timezone": "UTC"},
            "rates": {"input": 0.22, "output": 0.66, "cache_read": 0.007},
        },
        {
            "when": {"days": weekdays, "window": [600, 1000], "timezone": "UTC"},
            "rates": {"input": 0.44, "output": 1.32, "cache_read": 0.014},
        },
        {
            "when": {"days": weekdays, "window": [1000, 2400], "timezone": "UTC"},
            "rates": {"input": 0.22, "output": 0.66, "cache_read": 0.007},
        },
    ]


def test_build_row_rejects_unknown_weekday_name():
    model = OpenrouterModel(
        "a/b",
        "A",
        None,
        None,
        None,
        pricing={
            "prompt": "0.000001",
            "overrides": [{"utc_days": ["monday", "funday"], "prompt": "0.000002"}],
        },
    )
    with pytest.raises(ValueError, match="funday"):
        build_row(model, "2026-08-26", VERSION)


def test_build_row_rejects_unknown_key_in_scheduled_override():
    model = OpenrouterModel(
        "a/b",
        "A",
        None,
        None,
        None,
        pricing={
            "prompt": "0.000001",
            "overrides": [{"utc_days": ["monday"], "audio": "0.5"}],
        },
    )
    with pytest.raises(ValueError, match="audio"):
        build_row(model, "2026-08-26", VERSION)


def test_build_row_rejects_unpaired_window_bounds():
    model = OpenrouterModel(
        "a/b",
        "A",
        None,
        None,
        None,
        pricing={
            "prompt": "0.000001",
            "overrides": [{"utc_start": 100, "prompt": "0.000002"}],
        },
    )
    with pytest.raises(ValueError, match="utc_end"):
        build_row(model, "2026-08-26", VERSION)


def test_build_row_names_non_string_override_pricing_values():
    model = OpenrouterModel(
        "a/b",
        "A",
        None,
        None,
        None,
        pricing={
            "prompt": "0.000001",
            "overrides": [{"utc_start": 0, "utc_end": 100, "prompt": {"x": 1}}],
        },
    )
    with pytest.raises(ValueError, match="per-token string"):
        build_row(model, "2026-08-26", VERSION)

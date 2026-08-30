from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_pricelog.validate import ROW_KEYS, SCHEMA_VERSION, ValidationError, validate_row

DATA = Path(__file__).resolve().parents[1] / "data"

# keys that exist only in rows already in the store (the pre-split max_tokens)
# or only in index entries (first_seen, removed_at); not producible today
_LEGACY_ROW_KEYS = frozenset({"max_tokens"})
_INDEX_ENTRY_KEYS = frozenset({"first_seen", "removed_at"})


def row(**overrides) -> dict:
    values = {
        "source": "deepseek",
        "model_id": "deepseek-chat",
        "observed_at": "2026-08-26",
        "input_mtok": 0.27,
        "output_mtok": 1.1,
    }
    values.update(overrides)
    return values


def test_valid_row_passes():
    validate_row(row())


def test_removal_row_with_a_price_snapshot_passes():
    validate_row(row(removed=True, input_mtok=0.0, max_tokens_in=4096))


def test_removal_row_with_a_non_usd_snapshot_validates():
    validate_row(
        row(
            removed=True,
            currency="EUR",
            currency_rate=1.1643,
            currency_rate_date="2026-08-28",
        )
    )


def test_removal_row_with_a_bad_snapshot_price_fails():
    with pytest.raises(ValidationError, match="input_mtok"):
        validate_row(row(removed=True, input_mtok=-1.0))


def test_bad_effective_at_rejected():
    with pytest.raises(ValidationError, match="effective_at"):
        validate_row(row(effective_at="08-23"))


def test_valid_effective_at_passes():
    validate_row(row(effective_at="2026-08-23"))


def test_future_effective_at_is_valid():
    # a rate announced ahead of time carries an effective date after its
    # observation; consumers clamp rows to effective <= the query date
    validate_row(row(observed_at="2026-08-28", effective_at="2026-08-30"))


def test_zero_prices_are_valid():
    # openrouter free rows keep zero pricing strings as 0.0 by design
    validate_row(row(input_mtok=0.0, output_mtok=0.0))


def test_missing_input_and_output_are_valid():
    # openrouter free rows carry no input/output prices at all
    validate_row({"source": "openrouter", "model_id": "x/y:free", "observed_at": "2026-08-26"})


def test_valid_peak_row_passes():
    validate_row(
        row(
            input_mtok=0.22,
            output_mtok=0.66,
            peak_input_mtok=0.44,
            peak_output_mtok=1.32,
            peak_cache_read_mtok=0.014,
            peak_windows=[["01:00:00Z", "04:00:00Z"], ["06:00:00Z", "10:00:00Z"]],
        )
    )


def test_peak_windows_without_peak_price_is_valid():
    # build_row cannot produce it, but windows alone break nothing
    validate_row(row(peak_windows=[["01:00:00Z", "04:00:00Z"]]))


def test_window_entry_with_quota_multiplier_only_passes():
    # zai plan-quota entries carry a multiplier and no rate keys
    validate_row(
        row(
            window_rates=[
                {"quota_multiplier": 0.4},
                {"days": ["monday", "tuesday"], "window": [600, 1000], "quota_multiplier": 1.2},
            ]
        )
    )


@pytest.mark.parametrize("bad", [0, -1, 0.0, True, "1.2", float("inf"), float("nan")])
def test_window_entry_with_bad_quota_multiplier_rejected(bad):
    with pytest.raises(ValidationError, match="quota_multiplier"):
        validate_row(row(window_rates=[{"quota_multiplier": bad}]))


def test_window_entry_with_neither_rates_nor_multiplier_rejected():
    with pytest.raises(ValidationError, match="quota_multiplier"):
        validate_row(row(window_rates=[{"window": [600, 1000]}]))


def test_volume_rates_entry_passes():
    validate_row(
        row(
            volume_rates=[
                {"min_tokens": 32000, "input_mtok": 0.1, "output_mtok": 0.4},
                {"min_tokens": 256000, "input_mtok": 0.2, "image_mtok": 3.0},
            ]
        )
    )


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "32000", None])
def test_volume_rates_bad_min_tokens_rejected(bad):
    with pytest.raises(ValidationError, match="min_tokens"):
        validate_row(row(volume_rates=[{"min_tokens": bad, "input_mtok": 0.1}]))


def test_volume_rates_unknown_key_rejected():
    with pytest.raises(ValidationError, match="volume_rates"):
        validate_row(row(volume_rates=[{"min_tokens": 100, "bogus": 1.0}]))


def test_volume_rates_empty_list_rejected():
    with pytest.raises(ValidationError, match="volume_rates"):
        validate_row(row(volume_rates=[]))


def test_volume_rates_entry_without_rates_rejected():
    with pytest.raises(ValidationError, match="volume_rates"):
        validate_row(row(volume_rates=[{"min_tokens": 100}]))


def test_row_timezone_passes_beside_window_rates():
    validate_row(
        row(window_rates=[{"window": [600, 1000], "input_mtok": 1.0}], timezone="Asia/Shanghai")
    )


def test_row_timezone_without_window_rates_rejected():
    with pytest.raises(ValidationError, match="timezone"):
        validate_row(row(timezone="UTC"))


@pytest.mark.parametrize("bad", ["Mars/Olympus", "", "utc", 5])
def test_row_bad_timezone_rejected(bad):
    with pytest.raises(ValidationError, match="timezone"):
        validate_row(
            row(
                window_rates=[{"window": [600, 1000], "input_mtok": 1.0}],
                timezone=bad,
            )
        )


@pytest.mark.parametrize("model_id", [None, "", 5, ["deepseek-chat"]])
def test_bad_model_id_rejected(model_id):
    with pytest.raises(ValidationError, match="model_id"):
        validate_row(row(model_id=model_id))


@pytest.mark.parametrize(
    "field",
    [
        "input_mtok",
        "output_mtok",
        "cache_read_mtok",
        "cache_write_mtok",
        "cache_write_1h_mtok",
    ],
)
@pytest.mark.parametrize("bad", [-1.0, float("inf"), float("nan"), True, 5, "0.1"])
def test_bad_price_rejected(field, bad):
    with pytest.raises(ValidationError, match=field):
        validate_row(row(**{field: bad}))


@pytest.mark.parametrize("field", ["peak_input_mtok", "peak_output_mtok", "peak_cache_read_mtok"])
@pytest.mark.parametrize("bad", [-1.0, float("inf"), float("nan"), True, 5])
def test_bad_peak_price_rejected(field, bad):
    with pytest.raises(ValidationError, match=field):
        validate_row(row(**{field: bad}, peak_windows=[["01:00:00Z", "04:00:00Z"]]))


def test_peak_price_without_windows_rejected():
    with pytest.raises(ValidationError, match="peak_windows"):
        validate_row(row(peak_input_mtok=0.44))


def test_peak_cache_read_without_windows_rejected():
    with pytest.raises(ValidationError, match="peak_windows"):
        validate_row(row(peak_cache_read_mtok=0.014))


def test_empty_peak_windows_rejected():
    with pytest.raises(ValidationError, match="peak_windows"):
        validate_row(row(peak_input_mtok=0.44, peak_output_mtok=1.32, peak_windows=[]))


@pytest.mark.parametrize("bad_window", [[], ["01:00:00Z"], [1, 2], [["", "04:00:00Z"]]])
def test_bad_peak_window_shape_rejected(bad_window):
    with pytest.raises(ValidationError, match="peak_windows"):
        validate_row(row(peak_input_mtok=0.44, peak_windows=[bad_window]))


_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]


def window_row(**overrides) -> dict:
    values = {
        "source": "openrouter",
        "model_id": "deepseek/deepseek-v4-pro-0813",
        "observed_at": "2026-08-28",
        "input_mtok": 0.66,
        "output_mtok": 1.98,
        "window_rates": [
            {
                "days": ["saturday", "sunday"],
                "input_mtok": 0.66,
                "output_mtok": 1.98,
                "cache_read_mtok": 0.022,
            },
            {
                "days": _WEEKDAYS,
                "window": [100, 400],
                "input_mtok": 1.32,
                "output_mtok": 3.96,
                "cache_read_mtok": 0.044,
                "cache_write_mtok": 12.5,
                "cache_write_1h_mtok": 20.0,
            },
        ],
    }
    values.update(overrides)
    return values


def test_valid_window_rates_row_passes():
    validate_row(window_row())


def test_window_only_entry_without_days_passes():
    validate_row(window_row(window_rates=[{"window": [1600, 2400], "input_mtok": 0.0825}]))


def test_days_only_entry_without_window_passes():
    validate_row(window_row(window_rates=[{"days": ["saturday"], "input_mtok": 0.66}]))


@pytest.mark.parametrize(
    "bad_days", [[], "monday", ["monday", "funday"], ["MONDAY"], [1, 2], 5, True]
)
def test_bad_window_days_rejected(bad_days):
    with pytest.raises(ValidationError, match="window_rates"):
        validate_row(window_row(window_rates=[{"days": bad_days, "input_mtok": 0.66}]))


@pytest.mark.parametrize(
    "bad_window",
    [
        [100],
        [100, 400, 600],
        [400, 100],
        [100, 2401],
        [-1, 100],
        [100, "400"],
        [100.5, 400],
        [True, 100],
        [100, True],
        "100-400",
        [100, 100],
        [199, 400],
        [100, 199],
    ],
)
def test_bad_window_rejected(bad_window):
    with pytest.raises(ValidationError, match="window_rates"):
        validate_row(window_row(window_rates=[{"window": bad_window, "input_mtok": 0.66}]))


@pytest.mark.parametrize(
    "field",
    ["input_mtok", "output_mtok", "cache_read_mtok", "cache_write_mtok", "cache_write_1h_mtok"],
)
@pytest.mark.parametrize("bad", [0.0, -1.0, float("inf"), float("nan"), True, 5, "0.66"])
def test_bad_window_rate_rejected(field, bad):
    entry = {"window": [100, 400], field: bad}
    with pytest.raises(ValidationError, match=field):
        validate_row(window_row(window_rates=[entry]))


def test_window_entry_without_rates_rejected():
    with pytest.raises(ValidationError, match="window_rates"):
        validate_row(window_row(window_rates=[{"days": ["monday"], "window": [100, 400]}]))


def test_window_entry_without_days_or_window_rejected():
    with pytest.raises(ValidationError, match="window_rates"):
        validate_row(window_row(window_rates=[{"input_mtok": 0.66}]))


def test_window_entry_with_unknown_key_rejected():
    with pytest.raises(ValidationError, match="window_rates"):
        validate_row(
            window_row(window_rates=[{"days": ["monday"], "input_mtok": 0.66, "audio": 1.0}])
        )


@pytest.mark.parametrize("bad_field", [{}, "not-a-list", 5])
def test_window_rates_bad_field_shape_rejected(bad_field):
    with pytest.raises(ValidationError, match="window_rates"):
        validate_row(row(window_rates=bad_field))


def test_empty_window_rates_list_rejected():
    with pytest.raises(ValidationError, match="window_rates"):
        validate_row(row(window_rates=[]))


def test_removed_row_with_window_rates_passes():
    # the final snapshot can carry the last row's schedule container
    validate_row(
        {
            "source": "openrouter",
            "model_id": "deepseek/deepseek-v4-pro-0813",
            "observed_at": "2026-08-28",
            "removed": True,
            "window_rates": [{"days": ["monday"], "input_mtok": 0.66}],
        }
    )


def test_removed_row_passes():
    validate_row(
        {
            "source": "deepseek",
            "model_id": "deepseek-chat",
            "observed_at": "2026-08-26",
            "removed": True,
        }
    )


@pytest.mark.parametrize("bad", [False, 0, 1, "true", None, []])
def test_removed_flag_must_be_true(bad):
    with pytest.raises(ValidationError, match="removed"):
        validate_row(
            {
                "source": "deepseek",
                "model_id": "deepseek-chat",
                "observed_at": "2026-08-26",
                "removed": bad,
            }
        )


def test_removed_row_with_price_fields_passes():
    # the removal row carries the final price snapshot; its price fields
    # validate like any row's
    validate_row(
        {
            "source": "deepseek",
            "model_id": "deepseek-chat",
            "observed_at": "2026-08-26",
            "removed": True,
            "input_mtok": 1.0,
            "output_mtok": 2.0,
            "cache_read_mtok": 0.1,
            "cache_write_mtok": 0.125,
            "cache_write_1h_mtok": 0.2,
            "peak_input_mtok": 2.0,
            "peak_output_mtok": 4.0,
            "peak_cache_read_mtok": 0.2,
            "peak_windows": [["01:00:00Z", "04:00:00Z"]],
            "window_rates": [{"window": [600, 1000], "input_mtok": 3.0}],
        }
    )


def eur_row(**overrides) -> dict:
    values = {
        "source": "scaleway",
        "model_id": "m",
        "observed_at": "2026-08-28",
        "input_mtok": 1.1643,
        "output_mtok": 2.3286,
        "currency": "EUR",
        "currency_rate": 1.1643,
        "currency_rate_date": "2026-08-28",
    }
    values.update(overrides)
    return values


def test_valid_eur_row_passes():
    validate_row(eur_row())


def test_valid_dbu_row_passes():
    validate_row(eur_row(currency="DBU", currency_rate=0.55))


@pytest.mark.parametrize("bad", ["eur", "EURO", "EU R", "EU1", "E", "", 5, True])
def test_bad_currency_rejected(bad):
    with pytest.raises(ValidationError, match="currency"):
        validate_row(eur_row(currency=bad))


@pytest.mark.parametrize("good", ["EUR", "DBU"])
def test_valid_non_usd_currency_passes(good):
    validate_row(eur_row(currency=good, currency_rate=0.55))


def test_explicit_usd_currency_without_rate_passes():
    validate_row(row(currency="USD"))


def test_non_usd_currency_requires_rate():
    with pytest.raises(ValidationError, match="currency_rate"):
        validate_row(eur_row(currency_rate=None))


@pytest.mark.parametrize("bad", [0.0, -1.0, float("inf"), float("nan"), True, "1.1643"])
def test_non_usd_currency_rejects_bad_rate(bad):
    with pytest.raises(ValidationError, match="currency_rate"):
        validate_row(eur_row(currency_rate=bad))


def test_rate_without_non_usd_currency_rejected():
    with pytest.raises(ValidationError, match="currency_rate"):
        validate_row(row(currency_rate=1.1643))


def test_rate_with_usd_currency_rejected():
    with pytest.raises(ValidationError, match="currency_rate"):
        validate_row(row(currency="USD", currency_rate=1.1643))


def test_rate_date_without_non_usd_currency_rejected():
    with pytest.raises(ValidationError, match="currency_rate"):
        validate_row(row(currency_rate_date="2026-08-28"))


@pytest.mark.parametrize("bad", ["28-08-2026", "2026/08/28", "2026-8-28", "", 20260828, True])
def test_bad_rate_date_rejected(bad):
    with pytest.raises(ValidationError, match="currency_rate_date"):
        validate_row(eur_row(currency_rate_date=bad))


@pytest.mark.parametrize("bad", ["Tokens", "TOKENS", "tokens!", " tokens", "", 5, True])
def test_bad_unit_rejected(bad):
    with pytest.raises(ValidationError, match="unit"):
        validate_row(eur_row(unit=bad))


@pytest.mark.parametrize("good", ["tokens", "dbu", "dbu-hours"])
def test_valid_unit_passes(good):
    validate_row(eur_row(unit=good))


def test_unknown_top_level_key_rejected():
    with pytest.raises(ValidationError, match="schema"):
        validate_row(row(junk=1.0))


def test_unknown_key_on_removed_row_rejected():
    with pytest.raises(ValidationError, match="schema"):
        validate_row(
            {
                "source": "deepseek",
                "model_id": "deepseek-chat",
                "observed_at": "2026-08-26",
                "removed": True,
                "junk": 1,
            }
        )


def test_schema_file_version_matches_code():
    schema = json.loads((DATA / "schema.json").read_text(encoding="utf-8"))
    assert schema["version"] == SCHEMA_VERSION


def test_store_rows_carry_only_schema_keys():
    for line in (DATA / "history.ndjson").read_text(encoding="utf-8").splitlines():
        unknown = set(json.loads(line)) - (ROW_KEYS | _LEGACY_ROW_KEYS)
        assert not unknown, f"store row carries keys outside the schema: {sorted(unknown)}"


def test_index_entries_carry_only_schema_keys():
    index = json.loads((DATA / "index.json").read_text(encoding="utf-8"))
    for models in index["sources"].values():
        for entry in models.values():
            unknown = set(entry) - (ROW_KEYS | _LEGACY_ROW_KEYS | _INDEX_ENTRY_KEYS)
            assert not unknown, f"index entry carries keys outside the schema: {sorted(unknown)}"

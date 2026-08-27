from __future__ import annotations

import pytest

from ai_pricelog.validate import ValidationError, validate_row


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


@pytest.mark.parametrize("model_id", [None, "", 5, ["deepseek-chat"]])
def test_bad_model_id_rejected(model_id):
    with pytest.raises(ValidationError, match="model_id"):
        validate_row(row(model_id=model_id))


@pytest.mark.parametrize("field", ["input_mtok", "output_mtok"])
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


@pytest.mark.parametrize(
    "field",
    [
        "input_mtok",
        "output_mtok",
        "cache_read_mtok",
        "peak_input_mtok",
        "peak_output_mtok",
        "peak_cache_read_mtok",
    ],
)
def test_removed_row_with_price_field_rejected(field):
    with pytest.raises(ValidationError, match=field):
        validate_row(
            {
                "source": "deepseek",
                "model_id": "deepseek-chat",
                "observed_at": "2026-08-26",
                "removed": True,
                field: 1.0,
            }
        )


def test_removed_row_with_peak_windows_rejected():
    with pytest.raises(ValidationError, match="peak_windows"):
        validate_row(
            {
                "source": "deepseek",
                "model_id": "deepseek-chat",
                "observed_at": "2026-08-26",
                "removed": True,
                "peak_windows": [["01:00:00Z", "04:00:00Z"]],
            }
        )

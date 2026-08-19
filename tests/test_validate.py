import pytest

from autopr_genai_prices.pricing import Pricing
from autopr_genai_prices.validate import ValidationError, validate_entry


def pricing(**overrides) -> Pricing:
    values = dict(
        input_cost_per_token=2.7e-07,
        output_cost_per_token=1.1e-06,
        mode="chat",
        max_tokens=65536,
    )
    values.update(overrides)
    return Pricing(**values)


def test_valid_entry_passes():
    validate_entry("deepseek-chat", pricing())


def test_valid_peak_entry_passes():
    validate_entry(
        "deepseek-v4-flash",
        pricing(
            input_cost_per_token=0.22 / 1e6,
            output_cost_per_token=0.66 / 1e6,
            peak_input_cost_per_token=0.44 / 1e6,
            peak_output_cost_per_token=1.32 / 1e6,
            peak_windows=(("01:00:00Z", "04:00:00Z"), ("06:00:00Z", "10:00:00Z")),
        ),
    )


def test_max_tokens_zero_is_unset_and_valid():
    validate_entry("deepseek-chat", pricing(max_tokens=0))


@pytest.mark.parametrize(
    "model_id",
    [
        "deepseek-chat",
        "deepseek-v4-pro",
        "MiniMax-M1",
        "grok-4.20",
        "x-ai/grok-4.5",
        "devstral-small:free",
    ],
)
def test_id_charset_accepted(model_id):
    validate_entry(model_id, pricing())


@pytest.mark.parametrize(
    "model_id",
    [
        "",
        "bad id",
        "bad\nid",
        "-lead",
        "a(b)",
        "a[b]",
        "a{b}",
        "a*b",
        "a?b",
        "a|b",
        "a" * 101,
    ],
)
def test_id_charset_rejected(model_id):
    with pytest.raises(ValidationError, match="model id"):
        validate_entry(model_id, pricing())


@pytest.mark.parametrize("field", ["input_cost_per_token", "output_cost_per_token"])
@pytest.mark.parametrize("bad", [0, 0.0, -1.0, float("inf"), float("nan"), True, 5, None, "0.1"])
def test_bad_cost_rejected(field, bad):
    with pytest.raises(ValidationError, match=field):
        validate_entry("deepseek-chat", pricing(**{field: bad}))


@pytest.mark.parametrize("field", ["peak_input_cost_per_token", "peak_output_cost_per_token"])
@pytest.mark.parametrize("bad", [0, 0.0, -1.0, float("inf"), float("nan"), True, 5])
def test_bad_peak_cost_rejected(field, bad):
    with pytest.raises(ValidationError, match=field):
        validate_entry("deepseek-chat", pricing(**{field: bad}))


def test_peak_cost_none_is_valid():
    validate_entry(
        "deepseek-chat", pricing(peak_input_cost_per_token=None, peak_output_cost_per_token=None)
    )


@pytest.mark.parametrize("bad", [True, 1.5, 0.5, -1])
def test_bad_max_tokens_rejected(bad):
    with pytest.raises(ValidationError, match="max_tokens"):
        validate_entry("deepseek-chat", pricing(max_tokens=bad))

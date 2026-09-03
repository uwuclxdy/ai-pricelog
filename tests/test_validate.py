from __future__ import annotations

from pathlib import Path

import pytest

from ai_pricelog.validate import ValidationError, load_schema_keys, validate_row

ROOT = Path(__file__).resolve().parents[1]
KEYS = load_schema_keys(ROOT)


def row(**overrides) -> dict:
    values = {
        "schema": KEYS.version,
        "source": "deepseek",
        "model_id": "deepseek-chat",
        "observed_at": "2026-08-26",
    }
    values.update(overrides)
    return values


def check(r: dict) -> None:
    validate_row(r, KEYS)


def test_minimal_row_passes():
    check(row())


def test_full_row_with_every_container_passes():
    check(
        row(
            effective_at="2026-09-01",
            currency="EUR",
            rates={"input": 0.27, "output": 1.1, "cache_read": 0.05},
            fees={"web_search": 0.001},
            limits={"context": 131072, "output": 16384},
            unmapped={"some_key": "x"},
            provenance={
                "url": "https://example.com",
                "name": "pricing page",
                "fx_rate": 1.1643,
                "fx_rate_date": "2026-08-28",
            },
            overrides=[
                {
                    "when": {"days": ["monday"], "window": [600, 1000]},
                    "rates": {"input": 0.2},
                },
                {"quota_multiplier": 0.4},
            ],
        )
    )


def test_unknown_top_level_key_rejected():
    with pytest.raises(ValidationError, match="not part of the row schema"):
        check(row(junk=1.0))


def test_missing_required_key_rejected():
    r = row()
    del r["source"]
    with pytest.raises(ValidationError, match="missing required field"):
        check(r)


def test_wrong_schema_value_rejected():
    with pytest.raises(ValidationError, match="schema"):
        check(row(schema=3))


def test_rates_accept_zero():
    check(row(rates={"input": 0.0}))


@pytest.mark.parametrize("bad", [-1.0, True, "0.1", float("inf"), float("nan")])
def test_rates_reject_bad_value(bad):
    with pytest.raises(ValidationError, match="rates"):
        check(row(rates={"input": bad}))


def test_rates_reject_unknown_axis():
    with pytest.raises(ValidationError, match="rates"):
        check(row(rates={"bogus": 1.0}))


def test_rates_must_be_a_non_empty_dict():
    with pytest.raises(ValidationError, match="rates"):
        check(row(rates=[1.0]))


def test_override_rates_reject_zero():
    with pytest.raises(ValidationError, match="overrides"):
        check(row(overrides=[{"when": {"days": ["monday"]}, "rates": {"input": 0.0}}]))


@pytest.mark.parametrize("bad", [0, -1, True, 1.5])
def test_limits_reject_bad_value(bad):
    with pytest.raises(ValidationError, match="limits"):
        check(row(limits={"context": bad}))


def test_limits_reject_unknown_limit():
    with pytest.raises(ValidationError, match="limits"):
        check(row(limits={"bogus": 1}))


def test_when_with_only_timezone_rejected():
    with pytest.raises(ValidationError, match="timezone"):
        check(row(overrides=[{"when": {"timezone": "UTC"}, "rates": {"input": 1.0}}]))


def test_unknown_timezone_rejected():
    with pytest.raises(ValidationError, match="unknown zone"):
        check(
            row(
                overrides=[
                    {
                        "when": {"days": ["monday"], "timezone": "Mars/Olympus"},
                        "rates": {"input": 1.0},
                    }
                ]
            )
        )


def test_valid_timezone_beside_days_accepted():
    check(
        row(
            overrides=[
                {
                    "when": {"days": ["monday"], "timezone": "Asia/Shanghai"},
                    "rates": {"input": 1.0},
                }
            ]
        )
    )


@pytest.mark.parametrize(
    "bad_window",
    [
        [100, 100],
        [400, 100],
        [100, 2401],
        [100, 160],
        [199, 300],
        [True, 100],
        [100, True],
    ],
)
def test_bad_window_rejected(bad_window):
    with pytest.raises(ValidationError, match="window"):
        check(row(overrides=[{"when": {"window": bad_window}, "rates": {"input": 1.0}}]))


def test_override_rates_without_when_rejected():
    with pytest.raises(ValidationError, match="when"):
        check(row(overrides=[{"rates": {"input": 1.0}}]))


def test_override_rates_with_timezone_only_rejected():
    with pytest.raises(ValidationError, match="timezone"):
        check(row(overrides=[{"when": {"timezone": "UTC"}, "rates": {"input": 1.0}}]))


def test_quota_multiplier_only_without_when_accepted():
    check(row(overrides=[{"quota_multiplier": 0.4}]))


def test_override_with_neither_rates_nor_multiplier_rejected():
    with pytest.raises(ValidationError, match="quota_multiplier"):
        check(row(overrides=[{"when": {"days": ["monday"]}}]))


def test_fx_rate_beside_usd_rejected():
    with pytest.raises(ValidationError, match="fx_rate"):
        check(row(provenance={"url": "https://example.com", "fx_rate": 1.1}))


def test_non_usd_missing_fx_rate_rejected():
    with pytest.raises(ValidationError, match="fx_rate"):
        check(row(currency="EUR", provenance={"url": "https://example.com"}))


def test_non_usd_with_fx_rate_and_date_accepted():
    check(
        row(
            currency="EUR",
            provenance={
                "url": "https://example.com",
                "fx_rate": 1.1643,
                "fx_rate_date": "2026-08-28",
            },
        )
    )


def test_bare_removal_row_accepted():
    check(row(removed=True))


def test_removal_row_with_price_snapshot_accepted():
    check(row(removed=True, rates={"input": 0.0, "output": 1.1}))


@pytest.mark.parametrize("bad", [False, 0, 1, "true", None, []])
def test_removed_flag_must_be_true(bad):
    with pytest.raises(ValidationError, match="removed"):
        check(row(removed=bad))


@pytest.mark.parametrize("bad", ["eur", "EURO", "EU1", "E", "", 5, True])
def test_bad_currency_rejected(bad):
    with pytest.raises(ValidationError, match="currency"):
        check(row(currency=bad))


@pytest.mark.parametrize("model_id", [None, "", 5, ["deepseek-chat"]])
def test_bad_model_id_rejected(model_id):
    with pytest.raises(ValidationError, match="model_id"):
        check(row(model_id=model_id))


@pytest.mark.parametrize("source", [None, "", 5])
def test_bad_source_rejected(source):
    with pytest.raises(ValidationError, match="source"):
        check(row(source=source))


def test_bad_observed_at_rejected():
    with pytest.raises(ValidationError, match="observed_at"):
        check(row(observed_at="08-23"))


def test_bad_effective_at_rejected():
    with pytest.raises(ValidationError, match="effective_at"):
        check(row(effective_at="08-23"))


@pytest.mark.parametrize("bad", [-1.0, True, "0.1", float("inf"), float("nan")])
def test_fees_reject_bad_value(bad):
    with pytest.raises(ValidationError, match="fees"):
        check(row(fees={"web_search": bad}))


def test_fees_reject_unknown_fee():
    with pytest.raises(ValidationError, match="fees"):
        check(row(fees={"bogus": 0.1}))


@pytest.mark.parametrize("bad", [[], {}])
def test_unmapped_must_be_a_non_empty_dict(bad):
    with pytest.raises(ValidationError, match="unmapped"):
        check(row(unmapped=bad))


def test_provenance_reject_unknown_key():
    with pytest.raises(ValidationError, match="provenance"):
        check(row(provenance={"bogus": 1}))


def test_provenance_url_must_be_non_empty_string():
    with pytest.raises(ValidationError, match="provenance.url"):
        check(row(provenance={"url": ""}))


def test_provenance_bad_fx_rate_date_rejected():
    with pytest.raises(ValidationError, match="fx_rate_date"):
        check(
            row(
                currency="EUR",
                provenance={"url": "https://example.com", "fx_rate": 1.1, "fx_rate_date": "28-08"},
            )
        )


def test_override_empty_entry_rejected():
    with pytest.raises(ValidationError, match="overrides"):
        check(row(overrides=[{}]))


def test_override_bad_entry_shape_rejected():
    with pytest.raises(ValidationError, match="overrides"):
        check(row(overrides=["x"]))


def test_override_unknown_key_rejected():
    with pytest.raises(ValidationError, match="overrides"):
        check(row(overrides=[{"rates": {"input": 1.0}, "when": {"days": ["monday"]}, "junk": 1}]))


@pytest.mark.parametrize(
    "bad_days", [[], "monday", ["monday", "funday"], ["MONDAY"], [1, 2], ["monday", "monday"]]
)
def test_bad_override_days_rejected(bad_days):
    with pytest.raises(ValidationError, match="day-set"):
        check(row(overrides=[{"when": {"days": bad_days}, "rates": {"input": 1.0}}]))


@pytest.mark.parametrize("bad", [0, -1, True, 1.5])
def test_bad_min_tokens_rejected(bad):
    with pytest.raises(ValidationError, match="min_tokens"):
        check(row(overrides=[{"when": {"min_tokens": bad}, "rates": {"input": 1.0}}]))


@pytest.mark.parametrize("bad", [0, -1, 0.0, True, "1.2", float("inf"), float("nan")])
def test_bad_quota_multiplier_rejected(bad):
    with pytest.raises(ValidationError, match="quota_multiplier"):
        check(row(overrides=[{"quota_multiplier": bad}]))


def test_override_rates_reject_negative():
    with pytest.raises(ValidationError, match="input"):
        check(row(overrides=[{"when": {"days": ["monday"]}, "rates": {"input": -1.0}}]))


def test_override_rates_reject_unknown_axis():
    with pytest.raises(ValidationError, match="overrides"):
        check(row(overrides=[{"when": {"days": ["monday"]}, "rates": {"bogus": 1.0}}]))


def test_non_usd_row_without_provenance_is_refused():
    # the store is append-only: a quote with no rate is unpriceable forever,
    # and nesting the fx pair inside an optional container is what lets the
    # row reach the store carrying a currency it cannot convert
    with pytest.raises(ValidationError, match="carries no 'provenance.fx_rate'"):
        check(row(currency="EUR", rates={"input": 1.0}))
    check(
        row(
            currency="EUR",
            rates={"input": 1.0},
            provenance={"fx_rate": 1.1643, "fx_rate_date": "2026-08-28"},
        )
    )

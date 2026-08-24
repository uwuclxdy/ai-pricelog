"""Unit tests for the drift-refresh compare and spec assembly."""

import pytest
import yaml as pyyaml

from autopr_genai_prices.config import ProviderCfg
from autopr_genai_prices.matcher import ClauseEquals
from autopr_genai_prices.openrouter import OpenrouterModel
from autopr_genai_prices.pricing import Pricing
from autopr_genai_prices.refresh import build_update_spec, compare, old_values
from autopr_genai_prices.yml import ProviderYml, TrackedModel

PCFG = ProviderCfg(
    key="deepseek",
    yml="deepseek.yml",
    or_prefix="deepseek",
    detector="deepseek_page",
    detector_url="https://example.com/models",
    scraper="deepseek_page",
    scraper_url="https://example.com/pricing",
)

FLAT = Pricing(0.435e-6, 0.87e-6, "chat")
SPLIT = Pricing(
    0.435e-6,
    0.87e-6,
    "chat",
    peak_input_cost_per_token=0.87e-6,
    peak_output_cost_per_token=1.74e-6,
    peak_windows=(("01:00:00Z", "04:00:00Z"), ("06:00:00Z", "10:00:00Z")),
)


def view(text: str) -> object:
    return pyyaml.safe_load(text)["prices"]


def test_flat_equal_is_none() -> None:
    assert (
        compare(view("prices:\n  input_mtok: 0.435\n  output_mtok: 0.87\n"), FLAT).action == "none"
    )


def test_flat_rate_change_is_dated_append() -> None:
    drift = compare(view("prices:\n  input_mtok: 0.2\n  output_mtok: 0.4\n"), FLAT)
    assert drift.action == "dated_append"


def test_flat_with_split_live_is_conversion() -> None:
    drift = compare(view("prices:\n  input_mtok: 0.435\n  output_mtok: 0.87\n"), SPLIT)
    assert drift.action == "conversion"


def test_free_entry_with_paid_live_is_dated_append() -> None:
    assert compare(view("prices: {}\n"), FLAT).action == "dated_append"


def test_split_equal_is_none() -> None:
    split_view = view(
        "prices:\n"
        "  - prices:\n"
        "      input_mtok: 0.435\n"
        "      output_mtok: 0.87\n"
        "  - constraint:\n"
        "      start_time: 01:00:00Z\n"
        "      end_time: 04:00:00Z\n"
        "    prices:\n"
        "      input_mtok: 0.87\n"
        "      output_mtok: 1.74\n"
        "  - constraint:\n"
        "      start_time: 06:00:00Z\n"
        "      end_time: 10:00:00Z\n"
        "    prices:\n"
        "      input_mtok: 0.87\n"
        "      output_mtok: 1.74\n"
    )
    assert compare(split_view, SPLIT).action == "none"


def test_split_value_drift_is_replace() -> None:
    split_view = view(
        "prices:\n"
        "  - prices:\n"
        "      input_mtok: 0.435\n"
        "      output_mtok: 0.87\n"
        "  - constraint:\n"
        "      start_time: 01:00:00Z\n"
        "      end_time: 04:00:00Z\n"
        "    prices:\n"
        "      input_mtok: 0.6\n"
        "      output_mtok: 1.2\n"
        "  - constraint:\n"
        "      start_time: 06:00:00Z\n"
        "      end_time: 10:00:00Z\n"
        "    prices:\n"
        "      input_mtok: 0.6\n"
        "      output_mtok: 1.2\n"
    )
    assert compare(split_view, SPLIT).action == "replace"


def test_split_window_shift_is_replace() -> None:
    # same values, different window: the yml constraint no longer matches the
    # page schedule, so a structural replace is the verdict
    split_view = view(
        "prices:\n"
        "  - prices:\n"
        "      input_mtok: 0.435\n"
        "      output_mtok: 0.87\n"
        "  - constraint:\n"
        "      start_time: 00:30:00Z\n"
        "      end_time: 16:30:00Z\n"
        "    prices:\n"
        "      input_mtok: 0.87\n"
        "      output_mtok: 1.74\n"
    )
    assert compare(split_view, SPLIT).action == "replace"


def test_split_entry_with_flat_live_is_replace() -> None:
    split_view = view(
        "prices:\n"
        "  - prices:\n"
        "      input_mtok: 0.435\n"
        "      output_mtok: 0.87\n"
        "  - constraint:\n"
        "      start_time: 01:00:00Z\n"
        "      end_time: 04:00:00Z\n"
        "    prices:\n"
        "      input_mtok: 0.87\n"
        "      output_mtok: 1.74\n"
    )
    assert compare(split_view, FLAT).action == "replace"


def test_dated_list_equal_is_none() -> None:
    dated_view = view(
        "prices:\n"
        "  - prices:\n"
        "      input_mtok: 0.2\n"
        "      output_mtok: 0.4\n"
        "  - constraint:\n"
        "      start_date: 2020-01-01\n"
        "    prices:\n"
        "      input_mtok: 0.435\n"
        "      output_mtok: 0.87\n"
    )
    assert compare(dated_view, FLAT).action == "none"


def test_dated_list_drift_is_dated_append() -> None:
    dated_view = view(
        "prices:\n"
        "  - prices:\n"
        "      input_mtok: 0.2\n"
        "      output_mtok: 0.4\n"
        "  - constraint:\n"
        "      start_date: 2020-01-01\n"
        "    prices:\n"
        "      input_mtok: 0.5\n"
        "      output_mtok: 1.0\n"
    )
    assert compare(dated_view, FLAT).action == "dated_append"


def test_future_dated_entries_fall_back_to_base() -> None:
    # a dated entry starting next year must not count as the current price;
    # the live rate matching the base is no drift
    dated_view = view(
        "prices:\n"
        "  - prices:\n"
        "      input_mtok: 0.435\n"
        "      output_mtok: 0.87\n"
        "  - constraint:\n"
        "      start_date: 2999-01-01\n"
        "    prices:\n"
        "      input_mtok: 0.5\n"
        "      output_mtok: 1.0\n"
    )
    assert compare(dated_view, FLAT).action == "none"


def test_tiered_base_equal_is_none() -> None:
    tiered = view(
        "prices:\n"
        "  input_mtok:\n"
        "    base: 0.435\n"
        "    tiers:\n"
        "      - start: 512000\n"
        "        price: 0.87\n"
        "  cache_read_mtok:\n"
        "    base: 0.06\n"
        "    tiers:\n"
        "      - start: 512000\n"
        "        price: 0.12\n"
        "  output_mtok:\n"
        "    base: 0.87\n"
        "    tiers:\n"
        "      - start: 512000\n"
        "        price: 1.74\n"
    )
    assert compare(tiered, FLAT).action == "none"


def test_tiered_base_drift_is_tiered_append() -> None:
    tiered = view(
        "prices:\n"
        "  input_mtok:\n"
        "    base: 3\n"
        "    tiers:\n"
        "      - start: 200000\n"
        "        price: 6\n"
        "  output_mtok: 15\n"
    )
    assert compare(tiered, FLAT).action == "tiered_append"


def test_tiered_with_split_live_skips() -> None:
    tiered = view(
        "prices:\n"
        "  input_mtok:\n"
        "    base: 0.435\n"
        "    tiers:\n"
        "      - start: 512000\n"
        "        price: 0.87\n"
        "  output_mtok:\n"
        "    base: 0.87\n"
        "    tiers:\n"
        "      - start: 512000\n"
        "        price: 1.74\n"
    )
    drift = compare(tiered, SPLIT)
    assert drift.action == "none"
    assert "uncomparable" in drift.note


def test_tiered_malformed_skips() -> None:
    tiered = view(
        "prices:\n"
        "  input_mtok:\n"
        "    tiers:\n"
        "      - start: 512000\n"
        "        price: 0.87\n"
        "  output_mtok:\n"
        "    base: 0.87\n"
        "    tiers:\n"
        "      - start: 512000\n"
        "        price: 1.74\n"
    )
    assert compare(tiered, FLAT).action == "none"


def test_old_values_tiered_returns_bases() -> None:
    tiered = view(
        "prices:\n"
        "  input_mtok:\n"
        "    base: 3\n"
        "    tiers:\n"
        "      - start: 200000\n"
        "        price: 6\n"
        "  output_mtok: 15\n"
    )
    assert old_values(tiered) == (3, 15)


TIERED_VENDOR_TEXT = (
    "id: minimax\n"
    "name: MiniMax\n"
    "models:\n"
    "  - id: minimax-m3\n"
    "    match:\n"
    "      equals: minimax-m3\n"
    '    prices_checked: "2026-07-01"\n'
    "    prices:\n"
    "      input_mtok:\n"
    "        base: 0.3\n"
    "        tiers:\n"
    "          - start: 512000\n"
    "            price: 0.6\n"
    "      cache_read_mtok:\n"
    "        base: 0.06\n"
    "        tiers:\n"
    "          - start: 512000\n"
    "            price: 0.12\n"
    "      output_mtok:\n"
    "        base: 1.2\n"
    "        tiers:\n"
    "          - start: 512000\n"
    "            price: 2.4\n"
)

TIERED_ENTRY = TrackedModel(
    "minimax-m3",
    ClauseEquals("minimax-m3"),
    prices=pyyaml.safe_load(TIERED_VENDOR_TEXT)["models"][0]["prices"],
)


def test_build_update_spec_tiered_append_carries_tiers() -> None:
    drift = compare(TIERED_ENTRY.prices, FLAT)
    assert drift.action == "tiered_append"
    spec = build_update_spec(
        PCFG, TIERED_VENDOR_TEXT, TIERED_ENTRY, FLAT, drift, "2026-08-24", OR_TEXT, OR_YML, []
    )
    assert spec.case == "rate_change"
    # the old mapping stays as the unconstrained first entry, byte-identical
    assert "      - prices:\n          input_mtok:\n            base: 0.3\n" in spec.prices_section
    # the new entry swaps the input/output bases and carries the tiers
    assert (
        "            base: 0.435\n            tiers:\n              - start: 512000\n"
        in spec.prices_section
    )
    assert "                price: 0.6" in spec.prices_section
    assert (
        "            base: 0.87\n            tiers:\n              - start: 512000\n"
        in spec.prices_section
    )
    assert "                price: 2.4" in spec.prices_section
    # the cache tiers carry over unchanged
    assert (
        "            base: 0.06\n            tiers:\n              - start: 512000\n"
        in spec.prices_section
    )
    assert "          start_date: 2026-08-24" in spec.prices_section
    assert "tiered rate change" in spec.deviation
    assert spec.old_input_mtok == 0.3
    assert spec.old_output_mtok == 1.2
    assert spec.input_mtok == 0.435
    assert spec.output_mtok == 0.87


def test_missing_prices_skips() -> None:
    assert compare(None, FLAT).action == "none"
    assert compare([], FLAT).action == "none"


def test_old_values_flat_and_list() -> None:
    assert old_values(view("prices:\n  input_mtok: 0.2\n  output_mtok: 0.4\n")) == (0.2, 0.4)
    split_view = view(
        "prices:\n"
        "  - prices:\n"
        "      input_mtok: 0.435\n"
        "  - constraint:\n"
        "      start_time: 01:00:00Z\n"
        "      end_time: 04:00:00Z\n"
        "    prices:\n"
        "      input_mtok: 0.87\n"
    )
    assert old_values(split_view) == (0.435, None)


VENDOR_TEXT = (
    "id: deepseek\n"
    "name: Deepseek\n"
    "models:\n"
    "  - id: deepseek-chat\n"
    "    match:\n"
    "      equals: deepseek-chat\n"
    '    prices_checked: "2026-08-19"\n'
    "    prices:\n"
    "      input_mtok: 0.2\n"
    "      output_mtok: 0.4\n"
)

OR_TEXT = (
    "id: openrouter\n"
    "name: OpenRouter\n"
    "models:\n"
    "  - id: deepseek/deepseek-chat\n"
    "    match:\n"
    "      equals: deepseek/deepseek-chat\n"
    "    prices:\n"
    "      input_mtok: 0.2\n"
    "      cache_read_mtok: 0.02\n"
    "      output_mtok: 0.4\n"
)

OR_YML = ProviderYml(
    "openrouter",
    "OpenRouter",
    (
        TrackedModel(
            "deepseek/deepseek-chat",
            ClauseEquals("deepseek/deepseek-chat"),
            prices={"input_mtok": 0.2, "cache_read_mtok": 0.02, "output_mtok": 0.4},
        ),
    ),
)

ENTRY = TrackedModel(
    "deepseek-chat",
    ClauseEquals("deepseek-chat"),
    prices={"input_mtok": 0.2, "output_mtok": 0.4},
)

OR_MODEL = OpenrouterModel(
    id="deepseek/deepseek-chat",
    name="DeepSeek Chat",
    input_mtok=0.435,
    output_mtok=0.87,
    cache_read_mtok=0.003625,
)


def test_build_update_spec_dated_append_mirrors_when_api_caught_up() -> None:
    drift = compare(ENTRY.prices, FLAT)
    spec = build_update_spec(
        PCFG, VENDOR_TEXT, ENTRY, FLAT, drift, "2026-08-24", OR_TEXT, OR_YML, [OR_MODEL]
    )
    assert spec.case == "rate_change"
    assert (
        "      - prices:\n          input_mtok: 0.2\n          output_mtok: 0.4\n"
        in spec.prices_section
    )
    assert "          start_date: 2026-08-24" in spec.prices_section
    assert "          input_mtok: 0.435" in spec.prices_section
    assert spec.or_prices_section is not None
    assert "          cache_read_mtok: 0.003625" in spec.or_prices_section
    assert "          start_date: 2026-08-24" in spec.or_prices_section
    assert "never-overwrite rule is followed" in spec.deviation


def test_build_update_spec_notes_when_api_matches() -> None:
    drift = compare(ENTRY.prices, FLAT)
    or_model = OpenrouterModel(
        id="deepseek/deepseek-chat",
        name="DeepSeek Chat",
        input_mtok=0.2,
        output_mtok=0.4,
        cache_read_mtok=0.02,
    )
    spec = build_update_spec(
        PCFG, VENDOR_TEXT, ENTRY, FLAT, drift, "2026-08-24", OR_TEXT, OR_YML, [or_model]
    )
    assert spec.or_prices_section is None
    assert "already matches the API rates" in spec.or_note


def test_build_update_spec_notes_when_api_lacks_model() -> None:
    drift = compare(ENTRY.prices, FLAT)
    spec = build_update_spec(
        PCFG, VENDOR_TEXT, ENTRY, FLAT, drift, "2026-08-24", OR_TEXT, OR_YML, []
    )
    assert spec.or_prices_section is None
    assert "not listed on the OpenRouter models API" in spec.or_note


def test_build_update_spec_conversion_emits_split_section() -> None:
    drift = compare(ENTRY.prices, SPLIT)
    spec = build_update_spec(
        PCFG, VENDOR_TEXT, ENTRY, SPLIT, drift, "2026-08-24", OR_TEXT, OR_YML, [OR_MODEL]
    )
    assert spec.case == "conversion"
    assert "      - prices:\n          input_mtok: 0.435\n" in spec.prices_section
    assert "          start_time: 01:00:00Z" in spec.prices_section
    assert "          start_time: 06:00:00Z" in spec.prices_section
    assert "XOR constraint schema" in spec.deviation


def test_build_update_spec_missing_entry_raises() -> None:
    drift = compare(ENTRY.prices, FLAT)
    with pytest.raises(ValueError, match="prices"):
        build_update_spec(
            PCFG, "models: []\n", ENTRY, FLAT, drift, "2026-08-24", OR_TEXT, OR_YML, [OR_MODEL]
        )


def test_conversion_carries_tracked_cache_read() -> None:
    entry = TrackedModel(
        "deepseek-chat",
        ClauseEquals("deepseek-chat"),
        prices={"input_mtok": 0.2, "output_mtok": 0.4, "cache_read_mtok": 0.035},
    )
    drift = compare(entry.prices, SPLIT)
    spec = build_update_spec(
        PCFG, VENDOR_TEXT, entry, SPLIT, drift, "2026-08-24", OR_TEXT, OR_YML, [OR_MODEL]
    )
    assert spec.case == "conversion"
    assert "          input_mtok: 0.435\n          cache_read_mtok: 0.035\n" in spec.prices_section


def test_replace_carries_split_cache_reads() -> None:
    entry = TrackedModel(
        "deepseek-chat",
        ClauseEquals("deepseek-chat"),
        prices=pyyaml.safe_load(
            "prices:\n"
            "  - prices:\n"
            "      input_mtok: 0.2\n"
            "      cache_read_mtok: 0.035\n"
            "      output_mtok: 0.4\n"
            "  - constraint:\n"
            "      start_time: 01:00:00Z\n"
            "      end_time: 04:00:00Z\n"
            "    prices:\n"
            "      input_mtok: 0.4\n"
            "      cache_read_mtok: 0.07\n"
            "      output_mtok: 0.8\n"
        )["prices"],
    )
    drift = compare(entry.prices, SPLIT)
    spec = build_update_spec(
        PCFG, VENDOR_TEXT, entry, SPLIT, drift, "2026-08-24", OR_TEXT, OR_YML, [OR_MODEL]
    )
    assert spec.case == "replace"
    assert "cache_read_mtok: 0.035" in spec.prices_section
    assert "cache_read_mtok: 0.07" in spec.prices_section


def test_replace_spec_carries_old_peak_schedule() -> None:
    entry = TrackedModel(
        "deepseek-chat",
        ClauseEquals("deepseek-chat"),
        prices=pyyaml.safe_load(
            "prices:\n"
            "  - prices:\n"
            "      input_mtok: 0.2\n"
            "      output_mtok: 0.4\n"
            "  - constraint:\n"
            "      start_time: 01:00:00Z\n"
            "      end_time: 04:00:00Z\n"
            "    prices:\n"
            "      input_mtok: 0.4\n"
            "      output_mtok: 0.8\n"
        )["prices"],
    )
    drift = compare(entry.prices, SPLIT)
    spec = build_update_spec(
        PCFG, VENDOR_TEXT, entry, SPLIT, drift, "2026-08-24", OR_TEXT, OR_YML, [OR_MODEL]
    )
    assert spec.old_peak_windows == (("01:00:00Z", "04:00:00Z"),)
    assert spec.old_peak_input_mtok == 0.4
    assert spec.old_peak_output_mtok == 0.8


def test_mirror_free_api_emits_free_dated_entry() -> None:
    drift = compare(ENTRY.prices, FLAT)
    free_model = OpenrouterModel(
        id="deepseek/deepseek-chat",
        name="DeepSeek Chat",
        input_mtok=None,
        output_mtok=None,
        cache_read_mtok=None,
    )
    spec = build_update_spec(
        PCFG, VENDOR_TEXT, ENTRY, FLAT, drift, "2026-08-24", OR_TEXT, OR_YML, [free_model]
    )
    assert spec.or_prices_section is not None
    assert "        prices: {}\n" in spec.or_prices_section
    assert "input_mtok: 0\n" not in spec.or_prices_section


def test_multi_dated_list_last_active_wins() -> None:
    dated_view = view(
        "prices:\n"
        "  - prices:\n"
        "      input_mtok: 0.2\n"
        "      output_mtok: 0.4\n"
        "  - constraint:\n"
        "      start_date: 2020-01-01\n"
        "    prices:\n"
        "      input_mtok: 0.5\n"
        "      output_mtok: 1.0\n"
        "  - constraint:\n"
        "      start_date: 2021-01-01\n"
        "    prices:\n"
        "      input_mtok: 0.435\n"
        "      output_mtok: 0.87\n"
    )
    assert compare(dated_view, FLAT).action == "none"
    drifted = view(
        "prices:\n"
        "  - prices:\n"
        "      input_mtok: 0.2\n"
        "      output_mtok: 0.4\n"
        "  - constraint:\n"
        "      start_date: 2020-01-01\n"
        "    prices:\n"
        "      input_mtok: 0.5\n"
        "      output_mtok: 1.0\n"
        "  - constraint:\n"
        "      start_date: 2021-01-01\n"
        "    prices:\n"
        "      input_mtok: 0.6\n"
        "      output_mtok: 1.2\n"
    )
    assert compare(drifted, FLAT).action == "dated_append"


def test_mirror_uses_the_dated_or_entry_as_current() -> None:
    or_yml = ProviderYml(
        "openrouter",
        "OpenRouter",
        (
            TrackedModel(
                "deepseek/deepseek-chat",
                ClauseEquals("deepseek/deepseek-chat"),
                prices=pyyaml.safe_load(
                    "prices:\n"
                    "  - prices:\n"
                    "      input_mtok: 0.2\n"
                    "      cache_read_mtok: 0.02\n"
                    "      output_mtok: 0.4\n"
                    "  - constraint:\n"
                    "      start_date: 2020-01-01\n"
                    "    prices:\n"
                    "      input_mtok: 0.435\n"
                    "      cache_read_mtok: 0.003625\n"
                    "      output_mtok: 0.87\n"
                )["prices"],
            ),
        ),
    )
    drift = compare(ENTRY.prices, FLAT)
    matched = build_update_spec(
        PCFG, VENDOR_TEXT, ENTRY, FLAT, drift, "2026-08-24", OR_TEXT, or_yml, [OR_MODEL]
    )
    assert matched.or_prices_section is None
    assert "already matches the API rates" in matched.or_note
    changed_api = OpenrouterModel(
        id="deepseek/deepseek-chat",
        name="DeepSeek Chat",
        input_mtok=0.5,
        output_mtok=1.0,
        cache_read_mtok=0.004,
    )
    drifted_spec = build_update_spec(
        PCFG, VENDOR_TEXT, ENTRY, FLAT, drift, "2026-08-24", OR_TEXT, or_yml, [changed_api]
    )
    assert drifted_spec.or_prices_section is not None
    assert "          cache_read_mtok: 0.004" in drifted_spec.or_prices_section

import re
from pathlib import Path

import pytest

from autopr_genai_prices.matcher import (
    ClauseAnd,
    ClauseEndsWith,
    ClauseEquals,
    ClauseOr,
    ClauseRegex,
    ClauseStartsWith,
)
from autopr_genai_prices.pricing import Pricing
from autopr_genai_prices.yml import (
    ProviderYml,
    TrackedModel,
    build_openrouter_entry,
    build_vendor_entry,
    dated_append_section,
    entry_span,
    insert_entry,
    is_tracked,
    parse,
    prices_section,
    prices_section_text,
    rewrite_entry,
)

FIXTURES = Path(__file__).parent / "fixtures" / "genai_prices"


@pytest.fixture(scope="module")
def provider_ymls() -> dict[str, ProviderYml]:
    return {
        path.stem: parse(path)
        for path in sorted(FIXTURES.glob("*.yml"))
        if path.name != "openrouter.yml"
    }


@pytest.fixture(scope="module")
def openrouter_yml() -> ProviderYml:
    return parse(FIXTURES / "openrouter.yml")


def test_parse_all_fixture_files(provider_ymls: dict[str, ProviderYml]) -> None:
    expected = {
        "deepseek": ("deepseek", "Deepseek"),
        "zai": ("zai", "Z.AI"),
        "x_ai": ("x-ai", "X AI"),
        "mistral": ("mistral", "Mistral"),
        "minimax": ("minimax", "MiniMax"),
        "moonshotai": ("moonshotai", "MoonshotAi"),
        "perplexity": ("perplexity", "Perplexity"),
    }
    assert set(provider_ymls) == set(expected)
    for name, (yml_id, yml_name) in expected.items():
        yml = provider_ymls[name]
        assert (yml.id, yml.name) == (yml_id, yml_name)
        assert yml.models


def test_zai_tracks_glm_5_2_not_glm_5_3(provider_ymls: dict[str, ProviderYml]) -> None:
    yml = provider_ymls["zai"]
    assert is_tracked(yml, "GLM-5.2")
    assert is_tracked(yml, "glm-5.2")
    assert not is_tracked(yml, "GLM-5.3")
    assert not is_tracked(yml, "glm-5.3")


def test_xai_tracks_dated_and_prefixed_variants(provider_ymls: dict[str, ProviderYml]) -> None:
    yml = provider_ymls["x_ai"]
    assert is_tracked(yml, "grok-4.5")
    assert is_tracked(yml, "grok-4.5-20260819")
    assert is_tracked(yml, "x-ai/grok-4.5")
    assert is_tracked(yml, "x-ai/grok-4.5-20260819")
    assert not is_tracked(yml, "grok-4.20-0309-non-reasoning")
    assert not is_tracked(yml, "grok-4.3-0309")


def test_deepseek_starts_with_tracks_dated_spellings(provider_ymls: dict[str, ProviderYml]) -> None:
    yml = provider_ymls["deepseek"]
    assert is_tracked(yml, "deepseek-v4-pro-0423")
    assert is_tracked(yml, "deepseek-chat-v3-0324")
    assert not is_tracked(yml, "deepseek-reasoner")


def test_removed_entries_are_parsed_but_not_tracked(tmp_path: Path) -> None:
    path = tmp_path / "removed.yml"
    path.write_text(
        """name: Test
id: test
models:
  - id: old-model
    match:
      equals: old-model
    prices:
      input_mtok: 1
    removed: true
  - id: live-model
    match:
      equals: live-model
    prices:
      input_mtok: 2
"""
    )
    yml = parse(path)
    assert [m.id for m in yml.models] == ["old-model", "live-model"]
    assert yml.models[0].removed
    assert not is_tracked(yml, "old-model")
    assert is_tracked(yml, "live-model")


DEEPSEEK_ENTRY = """  - id: deepseek-v4.1
    name: deepseek-v4.1
    match:
      or:
        - starts_with: deepseek-v4.1
    context_window: 1000000
    prices_checked: "2026-08-19"
    price_comments: "Ref: https://api-docs.deepseek.com/quick_start/pricing"
    prices:
      input_mtok: 0.435
      output_mtok: 0.87
"""


def test_build_vendor_entry_deepseek_copies_sibling_shape(
    provider_ymls: dict[str, ProviderYml],
) -> None:
    yml = provider_ymls["deepseek"]
    entry, skipped = build_vendor_entry(
        yml,
        "deepseek-v4.1",
        Pricing(0.435e-6, 0.87e-6, "chat", 1_000_000),
        "2026-08-19",
        "https://api-docs.deepseek.com/quick_start/pricing",
    )
    assert entry == DEEPSEEK_ENTRY
    assert skipped == ()


ZAI_ENTRY = """  - id: GLM-5.3
    name: GLM-5.3
    match:
      or:
        - equals: GLM-5.3
        - equals: glm-5.3
    context_window: 1000000
    prices_checked: "2026-08-19"
    price_comments: "Ref: https://docs.z.ai/guides/overview/pricing"
    prices:
      input_mtok: 1.4
      output_mtok: 4.4
"""


def test_build_vendor_entry_zai_case_pair_equals(provider_ymls: dict[str, ProviderYml]) -> None:
    yml = provider_ymls["zai"]
    entry, skipped = build_vendor_entry(
        yml,
        "GLM-5.3",
        Pricing(1.4e-6, 4.4e-6, "chat", 1_000_000),
        "2026-08-19",
        "https://docs.z.ai/guides/overview/pricing",
    )
    assert entry == ZAI_ENTRY
    assert skipped == ()


XAI_ENTRY = """  - id: grok-4.6
    name: grok-4.6
    match:
      or:
        - equals: grok-4.6
        - regex: ^grok-4\\.6-\\d{8}$
        - equals: x-ai/grok-4.6
        - regex: ^x-ai/grok-4\\.6-\\d{8}$
    context_window: 500000
    prices_checked: "2026-08-19"
    price_comments: "Ref: https://docs.x.ai/docs/models"
    prices:
      input_mtok: 2
      output_mtok: 6
"""


def test_build_vendor_entry_xai_rebuilds_dated_regex(provider_ymls: dict[str, ProviderYml]) -> None:
    yml = provider_ymls["x_ai"]
    entry, skipped = build_vendor_entry(
        yml,
        "grok-4.6",
        Pricing(2e-6, 6e-6, "chat", 500_000),
        "2026-08-19",
        "https://docs.x.ai/docs/models",
    )
    assert entry == XAI_ENTRY
    assert skipped == ("grok-4.5-latest", "grok-latest")


def test_build_vendor_entry_falls_back_to_first_model_when_none_smaller(
    provider_ymls: dict[str, ProviderYml],
) -> None:
    yml = provider_ymls["zai"]
    entry, skipped = build_vendor_entry(
        yml,
        "GLM-4",
        Pricing(1.4e-6, 4.4e-6, "chat", 1_000_000),
        "2026-08-19",
        "https://docs.z.ai/guides/overview/pricing",
    )
    assert "        - equals: GLM-4\n        - equals: glm-4\n" in entry
    assert skipped == ()


def test_build_vendor_entry_drops_regex_without_sibling_id() -> None:
    yml = ProviderYml(
        "t",
        "Test",
        (
            TrackedModel(
                "foo-v1",
                ClauseOr((ClauseRegex(re.compile(r"^bar-\d+$")), ClauseEquals("foo-v1"))),
            ),
        ),
    )
    entry, skipped = build_vendor_entry(
        yml, "foo-v2", Pricing(1e-6, 2e-6, "chat"), "2026-08-19", "https://example.com"
    )
    assert entry == (
        "  - id: foo-v2\n"
        "    name: foo-v2\n"
        "    match:\n"
        "      or:\n"
        "        - equals: foo-v2\n"
        '    prices_checked: "2026-08-19"\n'
        '    price_comments: "Ref: https://example.com"\n'
        "    prices:\n"
        "      input_mtok: 1\n"
        "      output_mtok: 2\n"
    )
    assert skipped == ()


def test_build_vendor_entry_drops_latest_clauses_and_falls_back() -> None:
    yml = ProviderYml("t", "Test", (TrackedModel("foo-latest", ClauseEquals("foo-latest")),))
    entry, skipped = build_vendor_entry(
        yml, "bar", Pricing(1e-6, 2e-6, "chat"), "2026-08-19", "https://example.com"
    )
    assert "    match:\n      equals: bar\n" in entry
    assert skipped == ("foo-latest",)


def test_build_vendor_entry_passes_through_unrelated_clauses() -> None:
    yml = ProviderYml(
        "t",
        "Test",
        (TrackedModel("foo", ClauseOr((ClauseEquals("foo"), ClauseEquals("foo-alias")))),),
    )
    entry, skipped = build_vendor_entry(
        yml, "bar", Pricing(1e-6, 2e-6, "chat"), "2026-08-19", "https://example.com"
    )
    assert "        - equals: bar\n        - equals: foo-alias\n" in entry
    assert skipped == ()


DEEPSEEK_PEAK_ENTRY = (
    """  - id: deepseek-v4.1
    name: deepseek-v4.1
    match:
      or:
        - starts_with: deepseek-v4.1
    context_window: 1000000
    prices_checked: "2026-08-19"
    price_comments: "Ref: https://api-docs.deepseek.com/quick_start/pricing. """
    """Off-peak rates are half of the peak rates. """
    """Peak hours are 01:00:00Z - 04:00:00Z + 06:00:00Z - 10:00:00Z """
    """UTC (all other hours are off-peak)"
    prices:
      - prices:
          input_mtok: 0.435
          output_mtok: 0.87
      - constraint:
          start_time: 01:00:00Z
          end_time: 04:00:00Z
        prices:
          input_mtok: 0.87
          output_mtok: 1.74
      - constraint:
          start_time: 06:00:00Z
          end_time: 10:00:00Z
        prices:
          input_mtok: 0.87
          output_mtok: 1.74
"""
)


def test_build_vendor_entry_peak_prices_become_conditional_list(
    provider_ymls: dict[str, ProviderYml],
) -> None:
    yml = provider_ymls["deepseek"]
    entry, skipped = build_vendor_entry(
        yml,
        "deepseek-v4.1",
        Pricing(
            0.435e-6,
            0.87e-6,
            "chat",
            1_000_000,
            peak_input_cost_per_token=0.87e-6,
            peak_output_cost_per_token=1.74e-6,
            peak_windows=(("01:00:00Z", "04:00:00Z"), ("06:00:00Z", "10:00:00Z")),
        ),
        "2026-08-19",
        "https://api-docs.deepseek.com/quick_start/pricing",
    )
    assert entry == DEEPSEEK_PEAK_ENTRY
    assert skipped == ()


def test_build_vendor_entry_peak_prices_without_windows_asserts(
    provider_ymls: dict[str, ProviderYml],
) -> None:
    yml = provider_ymls["deepseek"]
    with pytest.raises(AssertionError):
        build_vendor_entry(
            yml,
            "deepseek-v4.1",
            Pricing(0.435e-6, 0.87e-6, "chat", peak_input_cost_per_token=0.87e-6),
            "2026-08-19",
            "https://api-docs.deepseek.com/quick_start/pricing",
        )


def test_build_vendor_entry_omits_context_window_when_max_tokens_zero(
    provider_ymls: dict[str, ProviderYml],
) -> None:
    yml = provider_ymls["deepseek"]
    entry, _ = build_vendor_entry(
        yml,
        "deepseek-v4.1",
        Pricing(0.435e-6, 0.87e-6, "chat"),
        "2026-08-19",
        "https://api-docs.deepseek.com/quick_start/pricing",
    )
    assert "context_window" not in entry


SYNTHETIC = """models:
  - id: a
    match:
      equals: a
    prices:
      input_mtok: 1

  - id: c
    match:
      equals: c
    prices:
      input_mtok: 3
"""

ENTRY_B = """  - id: b
    match:
      equals: b
    prices:
      input_mtok: 2
"""


def test_insert_entry_middle() -> None:
    result = insert_entry(SYNTHETIC, "b", ENTRY_B)
    assert result == (
        "models:\n"
        "  - id: a\n"
        "    match:\n"
        "      equals: a\n"
        "    prices:\n"
        "      input_mtok: 1\n"
        "\n"
        "  - id: b\n"
        "    match:\n"
        "      equals: b\n"
        "    prices:\n"
        "      input_mtok: 2\n"
        "\n"
        "  - id: c\n"
        "    match:\n"
        "      equals: c\n"
        "    prices:\n"
        "      input_mtok: 3\n"
    )


def test_insert_entry_appends_at_end() -> None:
    result = insert_entry(SYNTHETIC, "z", ENTRY_B)
    assert result == SYNTHETIC + "\n" + ENTRY_B
    assert result.endswith("\n")


def test_insert_entry_into_openrouter_fixture_preserves_bytes() -> None:
    text = (FIXTURES / "openrouter.yml").read_text()
    entry = build_openrouter_entry("minimax/minimax-m1", "MiniMax M1", 0.4, 2.2, 0.04)
    pos = text.index("  - id: minimax/minimax-m3\n")
    assert insert_entry(text, "minimax/minimax-m1", entry) == text[:pos] + entry + "\n" + text[pos:]


def test_insert_entry_before_quoted_first_entry() -> None:
    text = (FIXTURES / "openrouter.yml").read_text()
    entry = build_openrouter_entry(
        "agentica-org/deepcoder-14b-preview:beta", "Beta", 0.1, 0.2, None
    )
    pos = text.index('  - id: "agentica-org/deepcoder-14b-preview:free"\n')
    expected = text[:pos] + entry + "\n" + text[pos:]
    assert insert_entry(text, "agentica-org/deepcoder-14b-preview:beta", entry) == expected


OPENROUTER_ENTRY = """  - id: deepseek/deepseek-v4-pro
    name: "DeepSeek V4 Pro"
    match:
      equals: deepseek/deepseek-v4-pro
    prices:
      input_mtok: 0.435
      cache_read_mtok: 0.003625
      output_mtok: 0.87
"""


def test_build_openrouter_entry_full() -> None:
    entry = build_openrouter_entry(
        "deepseek/deepseek-v4-pro", "DeepSeek V4 Pro", 0.435, 0.87, 0.003625
    )
    assert entry == OPENROUTER_ENTRY


def test_build_openrouter_entry_without_cache_read() -> None:
    entry = build_openrouter_entry("a/b", "B", 0.435, 0.87, None)
    assert "cache_read_mtok" not in entry
    assert "      input_mtok: 0.435\n      output_mtok: 0.87\n" in entry


def test_build_openrouter_entry_free_model() -> None:
    entry = build_openrouter_entry("a/b:free", "Free B", None, None, None)
    assert entry == (
        '  - id: a/b:free\n    name: "Free B"\n    match:\n      equals: a/b:free\n    prices: {}\n'
    )


def test_build_openrouter_entry_output_none_omits_line() -> None:
    entry = build_openrouter_entry("a/b", "B", 0.4, None, 0.04)
    assert "      input_mtok: 0.4\n      cache_read_mtok: 0.04\n" in entry
    assert "output_mtok" not in entry


def test_build_vendor_entry_nested_and_match() -> None:
    yml = ProviderYml(
        "t",
        "Test",
        (TrackedModel("foo", ClauseAnd((ClauseStartsWith("foo"), ClauseEndsWith("pro")))),),
    )
    entry, skipped = build_vendor_entry(
        yml, "bar-pro", Pricing(1e-6, 2e-6, "chat"), "2026-08-19", "https://example.com"
    )
    assert (
        "    match:\n      and:\n        - starts_with: bar-pro\n        - ends_with: pro\n"
        in entry
    )
    assert skipped == ()


def test_build_vendor_entry_and_empty_after_drops_falls_back() -> None:
    yml = ProviderYml(
        "t",
        "Test",
        (
            TrackedModel(
                "foo",
                ClauseAnd((ClauseEquals("foo-latest"), ClauseEquals("foo-alias-latest"))),
            ),
        ),
    )
    entry, skipped = build_vendor_entry(
        yml, "bar", Pricing(1e-6, 2e-6, "chat"), "2026-08-19", "https://example.com"
    )
    assert "    match:\n      equals: bar\n" in entry
    assert skipped == ("foo-latest", "foo-alias-latest")


def test_parse_missing_top_level_keys_raises(tmp_path: Path) -> None:
    path = tmp_path / "broken.yml"
    path.write_text("name: Test\nmodels: []\n")
    with pytest.raises(ValueError, match="id"):
        parse(path)


def test_parse_model_missing_match_raises(tmp_path: Path) -> None:
    path = tmp_path / "broken.yml"
    path.write_text("name: Test\nid: test\nmodels:\n  - id: x\n    prices: {}\n")
    with pytest.raises(ValueError, match="match"):
        parse(path)


def test_parse_invalid_yaml_raises(tmp_path: Path) -> None:
    path = tmp_path / "broken.yml"
    path.write_text("name: [unclosed\n")
    with pytest.raises(ValueError, match="yaml"):
        parse(path)


def test_parse_models_not_a_list_raises(tmp_path: Path) -> None:
    path = tmp_path / "broken.yml"
    path.write_text("name: Test\nid: test\nmodels: nope\n")
    with pytest.raises(ValueError, match="models"):
        parse(path)


def test_parse_captures_prices(tmp_path: Path) -> None:
    path = tmp_path / "prices.yml"
    path.write_text(
        """name: Test
id: test
models:
  - id: flat
    match:
      equals: flat
    prices:
      input_mtok: 1
      output_mtok: 2
  - id: split
    match:
      equals: split
    prices:
      - prices:
          input_mtok: 0.5
      - constraint:
          start_time: 01:00:00Z
          end_time: 04:00:00Z
        prices:
          input_mtok: 1
"""
    )
    yml = parse(path)
    assert yml.models[0].prices == {"input_mtok": 1, "output_mtok": 2}
    assert yml.models[1].prices == [
        {"prices": {"input_mtok": 0.5}},
        {
            "constraint": {"start_time": "01:00:00Z", "end_time": "04:00:00Z"},
            "prices": {"input_mtok": 1},
        },
    ]


def test_parse_entry_without_prices_leaves_none(tmp_path: Path) -> None:
    path = tmp_path / "noprices.yml"
    path.write_text("name: Test\nid: test\nmodels:\n  - id: x\n    match:\n      equals: x\n")
    assert parse(path).models[0].prices is None


TWO_ENTRIES = """models:
  - id: a
    match:
      equals: a
    prices:
      input_mtok: 1

  - id: b
    match:
      equals: b
    prices:
      input_mtok: 2
"""


def test_entry_span_finds_block() -> None:
    assert entry_span(TWO_ENTRIES, "a") == (1, 7)
    assert entry_span(TWO_ENTRIES, "b") == (7, 12)
    assert entry_span(TWO_ENTRIES, "z") is None


def test_entry_span_tolerates_quoted_id() -> None:
    text = 'models:\n  - id: "a:b"\n    match:\n      equals: "a:b"\n'
    assert entry_span(text, "a:b") == (1, 4)


def test_prices_section_text_flat_and_list() -> None:
    assert prices_section_text(TWO_ENTRIES, "a") == "    prices:\n      input_mtok: 1\n"
    text = (
        "  - id: s\n"
        "    match:\n"
        "      equals: s\n"
        "    prices:\n"
        "      - prices:\n"
        "          input_mtok: 0.5\n"
        "      - constraint:\n"
        "          start_time: 01:00:00Z\n"
        "          end_time: 04:00:00Z\n"
        "        prices:\n"
        "          input_mtok: 1\n"
        "  - id: t\n"
        "    match:\n"
        "      equals: t\n"
    )
    assert prices_section_text(text, "s") == (
        "    prices:\n"
        "      - prices:\n"
        "          input_mtok: 0.5\n"
        "      - constraint:\n"
        "          start_time: 01:00:00Z\n"
        "          end_time: 04:00:00Z\n"
        "        prices:\n"
        "          input_mtok: 1\n"
    )


def test_prices_section_text_missing_returns_none() -> None:
    assert prices_section_text(TWO_ENTRIES, "z") is None


def test_rewrite_entry_replaces_section_and_updates_quoted_checked() -> None:
    text = (
        "  - id: m\n"
        "    match:\n"
        "      equals: m\n"
        '    prices_checked: "2026-08-19"\n'
        "    prices:\n"
        "      input_mtok: 0.435\n"
        "      output_mtok: 0.87\n"
    )
    result = rewrite_entry(text, "m", "    prices:\n      input_mtok: 1\n", checked="2026-08-24")
    assert result == (
        "  - id: m\n"
        "    match:\n"
        "      equals: m\n"
        '    prices_checked: "2026-08-24"\n'
        "    prices:\n"
        "      input_mtok: 1\n"
    )


def test_rewrite_entry_keeps_unquoted_checked_style() -> None:
    text = (
        "  - id: m\n"
        "    match:\n"
        "      equals: m\n"
        "    prices_checked: 2026-08-19\n"
        "    prices:\n"
        "      input_mtok: 1\n"
    )
    result = rewrite_entry(text, "m", "    prices:\n      input_mtok: 2\n", checked="2026-08-24")
    assert "    prices_checked: 2026-08-24\n" in result
    assert '"' not in result.splitlines()[3]


def test_rewrite_entry_inserts_missing_checked_before_prices() -> None:
    text = "  - id: m\n    match:\n      equals: m\n    prices:\n      input_mtok: 1\n"
    result = rewrite_entry(text, "m", "    prices:\n      input_mtok: 2\n", checked="2026-08-24")
    assert result == (
        "  - id: m\n"
        "    match:\n"
        "      equals: m\n"
        '    prices_checked: "2026-08-24"\n'
        "    prices:\n"
        "      input_mtok: 2\n"
    )


def test_rewrite_entry_updates_checked_after_prices() -> None:
    # anthropic-style field order: prices first, prices_checked after
    text = (
        "  - id: m\n"
        "    match:\n"
        "      equals: m\n"
        "    prices:\n"
        "      input_mtok: 1\n"
        '    prices_checked: "2026-08-19"\n'
    )
    result = rewrite_entry(text, "m", "    prices:\n      input_mtok: 2\n", checked="2026-08-24")
    assert result == (
        "  - id: m\n"
        "    match:\n"
        "      equals: m\n"
        "    prices:\n"
        "      input_mtok: 2\n"
        '    prices_checked: "2026-08-24"\n'
    )


def test_rewrite_entry_leaves_neighbours_untouched() -> None:
    result = rewrite_entry(
        TWO_ENTRIES, "a", "    prices:\n      input_mtok: 9\n", checked="2026-08-24"
    )
    assert "  - id: b\n" in result
    assert "      input_mtok: 2\n" in result
    assert "prices_checked" not in result.split("  - id: b")[1]


def test_rewrite_entry_missing_model_raises() -> None:
    with pytest.raises(ValueError, match="no entry"):
        rewrite_entry(TWO_ENTRIES, "z", "    prices:\n")


def test_rewrite_entry_section_start_asserts() -> None:
    with pytest.raises(AssertionError):
        rewrite_entry(TWO_ENTRIES, "a", "      input_mtok: 1\n")


FLAT_SECTION = "    prices:\n      input_mtok: 0.435\n      output_mtok: 0.87\n"


def test_dated_append_section_mapping_becomes_list() -> None:
    result = dated_append_section(
        FLAT_SECTION, 0.54e-6, 1.08e-6, "2026-08-24", "rate change; effective date unknown"
    )
    assert result == (
        "    prices:\n"
        "      - prices:\n"
        "          input_mtok: 0.435\n"
        "          output_mtok: 0.87\n"
        "      - constraint:\n"
        "          # rate change; effective date unknown\n"
        "          start_date: 2026-08-24\n"
        "        prices:\n"
        "          input_mtok: 0.54\n"
        "          output_mtok: 1.08\n"
    )


LIST_SECTION = (
    "    prices:\n"
    "      - prices:\n"
    "          input_mtok: 0.435\n"
    "          output_mtok: 0.87\n"
    "      - constraint:\n"
    "          start_time: 01:00:00Z\n"
    "          end_time: 04:00:00Z\n"
    "        prices:\n"
    "          input_mtok: 0.87\n"
    "          output_mtok: 1.74\n"
)


def test_dated_append_section_on_list_appends_last() -> None:
    result = dated_append_section(LIST_SECTION, 0.54e-6, 1.08e-6, "2026-08-24", "rate change")
    assert result == LIST_SECTION + (
        "      - constraint:\n"
        "          # rate change\n"
        "          start_date: 2026-08-24\n"
        "        prices:\n"
        "          input_mtok: 0.54\n"
        "          output_mtok: 1.08\n"
    )
    assert result.index("01:00:00Z") < result.index("start_date: 2026-08-24")


def test_dated_append_section_free_entry_base() -> None:
    result = dated_append_section("    prices: {}\n", 1e-6, 2e-6, "2026-08-24", "went paid")
    assert result == (
        "    prices:\n"
        "      - prices: {}\n"
        "      - constraint:\n"
        "          # went paid\n"
        "          start_date: 2026-08-24\n"
        "        prices:\n"
        "          input_mtok: 1\n"
        "          output_mtok: 2\n"
    )


def test_prices_section_split() -> None:
    section = prices_section(
        Pricing(
            0.435e-6,
            0.87e-6,
            "chat",
            peak_input_cost_per_token=0.87e-6,
            peak_output_cost_per_token=1.74e-6,
            peak_windows=(("01:00:00Z", "04:00:00Z"),),
        )
    )
    assert section == (
        "    prices:\n"
        "      - prices:\n"
        "          input_mtok: 0.435\n"
        "          output_mtok: 0.87\n"
        "      - constraint:\n"
        "          start_time: 01:00:00Z\n"
        "          end_time: 04:00:00Z\n"
        "        prices:\n"
        "          input_mtok: 0.87\n"
        "          output_mtok: 1.74\n"
    )

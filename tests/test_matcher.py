import re

import pytest
import yaml

from ai_pricelog.matcher import (
    ClauseAnd,
    ClauseContains,
    ClauseEndsWith,
    ClauseEquals,
    ClauseOr,
    ClauseRegex,
    ClauseStartsWith,
    parse_match,
)


def test_equals_is_case_insensitive() -> None:
    clause = ClauseEquals("GLM-5.2")
    assert clause.is_match("glm-5.2")
    assert clause.is_match("GLM-5.2")
    assert not clause.is_match("GLM-5.3")


def test_starts_with_is_case_insensitive() -> None:
    clause = ClauseStartsWith("deepseek-v4-pro")
    assert clause.is_match("DeepSeek-V4-Pro-0423")
    assert not clause.is_match("deepseek-v4-flash")


def test_ends_with_is_case_insensitive() -> None:
    clause = ClauseEndsWith("-latest")
    assert clause.is_match("Grok-Latest")
    assert not clause.is_match("grok-4.5-beta")


def test_contains_is_case_insensitive() -> None:
    clause = ClauseContains("m2.1-highspeed")
    assert clause.is_match("MiniMax-M2.1-HIGHSPEED-2512")
    assert not clause.is_match("MiniMax-M2.5-highspeed")


def test_regex_is_case_sensitive_search() -> None:
    dated = ClauseRegex(re.compile(r"^grok-4\.5-\d{8}$"))
    assert dated.is_match("grok-4.5-20260819")
    assert not dated.is_match("GROK-4.5-20260819")
    # re.search semantics, not fullmatch: the pattern can match anywhere
    search = ClauseRegex(re.compile(r"4\.5-\d{8}"))
    assert search.is_match("x-grok-4.5-20260819-y")
    assert not search.is_match("x-grok-4.5-2026-y")


def test_or_matches_when_any_clause_matches() -> None:
    clause = ClauseOr((ClauseEquals("a"), ClauseEquals("b")))
    assert clause.is_match("b")
    assert not clause.is_match("c")


def test_and_matches_only_when_all_clauses_match() -> None:
    clause = ClauseAnd((ClauseStartsWith("grok"), ClauseContains("4.5")))
    assert clause.is_match("grok-4.5-x")
    assert not clause.is_match("grok-3")


def test_nested_or_inside_and() -> None:
    clause = ClauseAnd(
        (
            ClauseStartsWith("deepseek"),
            ClauseOr((ClauseEndsWith("pro"), ClauseEndsWith("flash"))),
        )
    )
    assert clause.is_match("deepseek-v4-flash")
    assert not clause.is_match("deepseek-v4-x")


def test_parse_match_round_trip_from_yaml_dict() -> None:
    data = yaml.safe_load(
        "or:\n  - equals: GLM-5.2\n  - regex: '^glm-5\\.2-\\d{8}$'\n  - starts_with: glm-5.2-\n"
    )
    clause = parse_match(data)
    assert clause.is_match("glm-5.2")
    assert clause.is_match("glm-5.2-20260819")
    assert not clause.is_match("glm-5.3")


def test_parse_match_and_clause() -> None:
    clause = parse_match({"and": [{"starts_with": "grok"}, {"contains": "4.5"}]})
    assert isinstance(clause, ClauseAnd)
    assert clause.is_match("grok-4.5-x")
    assert not clause.is_match("grok-3")


def test_parse_match_unknown_key_raises_naming_the_key() -> None:
    with pytest.raises(ValueError, match="eq"):
        parse_match({"eq": "x"})


def test_parse_match_multiple_keys_raises() -> None:
    with pytest.raises(ValueError, match="starts_with"):
        parse_match({"equals": "a", "starts_with": "b"})


def test_parse_match_non_dict_raises() -> None:
    with pytest.raises(ValueError, match="dict"):
        parse_match("not-a-dict")


def test_parse_match_wrong_value_types_raise() -> None:
    with pytest.raises(ValueError, match="or"):
        parse_match({"or": "not-a-list"})
    with pytest.raises(ValueError, match="regex"):
        parse_match({"regex": 5})
    with pytest.raises(ValueError, match="equals"):
        parse_match({"equals": ["a"]})

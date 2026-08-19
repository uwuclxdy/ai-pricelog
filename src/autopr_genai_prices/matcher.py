"""Match-clause semantics mirrored from pydantic/genai-prices `prices_types.py`.

The target defines seven clause kinds: equals, starts_with, ends_with, contains
(all case-insensitive), regex (case-sensitive re.search), combined via or/and.
This module keeps the same semantics so tracked-model checks behave identically
to the target build's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ClauseEquals:
    equals: str

    def is_match(self, text: str) -> bool:
        return text.lower() == self.equals.lower()


@dataclass(frozen=True)
class ClauseStartsWith:
    starts_with: str

    def is_match(self, text: str) -> bool:
        return text.lower().startswith(self.starts_with.lower())


@dataclass(frozen=True)
class ClauseEndsWith:
    ends_with: str

    def is_match(self, text: str) -> bool:
        return text.lower().endswith(self.ends_with.lower())


@dataclass(frozen=True)
class ClauseContains:
    contains: str

    def is_match(self, text: str) -> bool:
        return self.contains.lower() in text.lower()


@dataclass(frozen=True)
class ClauseRegex:
    regex: re.Pattern[str]

    def is_match(self, text: str) -> bool:
        return bool(self.regex.search(text))


@dataclass(frozen=True)
class ClauseOr:
    or_: tuple[MatchLogic, ...]

    def is_match(self, text: str) -> bool:
        return any(clause.is_match(text) for clause in self.or_)


@dataclass(frozen=True)
class ClauseAnd:
    and_: tuple[MatchLogic, ...]

    def is_match(self, text: str) -> bool:
        return all(clause.is_match(text) for clause in self.and_)


MatchLogic = (
    ClauseEquals
    | ClauseStartsWith
    | ClauseEndsWith
    | ClauseContains
    | ClauseRegex
    | ClauseOr
    | ClauseAnd
)

_STRING_CLAUSES: dict[str, type] = {
    "equals": ClauseEquals,
    "starts_with": ClauseStartsWith,
    "ends_with": ClauseEndsWith,
    "contains": ClauseContains,
    "regex": ClauseRegex,
}
_LIST_CLAUSES: dict[str, type] = {"or": ClauseOr, "and": ClauseAnd}
_KNOWN_KEYS = {*_STRING_CLAUSES, *_LIST_CLAUSES}


def parse_match(data: object) -> MatchLogic:
    """Build nested clause objects from a loaded yaml dict.

    Each clause is a plain dict with exactly one of the known clause keys;
    anything else raises ValueError naming the bad key.
    """
    if not isinstance(data, dict):
        raise ValueError(f"match clause must be a dict, got {type(data).__name__}")
    if len(data) != 1:
        raise ValueError(f"match clause must have exactly one key, got: {sorted(data)!r}")
    key, value = next(iter(data.items()))
    if key in _STRING_CLAUSES:
        if not isinstance(value, str):
            raise ValueError(
                f"match clause {key!r} value must be a string, got {type(value).__name__}"
            )
        if key == "regex":
            try:
                return ClauseRegex(re.compile(value))
            except re.error as exc:
                raise ValueError(
                    f"match clause regex pattern is invalid: {value!r}: {exc}"
                ) from exc
        return _STRING_CLAUSES[key](value)
    if key in _LIST_CLAUSES:
        if not isinstance(value, list):
            raise ValueError(
                f"match clause {key!r} value must be a list, got {type(value).__name__}"
            )
        return _LIST_CLAUSES[key](tuple(parse_match(item) for item in value))
    raise ValueError(f"unknown match clause key: {key!r}, expected one of {sorted(_KNOWN_KEYS)}")

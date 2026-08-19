"""Provider yml parsing, entry building, and splicing for pydantic/genai-prices.

`parse` and `is_tracked` mirror the target build's semantics (prices_types.py:
case-insensitive clause matching, removed entries excluded from tracking).
`build_vendor_entry` and `build_openrouter_entry` emit model-list item text in
the target's own yaml conventions (2-space indent, one blank line between
entries, file ends with a newline).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from autopr_genai_prices.matcher import (
    ClauseAnd,
    ClauseContains,
    ClauseEndsWith,
    ClauseEquals,
    ClauseOr,
    ClauseRegex,
    ClauseStartsWith,
    MatchLogic,
    parse_match,
)
from autopr_genai_prices.pricing import Pricing


@dataclass(frozen=True)
class TrackedModel:
    id: str
    match: MatchLogic
    removed: bool = False


@dataclass(frozen=True)
class ProviderYml:
    id: str
    name: str
    models: tuple[TrackedModel, ...]


def parse(path: Path) -> ProviderYml:
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ValueError(f"file '{path}': invalid yaml: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"file '{path}': root must be a yaml mapping")
    missing = [key for key in ("id", "name", "models") if key not in data]
    if missing:
        raise ValueError(f"file '{path}': missing top-level keys: {missing}")
    yml_id, name = data["id"], data["name"]
    if not isinstance(yml_id, str) or not isinstance(name, str):
        raise ValueError(f"file '{path}': top-level id/name must be strings")
    models_data = data["models"]
    if not isinstance(models_data, list):
        raise ValueError(f"file '{path}': 'models' must be a list")
    models = [_parse_model(path, index, entry) for index, entry in enumerate(models_data)]
    return ProviderYml(yml_id, name, tuple(models))


def _parse_model(path: Path, index: int, entry: object) -> TrackedModel:
    if not isinstance(entry, dict):
        raise ValueError(f"file '{path}': model {index} must be a mapping")
    missing = [key for key in ("id", "match") if key not in entry]
    if missing:
        raise ValueError(f"file '{path}': model {index} missing keys: {missing}")
    model_id = entry["id"]
    if not isinstance(model_id, str):
        raise ValueError(f"file '{path}': model {index} id must be a string")
    return TrackedModel(model_id, parse_match(entry["match"]), bool(entry.get("removed", False)))


def is_tracked(yml: ProviderYml, model_id: str) -> bool:
    """Whether any non-removed model's match accepts the id, in list order."""
    return any(not model.removed and model.match.is_match(model_id) for model in yml.models)


def to_mtok(per_token: float) -> float:
    """Per-token dollars -> per-megatoken dollars, rounded to 6 decimals."""
    return round(per_token * 1_000_000, 6)


def _fmt_mtok(per_token: float) -> str:
    return f"{to_mtok(per_token):g}"


def build_vendor_entry(
    yml: ProviderYml,
    model_id: str,
    pricing: Pricing,
    checked: str,
    scraper_url: str,
) -> tuple[str, tuple[str, ...]]:
    """Build one models-list item for a vendor yml.

    Returns (entry_text, skipped_latest): clause values ending in `-latest`
    are dropped as family/version aliases and returned for the PR body.
    """
    has_peak = (
        pricing.peak_input_cost_per_token is not None
        or pricing.peak_output_cost_per_token is not None
    )
    assert not has_peak or pricing.peak_windows, "peak prices set but peak_windows is empty"
    sibling = _sibling(yml, model_id)
    skipped: list[str] = []
    match = _rebuild_match(sibling.match, sibling.id, model_id, skipped)
    if match is None:
        match = ClauseEquals(model_id)
    lines = [f"  - id: {model_id}", f"    name: {model_id}", "    match:"]
    lines.extend(_render_clause(match, "      "))
    if pricing.max_tokens > 0:
        lines.append(f"    context_window: {pricing.max_tokens}")
    lines.append(f'    prices_checked: "{checked}"')
    comment = f"Ref: {scraper_url}"
    if has_peak:
        windows = " + ".join(f"{start} - {end}" for start, end in pricing.peak_windows)
        comment += (
            ". Off-peak rates are half of the peak rates. "
            f"Peak hours are {windows} UTC (all other hours are off-peak)"
        )
    lines.append(f'    price_comments: "{comment}"')
    lines.append("    prices:")
    if has_peak:
        lines.append("      - prices:")
        lines.append(f"          input_mtok: {_fmt_mtok(pricing.input_cost_per_token)}")
        lines.append(f"          output_mtok: {_fmt_mtok(pricing.output_cost_per_token)}")
        for start, end in pricing.peak_windows:
            lines.append("      - constraint:")
            lines.append(f"          start_time: {start}")
            lines.append(f"          end_time: {end}")
            lines.append("        prices:")
            lines.append(f"          input_mtok: {_fmt_mtok(pricing.peak_input_cost_per_token)}")
            lines.append(f"          output_mtok: {_fmt_mtok(pricing.peak_output_cost_per_token)}")
    else:
        lines.append(f"      input_mtok: {_fmt_mtok(pricing.input_cost_per_token)}")
        lines.append(f"      output_mtok: {_fmt_mtok(pricing.output_cost_per_token)}")
    return "\n".join(lines) + "\n", tuple(skipped)


def _sibling(yml: ProviderYml, model_id: str) -> TrackedModel:
    """The tracked model with the greatest id strictly less than model_id.

    Falls back to the first tracked model when no id sorts smaller.
    """
    tracked = [model for model in yml.models if not model.removed]
    smaller = [model for model in tracked if model.id < model_id]
    return max(smaller, key=lambda model: model.id) if smaller else tracked[0]


def _rebuild_match(
    match: MatchLogic,
    sibling_id: str,
    model_id: str,
    skipped: list[str],
) -> MatchLogic | None:
    """Copy the sibling's match shape with the sibling id replaced by model_id.

    Returns None when every clause was dropped. String clauses ending in a
    trailing sibling-id span (the whole value, or after a vendor prefix
    separator) get that span substituted in the same case form; other values
    pass through unchanged. Regex clauses keep the pattern only when it
    contains the escaped sibling id (replaced once); any clause whose value
    ends in `-latest` is dropped and recorded in `skipped`.
    """
    if isinstance(match, (ClauseEquals, ClauseStartsWith, ClauseEndsWith, ClauseContains)):
        value = _string_value(match)
        if value.lower().endswith("-latest"):
            skipped.append(value)
            return None
        value = _substitute(value, sibling_id, model_id)
        if value.lower().endswith("-latest"):
            skipped.append(value)
            return None
        return type(match)(value)
    if isinstance(match, ClauseRegex):
        pattern = match.regex.pattern
        escaped_sibling = _escape_id(sibling_id)
        if escaped_sibling not in pattern:
            return None
        pattern = pattern.replace(escaped_sibling, _escape_id(model_id), 1)
        if pattern.lower().endswith("-latest"):
            skipped.append(pattern)
            return None
        return ClauseRegex(re.compile(pattern))
    if isinstance(match, ClauseOr):
        children = [
            child
            for clause in match.or_
            if (child := _rebuild_match(clause, sibling_id, model_id, skipped)) is not None
        ]
        return ClauseOr(tuple(children)) if children else None
    if isinstance(match, ClauseAnd):
        children = [
            child
            for clause in match.and_
            if (child := _rebuild_match(clause, sibling_id, model_id, skipped)) is not None
        ]
        return ClauseAnd(tuple(children)) if children else None
    raise AssertionError(f"unhandled clause type: {type(match).__name__}")


def _string_value(match: MatchLogic) -> str:
    if isinstance(match, ClauseEquals):
        return match.equals
    if isinstance(match, ClauseStartsWith):
        return match.starts_with
    if isinstance(match, ClauseEndsWith):
        return match.ends_with
    return match.contains


def _substitute(value: str, sibling_id: str, model_id: str) -> str:
    """Replace a trailing sibling-id span with the new id in the same case form.

    The span is the whole value (equals) or the part after a vendor prefix
    separator (`x-ai/grok-4.5`). Other values pass through unchanged.
    """
    lower_value = value.lower()
    lower_sibling = sibling_id.lower()
    if lower_value == lower_sibling:
        start = 0
    elif lower_value.endswith("/" + lower_sibling):
        start = len(value) - len(sibling_id)
    else:
        return value
    span = value[start:]
    if span == lower_sibling:
        replacement = model_id.lower()
    elif span == sibling_id.upper():
        replacement = model_id.upper()
    else:
        replacement = model_id
    return value[:start] + replacement


def _escape_id(model_id: str) -> str:
    r"""Escape an id the way the target escapes ids inside regex patterns.

    The target escapes only periods (`^grok-4\.5-\d{8}$`); hyphens and slashes
    stay literal, so a full re.escape (which escapes hyphens too) never
    matches their patterns.
    """
    return model_id.replace(".", "\\.")


def _render_clause(match: MatchLogic, indent: str) -> list[str]:
    """Render a clause at the given line indent; or/and children become list items."""
    if isinstance(match, ClauseOr):
        return _render_list("or", match.or_, indent)
    if isinstance(match, ClauseAnd):
        return _render_list("and", match.and_, indent)
    if isinstance(match, ClauseRegex):
        return [f"{indent}regex: {match.regex.pattern}"]
    key = (
        "equals"
        if isinstance(match, ClauseEquals)
        else "starts_with"
        if isinstance(match, ClauseStartsWith)
        else "ends_with"
        if isinstance(match, ClauseEndsWith)
        else "contains"
    )
    return [f"{indent}{key}: {_string_value(match)}"]


def _render_list(key: str, children: tuple[MatchLogic, ...], indent: str) -> list[str]:
    lines = [f"{indent}{key}:"]
    for child in children:
        lines.extend(_render_clause(child, indent + "  - "))
    return lines


def insert_entry(text: str, model_id: str, entry: str) -> str:
    """Splice one model-list item into a provider yml at sorted id position.

    Inserts before the first `  - id: ` block whose id sorts greater than
    model_id (plain string sort, matching the target build's sorted(ids)
    check); appends at the end of the file when nothing sorts greater.
    Every other byte of the text is preserved.
    """
    lines = text.splitlines(keepends=True)
    anchor = None
    for index, line in enumerate(lines):
        if not line.startswith("  - id: "):
            continue
        rest = line[len("  - id: ") :].rstrip("\n")
        if rest.startswith('"') and rest.endswith('"'):
            rest = rest[1:-1]
        if rest > model_id:
            anchor = index
            break
    if anchor is None:
        return text + "\n" + entry
    pos = sum(len(line) for line in lines[:anchor])
    return text[:pos] + entry + "\n" + text[pos:]


def build_openrouter_entry(
    slug: str,
    name: str,
    input_mtok: float | None,
    output_mtok: float | None,
    cache_read_mtok: float | None,
) -> str:
    """Build one openrouter.yml models-list item; free models emit `prices: {}`.

    All three price args are already per-megatoken values (the openrouter API
    parse converts); the name is quoted because API names can carry `: `.
    """
    lines = [
        f"  - id: {slug}",
        f'    name: "{name}"',
        "    match:",
        f"      equals: {slug}",
    ]
    if input_mtok is None:
        lines.append("    prices: {}")
    else:
        lines.append("    prices:")
        lines.append(f"      input_mtok: {input_mtok:g}")
        if cache_read_mtok is not None:
            lines.append(f"      cache_read_mtok: {cache_read_mtok:g}")
        if output_mtok is not None:
            lines.append(f"      output_mtok: {output_mtok:g}")
    return "\n".join(lines) + "\n"

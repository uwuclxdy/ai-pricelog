"""the canonical model mapping: cross-source identity, human-maintained.

`data/models.json` links first-party ids to openrouter ids plus display
names, keyed by a canonical id, so consumers can compare prices across
sources. the pipeline never writes it: each run proposes mapping
candidates on the PR body, and the human review lands confirmed entries.
serving tiers stay out (cloudy 2026-08-30: mapping only).
"""

from __future__ import annotations

import json
from pathlib import Path

MODELS_FILE = "data/models.json"


class MappingError(ValueError):
    """the models file failed its schema check; the message names the fix."""


def load_models(path: Path) -> dict[str, dict[str, object]]:
    """The committed mapping, schema-checked; a missing file is empty."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise MappingError(f"models file '{path}': invalid json: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise MappingError(f"models file '{path}': must be an object")
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise MappingError(f"models file '{path}': version must be the integer 1")
    models = data.get("models")
    if not isinstance(models, dict):
        raise MappingError(f"models file '{path}': 'models' must be an object")
    for canonical, entry in models.items():
        if not isinstance(canonical, str) or not canonical:
            raise MappingError(f"models file '{path}': canonical id must be a non-empty string")
        if not isinstance(entry, dict):
            raise MappingError(f"models file '{path}': model '{canonical}' must be an object")
        unknown = set(entry) - {"name", "sources"}
        if unknown:
            raise MappingError(
                f"models file '{path}': model '{canonical}' has unknown key '{sorted(unknown)[0]}'"
            )
        name = entry.get("name")
        if name is not None and (not isinstance(name, str) or not name):
            raise MappingError(
                f"models file '{path}': model '{canonical}' name must be a non-empty string"
            )
        sources = entry.get("sources")
        if not isinstance(sources, dict) or not sources:
            raise MappingError(
                f"models file '{path}': model '{canonical}' sources must be a non-empty object"
            )
        for source, model_id in sources.items():
            if (
                not isinstance(source, str)
                or not source
                or not isinstance(model_id, str)
                or not model_id
            ):
                raise MappingError(
                    f"models file '{path}': model '{canonical}' sources must map"
                    " non-empty source names to non-empty ids"
                )
    return models


def canonical_spelling(model_id: str) -> str:
    """The candidate canonical spelling: an openrouter-style vendor prefix strips."""
    return model_id.split("/", 1)[1] if "/" in model_id else model_id


def hint_candidates(
    stored_rows: list[dict[str, object]],
    mapping: dict[str, dict[str, object]],
    landed_ids: set[tuple[str, str]],
) -> list[tuple[str, str, str]]:
    """(source, model_id, canonical) triples worth a human's mapping decision.

    a landed id hints a canonical when its stripped spelling matches a
    stored id under another source and the pair is not already mapped. the
    pipeline renders the hints on the PR body; a human confirms them into
    models.json during review.
    """
    by_spelling: dict[tuple[str, str], set[str]] = {}
    for row in stored_rows:
        source = row.get("source")
        model_id = row.get("model_id")
        if isinstance(source, str) and isinstance(model_id, str):
            by_spelling.setdefault((canonical_spelling(model_id), source), set()).add(model_id)
    mapped = {
        (source, model_id)
        for entry in mapping.values()
        for source, model_id in entry.get("sources", {}).items()
    }
    hints: list[tuple[str, str, str]] = []
    for source, model_id in sorted(landed_ids):
        spelling = canonical_spelling(model_id)
        if (source, model_id) in mapped:
            continue
        for (stored_spelling, stored_source), _spellings in by_spelling.items():
            if stored_source == source or stored_spelling != spelling:
                continue
            hints.append((source, model_id, spelling))
            break
    return hints

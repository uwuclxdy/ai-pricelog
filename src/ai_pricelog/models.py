"""the canonical model mapping: cross-source identity, human-maintained.

`data/models.json` links first-party ids to openrouter ids plus display
names, keyed by a canonical id, so consumers can compare prices across
sources. v3 adds dated api-alias records under `aliases`: alias id ->
records `{"from": "<date|null>", "to": "<date|null>", "canonical":
"<id>", "citation": "<url>"}`, so a consumer resolves an api alias
against the date it was used. the loader schema-checks the aliases and
returns the models map; a consumer reads the file for the alias table.
the pipeline never writes the file: each run proposes mapping candidates
on the PR body, and the human review lands confirmed entries. serving
tiers stay out (cloudy 2026-08-30: mapping only).
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

MODELS_FILE = "data/models.json"

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


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
    if isinstance(version, bool) or not isinstance(version, int) or version != 3:
        raise MappingError(f"models file '{path}': version must be the integer 3")
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
        normalized: dict[str, list[str]] = {}
        for source, model_ids in sources.items():
            if not isinstance(source, str) or not source:
                raise MappingError(
                    f"models file '{path}': model '{canonical}' sources must map"
                    " non-empty source names to non-empty ids"
                )
            if isinstance(model_ids, str):
                ids = [model_ids]
            elif isinstance(model_ids, list) and model_ids:
                ids = model_ids
            else:
                raise MappingError(
                    f"models file '{path}': model '{canonical}' sources entry"
                    f" '{source}' must map to one id or a non-empty list of ids"
                )
            if not all(isinstance(model_id, str) and model_id for model_id in ids):
                raise MappingError(
                    f"models file '{path}': model '{canonical}' sources entry"
                    f" '{source}' ids must be non-empty strings"
                )
            normalized[source] = ids
        entry["sources"] = normalized
    aliases = data.get("aliases")
    if not isinstance(aliases, dict):
        raise MappingError(f"models file '{path}': 'aliases' must be an object")
    for alias, records in aliases.items():
        if not isinstance(alias, str) or not alias:
            raise MappingError(f"models file '{path}': alias id must be a non-empty string")
        if not isinstance(records, list) or not records:
            raise MappingError(
                f"models file '{path}': alias '{alias}' records must be a non-empty list"
            )
        for record in records:
            if not isinstance(record, dict):
                raise MappingError(
                    f"models file '{path}': alias '{alias}' record must be an object"
                )
            unknown = set(record) - {"from", "to", "canonical", "citation"}
            if unknown:
                raise MappingError(
                    f"models file '{path}': alias '{alias}' record has unknown key"
                    f" '{sorted(unknown)[0]}'"
                )
            canonical = record.get("canonical")
            if not isinstance(canonical, str) or canonical not in models:
                raise MappingError(
                    f"models file '{path}': alias '{alias}' record canonical must"
                    " name a model in the file"
                )
            for field in ("from", "to"):
                if field not in record:
                    raise MappingError(
                        f"models file '{path}': alias '{alias}' record is missing '{field}'"
                    )
                value = record[field]
                if value is None:
                    continue
                if not isinstance(value, str) or _DATE.fullmatch(value) is None:
                    raise MappingError(
                        f"models file '{path}': alias '{alias}' record '{field}'"
                        " must be a YYYY-MM-DD date or null"
                    )
                try:
                    date.fromisoformat(value)
                except ValueError:
                    raise MappingError(
                        f"models file '{path}': alias '{alias}' record '{field}'"
                        " must be a YYYY-MM-DD date or null"
                    ) from None
            start, end = record["from"], record["to"]
            if start is not None and end is not None and start >= end:
                raise MappingError(
                    f"models file '{path}': alias '{alias}' record 'from' must be before 'to'"
                )
            citation = record.get("citation")
            if not isinstance(citation, str) or not citation.startswith(("http://", "https://")):
                raise MappingError(
                    f"models file '{path}': alias '{alias}' record citation must be an http(s) url"
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
    mapped: set[tuple[str, str]] = set()
    for entry in mapping.values():
        for source, model_ids in entry.get("sources", {}).items():
            if not isinstance(model_ids, list):
                model_ids = [model_ids]
            for model_id in model_ids:
                if isinstance(model_id, str):
                    mapped.add((source, model_id))
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

"""the model catalog: cross-source identity, human-maintained plus pipeline seeds.

`data/catalog/models.json` links per-source spellings to one canonical id,
with a `vendor` (who made the model) and a `curated` flag (false on a
pipeline-seeded entry, true once a human confirms it or merges twins). the
dated api-alias records split into `data/catalog/aliases.json`: alias id ->
records `{"from": "<date|null>", "to": "<date|null>", "canonical": "<id>",
"citation": "<url>"}`, so a consumer resolves an api alias against the date
it was used. the pipeline seeds one `curated:false` entry per store key it
cannot map; the human review merges twins and confirms.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path

from ai_pricelog.store import _atomic_write

CATALOG_VERSION = 4
MODELS_FILE = "data/catalog/models.json"
ALIASES_FILE = "data/catalog/aliases.json"

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class MappingError(ValueError):
    """the models file failed its schema check; the message names the fix."""


def load_models(path: Path, allow_missing: bool = True) -> dict[str, dict[str, object]]:
    """The committed model catalog, schema-checked.

    A missing file reads as empty when `allow_missing`; the production read
    passes False so a checkout with no catalog fails instead of seeding over it.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if allow_missing:
            return {}
        raise MappingError(f"models file '{path}': missing") from None
    except json.JSONDecodeError as exc:
        raise MappingError(f"models file '{path}': invalid json: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise MappingError(f"models file '{path}': must be an object")
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version != CATALOG_VERSION:
        raise MappingError(f"models file '{path}': version must be the integer {CATALOG_VERSION}")
    models = data.get("models")
    if not isinstance(models, dict):
        raise MappingError(f"models file '{path}': 'models' must be an object")
    for canonical, entry in models.items():
        if not isinstance(canonical, str) or not canonical:
            raise MappingError(f"models file '{path}': canonical id must be a non-empty string")
        if not isinstance(entry, dict):
            raise MappingError(f"models file '{path}': model '{canonical}' must be an object")
        unknown = set(entry) - {"name", "vendor", "curated", "sources"}
        if unknown:
            raise MappingError(
                f"models file '{path}': model '{canonical}' has unknown key '{sorted(unknown)[0]}'"
            )
        name = entry.get("name")
        if name is not None and (not isinstance(name, str) or not name):
            raise MappingError(
                f"models file '{path}': model '{canonical}' name must be a non-empty string"
            )
        vendor = entry.get("vendor")
        if vendor is not None and (not isinstance(vendor, str) or not vendor):
            raise MappingError(
                f"models file '{path}': model '{canonical}' vendor must be"
                " a non-empty string or null"
            )
        if "vendor" not in entry:
            raise MappingError(f"models file '{path}': model '{canonical}' is missing 'vendor'")
        curated = entry.get("curated")
        if not isinstance(curated, bool):
            raise MappingError(
                f"models file '{path}': model '{canonical}' curated must be a boolean"
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
    return models


def load_aliases(
    path: Path, models: Mapping[str, object] | None
) -> dict[str, list[dict[str, object]]]:
    """The committed api-alias records, schema-checked; a missing file is empty.

    `models` is the models map from load_models; every record's `canonical`
    must name one of its keys (the invariant spans the two files). pass None
    only for a shape check that does not hold the models map.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise MappingError(f"aliases file '{path}': invalid json: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise MappingError(f"aliases file '{path}': must be an object")
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version != CATALOG_VERSION:
        raise MappingError(f"aliases file '{path}': version must be the integer {CATALOG_VERSION}")
    aliases = data.get("aliases")
    if not isinstance(aliases, dict):
        raise MappingError(f"aliases file '{path}': 'aliases' must be an object")
    for alias, records in aliases.items():
        if not isinstance(alias, str) or not alias:
            raise MappingError(f"aliases file '{path}': alias id must be a non-empty string")
        if not isinstance(records, list) or not records:
            raise MappingError(
                f"aliases file '{path}': alias '{alias}' records must be a non-empty list"
            )
        for record in records:
            if not isinstance(record, dict):
                raise MappingError(
                    f"aliases file '{path}': alias '{alias}' record must be an object"
                )
            unknown = set(record) - {"from", "to", "canonical", "citation"}
            if unknown:
                raise MappingError(
                    f"aliases file '{path}': alias '{alias}' record has unknown key"
                    f" '{sorted(unknown)[0]}'"
                )
            canonical = record.get("canonical")
            if not isinstance(canonical, str) or not canonical:
                raise MappingError(
                    f"aliases file '{path}': alias '{alias}' record canonical must"
                    " be a non-empty string"
                )
            if models is not None and canonical not in models:
                raise MappingError(
                    f"aliases file '{path}': alias '{alias}' record canonical must"
                    " name a model in the file"
                )
            for field in ("from", "to"):
                if field not in record:
                    raise MappingError(
                        f"aliases file '{path}': alias '{alias}' record is missing '{field}'"
                    )
                value = record[field]
                if value is None:
                    continue
                if not isinstance(value, str) or _DATE.fullmatch(value) is None:
                    raise MappingError(
                        f"aliases file '{path}': alias '{alias}' record '{field}'"
                        " must be a YYYY-MM-DD date or null"
                    )
                try:
                    date.fromisoformat(value)
                except ValueError:
                    raise MappingError(
                        f"aliases file '{path}': alias '{alias}' record '{field}'"
                        " must be a YYYY-MM-DD date or null"
                    ) from None
            start, end = record["from"], record["to"]
            if start is not None and end is not None and start >= end:
                raise MappingError(
                    f"aliases file '{path}': alias '{alias}' record 'from' must be before 'to'"
                )
            citation = record.get("citation")
            if not isinstance(citation, str) or not citation.startswith(("http://", "https://")):
                raise MappingError(
                    f"aliases file '{path}': alias '{alias}' record citation must be an http(s) url"
                )
    return aliases


# an explicit family token -> maker table, census-checked against the 191
# curated entries and each provider's published vendor prefix. a token that
# is not here yields null: a wrong vendor is worse than a missing one.
FAMILY_MAKER = {
    "claude": "anthropic",
    "command": "cohere",
    "codestral": "mistral",
    "deepseek": "deepseek",
    "ernie": "baidu",
    "gemini": "google",
    "gemma": "google",
    "glm": "zai",
    "gpt": "openai",
    "granite": "ibm",
    "grok": "xai",
    "hy3": "tencent",
    "inkling": "thinkingmachines",
    "kimi": "moonshot",
    "ling": "inclusionai",
    "llama": "meta",
    "mimo": "xiaomi",
    "minimax": "minimax",
    "mistral": "mistral",
    "muse": "meta",
    "mythomax": "gryphe",
    "nemotron": "nvidia",
    "o1": "openai",
    "o3": "openai",
    "o4": "openai",
    "phi": "microsoft",
    "pixtral": "mistral",
    "qwen": "alibaba",
    "sonar": "perplexity",
    "step": "stepfun",
    "wizardlm": "microsoft",
}


def _family_vendor(model_id: str) -> str | None:
    """The maker named by one family token in the id, or null.

    The id splits on non-alphanumeric delimiters and each token checks against
    FAMILY_MAKER by exact equality. exactly one distinct maker matches; zero
    tokens and two tokens naming different makers both yield null, so a token
    absent from the table never guesses.
    """
    makers = {
        FAMILY_MAKER[token]
        for token in re.split(r"[^a-z0-9]+", model_id.lower())
        if token in FAMILY_MAKER
    }
    return makers.pop() if len(makers) == 1 else None


def derive_vendor(
    model_id: str, provider_vendor: str | None, provider_kind: str | None
) -> str | None:
    """The maker of a model id from its shape; null when the shape names none.

    The five arms, in order: a 3-segment `@cf/<vendor>/<model>` id yields
    segment 1; a 2-segment `<vendor>/<model>` id yields segment 0; a family
    token in the id names a maker; an unprefixed id on a first-party source
    yields that provider's vendor; anything else is null. near-miss vendor
    slugs stay un-unified: that twin merge is the human's, and `curated:false`
    marks the entry as pending.
    """
    parts = model_id.split("/")
    if len(parts) == 3 and parts[0] == "@cf" and parts[1]:
        return parts[1].lower()
    if len(parts) == 2 and parts[0]:
        return parts[0].lower()
    family = _family_vendor(model_id)
    if family is not None:
        return family
    if (
        len(parts) == 1
        and provider_kind == "first_party"
        and isinstance(provider_vendor, str)
        and provider_vendor
    ):
        return provider_vendor.lower()
    return None


def is_resold(entry: Mapping[str, object], provider: Mapping[str, object]) -> bool:
    """Whether a provider serving a catalog entry resells it.

    Plan decision 29: a row is resold when the model's maker differs from the
    provider's vendor; a provider carrying no vendor resells everything, and a
    model whose maker the catalog cannot name is nobody's first-party row. A
    bare inequality would read those two nulls as a match.
    """
    provider_vendor = provider.get("vendor")
    return provider_vendor is None or entry.get("vendor") != provider_vendor


def seed_entries(
    keys: Iterable[tuple[str, str]],
    mapping: dict[str, dict[str, object]],
    providers: Mapping[str, tuple[str | None, str | None]],
) -> dict[str, dict[str, object]]:
    """One `curated:false` entry per store key no existing entry covers.

    The canonical id is `<source>/<model_id>`: the store key pair is unique,
    and a migrated canonical id never carries a `/`, so the seeded id cannot
    collide with an existing or another seeded one. `providers` maps a source
    to its `(vendor, kind)` pair for derive_vendor.
    """
    covered: set[tuple[str, str]] = set()
    for entry in mapping.values():
        for source, model_ids in entry.get("sources", {}).items():
            if isinstance(model_ids, str):
                model_ids = [model_ids]
            for model_id in model_ids:
                if isinstance(model_id, str):
                    covered.add((source, model_id))
    seeded: dict[str, dict[str, object]] = {}
    for source, model_id in sorted(keys):
        if (source, model_id) in covered:
            continue
        vendor, kind = providers.get(source, (None, None))
        canonical = f"{source}/{model_id}"
        if canonical in mapping:
            raise MappingError(
                f"seed '{canonical}' collides with an existing catalog entry;"
                " a store key no entry covers must not reuse a canonical id"
            )
        seeded[canonical] = {
            "vendor": derive_vendor(model_id, vendor, kind),
            "curated": False,
            "sources": {source: [model_id]},
        }
    return seeded


def save_models(models_map: Mapping[str, dict[str, object]], path: Path) -> None:
    """Write the model catalog in the committed sorted, 2-space shape."""
    _atomic_write(
        json.dumps(
            {"version": CATALOG_VERSION, "models": models_map},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        path,
    )

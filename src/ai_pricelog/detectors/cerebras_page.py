"""detect cerebras model ids from the public models api.

https://api.cerebras.ai/public/v1/models is keyless and serves the model
list as json (an openai-style object with a data list; an openrouter
format= variant also exists, the plain shape is watched). every entry
counts, priced or not: an unpriced entry scrapes to None and
re-candidates next run (decision 8). an entry without an id string or
with a non-object pricing is additive drift: detection skips it with a
warning (plan #22); invalid json, a non-object root, or no model entries
still raise.
"""

from __future__ import annotations

import json
import logging

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_text

log = logging.getLogger(__name__)


def payload_entries(text: str, url: str) -> list[object]:
    """the api's data list; invalid json or a non-object root is a shape break."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FetchError(f"fetch for {url}: invalid json: {exc.msg}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise FetchError(f"root must be an object with a 'data' list on {url}")
    return data["data"]


def _entry_id(entry: object, url: str) -> str:
    """the entry's id; an entry outside the shape is a FetchError."""
    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
        raise FetchError(f"model entry without an id string on {url}")
    return entry["id"]


def _entry_pricing(entry: dict, url: str) -> dict | None:
    """the entry's pricing object; a non-object pricing is a FetchError."""
    pricing = entry.get("pricing")
    if pricing is not None and not isinstance(pricing, dict):
        raise FetchError(f"model entry {entry['id']!r} on {url}: pricing must be an object")
    return pricing


def detect(cfg: ProviderCfg) -> list[str]:
    entries = payload_entries(fetch_text(cfg.detector_url), cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        try:
            model_id = _entry_id(entry, cfg.detector_url)
            _entry_pricing(entry, cfg.detector_url)
        except FetchError as exc:
            log.warning("detect skip for %s: %s", cfg.key, exc)
            continue
        if model_id not in seen:
            seen.add(model_id)
            ids.append(model_id)
    if not ids:
        raise FetchError(f"no model entries on {cfg.detector_url}")
    return ids

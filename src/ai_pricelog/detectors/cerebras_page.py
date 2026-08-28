"""detect cerebras model ids from the public models api.

https://api.cerebras.ai/public/v1/models is keyless and serves the model
list as json (an openai-style object with a data list; an openrouter
format= variant also exists, the plain shape is watched). every entry
counts, priced or not: an unpriced entry scrapes to None and
re-candidates next run (decision 8).
"""

from __future__ import annotations

import json

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_text


def payload_entries(text: str, url: str) -> list[dict]:
    """the api's data entries; anything else on the wire is a shape break."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FetchError(f"fetch for {url}: invalid json: {exc.msg}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise FetchError(f"root must be an object with a 'data' list on {url}")
    entries: list[dict] = []
    for entry in data["data"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise FetchError(f"model entry without an id string on {url}")
        pricing = entry.get("pricing")
        if pricing is not None and not isinstance(pricing, dict):
            raise FetchError(f"model entry {entry['id']!r} on {url}: pricing must be an object")
        entries.append(entry)
    return entries


def detect(cfg: ProviderCfg) -> list[str]:
    entries = payload_entries(fetch_text(cfg.detector_url), cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if entry["id"] not in seen:
            seen.add(entry["id"])
            ids.append(entry["id"])
    if not ids:
        raise FetchError(f"no model entries on {cfg.detector_url}")
    return ids

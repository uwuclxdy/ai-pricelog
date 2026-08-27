"""detect openai model ids from the platform pricing page.

https://platform.openai.com/docs/pricing serves the per-token chat tables as
astro island props: every astro-island with
component-export="TextTokenPricingTables" carries a tier ("standard" |
"batch" | "flex" | "fast") and the model rows as a json attribute (html-
escaped on the wire, decoded by the parser). each row is [model, input,
cached read, cache write?, output], dollars per 1M tokens. the standard
tier is watched: it is the base rate the other tiers discount or premium
on. five-column rows carry the cache-write rate in the middle column (the
page's own "Cache writes" heading; measured at 1.25x the input on every
five-column row in the 2026-08-27 fixture); the index has no slot for it
and drops it here. model names may carry a page annotation
("gpt-5.5 (<272K context length)"); the annotation is stripped and the
bare name is the id. a page without the standard island, with unparseable
props, or with a row outside this shape is a parse failure (FetchError).
"""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup, Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup

_NAME_PATTERN = re.compile(r"^(?P<id>[a-z0-9][a-z0-9.-]*)(?: \(.*\))?$")
_ROW_LENGTHS = (4, 5)


def _decode(value):
    """decode the astro island tuple format: [0, x] scalar, [1, [...]] list."""
    if (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], int)
        and value[0] in (0, 1)
    ):
        if value[0] == 1:
            return [_decode(item) for item in value[1]]
        return value[1]
    if isinstance(value, dict):
        return {key: _decode(val) for key, val in value.items()}
    return value


def _island_props(island: Tag, url: str) -> dict:
    """the island's props as a decoded dict; unreadable props are a FetchError."""
    props = island.get("props") or ""
    try:
        data = _decode(json.loads(props))
    except (json.JSONDecodeError, TypeError) as exc:
        raise FetchError(f"unparseable pricing island props on {url}: {exc}") from exc
    if not isinstance(data, dict):
        raise FetchError(f"pricing island props are not a table object on {url}")
    return data


def _standard_rows(soup: BeautifulSoup, url: str) -> list[list]:
    """the standard tier's rows, [model, input, cached read, cache write?, output] each."""
    for island in soup.find_all("astro-island"):
        if island.get("component-export") != "TextTokenPricingTables":
            continue
        data = _island_props(island, url)
        if data.get("tier") != "standard":
            continue
        rows = data.get("rows")
        if not isinstance(rows, list) or not rows:
            raise FetchError(f"standard pricing island without rows on {url}")
        return rows
    raise FetchError(f"no standard pricing table on {url}")


def _row_id(row, url: str) -> str:
    """the row's model id; a row outside the shape is a FetchError."""
    if not isinstance(row, list) or len(row) not in _ROW_LENGTHS or not isinstance(row[0], str):
        raise FetchError(f"row outside the pricing shape on {url}: {row!r}")
    match = _NAME_PATTERN.fullmatch(row[0])
    if match is None:
        raise FetchError(f"model name {row[0]!r} outside the id shape on {url}")
    return match.group("id")


def detect(cfg: ProviderCfg) -> list[str]:
    """current standard-tier model ids, page order, deduped."""
    soup = fetch_soup(cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    for row in _standard_rows(soup, cfg.detector_url):
        model_id = _row_id(row, cfg.detector_url)
        if model_id not in seen:
            seen.add(model_id)
            ids.append(model_id)
    if not ids:
        raise FetchError(f"no model rows in the standard pricing table on {cfg.detector_url}")
    return ids

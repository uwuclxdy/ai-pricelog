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
five-column row in the 2026-08-27 fixture); the scraper stores it as the
default cache-write tier. model names may carry a page annotation
("gpt-5.5 (<272K context length)"); the annotation is stripped and the
bare name is the id. rows outside this shape and names outside the id
shape are additive drift: detection skips them with a warning (plan #22),
and a page without the standard island, with unparseable props, or with no
model rows still raises.

the image-generation models sit in their own island shape: the content
switcher root data-content-switcher-id="multimodal-image-pricing" holds
standard and batch panes, and the standard pane's astro-island
(component-export="GroupedPricingTable") carries groups of {model, rows}
where each row is [label, input, cached input, output] with label "Image"
or "Text". the batch pane repeats the ids at discounted rates, so the
pane's DOM containment picks the island, never its position: the video
and specialized sections carry GroupedPricingTable islands of their own.
detection appends the image ids after the chat ids, page order, deduped
(they also appear in hiddenModels, which is why groups alone carry them).
a missing image section or standard pane is additive drift — a warning,
and the chat ids stand — while an island with unparseable props or no
groups still raises.
"""

from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup, Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup

log = logging.getLogger(__name__)

_NAME_PATTERN = re.compile(r"^(?P<id>[a-z0-9][a-z0-9.-]*)(?: \(.*\))?$")
_ROW_LENGTHS = (4, 5)


def _decode(value):
    """decode the astro island tuple format: [0, x] scalar, [1, [...]] list.

    a scalar can be a dict whose own values are still tuple-wrapped (the
    image tables pass group objects as [0, {...}] scalars), so the unwrap
    recurses instead of returning the payload raw.
    """
    if (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], int)
        and value[0] in (0, 1)
    ):
        if value[0] == 1:
            return [_decode(item) for item in value[1]]
        return _decode(value[1])
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


_IMAGE_SWITCHER_ID = "multimodal-image-pricing"


def _image_standard_groups(soup: BeautifulSoup, url: str) -> list[dict] | None:
    """the image-generation standard pane's group dicts, or None when the
    section or its standard pane is missing.

    the pane's DOM containment picks the island: the video and specialized
    sections carry GroupedPricingTable islands of their own, and the batch
    pane repeats the image ids at discounted rates.
    """
    root = soup.find(attrs={"data-content-switcher-id": _IMAGE_SWITCHER_ID})
    if root is None:
        return None
    pane = root.find(attrs={"data-content-switcher-pane": "true", "data-value": "standard"})
    if pane is None:
        return None
    islands = pane.find_all("astro-island", attrs={"component-export": "GroupedPricingTable"})
    if not islands:
        return None
    data = _island_props(islands[0], url)
    groups = data.get("groups")
    if not isinstance(groups, list) or not groups:
        raise FetchError(f"image pricing island without groups on {url}")
    return groups


def _group_id(group, url: str) -> str:
    """the group's model id; a group outside the shape is a FetchError."""
    if not isinstance(group, dict) or not isinstance(group.get("model"), str):
        raise FetchError(f"group outside the group shape on {url}: {group!r}")
    match = _NAME_PATTERN.fullmatch(group["model"])
    if match is None:
        raise FetchError(f"model name {group['model']!r} outside the id shape on {url}")
    return match.group("id")


def detect(cfg: ProviderCfg) -> list[str]:
    """current standard-tier model ids, page order, deduped."""
    soup = fetch_soup(cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    for row in _standard_rows(soup, cfg.detector_url):
        try:
            model_id = _row_id(row, cfg.detector_url)
        except FetchError as exc:
            log.warning("detect skip for %s: %s", cfg.key, exc)
            continue
        if model_id not in seen:
            seen.add(model_id)
            ids.append(model_id)
    groups = _image_standard_groups(soup, cfg.detector_url)
    if groups is None:
        log.warning(
            "detect for %s: no image-generation standard pane on %s; keeping the chat ids",
            cfg.key,
            cfg.detector_url,
        )
    else:
        for group in groups:
            try:
                model_id = _group_id(group, cfg.detector_url)
            except FetchError as exc:
                log.warning("detect skip for %s: %s", cfg.key, exc)
                continue
            if model_id not in seen:
                seen.add(model_id)
                ids.append(model_id)
    if not ids:
        raise FetchError(f"no model rows in the standard pricing table on {cfg.detector_url}")
    return ids

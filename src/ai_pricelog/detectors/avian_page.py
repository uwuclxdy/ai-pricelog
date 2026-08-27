"""detect model ids on the avian pricing page.

reads https://www.avian.io/pricing (static server-rendered html). models are
per-vendor cards inside the ``#avModelGrid`` div, one ``.av-model-card`` per
model: ``.av-model-label`` (name), ``.av-mp`` price blocks, ``.av-model-meta``
(context + max output). only cards inside the grid are models; the grid's
sibling Dedicated Deployments note has no per-token prices and is never
detected.

ids are the lowercase-hyphen slug of the card label: lowercase, dots kept,
every other non-alphanumeric run collapsed to a single ``-``, edges trimmed
("MiMo-V2.5 Small" -> "mimo-v2.5-small", "GLM-4.7" -> "glm-4.7",
"DeepSeek V3.2 (Legacy)" -> "deepseek-v3.2-legacy"). this slug is the entry
id for new models. every labeled card in the grid is detected, priced or not:
an unpriced card scrapes to None and the pipeline retries next run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup

_GRID_ID = "avModelGrid"
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]*$")


@dataclass(frozen=True)
class _Card:
    """one model card: page label, meta line, price blocks by label name."""

    label: str
    meta: str
    prices: dict[str, str]


def _slug(name: str) -> str:
    """lowercase-hyphen slug of a page spelling; the new-model entry id."""
    return re.sub(r"[^a-z0-9.]+", "-", name.lower()).strip("-")


def _cards(soup, url: str) -> list[_Card]:
    """model cards inside the pricing grid, page order."""
    grid = soup.find(id=_GRID_ID)
    if grid is None:
        raise FetchError(f"no #{_GRID_ID} model grid on {url}")
    cards: list[_Card] = []
    for card in grid.find_all(class_="av-model-card", recursive=False):
        label_el = card.find(class_="av-model-label")
        if label_el is None:
            continue
        label = label_el.get_text(" ", strip=True)
        if not _ID_PATTERN.fullmatch(_slug(label)):
            continue
        prices: dict[str, str] = {}
        for block in card.find_all(class_="av-mp"):
            name_el = block.find(class_="av-mp-label")
            value_el = block.find(class_="av-mp-val")
            if name_el is None or value_el is None:
                continue
            prices[name_el.get_text(" ", strip=True)] = value_el.get_text(" ", strip=True)
        meta_el = card.find(class_="av-model-meta")
        meta = meta_el.get_text(" ", strip=True) if meta_el is not None else ""
        cards.append(_Card(label=label, meta=meta, prices=prices))
    if not cards:
        raise FetchError(f"no model cards in #{_GRID_ID} on {url}")
    return cards


def detect(cfg: ProviderCfg) -> list[str]:
    """current model slugs, page order, deduped."""
    ids: list[str] = []
    seen: set[str] = set()
    for card in _cards(fetch_soup(cfg.detector_url), cfg.detector_url):
        slug = _slug(card.label)
        if slug not in seen:
            seen.add(slug)
            ids.append(slug)
    return ids

"""detect model ids on the baseten pricing page.

the page (https://www.baseten.co/pricing) serves the "Model APIs" section
statically: a grid whose header cells read Model | Input | Cache Input |
Output, then one grid row per token-priced model. the id is the model's
/library/ path slug (the name cell links to /library/<slug>/): the stable
spelling on baseten, unlike the app.baseten.co "Try Model API" link which
embeds an org path and the display name. every model-row cell renders twice
(desktop and mobile duplicates); only the desktop wrapper is read, so a row
yields one id. the other grid tables on the page (dedicated deployments,
training) price GPU hours and carry a different header; the footer's
"Popular models" links sit outside the table. a row whose name cell is
malformed (odd desktop renders, a missing or unexpected /library/ link,
an out-of-charset slug) is additive drift: detection skips it with a
warning (plan #22), and the header pins after folding case, whitespace,
and &/and. a page without the Model APIs table, model rows, or any
usable ids is a parse failure (FetchError).
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup, Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup, fold_heading

log = logging.getLogger(__name__)

_HEADER_CELLS = ["Model", "Input", "Cache Input", "Output"]
_FOLDED_HEADER_CELLS = tuple(fold_heading(cell) for cell in _HEADER_CELLS)
_LIBRARY_HREF_RE = re.compile(r"^/library/([^/]+)/?$")


def detect(cfg: ProviderCfg) -> list[str]:
    rows = _model_rows(fetch_soup(cfg.detector_url), cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    for row in rows:
        try:
            model_id = _model_id(row[0], cfg.detector_url)
        except FetchError as exc:
            log.warning("detect skip for %s: %s", cfg.key, exc)
            continue
        if model_id not in seen:
            seen.add(model_id)
            ids.append(model_id)
    if not ids:
        raise FetchError(f"no model ids in the Model APIs table on {cfg.detector_url}")
    return ids


def _model_rows(soup: BeautifulSoup, url: str) -> list[list[Tag]]:
    """the Model | Input | Cache Input | Output grid rows; missing -> FetchError."""
    for grid in soup.select("div.grid"):
        cells = [cell for cell in grid.find_all("div", recursive=False)]
        if tuple(fold_heading(cell.get_text(" ", strip=True)) for cell in cells) != (
            _FOLDED_HEADER_CELLS
        ):
            continue
        rows = [
            [cell for cell in row.find_all("div", recursive=False)]
            for row in grid.find_next_siblings("div")
            if "grid" in (row.get("class") or [])
        ]
        if not rows:
            raise FetchError(f"no model rows on {url}")
        return rows
    raise FetchError(f"no Model APIs pricing table on {url}")


def _desktop(cell: Tag, url: str) -> Tag:
    """the desktop render of a cell; not exactly one -> FetchError."""
    wrappers = [
        child
        for child in cell.find_all("div", recursive=False)
        if "hidden" in (child.get("class") or []) and "md:flex" in (child.get("class") or [])
    ]
    if len(wrappers) != 1:
        raise FetchError(
            f"malformed pricing cell on {url}: {len(wrappers)} desktop renders, want 1"
        )
    return wrappers[0]


_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _model_id(name_cell: Tag, url: str) -> str:
    """the /library/ slug of a name cell; a missing, odd, or out-of-charset
    link is a FetchError, so a reshaped slug cannot silently alias."""
    anchors = _desktop(name_cell, url).find_all("a", href=True)
    if len(anchors) != 1:
        raise FetchError(f"malformed model name cell on {url}: {len(anchors)} links, want 1")
    match = _LIBRARY_HREF_RE.match(anchors[0]["href"])
    if match is None:
        raise FetchError(f"unexpected model link {anchors[0]['href']!r} on {url}")
    slug = match.group(1).lower()
    if not _ID_PATTERN.fullmatch(slug):
        raise FetchError(f"model slug {slug!r} outside the id charset on {url}")
    return slug

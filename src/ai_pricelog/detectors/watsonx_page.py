"""detect per-token model ids on the ibm watsonx pricing page.

https://www.ibm.com/products/watsonx-ai/pricing serves the per-model tables
as c4d-pricing-table web components. of the eight components, four are
per-model token tables (header columns Model Name | Model Provider | Pay as
you go | a hosting/context column, one row per model); the plan tables and
the embeddings tables (no Model Provider column) are excluded by shape. the
row-label cell is the model name, sometimes suffixed "New". ids are the
names slugged: lowercase, the "New" suffix stripped, runs of
non-alphanumerics -> dashes, charset-checked against the stored-id pattern.
rows whose pay-as-you-go cell carries no USD amount ("Not available") are
skipped: there is nothing to price. a page with no per-model token table is
a parse failure (FetchError).
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup

_AMOUNT_RE = re.compile(r"USD ([\d,]+(?:\.\d+)?)")
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._/-]*$")
_NEW_SUFFIX_RE = re.compile(r"\s+New$")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_CELL_TAGS = ("c4d-pricing-table-cell", "c4d-pricing-table-header-cell")


def detect(cfg: ProviderCfg) -> list[str]:
    """current priced model ids, page order, deduped."""
    soup = fetch_soup(cfg.detector_url)
    comps = _per_model_comps(soup, cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    for comp, headers, price_col in comps:
        for cells in _comp_rows(comp):
            if not cells:
                continue
            if len(cells) < len(headers):
                raise FetchError(f"malformed pricing row on {cfg.detector_url}")
            if not _AMOUNT_RE.search(cells[price_col]):
                continue
            normalized = _normalize_id(cells[0])
            if _ID_PATTERN.fullmatch(normalized) and normalized not in seen:
                seen.add(normalized)
                ids.append(normalized)
    if not ids:
        raise FetchError(f"no model ids in the per-token model tables on {cfg.detector_url}")

    return ids


def _per_model_comps(soup: BeautifulSoup, url: str) -> list[tuple[Tag, list[str], int]]:
    """(component, header texts, pay-as-you-go column) per per-model token table.

    components without a Model Name | Model Provider header are the plan and
    embeddings tables, out of scope. none left -> FetchError.
    """
    comps: list[tuple[Tag, list[str], int]] = []
    for comp in soup.find_all("c4d-pricing-table"):
        headers = _header_cells(comp)
        if not any(h.startswith("Model Name") for h in headers):
            continue
        if not any(h.startswith("Model Provider") for h in headers):
            continue
        price_col = next((i for i, h in enumerate(headers) if h.startswith("Pay as you go")), -1)
        if price_col < 0:
            raise FetchError(f"per-model table without a pay-as-you-go column on {url}")
        comps.append((comp, headers, price_col))
    if not comps:
        raise FetchError(f"no per-token model table on {url}")
    return comps


def _header_cells(comp: Tag) -> list[str]:
    head = comp.find("c4d-pricing-table-head")
    row = head.find("c4d-pricing-table-header-row") if head else None
    return (
        [cell.get_text(" ", strip=True) for cell in row.find_all(_CELL_TAGS, recursive=False)]
        if row
        else []
    )


def _comp_rows(comp: Tag) -> list[list[str]]:
    body = comp.find("c4d-pricing-table-body")
    return (
        [
            [cell.get_text(" ", strip=True) for cell in row.find_all(_CELL_TAGS, recursive=False)]
            for row in body.find_all("c4d-pricing-table-row")
        ]
        if body
        else []
    )


def _normalize_id(name: str) -> str:
    return _NON_ALNUM_RE.sub("-", _NEW_SUFFIX_RE.sub("", name).lower()).strip("-")

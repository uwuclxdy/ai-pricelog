"""detect digitalocean serverless model ids on the docs pricing page.

the page (https://docs.digitalocean.com/products/inference/details/pricing/)
serves the per-model tables statically, one per provider group. the
token-priced tables carry the header Model | Serverless Inference, or
Provider | Model | Serverless Inference for digitalocean-hosted models,
matched after folding case, whitespace, and &/and (web.fold_heading); a
row is in scope when its Serverless Inference cell holds a
span.gen-ai-pricing-grid with per-1M token rates. the fal and
digitalocean-hosted image/audio/video rows (per megapixel, per compute
second, per video, per image, per character) carry no grid and are
skipped; grid-carrying image models (the gpt-image rows) are skipped by
name. the other tables on the page (GPU, embeddings, reranking,
guardrails) have different headers and are out of scope. ids are the model
name taken from its link when present ("MiniMax M2.5 (Public Preview)" ->
"minimax-m2.5"), normalized to the index spelling: lowercase, runs of
non-alphanumerics (dots kept) -> dashes; names that do not fit the stored
id charset are skipped. page order across tables, deduped. a page with no
such table, or with no ids, is a parse failure (FetchError).
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup, fold_heading

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._/-]*$")
_IMAGE_MODEL_RE = re.compile(r"\bimage\b", re.IGNORECASE)
_MODEL_HEADERS = (
    ("model", "serverless inference"),
    ("provider", "model", "serverless inference"),
)
_FOLDED_MODEL_HEADERS = tuple(
    tuple(fold_heading(cell) for cell in headers) for headers in _MODEL_HEADERS
)
_GRID_CLASS = "gen-ai-pricing-grid"


def _model_tables(soup: BeautifulSoup) -> list[tuple[Tag, int]]:
    """top-level per-model serverless tables as (table, model column)."""
    tables: list[tuple[Tag, int]] = []
    for table in soup.find_all("table"):
        if table.find_parent("table") is not None:
            continue
        thead = table.find("thead")
        if thead is None:
            continue
        headers = tuple(fold_heading(th.get_text(" ", strip=True)) for th in thead.find_all("th"))
        if headers in _FOLDED_MODEL_HEADERS:
            tables.append((table, len(headers) - 2))
    return tables


def _table_rows(table: Tag) -> list[list[Tag]]:
    """the table's own rows as td cell lists (nested tables excluded)."""
    return [
        row.find_all("td", recursive=False)
        for row in table.find_all("tr")
        if row.find_parent("table") is table
    ]


def _model_name(cell: Tag) -> str:
    link = cell.find("a")
    return link.get_text(" ", strip=True) if link else cell.get_text(" ", strip=True)


def _normalize_id(name: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", name.lower()).strip("-")


def _priced_rows(soup: BeautifulSoup, url: str) -> list[tuple[str, Tag]]:
    """(normalized model name, pricing grid) per in-scope row, page order.

    a row without a pricing grid is not token-priced and is out of scope; a
    page without any per-model serverless table is a parse failure.
    """
    tables = _model_tables(soup)
    if not tables:
        raise FetchError(f"no per-model serverless pricing table on {url}")
    rows: list[tuple[str, Tag]] = []
    for table, model_col in tables:
        for cells in _table_rows(table):
            if len(cells) <= model_col + 1:
                continue
            grid = cells[model_col + 1].find("span", class_=_GRID_CLASS)
            if grid is None:
                continue
            name = _model_name(cells[model_col])
            if _IMAGE_MODEL_RE.search(name):
                continue
            rows.append((_normalize_id(name), grid))
    return rows


def detect(cfg: ProviderCfg) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for name, _ in _priced_rows(fetch_soup(cfg.detector_url), cfg.detector_url):
        if _ID_PATTERN.fullmatch(name) and name not in seen:
            seen.add(name)
            ids.append(name)
    if not ids:
        raise FetchError(f"no model ids on {cfg.detector_url}")
    return ids

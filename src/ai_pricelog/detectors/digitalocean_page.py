"""detect digitalocean serverless model ids on the docs pricing page.

the page (https://docs.digitalocean.com/products/inference/details/pricing/)
serves the per-model tables statically, one per provider group. the
token-priced tables carry the header Model | Serverless Inference, or
Provider | Model | Serverless Inference for provider-hosted models,
matched by folded-cell prefix (case, whitespace, &/and folded): the live
header appends "USD per 1M tokens unless noted" since 2026-09-15. a row
is in scope when its Serverless Inference cell holds a
span.gen-ai-pricing-matrix (role=table): a header row naming the columns
(Processing mode, Prompt length, Input, Output, Cache write (5m), Cache
write (1h), Cache read) plus one data row per processing mode. the fal
and digitalocean-hosted image/audio/video rows (per megapixel, per
compute second, per video, per image, per character) carry no matrix and
are skipped; matrix-carrying image models (the gpt-image rows) are
skipped by name. ids are the model name taken from its link when present
("MiniMax M2.5 (Public Preview)" -> "minimax-m2.5"), normalized to the
index spelling: lowercase, runs of non-alphanumerics (dots kept) ->
dashes; a name or mode that does not fit the stored id charset (a mode
label normalizing to nothing included) is skipped with a warning
(additive drift, plan #22). a non-Standard processing mode row prices
its own stored id, the base id with the mode's slug appended ("Fast
Mode" -> "claude-opus-5-fast-mode", "Flex Mode" -> "gpt-5-flex-mode").
page order across tables, deduped. a page with no such table, or with no
ids, is a parse failure (FetchError).
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup, Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup, fold_heading

log = logging.getLogger(__name__)

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._/-]*$")
_IMAGE_MODEL_RE = re.compile(r"\bimage\b", re.IGNORECASE)
_MODEL_HEADERS = (
    ("model", "serverless inference"),
    ("provider", "model", "serverless inference"),
)
_FOLDED_MODEL_HEADERS = tuple(
    tuple(fold_heading(cell) for cell in headers) for headers in _MODEL_HEADERS
)
_MATRIX_CLASS = "gen-ai-pricing-matrix"
_MODE_LABEL = "processing mode"


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
        for pinned in _FOLDED_MODEL_HEADERS:
            if len(headers) == len(pinned) and all(
                cell.startswith(pin) for cell, pin in zip(headers, pinned, strict=True)
            ):
                tables.append((table, len(pinned) - 2))
                break
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
    """(normalized model name, pricing matrix) per in-scope row, page order.

    a row without a pricing matrix is not token-priced and is out of scope; a
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
            matrix = cells[model_col + 1].find("span", class_=_MATRIX_CLASS)
            if matrix is None:
                continue
            name = _model_name(cells[model_col])
            if _IMAGE_MODEL_RE.search(name):
                continue
            rows.append((_normalize_id(name), matrix))
    return rows


def _matrix_rows(matrix: Tag, url: str) -> tuple[tuple[str, ...], list[tuple[str, ...]]]:
    """a pricing matrix as (folded column labels, data rows).

    a row whose cell count does not match the header is a shape break; an
    empty matrix (header with no data rows) is a shape break too.
    """
    header = matrix.find("span", class_="gen-ai-pricing-matrix-header")
    if header is None:
        raise FetchError(f"pricing matrix without a header row on {url}")
    labels = tuple(
        fold_heading(cell.get_text(" ", strip=True))
        for cell in header.find_all("span", recursive=False)
    )
    data_rows: list[tuple[str, ...]] = []
    for row in matrix.find_all("span", class_="gen-ai-pricing-matrix-row"):
        if "gen-ai-pricing-matrix-header" in (row.get("class") or []):
            continue
        cells = tuple(
            cell.get_text(" ", strip=True) for cell in row.find_all("span", recursive=False)
        )
        if len(cells) != len(labels):
            raise FetchError(
                f"pricing matrix row with {len(cells)} cells against {len(labels)} columns on {url}"
            )
        data_rows.append(cells)
    if not data_rows:
        raise FetchError(f"pricing matrix with no data rows on {url}")
    return labels, data_rows


def _column_index(labels: tuple[str, ...], label: str, url: str) -> int:
    try:
        return labels.index(label)
    except ValueError:
        raise FetchError(f"pricing matrix without a {label!r} column on {url}") from None


def detect(cfg: ProviderCfg) -> list[str]:
    """current model ids, page order; mode rows emit `<base>-<mode>` ids."""
    ids: list[str] = []
    seen: set[str] = set()
    for name, matrix in _priced_rows(fetch_soup(cfg.detector_url), cfg.detector_url):
        labels, data_rows = _matrix_rows(matrix, cfg.detector_url)
        mode_col = _column_index(labels, _MODE_LABEL, cfg.detector_url)
        for row in data_rows:
            slug = _normalize_id(row[mode_col])
            model_id = name if slug == "standard" else f"{name}-{slug}"
            if not slug or not _ID_PATTERN.fullmatch(model_id):
                log.warning(
                    "detect skip for %s: %r outside the id charset on %s",
                    cfg.key,
                    row[mode_col],
                    cfg.detector_url,
                )
                continue
            if model_id not in seen:
                seen.add(model_id)
                ids.append(model_id)
    if not ids:
        raise FetchError(f"no model ids on {cfg.detector_url}")
    return ids

"""detect databricks foundation-model-serving model ids from the pricing page.

reads https://www.databricks.com/product/pricing/foundation-model-serving
(static server-rendered html). the per-token rates live in two tables
("Standard Pay Per Token (DBU Per 1M Tokens)" and "Priority Pay Per
Token", each pinning by its `Input | Output | Cache read` sub-header row
and its tier span, in page order), so both are watched; the per-hour
tables further down the page never match: the Provisioned Throughput table
names reservation terms in its sub-header, and the Batch Inference table
carries no sub-header at all. the page carries display names only ("Kimi
K3", "GTE"), so each row's canonical ids resolve through the display-name
mappings: the standard table's names -> the openrouter id spelling minus
its vendor prefix (measured against the stored openrouter id set
2026-08-29), the priority table's names -> the same with a "-priority"
suffix. the "GLM-5.2, 5.3" row carries one rate pair covering both store
ids. the ⌖ marker (regional-processing uplift, per the page's footnote 4)
strips off the name. rate cells read numeric DBU amounts or "-" (unpriced);
a row with a "-" input is known unpriced and skipped, "-" output reads as
a zero output rate (embedding rows bill input only). rows outside these
shapes (odd cell counts, unknown rate-cell text, unmapped names) are
additive drift: detection skips them with a warning (plan #22), and the
scraper stays strict for the matched row, so a drifted price column cannot
read as a missing model. a page whose per-token tables or priced rows are
gone still raises. zero-rate rows stay emitted (the scraper decides); the
scraper's dedup_keys maps the page's undated deepseek spellings back to
the dated store spellings their rows live under.
"""

from __future__ import annotations

import logging
import re
from functools import cache

from bs4 import BeautifulSoup, Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup, fold_heading

log = logging.getLogger(__name__)

# the second header row of the watched tables; fold_heading tolerates case,
# whitespace and &/and drift
_TABLE_HEADERS = ("Input", "Output", "Cache read")
_FOLDED_TABLE_HEADERS = tuple(fold_heading(cell) for cell in _TABLE_HEADERS)
# the tier spans of the two watched tables: a watched table is the priority
# one when its folded span equals the priority wording, the standard one
# when it equals the standard wording. a span matching NEITHER pin raises,
# so a reworded tier cannot silently classify a priority row as its base
# id (the two tables share display names; the seen-set would dedupe the
# priority id away with no warning)
_PRIORITY_SPAN = "Priority Pay Per Token (DBU Per 1M Tokens)"
_STANDARD_SPAN = "Standard Pay Per Token (DBU Per 1M Tokens)"
_FOLDED_PRIORITY_SPAN = fold_heading(_PRIORITY_SPAN)
_FOLDED_STANDARD_SPAN = fold_heading(_STANDARD_SPAN)
_RATE_RE = re.compile(r"^\d+(?:\.\d+)?$")
_DASH = "-"
_UPLIFT = "⌖"  # the ⌖ regional-uplift marker glued onto some names

# display name -> canonical ids, standard table. the ids are the stored
# openrouter id set's spellings minus the vendor prefix
# ("moonshotai/kimi-k3" -> "kimi-k3"), measured 2026-08-29; the 2026-09-05
# page restructure renamed several displays ("GPT-OSS-120B", "Qwen 3 80B
# Instruct" = the stored qwen3-next-80b id), dropped the deepseek snapshot
# dates, and merged GLM-5.2 and GLM-5.3 into one row at their shared rate
# pair.
_DISPLAY_IDS: dict[str, tuple[str, ...]] = {
    "Kimi K3": ("kimi-k3",),
    "Kimi K2.7": ("kimi-k2.7",),
    "GLM-5.2, 5.3": ("glm-5.2", "glm-5.3"),
    "GLM-5.3 Flash": ("glm-5.3-flash",),
    "Inkling": ("inkling",),
    "DeepSeek V4 Pro": ("deepseek-v4-pro",),
    "DeepSeek V4 Flash": ("deepseek-v4-flash",),
    "Qwen 3.5 122B": ("qwen3.5-122b-a10b",),
    "Qwen 3 80B Instruct": ("qwen3-next-80b-a3b-instruct",),
    "GPT-OSS-120B": ("gpt-oss-120b",),
    "GPT-OSS-20B": ("gpt-oss-20b",),
    "Llama 4 Maverick": ("llama-4-maverick",),
    "Llama 3.3 70B": ("llama-3.3-70b-instruct",),
    "Gemma 3 12B": ("gemma-3-12b-it",),
    "Llama 3.1 8B": ("llama-3.1-8b-instruct",),
    "Qwen 3 0.6B Embedding": ("qwen3-embedding-0.6b",),
    "GTE": ("gte",),
    "BGE Large": ("bge-large",),
}

# the priority table re-lists a subset of the models at priority rates,
# under the base display spellings (no "(Priority)" annotation and no
# merged rows since the 2026-09-05 restructure; measured on the live page)
_PRIORITY_DISPLAYS: dict[str, tuple[str, ...]] = {
    "GLM-5.2": ("glm-5.2-priority",),
    "Qwen 3.5 122B": ("qwen3.5-122b-a10b-priority",),
}


@cache
def _page(url: str) -> BeautifulSoup:
    """fetch and parse the page; cached per url so the scraper reuses this fetch."""
    return fetch_soup(url)


def _model_tables(soup: BeautifulSoup, url: str) -> list[Tag]:
    """the per-token tables (standard first, then priority), page order.

    a table pins when its second header row's first three cells fold to
    Input | Output | Cache read; the per-hour tables name reservation terms
    there instead, so they never match. a page with no match still raises.
    """
    tables = []
    for table in soup.find_all("table"):
        if table.find_parent("table") is not None:
            continue
        thead = table.find("thead")
        if thead is None or table.find("tbody") is None:
            continue
        header_rows = thead.find_all("tr", recursive=False)
        if len(header_rows) != 2:
            continue
        cells = [cell.get_text(" ", strip=True) for cell in header_rows[1].find_all("th")]
        if tuple(fold_heading(cell) for cell in cells[:3]) == _FOLDED_TABLE_HEADERS:
            tables.append(table)
    if not tables:
        raise FetchError(f"no foundation-model-serving dbu table on {url}")
    return tables


def _is_priority_table(table: Tag, url: str) -> bool:
    """whether a watched table is the priority one, read off its tier span.

    the first header row's second cell names the tier; the folded span
    compares equal to one of the two pinned tier wordings (case,
    whitespace and &/and tolerant, like the sub-header pin), so a wording
    tweak still classifies. a span matching neither pin raises: both
    tables share display names, so a mis-tiered priority row would map to
    its base id and the seen-set would silently drop the priority id.
    """
    header_rows = table.find("thead").find_all("tr", recursive=False)
    spans = header_rows[0].find_all("th")
    if len(spans) < 2:
        raise FetchError(f"tier span row outside the header shape on {url}")
    span = fold_heading(spans[1].get_text(" ", strip=True))
    if span == _FOLDED_PRIORITY_SPAN:
        return True
    if span == _FOLDED_STANDARD_SPAN:
        return False
    raise FetchError(f"unreadable pay-per-token tier span {span!r} on {url}")


def _row_cells(row: Tag, url: str) -> list[Tag]:
    cells = row.find_all(["th", "td"])
    if len(cells) != 4:
        raise FetchError(
            f"row outside the pricing shape on {url}: {row.get_text(' ', strip=True)!r}"
        )
    return cells


def _try_rate(cell: Tag) -> float | None:
    """the cell's DBU amount; every non-numeric shape reads as None."""
    text = cell.get_text(" ", strip=True)
    if text == _DASH:
        return None
    match = _RATE_RE.fullmatch(text)
    return float(match.group(0)) if match is not None else None


def _rate(cell: Tag, url: str) -> float | None:
    """strict: as _try_rate, but a cell outside the known shapes raises.

    the known shapes are a numeric amount and "-" (unpriced); anything else
    is a page-shape break, so a drifted rate column cannot silently read
    as an unpriced row.
    """
    text = cell.get_text(" ", strip=True)
    rate = _try_rate(cell)
    if rate is not None or text == _DASH:
        return rate
    raise FetchError(f"unreadable dbu rate cell {text!r} on {url}")


def parse_id(cell: Tag, url: str, priority: bool = False) -> tuple[str, ...]:
    """the row's canonical ids for its display name; unknown names raise."""
    name = cell.get_text(" ", strip=True).replace(_UPLIFT, "").strip()
    model_ids = (_PRIORITY_DISPLAYS if priority else _DISPLAY_IDS).get(name)
    if model_ids is None:
        raise FetchError(f"unmapped model name {name!r} on {url}")
    return model_ids


def detect(cfg: ProviderCfg) -> list[str]:
    """per-token-priced model ids, standard table then priority; unpriced rows skip."""
    soup = _page(cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    for table in _model_tables(soup, cfg.detector_url):
        priority = _is_priority_table(table, cfg.detector_url)
        for row in table.find("tbody").find_all("tr", recursive=False):
            try:
                cells = _row_cells(row, cfg.detector_url)
                if _rate(cells[1], cfg.detector_url) is None:
                    continue  # a "-" input cell: no per-token pricing
                _rate(cells[2], cfg.detector_url)
                _rate(cells[3], cfg.detector_url)
                model_ids = parse_id(cells[0], cfg.detector_url, priority=priority)
            except FetchError as exc:
                log.warning("detect skip for %s: %s", cfg.key, exc)
                continue
            for model_id in model_ids:
                if model_id not in seen:
                    seen.add(model_id)
                    ids.append(model_id)
    if not ids:
        raise FetchError(f"no per-token model rows on {cfg.detector_url}")
    return ids

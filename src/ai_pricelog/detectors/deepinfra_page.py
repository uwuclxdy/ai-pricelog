"""detect deepinfra model ids from the deepinfra pricing page.

https://deepinfra.com/pricing is next.js ssr. every per-token table (header
row Model | Context | $ per 1M input tokens | $ per 1M output tokens |
Actions) is rendered twice with identical rows; ids dedup across the copies,
first table in document order wins, so the two gemma-3 rows the MythoMax
family table repeats resolve to the gemma table's row. the model cell holds
one link to the model's own page and its last path segment is the id: the
display name can abbreviate it ("Llama-4-Scout-17B-16E" links to
/meta-llama/Llama-4-Scout-17B-16E-Instruct), so the link slug, lowercased,
is the stored spelling. the other tables (audio, image, embeddings,
hardware, tiers) carry different headers and are out of scope. a page with
no per-token model table, a model cell without its link, or a slug outside
the stored id charset, is a parse failure (FetchError).
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._/-]*$")
_TOKEN_HEADERS = ["Model", "Context", "$ per 1M input tokens", "$ per 1M output tokens", "Actions"]


def _model_tables(soup: BeautifulSoup) -> list[Tag]:
    """top-level tables whose header row is Model | Context | ... | Actions."""
    tables: list[Tag] = []
    for table in soup.find_all("table"):
        if table.find_parent("table") is not None:
            continue
        thead = table.find("thead")
        headers = [th.get_text(" ", strip=True) for th in thead.find_all("th")] if thead else []
        if headers == _TOKEN_HEADERS:
            tables.append(table)
    return tables


def _table_rows(table: Tag) -> list[list[Tag]]:
    """the table's own body rows as td cell lists (nested tables excluded)."""
    return [
        row.find_all("td", recursive=False)
        for row in table.find_all("tr")
        if row.find_parent("table") is table
    ]


def _model_id(cell: Tag) -> str | None:
    """the model-cell link's last path segment, lowercased; None without a link."""
    link = cell.find("a")
    href = link.get("href") if link is not None else None
    if not href:
        return None
    return href.rsplit("/", 1)[-1].lower()


def _row_id(cell: Tag, url: str) -> str:
    """the row's model id; a missing link or an out-of-charset slug is a FetchError."""
    model_id = _model_id(cell)
    if model_id is None:
        raise FetchError(f"model cell without a model link on {url}")
    if not _ID_PATTERN.fullmatch(model_id):
        raise FetchError(f"model id {model_id!r} outside the id charset on {url}")
    return model_id


def detect(cfg: ProviderCfg) -> list[str]:
    """current model ids, page order, deduped across the duplicate tables."""
    soup = fetch_soup(cfg.detector_url)
    tables = _model_tables(soup)
    if not tables:
        raise FetchError(f"no per-token model table on {cfg.detector_url}")
    ids: list[str] = []
    seen: set[str] = set()
    for table in tables:
        for row in _table_rows(table):
            if not row:
                continue
            model_id = _row_id(row[0], cfg.detector_url)
            if model_id not in seen:
                seen.add(model_id)
                ids.append(model_id)
    if not ids:
        raise FetchError(f"no model ids in the per-token model tables on {cfg.detector_url}")
    return ids

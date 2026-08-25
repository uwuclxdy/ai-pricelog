"""detect together chat model ids from the together.ai pricing page.

https://www.together.ai/pricing is static server-rendered html. the
serverless-inference section holds per-token tables whose header row is
Model | Input | output: the chat table (input cells may carry a cached
sub-cell) and the vision table (same shape, today a strict subset of the
chat rows at identical rates). rows from both are merged by slug, first
table in document order wins, so each model id appears once. ids are the
Model column cells slugged: lowercase, whitespace runs -> "-", other
punctuation kept as written ("DeepSeek V4 Pro 0813" -> "deepseek-v4-pro-0813";
page names already carry dots and dashes, which the target's id charset
allows). cells whose slug does not fit that charset are skipped. every other
table (image, audio, embeddings, moderation, fine-tuning, hardware) has
different headers and is out of scope; the batch-api-price toggle holds no
rates in the static html, so standard rates are the only ones read. a page
with no per-token model table, or with no usable ids, is a parse failure
(FetchError).
"""

import re

from bs4 import BeautifulSoup, Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._/-]*$")
_MODEL_HEADERS = ("model", "input", "output")


def _model_tables(soup: BeautifulSoup) -> list[Tag]:
    """top-level tables whose header row is Model | Input | output."""
    tables: list[Tag] = []
    for table in soup.find_all("table"):
        if table.find_parent("table") is not None:
            continue
        thead = table.find("thead")
        headers = (
            [th.get_text(" ", strip=True).casefold() for th in thead.find_all("th")]
            if thead
            else []
        )
        if tuple(headers) == _MODEL_HEADERS:
            tables.append(table)
    return tables


def _table_rows(table: Tag) -> list[list[Tag]]:
    """the table's own rows as td cell lists (nested tables excluded)."""
    return [
        row.find_all("td", recursive=False)
        for row in table.find_all("tr")
        if row.find_parent("table") is table
    ]


def _model_name(cell: Tag) -> str:
    link = cell.find("a", class_="pricing_model-link")
    return link.get_text(" ", strip=True) if link else cell.get_text(" ", strip=True)


def _normalize_id(name: str) -> str:
    return re.sub(r"\s+", "-", name.strip()).lower()


def detect(cfg: ProviderCfg) -> list[str]:
    """current model ids, page order, deduped across the per-token tables."""
    soup = fetch_soup(cfg.detector_url)
    tables = _model_tables(soup)
    if not tables:
        raise FetchError(f"no per-token model table on {cfg.detector_url}")
    ids: list[str] = []
    seen: set[str] = set()
    for table in tables:
        for cells in _table_rows(table):
            if not cells:
                continue
            normalized = _normalize_id(_model_name(cells[0]))
            if _ID_PATTERN.fullmatch(normalized) and normalized not in seen:
                seen.add(normalized)
                ids.append(normalized)
    if not ids:
        raise FetchError(f"no model ids in the per-token model tables on {cfg.detector_url}")
    return ids

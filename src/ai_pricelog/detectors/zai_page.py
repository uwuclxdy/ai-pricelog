"""detect model ids on the z.ai pricing page.

the page (https://docs.z.ai/guides/overview/pricing) carries 7 tables under
section headings. the watched tables are the ones priced per 1M input/output
tokens: Text Models and Vision Models, both headed Model | Input | Cached
Input | Cached Input Storage | Output, the header cells matched after
folding case, whitespace, and &/and (web.fold_heading). the single-rate
tables (image, video,
ASR: Model | Price), the built-in tools (per use) and the agents tables
(per request/video) are out of scope. the page spells ids like
GLM-4.7-FlashX; ids are lowercased because litellm keys are lowercase. a
page with no such table is a parse failure (FetchError).
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup, fold_heading

_GLM_ID_PATTERN = re.compile(r"^glm-[a-z0-9][a-z0-9.-]*$", re.IGNORECASE)
_TOKEN_HEADERS = frozenset(fold_heading(cell) for cell in ("Model", "Input", "Output"))


def detect(cfg: ProviderCfg) -> list[str]:
    tables = _token_model_tables(fetch_soup(cfg.detector_url), cfg.detector_url)
    ids = [
        row[0].strip().lower()
        for table in tables
        for row in table[1:]
        if row and _GLM_ID_PATTERN.fullmatch(row[0].strip())
    ]
    if not ids:
        raise FetchError(f"no GLM model rows on {cfg.detector_url}")
    return ids


def _token_model_tables(soup: BeautifulSoup, url: str) -> list[list[list[str]]]:
    """every top-level table priced per 1M input/output tokens, rows included.

    a table qualifies when its header row holds Model/Input/Output columns;
    that is the per-token pricing shape (the other tables are single-rate
    Model | Price or per-use tables). the heading is not consulted: the
    vision table shares the text table's columns exactly.
    """
    tables: list[list[list[str]]] = []
    for table in soup.find_all("table"):
        if table.find_parent("table") is not None:
            continue
        rows = [
            [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
            for row in table.find_all("tr")
            if row.find_parent("table") is table
        ]
        if rows and {fold_heading(cell) for cell in rows[0]} >= _TOKEN_HEADERS:
            tables.append(rows)
    if not tables:
        raise FetchError(f"no model pricing tables on {url}")
    return tables

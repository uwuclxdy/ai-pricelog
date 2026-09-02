"""detect model ids on the fireworks serverless pricing docs page.

the page (https://docs.fireworks.ai/serverless/pricing) serves the per-token
table statically: Model | Standard | Priority, the header pinned after
folding case, whitespace, and &/and (web.fold_heading). the row name is
the page
spelling of the sku (display names like "Kimi K3 Fast" and "Kimi K3 US"
share one api id but price separately), normalized to the index spelling:
lowercased, runs of spaces and parens -> dashes. the other tables on the
page (SFT and embeddings, priced by size class) are not per-model. a page
without the table is a parse failure (FetchError).
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup, fold_heading

_ID_SPLIT_RE = re.compile(r"[\s()]+")
_FOLDED_HEADER = [fold_heading(cell) for cell in ("Model", "Standard", "Priority")]


def detect(cfg: ProviderCfg) -> list[str]:
    table = _serverless_table(fetch_soup(cfg.detector_url), cfg.detector_url)
    ids = [_normalize_id(row[0]) for row in table[1:] if row and row[0].strip()]
    if not ids:
        raise FetchError(f"no model rows on {cfg.detector_url}")
    return ids


def _serverless_table(soup: BeautifulSoup, url: str) -> list[list[str]]:
    """the Model | Standard | Priority table; missing -> FetchError."""
    for table in soup.find_all("table"):
        rows = [
            [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
            for row in table.find_all("tr")
        ]
        if rows and [fold_heading(cell) for cell in rows[0][:3]] == _FOLDED_HEADER:
            return rows
    raise FetchError(f"no serverless pricing table on {url}")


def _normalize_id(name: str) -> str:
    return _ID_SPLIT_RE.sub("-", name.lower()).strip("-")

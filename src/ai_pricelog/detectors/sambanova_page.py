"""detect model ids on the sambanova cloud pricing page.

https://cloud.sambanova.ai/pricing (redirects to /plans/pricing) serves the
per-token table statically: Model | Cached Input Tokens | Input (per 1M
tokens) | Output (per 1M tokens). the same rows ride the page's next.js rsc
flight payload; the captured fixture carries the identical seven rows in
both sources, so the rendered table is parsed (stable dom, nothing to
deserialize). ids are the Model column cells normalized to the index
spelling: lowercase, runs of non-alphanumeric characters except dots ->
dashes, checked against the stored id charset (cells missing it are
skipped). a page without the table, or with no usable ids, is a parse
failure (FetchError).
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, extract_tables, fetch_soup

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._/-]*$")
_NON_ID_RE = re.compile(r"[^a-z0-9.]+")
_MODEL_HEADERS = ("Model", "Cached Input Tokens", "Input (per 1M tokens)", "Output (per 1M tokens)")


def detect(cfg: ProviderCfg) -> list[str]:
    table = _pricing_table(fetch_soup(cfg.detector_url), cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    for row in table[1:]:
        if not row or not row[0]:
            continue
        normalized = _normalize_id(row[0])
        if _ID_PATTERN.fullmatch(normalized) and normalized not in seen:
            seen.add(normalized)
            ids.append(normalized)
    if not ids:
        raise FetchError(f"no model ids in the pricing table on {cfg.detector_url}")
    return ids


def _pricing_table(soup: BeautifulSoup, url: str) -> list[list[str]]:
    """the Model | Cached Input Tokens | Input | Output table; missing -> FetchError."""
    for table in extract_tables(soup):
        if table and table[0] == list(_MODEL_HEADERS):
            return table
    raise FetchError(f"no pricing table on {url}")


def _normalize_id(name: str) -> str:
    return _NON_ID_RE.sub("-", name.lower()).strip("-")

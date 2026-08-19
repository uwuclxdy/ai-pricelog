"""detect model ids on the z.ai pricing page.

the page (https://docs.z.ai/guides/overview/pricing) carries 7 tables under
section headings. only the TEXT models table is watched: the table whose
preceding heading contains "text", whose header row holds Model/Input/Output
columns, and whose rows' first cells are GLM-*. the vision, image, video,
ASR and agents tables are out of scope (different pricing units). the page
spells ids like GLM-4.7-FlashX; ids are lowercased because litellm keys are
lowercase. a page with no such table is a parse failure (FetchError).
"""

import re

from bs4 import BeautifulSoup

from autopr_genai_prices.config import ProviderCfg
from autopr_genai_prices.web import FetchError, fetch_soup

_GLM_ID_PATTERN = re.compile(r"^glm-[a-z0-9][a-z0-9.-]*$", re.IGNORECASE)
_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def detect(cfg: ProviderCfg) -> list[str]:
    table = _text_models_table(fetch_soup(cfg.detector_url), cfg.detector_url)
    ids = [
        row[0].strip().lower()
        for row in table[1:]
        if row and _GLM_ID_PATTERN.fullmatch(row[0].strip())
    ]
    if not ids:
        raise FetchError(f"no GLM model rows on {cfg.detector_url}")
    return ids


def _text_models_table(soup: BeautifulSoup, url: str) -> list[list[str]]:
    for table in soup.find_all("table"):
        if table.find_parent("table") is not None:
            continue
        heading = _preceding_heading(table)
        if "text" not in heading.lower():
            continue
        rows = [
            [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
            for row in table.find_all("tr")
            if row.find_parent("table") is table
        ]
        if rows and {"Model", "Input", "Output"} <= set(rows[0]):
            return rows
    raise FetchError(f"no text-models pricing table on {url}")


def _preceding_heading(table: BeautifulSoup) -> str:
    for element in table.previous_elements:
        if getattr(element, "name", None) in _HEADING_TAGS:
            return element.get_text(" ", strip=True)
    return ""

"""detect gemini/gemma model ids on the gemini-api pricing page.

reads https://ai.google.dev/gemini-api/docs/pricing (static html). each model
section is an h2 whose heading group carries the canonical id as code tags
inside an em (``gemini-3.7-flash``); the h2 id is a nav anchor and can differ
from the model id (the embedding section anchors as ``gemini-embedding`` while
its slug is ``gemini-embedding-001``), so the em slug wins and the h2 id is
the fallback for sections without one (gemma-4). one section, the 3.1 Pro
Preview, carries two slugs in its em (the customtools endpoint); both are
emitted.

only sections carrying a token pricing table are watched: a table whose
header holds "Paid Tier, per 1M tokens in USD" and that has an input-price
row ("Input price", "Text input price", "Image input price"). that keeps
out imagen/veo/lyria (per image/second/request) and the tools/agents
tables. input-only sections (gemini-embedding-2) are detected; the scraper
returns None for them (no output row). ids are emitted as written on the
page, page order.
"""

from collections.abc import Iterator

from bs4 import BeautifulSoup, Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup

_PAID_HEADER = "Paid Tier, per 1M tokens in USD"


def _sections(soup: BeautifulSoup) -> list[Tag]:
    article = soup.find("article")
    return article.find_all("h2") if article is not None else []


def _section_elements(h2: Tag) -> Iterator[Tag]:
    """every element between an h2 and the next h2, document order."""
    node = h2
    while True:
        node = node.find_next()
        if node is None or node.name == "h2":
            break
        yield node


def _slugs(h2: Tag) -> list[str]:
    """the model ids a section spells, from its heading em codes (h2 id fallback)."""
    for element in _section_elements(h2):
        if element.name == "em":
            codes = [code.get_text(" ", strip=True) for code in element.find_all("code")]
            if codes:
                return codes
            break
    return [h2.get("id")] if h2.get("id") else []


def _is_token_table(table: Tag) -> bool:
    header_row = table.find("tr")
    if header_row is None:
        return False
    header_cells = [cell.get_text(" ", strip=True) for cell in header_row.find_all(["th", "td"])]
    if not any(_PAID_HEADER in cell for cell in header_cells):
        return False
    for row in table.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
        if cells and "input price" in cells[0].lower():
            return True
    return False


def detect(cfg: ProviderCfg) -> list[str]:
    soup = fetch_soup(cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    token_sections = 0
    for h2 in _sections(soup):
        elements = list(_section_elements(h2))
        if not any(
            element.name == "table"
            and element.get("class") == ["pricing-table"]
            and _is_token_table(element)
            for element in elements
        ):
            continue
        token_sections += 1
        for slug in _slugs(h2):
            if slug and slug not in seen:
                seen.add(slug)
                ids.append(slug)
    if not token_sections:
        raise FetchError(f"no token pricing tables found on {cfg.detector_url}")
    if not ids:
        raise FetchError(f"no model ids found on {cfg.detector_url}")
    return ids

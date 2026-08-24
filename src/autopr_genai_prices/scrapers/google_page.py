"""scrape per-token pricing for google models from the gemini-api pricing page.

same page and model sections as detection. the watched table is the Standard
tier: the table under the "Standard" h3 when the section carries tier tabs,
the section's single table otherwise. Batch/Flex/Priority tabs are ignored.

rows are keyed by their first cell: "Input price*" -> input, "Output price*"
-> output, "Context caching price" -> cache read; the paid column is the
header cell holding "Paid Tier". every cell's first dollar amount is the base
rate: promo cells list the current rate first ($0.75 through December 31,
2026. $1.50 starting January 1, 2027.), tiered cells list the <=200k base
first ($2.00, prompts <= 200k tokens $4.00, prompts > 200k tokens), and
cache cells list the read rate before the storage price. dollars per 1M
tokens -> divided by 1e6. a first amount directly followed by "per " is a
per-image/per-unit rate, not a per-token one (2.5 Flash Image output reads
$0.039 per image) -> the model has no usable output rate. cells without a
dollar amount (Free of charge, Not available) and sections without an output
row (embedding models) are unpriced -> None. max_tokens comes from a "1M
token context window" mention in the section's description paragraphs (only
Gemini 2.5 Flash carries one), else 0. mode is chat.

dedup_keys maps page spellings the target tracks under a different id:
- gemini-3.1-flash-image / gemini-3-pro-image -> the tracked -preview
  entries (their match clauses already list the GA spelling via equals)
- gemini-2.5-flash-native-audio-preview-<date> -> gemini-live-2.5-flash
- gemini-2.5-flash-lite-preview-<date> -> gemini-2.5-flash-lite
"""

import re

from bs4 import BeautifulSoup, Tag

from autopr_genai_prices.config import ProviderCfg
from autopr_genai_prices.detectors.google_page import (
    _PAID_HEADER,
    _section_elements,
    _sections,
    _slugs,
)
from autopr_genai_prices.pricing import Pricing
from autopr_genai_prices.web import FetchError, fetch_soup

_AMOUNT_RE = re.compile(r"\$([\d,]+(?:\.\d+)?)")
_CONTEXT_WINDOW_RE = re.compile(r"(\d[\d,]*)\s*([KkMm])\s+token context window")

_GA_IMAGE_IDS = {
    "gemini-3.1-flash-image": "gemini-3.1-flash-image-preview",
    "gemini-3-pro-image": "gemini-3-pro-image-preview",
}
_DATED_PREVIEW_IDS = {
    r"^gemini-2\.5-flash-native-audio-preview(-\d{2}-\d{4})?$": "gemini-live-2.5-flash",
    r"^gemini-2\.5-flash-lite-preview(-\d{2}-\d{4})?$": "gemini-2.5-flash-lite",
}


def dedup_keys(model_id: str) -> list[str]:
    """The target's tracked spelling of a divergent page id, or [] when unchanged."""
    if model_id in _GA_IMAGE_IDS:
        return [_GA_IMAGE_IDS[model_id]]
    for pattern, tracked in _DATED_PREVIEW_IDS.items():
        if re.fullmatch(pattern, model_id):
            return [tracked]
    return []


def _find_section(soup: BeautifulSoup, model_id: str) -> Tag | None:
    for h2 in _sections(soup):
        if model_id in _slugs(h2):
            return h2
    return None


def _standard_table(h2: Tag, model_id: str, url: str) -> Tag:
    elements = list(_section_elements(h2))
    for element in elements:
        if element.name == "devsite-selector":
            for tier in element.find_all("section", recursive=False):
                heading = tier.find("h3")
                if heading is not None and heading.get_text(" ", strip=True) == "Standard":
                    table = tier.find("table")
                    if table is not None:
                        return table
            raise FetchError(f"no Standard tier table for {model_id} on {url}")
    for element in elements:
        if element.name == "table":
            return element
    raise FetchError(f"no pricing table for {model_id} on {url}")


def _rows(table: Tag, model_id: str, url: str) -> dict[str, str]:
    header_row = table.find("tr")
    if header_row is None:
        raise FetchError(f"malformed pricing table for {model_id} on {url}: no header row")
    header = [cell.get_text(" ", strip=True) for cell in header_row.find_all(["th", "td"])]
    paid_index = next((index for index, cell in enumerate(header) if _PAID_HEADER in cell), None)
    if paid_index is None:
        raise FetchError(f"malformed pricing table for {model_id} on {url}: no Paid Tier column")
    rows: dict[str, str] = {}
    for row in table.find_all("tr")[1:]:
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
        if cells and cells[0] and len(cells) > paid_index:
            rows[cells[0]] = cells[paid_index]
    return rows


def _cell_value(rows: dict[str, str], prefix: str) -> str | None:
    return next((value for label, value in rows.items() if label.startswith(prefix)), None)


def _per_token(cell: str | None) -> float | None:
    if cell is None:
        return None
    match = _AMOUNT_RE.search(cell)
    if match is None:
        return None
    tail = cell[match.end() :].lstrip()
    if tail.startswith("per "):
        return None  # a per-image/per-unit rate, not a per-token one
    return float(match.group(1).replace(",", ""))


def _context_window(h2: Tag) -> int:
    for element in _section_elements(h2):
        if element.name != "p":
            continue
        match = _CONTEXT_WINDOW_RE.search(element.get_text(" ", strip=True))
        if match is None:
            continue
        value = float(match.group(1).replace(",", ""))
        scale = 1_000 if match.group(2) in ("k", "K") else 1_000_000
        return int(value * scale)
    return 0


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    soup = fetch_soup(cfg.scraper_url)
    h2 = _find_section(soup, model_id)
    if h2 is None:
        return None
    rows = _rows(_standard_table(h2, model_id, cfg.scraper_url), model_id, cfg.scraper_url)
    input_cost = _per_token(_cell_value(rows, "Input price"))
    output_cost = _per_token(_cell_value(rows, "Output price"))
    if input_cost is None or output_cost is None:
        return None
    cache_read = _per_token(rows.get("Context caching price"))
    return Pricing(
        input_cost_per_token=input_cost / 1e6,
        output_cost_per_token=output_cost / 1e6,
        mode="chat",
        max_tokens=_context_window(h2),
        cache_read_cost_per_token=cache_read / 1e6 if cache_read is not None else None,
    )

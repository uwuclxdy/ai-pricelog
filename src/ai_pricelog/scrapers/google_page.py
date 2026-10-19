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
cache cells list the read rate before the storage price. a cell carrying a
`> N` tier marker (`> 200k tokens`, `> 200k`) also emits the `$` amount right
before that marker as the long-context tier: one window_rates entry
`{"min_tokens": N, "<axis>_mtok": amount}` per model, the amount per-1M
verbatim (no /1e6); a cell without the marker contributes nothing, and a
model whose cells carry none emits no window_rates. dollars per 1M
tokens -> divided by 1e6. a first amount directly followed by "per " is a
per-image/per-unit rate, not a per-token one (2.5 Flash Image output reads
$0.039 per image) -> the model has no usable output rate. a cell carrying a
malformed "$" amount (a comma-decimal, a glued digit) raises FetchError
naming the model and cell. cells without a dollar amount (Free of charge,
Not available) are unpriced -> None. sections without an output row
(embedding models) price with output 0: embeddings bill input tokens only
(the litellm convention); their input label is "Input price" or "Text input
price". max_tokens_in comes from a "1M token context window" mention in the
section's description paragraphs (only Gemini 2.5 Flash carries one), else 0.
mode is chat.

dedup_keys maps page spellings the store holds under a different id:
- gemini-3.1-flash-image / gemini-3-pro-image -> the stored -preview
  entries
- gemini-2.5-flash-native-audio-preview-<date> -> gemini-live-2.5-flash
- gemini-2.5-flash-lite-preview-<date> -> gemini-2.5-flash-lite
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.google_page import (
    _PAID_HEADER,
    _section_elements,
    _sections,
    _slugs,
)
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, amount_scan, fetch_soup, unreadable_rate_error

_CONTEXT_WINDOW_RE = re.compile(r"(\d[\d,]*)\s*([KkMm])\s+token context window")
_LONG_TIER_RE = re.compile(r">\s*(\d[\d,]*)\s*([KkMm])\b")

_GA_IMAGE_IDS = {
    "gemini-3.1-flash-image": "gemini-3.1-flash-image-preview",
    "gemini-3-pro-image": "gemini-3-pro-image-preview",
}
_DATED_PREVIEW_IDS = {
    r"^gemini-2\.5-flash-native-audio-preview(-\d{2}-\d{4})?$": "gemini-live-2.5-flash",
    r"^gemini-2\.5-flash-lite-preview(-\d{2}-\d{4})?$": "gemini-2.5-flash-lite",
}


def dedup_keys(model_id: str) -> list[str]:
    """The stored spelling of a divergent page id, or [] when unchanged."""
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


def _per_token(cell: str | None, model_id: str, url: str) -> float | None:
    if cell is None:
        return None
    readable, malformed = amount_scan(cell, before="$")
    if malformed:
        raise unreadable_rate_error(cell, model_id, url)
    if not readable:
        return None
    first = readable[0]
    # `index` finds the exact "$<amount>" run, so a stray "$" earlier in the
    # cell cannot skew where the first amount ends
    end = cell.index("$" + first) + 1 + len(first)
    if cell[end:].lstrip().startswith("per "):
        return None  # a per-image/per-unit rate, not a per-token one
    return float(first.replace(",", ""))


def _long_tier(cell: str | None, model_id: str, url: str) -> tuple[int, float] | None:
    """(threshold, per-1M amount) of the cell's `> N` long tier, or None.

    the long-tier amount is the last `$` amount before the `> N` marker; a
    storage price after the marker (cache cells) never reads as the tier. a
    `> N` marker whose preceding amount is unreadable, or a cell carrying a
    second `> N` marker (an unmodeled multi-tier cell), raises (plan #22):
    silently dropping it would omit a rate the page carries.
    """
    if cell is None:
        return None
    match = _LONG_TIER_RE.search(cell)
    if match is None:
        return None
    if _LONG_TIER_RE.search(cell, match.end()) is not None:
        raise FetchError(f"model {model_id!r}: cell carries a second long tier on {url}: {cell!r}")
    scale = 1_000 if match.group(2) in ("k", "K") else 1_000_000
    threshold = int(match.group(1).replace(",", "")) * scale
    readable, malformed = amount_scan(cell[: match.start()], before="$")
    if malformed or not readable:
        raise unreadable_rate_error(cell, model_id, url)
    return threshold, float(readable[-1].replace(",", ""))


def _window_rates(
    input_cell: str | None,
    output_cell: str | None,
    cache_cell: str | None,
    model_id: str,
    url: str,
) -> tuple[dict[str, object], ...]:
    """the model's long-context tier as window_rates, () when no cell has one.

    each cell's `> N` tier contributes its per-1M amount under its axis key;
    the cells of one model describe one tier, so they must agree on the
    threshold (a single override carries one min_tokens). a cell without the
    marker contributes no key.
    """
    tiers: dict[str, tuple[int, float]] = {}
    for axis, cell in (
        ("input", input_cell),
        ("output", output_cell),
        ("cache_read", cache_cell),
    ):
        tier = _long_tier(cell, model_id, url)
        if tier is not None:
            tiers[axis] = tier
    if not tiers:
        return ()
    thresholds = {threshold for threshold, _ in tiers.values()}
    if len(thresholds) > 1:
        raise FetchError(
            f"model {model_id!r}: long-context tiers disagree on threshold:"
            f" {sorted(thresholds)} on {url}"
        )
    entry: dict[str, object] = {"min_tokens": next(iter(thresholds))}
    for axis in ("input", "output", "cache_read"):
        if axis in tiers:
            entry[f"{axis}_mtok"] = tiers[axis][1]
    return (entry,)


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
    input_cell = _cell_value(rows, "Input price")
    input_cost = _per_token(input_cell, model_id, cfg.scraper_url)
    if input_cost is None:
        input_cell = _cell_value(rows, "Text input price")
        input_cost = _per_token(input_cell, model_id, cfg.scraper_url)
    if input_cost is None:
        return None
    output_cell = _cell_value(rows, "Output price")
    output_cost = _per_token(output_cell, model_id, cfg.scraper_url)
    if output_cost is None and not any(label.startswith("Output price") for label in rows):
        output_cost = 0.0
    if output_cost is None:
        return None
    cache_cell = rows.get("Context caching price")
    cache_read = _per_token(cache_cell, model_id, cfg.scraper_url)
    return Pricing(
        input_cost_per_token=input_cost / 1e6,
        output_cost_per_token=output_cost / 1e6,
        mode="chat",
        max_tokens_in=_context_window(h2),
        cache_read_cost_per_token=cache_read / 1e6 if cache_read is not None else None,
        window_rates=_window_rates(input_cell, output_cell, cache_cell, model_id, cfg.scraper_url),
    )

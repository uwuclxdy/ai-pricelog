"""mistral pricing from the inference pricing page.

the page is static; each pricing table sits in a section whose unit line reads
``Prices /M Tokens`` (flagship, third-party-hosted, code sections) or ``Prices as
marked`` (specialized, labs: per-page/per-minute/per-char units, not token-priced).
rows link their model cell to the model-card slug and are matched by slug or
stored spelling (see ``dedup_keys``; the detector emits the stored spelling, so
``scrape`` accepts ``codestral-2508`` as well as ``codestral-25-08``).
cells are USD per 1M tokens in the default static html (the EUR tab is
client-side; the fixture pins the USD variant) -> /1e6. ``Free`` cells and
non-dollar cells (``$4 /1000 Pages``, ``$0.003 /Min``, ``—``) have no token
pricing -> None. the ``Cached input`` cell emits as cache-read cost when it
carries a bare dollar amount (zai-glm-5-2: $0.14); other cached cells leave it
None. the page carries no context window -> the max_tokens fields 0. mode is chat.
"""

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.mistral_page import _GENERATION_SEGMENT, SLUG_RE, _compact
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup

_HEADER = ["Model", "Input", "Cached input", "Output"]
_TOKEN_UNIT_LINE = "Prices /M Tokens"
_DOLLAR_CELL = re.compile(r"^\$(\d+(?:\.\d+)?)$")


def dedup_keys(model_id: str) -> list[str]:
    """The stored spellings of this page slug, or [] when unchanged.

    most slugs compact a dated tail (codestral-25-08 -> codestral-2508).
    ministral slugs also carry a generation segment the store drops
    (ministral-3-14b-25-12 -> ministral-3-14b-2512 AND ministral-14b-2512).
    the pipeline settles only when a returned spelling has a stored row,
    so an unknown candidate spelling is harmless.
    """
    compacted = _compact(model_id)
    keys = []
    if compacted != model_id:
        keys.append(compacted)
    match = _GENERATION_SEGMENT.match(compacted)
    if match:
        keys.append(f"{match.group(1)}-{match.group(3)}")
    return keys


def _price(cell: str) -> float | None:
    match = _DOLLAR_CELL.fullmatch(cell)
    if match is None:
        return None
    return float(match.group(1)) / 1e6


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    """Pricing for model_id, or None when the page carries no pricing for it."""
    soup = fetch_soup(cfg.scraper_url)
    found_token_table = False
    for table in soup.find_all("table"):
        if table.find_parent("table") is not None:
            continue
        section = table.find_parent("section")
        if section is None or _TOKEN_UNIT_LINE not in section.get_text(" ", strip=True):
            continue
        rows = table.find_all("tr")
        if not rows:
            continue
        header = [cell.get_text(" ", strip=True) for cell in rows[0].find_all(["th", "td"])]
        if header != _HEADER:
            continue
        found_token_table = True
        for row in rows[1:]:
            cells = row.find_all(["th", "td"])
            if len(cells) < 4:
                continue
            link = cells[0].find("a", href=True)
            if link is None:
                continue
            match = SLUG_RE.fullmatch(link["href"])
            if match is None or (
                match.group(1) != model_id and model_id not in dedup_keys(match.group(1))
            ):
                continue
            input_cost = _price(cells[1].get_text(" ", strip=True))
            cache_read_cost = _price(cells[2].get_text(" ", strip=True))
            output_cost = _price(cells[3].get_text(" ", strip=True))
            if input_cost is None or output_cost is None:
                return None
            return Pricing(
                input_cost_per_token=input_cost,
                output_cost_per_token=output_cost,
                mode="chat",
                cache_read_cost_per_token=cache_read_cost,
            )
    if not found_token_table:
        raise FetchError(f"no per-token pricing tables found on {cfg.scraper_url}")
    return None

"""detect databricks foundation-model-serving model ids from the pricing page.

reads https://www.databricks.com/product/pricing/foundation-model-serving
(static server-rendered html). the "Foundation Model Serving DBU rates"
table pins by its second header row (DBU / M input tokens, DBU / M output
tokens, DBU / M cache read tokens); the provisioned-throughput hour columns
are out of scope. the page carries display names only ("Kimi K3",
"Deepseek V4 Pro (0813)"), so each row's canonical id resolves through the
_DISPLAY_IDS mapping: display name -> the openrouter id spelling minus its
vendor prefix (measured against the stored openrouter id set 2026-08-29),
with "-priority" for the databricks-native tier rows. the ⌖ marker
(regional-processing uplift, per the page's footnote 4) strips off the
name. rate cells read numeric DBU amounts or "n/a"; a row with n/a input
is known unpriced (provisioned-only rows) and skipped, n/a output reads as
a zero output rate (embedding rows bill input only), and any other
rate-cell shape is a page-shape break (FetchError), so a drifted price
column cannot read as a missing model. zero-rate rows stay emitted (the
scraper decides); dated display spellings dedup to their base id in the
scraper's dedup_keys.
"""

from __future__ import annotations

import re
from functools import cache

from bs4 import BeautifulSoup, Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup

_TABLE_HEADERS = ("DBU / M input tokens", "DBU / M output tokens", "DBU / M cache read tokens")
_RATE_RE = re.compile(r"^\d+(?:\.\d+)?$")
_NA = "n/a"
_UPIIFT = "⌖"  # the ⌖ regional-uplift marker glued onto some names

# display name -> canonical id. the ids are the stored openrouter id set's
# spellings minus the vendor prefix ("moonshotai/kimi-k3" -> "kimi-k3"),
# measured 2026-08-29; "Kimi K2.7" and the embedding rows derive from the
# display name (openrouter carries only kimi-k2.7-code, and no ids for
# these embeddings), and the "(Priority)" tiers are databricks-native rows
# with a "-priority" suffix.
_DISPLAY_IDS: dict[str, str] = {
    "Kimi K3": "kimi-k3",
    "Kimi K2.7": "kimi-k2.7",
    "GLM-5.2": "glm-5.2",
    "GLM-5.2 (Priority)": "glm-5.2-priority",
    "Inkling": "inkling",
    "Deepseek V4 Pro (0813)": "deepseek-v4-pro-0813",
    "Deepseek V4 Flash (0731)": "deepseek-v4-flash-0731",
    "Qwen 3.5 122B": "qwen3.5-122b-a10b",
    "Qwen 3.5 122B (Priority)": "qwen3.5-122b-a10b-priority",
    "Qwen 3 Next 80B": "qwen3-next-80b-a3b-instruct",
    "GPT OSS 120B": "gpt-oss-120b",
    "GPT OSS 20B": "gpt-oss-20b",
    "Llama 4 Maverick": "llama-4-maverick",
    "Llama 3.3 70B": "llama-3.3-70b-instruct",
    "Gemma 3 12B": "gemma-3-12b-it",
    "Llama 3.1 8B": "llama-3.1-8b-instruct",
    "Qwen 3 0.6B Embedding": "qwen3-embedding-0.6b",
    "GTE": "gte",
    "BGE Large": "bge-large",
}


@cache
def _page(url: str) -> BeautifulSoup:
    """fetch and parse the page; cached per url so the scraper reuses this fetch."""
    return fetch_soup(url)


def _model_table(soup: BeautifulSoup, url: str) -> Tag:
    for table in soup.find_all("table"):
        if table.find_parent("table") is not None:
            continue
        thead = table.find("thead")
        if thead is None or table.find("tbody") is None:
            continue
        header_rows = thead.find_all("tr", recursive=False)
        if len(header_rows) != 2:
            continue
        cells = [cell.get_text(" ", strip=True) for cell in header_rows[1].find_all("th")]
        if cells[:3] == list(_TABLE_HEADERS):
            return table
    raise FetchError(f"no foundation-model-serving dbu table on {url}")


def _row_cells(row: Tag, url: str) -> list[Tag]:
    cells = row.find_all(["th", "td"])
    if len(cells) != 6:
        raise FetchError(
            f"row outside the pricing shape on {url}: {row.get_text(' ', strip=True)!r}"
        )
    return cells


def _try_rate(cell: Tag) -> float | None:
    """the cell's DBU amount; every non-numeric shape reads as None."""
    text = cell.get_text(" ", strip=True)
    if text == _NA:
        return None
    match = _RATE_RE.fullmatch(text)
    return float(match.group(0)) if match is not None else None


def _rate(cell: Tag, url: str) -> float | None:
    """strict: as _try_rate, but a cell outside the known shapes raises.

    the known shapes are a numeric amount and "n/a" (unpriced); anything
    else is a page-shape break, so a drifted rate column cannot silently
    read as an unpriced row.
    """
    text = cell.get_text(" ", strip=True)
    rate = _try_rate(cell)
    if rate is not None or text == _NA:
        return rate
    raise FetchError(f"unreadable dbu rate cell {text!r} on {url}")


def parse_id(cell: Tag, url: str) -> str:
    """the row's canonical id for its display name; unknown names raise."""
    name = cell.get_text(" ", strip=True).replace(_UPIIFT, "").strip()
    model_id = _DISPLAY_IDS.get(name)
    if model_id is None:
        raise FetchError(f"unmapped model name {name!r} on {url}")
    return model_id


def detect(cfg: ProviderCfg) -> list[str]:
    """per-token-priced model ids, page order; unpriced rows are skipped."""
    soup = _page(cfg.detector_url)
    table = _model_table(soup, cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    for row in table.find("tbody").find_all("tr", recursive=False):
        cells = _row_cells(row, cfg.detector_url)
        if _rate(cells[1], cfg.detector_url) is None:
            continue  # provisioned-only rows carry no per-token input
        # output: "n/a" (embedding rows bill input only) or numeric, else
        # the strict shape check raises
        _rate(cells[2], cfg.detector_url)
        _rate(cells[3], cfg.detector_url)  # cache: n/a or numeric, else raise
        model_id = parse_id(cells[0], cfg.detector_url)
        if model_id not in seen:
            seen.add(model_id)
            ids.append(model_id)
    if not ids:
        raise FetchError(f"no per-token model rows on {cfg.detector_url}")
    return ids

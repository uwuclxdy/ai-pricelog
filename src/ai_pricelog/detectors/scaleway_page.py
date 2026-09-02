"""detect scaleway model ids from the model-as-a-service pricing page.

reads https://www.scaleway.com/en/pricing/model-as-a-service/ (static
server-rendered html). the per-token table is the one captioned "Generative
API" (sr-only); the gpu-per-hour table is out of scope. a row's model id is
the Name cell's plain-text slug; the Try link's modelName query is a
second id source that must agree when the row carries one (a row without
a link falls back to the Name cell alone). the header pins after folding
case, whitespace, and &/and, so wording drift ("name", "input tokens")
still matches; a drifted header counts as a missing table.
the input cell reads "€X / million tokens", optionally with a cached rate
("... €Y / million tokens cached"); the output cell reads the same shape
or "Free" (a zero rate, the embedding convention). rows priced per audio
minute (whisper) are known unpriced and skipped. a Try-link disagreement,
an out-of-charset name, a row outside the five-cell shape, and a price
cell outside the known shapes are additive drift: detection skips the row
with a warning (plan #22), and a page whose generative-api table or
per-token model rows are gone still raises. zero-rate rows stay emitted
(the scraper decides); dated slug spellings dedup to their base id in the
scraper's dedup_keys.
"""

from __future__ import annotations

import logging
import re
from functools import cache

from bs4 import BeautifulSoup, Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup, fold_heading

log = logging.getLogger(__name__)

_TABLE_CAPTION = "Generative API"
_HEADER_PREFIXES = ("Name", "Tasks", "Input tokens", "Output tokens")
_FOLDED_PREFIXES = tuple(fold_heading(prefix) for prefix in _HEADER_PREFIXES)
_ID_CHARSET_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*$")
_MODEL_NAME_RE = re.compile(r"[?&]modelName=([^&]+)")
_RATE_RE = re.compile(r"^€(\d+(?:\.\d+)?) / million tokens$")
_CACHED_RE = re.compile(
    r"^€(\d+(?:\.\d+)?) / million tokens €(\d+(?:\.\d+)?) / million tokens cached$"
)
_AUDIO_RE = re.compile(r"^€\d+(?:\.\d+)? / Audio minute$")
_FREE = "Free"


@cache
def _page(url: str) -> BeautifulSoup:
    """fetch and parse the page; cached per url so the scraper reuses this fetch."""
    return fetch_soup(url)


def _model_table(soup: BeautifulSoup, url: str) -> Tag:
    for table in soup.find_all("table"):
        if table.find_parent("table") is not None:
            continue
        caption = table.find("caption")
        if caption is not None and caption.get_text(strip=True) == _TABLE_CAPTION:
            header = table.find("thead")
            if header is None or table.find("tbody") is None:
                raise FetchError(f"pricing table outside the row shape on {url}")
            header_cells = header.find_all("th")
            if len(header_cells) != 5 or not all(
                fold_heading(cell.get_text(" ", strip=True)).startswith(prefix)
                for cell, prefix in zip(header_cells[:4], _FOLDED_PREFIXES, strict=True)
            ):
                raise FetchError(f"pricing table headers drifted on {url}")
            return table
    raise FetchError(f"no generative-api pricing table on {url}")


def _row_cells(row: Tag, url: str) -> list[Tag]:
    cells = row.find_all(["th", "td"])
    if len(cells) != 5:
        raise FetchError(
            f"row outside the pricing shape on {url}: {row.get_text(' ', strip=True)!r}"
        )
    return cells


def parse_id(name_cell: Tag, try_cell: Tag, url: str) -> str:
    """the row's slug; the Try link's modelName is a second id source when present."""
    name = name_cell.get_text(" ", strip=True)
    link = try_cell.find("a", href=True)
    if link is not None:
        match = _MODEL_NAME_RE.search(link["href"])
        if match is None or match.group(1) != name:
            raise FetchError(f"Try link modelName disagrees with {name!r} on {url}")
    if _ID_CHARSET_RE.fullmatch(name) is None:
        raise FetchError(f"model id {name!r} outside the id charset on {url}")
    return name


def _input_amounts(cell: Tag, url: str) -> tuple[float, float | None] | None:
    """(per-1M rate, cached rate) for a token-priced input cell.

    a known unpriced form (per audio minute) returns None; a cell outside
    every known shape is a page-shape break, so a drifted price column
    cannot silently read as an unpriced row.
    """
    text = cell.get_text(" ", strip=True)
    if text == _FREE:
        return 0.0, None
    match = _CACHED_RE.fullmatch(text)
    if match is not None:
        return float(match.group(1)), float(match.group(2))
    match = _RATE_RE.fullmatch(text)
    if match is not None:
        return float(match.group(1)), None
    if _AUDIO_RE.fullmatch(text) is not None:
        return None
    raise FetchError(f"unreadable input price cell {text!r} on {url}")


def _output_amount(cell: Tag, url: str) -> float:
    """the per-1M output rate; "Free" is a zero rate, other shapes raise."""
    text = cell.get_text(" ", strip=True)
    if text == _FREE:
        return 0.0
    match = _RATE_RE.fullmatch(text)
    if match is not None:
        return float(match.group(1))
    raise FetchError(f"unreadable output price cell {text!r} on {url}")


def detect(cfg: ProviderCfg) -> list[str]:
    """per-token-priced model slugs, page order; unpriced rows are skipped."""
    soup = _page(cfg.detector_url)
    table = _model_table(soup, cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    for row in table.find("tbody").find_all("tr", recursive=False):
        try:
            cells = _row_cells(row, cfg.detector_url)
            if _input_amounts(cells[2], cfg.detector_url) is None:
                continue
            _output_amount(cells[3], cfg.detector_url)
            model_id = parse_id(cells[0], cells[4], cfg.detector_url)
        except FetchError as exc:
            log.warning("detect skip for %s: %s", cfg.key, exc)
            continue
        if model_id not in seen:
            seen.add(model_id)
            ids.append(model_id)
    if not ids:
        raise FetchError(f"no per-token model rows on {cfg.detector_url}")
    return ids

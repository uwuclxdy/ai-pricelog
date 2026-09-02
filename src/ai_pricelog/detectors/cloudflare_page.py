"""detect token-priced language model ids on the cloudflare workers ai pricing page.

https://developers.cloudflare.com/workers-ai/platform/pricing/ serves one
Model | Price in Tokens | Price in Neurons table per section - five tables
share that header. the LLM section (h2#llm-model-pricing) prices every row
per input and output token and is taken whole; the other section
(h2#other-model-pricing) mixes input-only classifiers and per-image rows,
so only its rows whose token cell parses into an input+output pair are
taken (m2m100, indictrans2, moondream3.1-9B-A2B today). embeddings, image,
and audio are out of scope. ids are the page spelling of the api id
("@cf/meta/llama-3.2-1b-instruct"), already lowercase, guarded by the
stored id charset with "@" allowed. the Price in Neurons column is an
equivalent unit the index has no slot for and is ignored. an LLM-table row
whose token cell stopped parsing into input+output rates is additive
drift: detection skips it with a warning (plan #22). a page without
either section, its table, or any usable ids is a parse failure
(FetchError).
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup, Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup, fold_heading

log = logging.getLogger(__name__)

_ID_PATTERN = re.compile(r"^@[a-z0-9][a-z0-9._/-]*$")
_HEADER = tuple(fold_heading(cell) for cell in ("Model", "Price in Tokens", "Price in Neurons"))
_SECTION_IDS = ("llm-model-pricing", "other-model-pricing")
_RATE_LINE_RE = re.compile(r"\$(\d+(?:\.\d+)?) per M (cached input|input|output) tokens")


def detect(cfg: ProviderCfg) -> list[str]:
    """current token-priced model ids, page order, deduped."""
    soup = fetch_soup(cfg.detector_url)
    tables = _section_tables(soup, cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    for index, table in enumerate(tables):
        for cells in _table_rows(table):
            if not cells:
                continue
            normalized = _model_id(cells[0])
            if not _ID_PATTERN.fullmatch(normalized) or normalized in seen:
                continue
            try:
                if len(cells) > 1 and index == 0:
                    # the LLM table prices every row per input and output token;
                    # a row that stopped doing so is additive drift, skipped
                    _token_rates(cells[1], normalized, cfg.detector_url)
                elif len(cells) > 1 and _token_rates_opt(cells[1]) is None:
                    # the other section mixes input-only and per-image rows;
                    # only rows with a clean input+output pair are token-priced
                    continue
            except FetchError as exc:
                log.warning("detect skip for %s: %s", cfg.key, exc)
                continue
            seen.add(normalized)
            ids.append(normalized)
    if not ids:
        raise FetchError(f"no model ids in the pricing tables on {cfg.detector_url}")
    return ids


def _section_tables(soup: BeautifulSoup, url: str) -> list[Tag]:
    """the header-matched table per section, in section order.

    each section's table must sit before the next h2; a missing section or
    table is a parse failure, so a rename cannot silently shrink the seed.
    """
    tables: list[Tag] = []
    for section_id in _SECTION_IDS:
        heading = soup.find(id=section_id)
        if heading is None:
            raise FetchError(f"no {section_id} pricing section on {url}")
        found = False
        for element in heading.find_all_next(["h2", "table"]):
            if element.name == "h2":
                break
            if _header_matches(element):
                tables.append(element)
                found = True
                break
        if not found:
            raise FetchError(f"no {section_id} pricing table on {url}")
    return tables


def _header_matches(table: Tag) -> bool:
    thead = table.find("thead")
    if thead is None:
        return False
    headers = tuple(fold_heading(th.get_text(" ", strip=True)) for th in thead.find_all("th"))
    return headers == _HEADER


def _table_rows(table: Tag) -> list[list[Tag]]:
    """the table's own rows as td cell lists (nested tables excluded)."""
    return [
        row.find_all("td", recursive=False)
        for row in table.find_all("tr")
        if row.find_parent("table") is table
    ]


def _model_id(cell: Tag) -> str:
    return cell.get_text(" ", strip=True).lower()


def _token_rates_opt(cell: Tag) -> tuple[float, float, float | None] | None:
    """input / output / cached-input per-1M dollars, or None when the cell
    does not hold a clean input+output pair (input-only or per-image rows)."""
    kinds: dict[str, float] = {}
    for line in cell.stripped_strings:
        match = _RATE_LINE_RE.fullmatch(line)
        if match is None or match.group(2) in kinds:
            return None
        kinds[match.group(2)] = float(match.group(1))
    if "input" not in kinds or "output" not in kinds:
        return None
    return kinds["input"], kinds["output"], kinds.get("cached input")


def _token_rates(cell: Tag, model_id: str, url: str) -> tuple[float, float, float | None]:
    """the raising form: an unknown line, a duplicate label, or no
    input/output pair is a page-shape break naming the offending line."""
    kinds: dict[str, float] = {}
    for line in cell.stripped_strings:
        match = _RATE_LINE_RE.fullmatch(line)
        if match is None:
            raise FetchError(f"malformed pricing cell for {model_id} on {url}: {line!r}")
        kind = match.group(2)
        if kind in kinds:
            raise FetchError(
                f"malformed pricing cell for {model_id} on {url}: duplicate {kind} line"
            )
        kinds[kind] = float(match.group(1))
    if "input" not in kinds or "output" not in kinds:
        raise FetchError(
            f"malformed pricing cell for {model_id} on {url}: missing input or output rate"
        )
    return kinds["input"], kinds["output"], kinds.get("cached input")

"""detect model ids on the kimi platform models page.

models.md (https://platform.kimi.ai/docs/models.md) is static markdown.
model tables carry a `Model Name` header (pinned after folding case,
whitespace, and &/and via web.fold_heading) and the first column of every
body row holds the raw model id, backtick-wrapped. separator cells are
GFM-minimal single dashes (`| - | - |`) since the 2026-09-28 docs
restructure. the table under a heading
containing "deprecated" is excluded. ids are lowercased (they are lowercase
on the page already; litellm keys are lowercase). a page with no Model Name
table rows is a parse failure (FetchError).

the candidates the models page gives and the prices the chat page carries
can disagree: the deprecated table holds the K2 series (measured 2026-11-19),
which the chat page still prices for existing users. `detect_priced` reads
the chat page's priced rows through the scraper's own table reader, so
absence keys on what is still priced rather than on what is still listed
for new users.
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.scrapers import moonshot_page as scraper
from ai_pricelog.web import FetchError, fetch_text, fold_heading, markdown_lines

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
_HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.*)")
_SEPARATOR_PATTERN = re.compile(r"^:?-+:?$")
_FOLDED_MODEL_NAME_HEADER = fold_heading("model name")


def detect(cfg: ProviderCfg) -> list[str]:
    ids: list[str] = []
    heading = ""
    header: list[str] | None = None
    header_seen = False
    for line in markdown_lines(fetch_text(cfg.detector_url)):
        heading_match = _HEADING_PATTERN.match(line)
        if heading_match:
            heading = heading_match.group(1).strip().lower()
            header = None
            header_seen = False
            continue
        cells = _table_cells(line)
        if cells is None:
            header = None
            header_seen = False
            continue
        if header is None:
            header = cells
            continue
        if _is_separator(cells):
            header_seen = True
            continue
        if (
            header_seen
            and fold_heading(header[0]) == _FOLDED_MODEL_NAME_HEADER
            and "deprecated" not in heading
        ):
            candidate = cells[0].strip("`").strip().lower()
            if _ID_PATTERN.fullmatch(candidate):
                ids.append(candidate)
    if not ids:
        raise FetchError(f"no Model Name table rows on {cfg.detector_url}")
    return ids


def detect_priced(cfg: ProviderCfg) -> list[str]:
    """the ids the chat pricing page prices: the priced set absence keys on.

    an id here but not in `detect` stays live and refreshes through its
    stored row; an id the page stops pricing counts absent as before. a page
    the reader prices nothing on raises, so a shape break skips the absence
    counters instead of marking every stored id absent.
    """
    model_ids, page_url = scraper.priced_model_ids(cfg)
    ids: list[str] = []
    for model_id in model_ids:
        candidate = model_id.strip().lower()
        if _ID_PATTERN.fullmatch(candidate) and candidate not in ids:
            ids.append(candidate)
    if not ids:
        raise FetchError(f"no priced model rows on {page_url}")
    return ids


def _table_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(_SEPARATOR_PATTERN.fullmatch(cell) for cell in cells)

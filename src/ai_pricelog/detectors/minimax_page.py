"""detect MiniMax language models from the models-intro page.

reads https://platform.minimax.io/docs/guides/models-intro.md (static markdown).
language tables list each model as a link in the first cell, either markdown or
an html <a> tag (the 2026-09-28 restructure wraps preview models in <a>); only
ids matching ^MiniMax-M\\d[\\w.-]*$ qualify: a version digit must follow
`MiniMax-M`, so `MiniMax-Music3` and `MiniMax-MCP` never read. ids are returned
as written on the page: the docs spell some legacy models with `-highspeed`
where litellm's file has `-lightning`; the human verifier reconciles that drift.

a pipe block that links a MiniMax-M id in a line's first non-empty cell but
fails table recognition (a broken separator) is additive drift: detection
skips it with a warning naming the id (plan #22); the line's cells come from
the table parser's shared cell split (markdown_row_cells), so a change to
that split reaches the scan; an id linked only from a description cell never
names a skip. a data row whose name cell - the first
non-empty cell, a leading `||` shifting it right - spells a MiniMax-M id the
detector could not read as a language link (the name cell's visible text:
markdown links reduced to their text, html tags removed, never a link target;
the id is case-insensitive and its `MiniMax[-\\s]` prefix optional, so a spaced
`MiniMax M2.7`, a lowercase `minimax-m2.7` and a prefix-less `M2.7` read,
while `MiniMax-Music3`, `MiniMax-MCP` and a longer token's tail
(`Hailuo-M2.7`) never read) skips with a warning naming
that id as the page spells it, so a dropped id in one of those shapes never
runs its absence counter silently (a zero-width space or a space between `M`
and the version digit still drops silently); a markdown emphasis marker is
no part of an id - an `_` at a word edge is a boundary, an `_` between two
word characters is not - so an italic name cell (`_MiniMax-M2.7_`, `_M2.7_`,
plain or linked) skips naming the id without the markers, while
`M2.7_highspeed` reads as one longer token, never `M2.7`; a description or
features cell after the name cell never names a skip, and a row whose name
cell spells no such id (an empty name cell in the video/audio/music tables,
a spacer row) stays silent. a page with no pipe lines or no model ids still raises.
"""

from __future__ import annotations

import logging
import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import (
    FetchError,
    extract_markdown_tables,
    fetch_text,
    markdown_pipe_blocks,
    markdown_row_cells,
)

log = logging.getLogger(__name__)

_ID_RE = re.compile(r"^MiniMax-M\d[\w.-]*$")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_ANCHOR_RE = re.compile(r"<a\s[^>]*>([^<]+)</a>")
# a markdown emphasis marker is no part of an id: an `_` at a word edge is a
# boundary, an `_` between two word characters is not; the class guards keep
# every other word/punct char's boundary behaviour unchanged
_ID_LEFT_EDGE = r"(?<![A-Za-z0-9.-])(?<![^\W_])(?<!\w_)"
_ID_RIGHT_EDGE = r"(?![A-Za-z0-9.-])(?![^\W_])(?!_\w)"
_BARE_ID_RE = re.compile(
    _ID_LEFT_EDGE + r"(?:MiniMax[-\s])?M\d[\w.-]*?" + _ID_RIGHT_EDGE, re.IGNORECASE
)
_TAG_RE = re.compile(r"<[^>]*>")


def _model_name(cell: str) -> str:
    """the link text of a markdown or html model link, else ""."""
    match = _LINK_RE.search(cell) or _ANCHOR_RE.search(cell)
    return match.group(1) if match else ""


def _first_model_name(block: list[str]) -> str | None:
    """the first MiniMax-M id a pipe block links in a line's first non-empty cell, or None.

    the cells come from the table parser's shared cell split
    (markdown_row_cells), so a change to that split reaches the scan.
    """
    for line in block:
        cells = markdown_row_cells(line)
        cell = next((cell for cell in cells if cell), "")
        for pattern in (_LINK_RE, _ANCHOR_RE):
            for match in pattern.finditer(cell):
                if _ID_RE.fullmatch(match.group(1)):
                    return match.group(1)
    return None


def _row_model_id(row: list[str]) -> str | None:
    """the MiniMax-M id a data row's name cell spells, or None.

    the name cell is the first non-empty cell (a leading `||` shifts it
    right); its visible text is searched (markdown links reduced to their
    text, html tags removed, never a link target). a markdown emphasis
    marker is no part of an id: an `_` at a word edge is a boundary
    (`_MiniMax-M2.7_` reads `MiniMax-M2.7`), an `_` between two word
    characters is not (`M2.7_highspeed` reads as one longer token).
    description and features cells never name a skip.
    """
    name_cell = next((cell for cell in row if cell), "")
    visible = _TAG_RE.sub(" ", _LINK_RE.sub(r"\1", name_cell))
    match = _BARE_ID_RE.search(visible)
    return match.group(0) if match else None


def detect(cfg: ProviderCfg) -> list[str]:
    """current MiniMax-M ids, page order; unreadable tables/rows detect-skip."""
    text = fetch_text(cfg.detector_url)
    blocks = markdown_pipe_blocks(text)
    if not blocks:
        raise FetchError(f"no pipe lines found on {cfg.detector_url}")
    ids: list[str] = []
    seen: set[str] = set()
    for block in blocks:
        tables = extract_markdown_tables("\n".join(block))
        if not tables:
            name = _first_model_name(block)
            if name is not None:
                log.warning(
                    "detect skip for %s: unreadable table block naming %r on %s",
                    cfg.key,
                    name,
                    cfg.detector_url,
                )
            continue
        for row in tables[0][2:]:
            name = _model_name(row[0]) if row else ""
            if _ID_RE.fullmatch(name):
                if name not in seen:
                    seen.add(name)
                    ids.append(name)
                continue
            skip_id = _row_model_id(row)
            if skip_id is not None:
                log.warning(
                    "detect skip for %s: unreadable model row naming %r on %s",
                    cfg.key,
                    skip_id,
                    cfg.detector_url,
                )
    if not ids:
        raise FetchError(f"no model ids matched on {cfg.detector_url}")
    return ids

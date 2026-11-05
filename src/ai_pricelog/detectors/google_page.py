"""detect gemini/gemma model ids on the AI Studio pricing markdown twin.

reads https://aistudio.google.com/docs/pricing.md, the static markdown twin
the pricing page serves beside its Angular shell (the old ai.google.dev page
302s into an OAuth auto-signin chain and is dead to a static fetch).
devsite markdown: `## Title  {% id="anchor" %}` headings open sections,
`{% tabs %}` wrap the tier tables, and `{% table %}` blocks hold rows as
`* cell` bullet groups split by `---` lines.

a section spells its model ids as code-span links into /docs/models/: the
api id is the link TEXT (the link target is the model page's slug and can
differ from it), falling back to the heading anchor for a section that
spells no link (gemma-4).

only sections carrying a token pricing table are watched: a `{% table %}`
whose header group holds "Paid Tier, per 1M tokens in USD" and that has a
row group whose first cell starts "Input price" or "Text input price". that
keeps out lyria (per request) and the tools/agents tables. input-only
sections (the embeddings) are detected; the scraper prices them with output
0 (embeddings bill input tokens only). ids are emitted as written on the
page, page order.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_text, markdown_lines

_PAID_HEADER = "Paid Tier, per 1M tokens in USD"

_SECTION_HEADING_RE = re.compile(r'^## .+?\{% id="(?P<anchor>[^"]+)" %\}\s*$')
_MODEL_LINK_RE = re.compile(r"\[`(?P<slug>[^\s`]+)`\]\((?P<target>/docs/models/\S+?)\)")
_DEVSITE_TAG_RE = re.compile(r"\{%.*?%\}")
_CELL_RE = re.compile(r"^\s*\* (?P<text>.*)$")
_ROW_SEPARATOR_RE = re.compile(r"^\s*---\s*$")
_TABS_OPEN_RE = re.compile(r"^\s*\{% tabs %\}\s*$")
_TABS_CLOSE_RE = re.compile(r"^\s*\{% /tabs %\}\s*$")
_TAB_OPEN_RE = re.compile(r'^\s*\{% tab title="(?P<title>[^"]*)" %\}\s*$')
_TAB_CLOSE_RE = re.compile(r"^\s*\{% /tab %\}\s*$")
_TABLE_OPEN_RE = re.compile(r"^\s*\{% table %\}\s*$")
_TABLE_CLOSE_RE = re.compile(r"^\s*\{% /table %\}\s*$")


@dataclass
class _Section:
    anchor: str
    body: str


@dataclass
class _Table:
    header: list[str]
    rows: list[list[str]]


def _sections(text: str) -> list[_Section]:
    """the page's `{% id %}` sections in page order; a body runs to the next heading."""
    sections: list[_Section] = []
    anchor: str | None = None
    lines: list[str] = []
    for line in markdown_lines(text):
        heading = _SECTION_HEADING_RE.match(line)
        if heading is not None:
            if anchor is not None:
                sections.append(_Section(anchor, "\n".join(lines)))
            anchor = heading.group("anchor")
            lines = []
        elif anchor is not None:
            lines.append(line)
    if anchor is not None:
        sections.append(_Section(anchor, "\n".join(lines)))
    return sections


def _slugs(section: _Section) -> list[str]:
    """the model ids a section spells: its lead-in /docs/models/ links'
    code-span texts, else the heading anchor. the scan stops at the section's
    first `{% table %}` block — every real id link sits in the lead-in
    two-column-layout, and a cross-link past the table must not emit an id
    whose scrape would resolve to the host section's rates. the link TEXT is
    the api id (the target is the model page's slug and can differ)."""
    leadin: list[str] = []
    for line in markdown_lines(section.body):
        if _TABLE_OPEN_RE.match(line):
            break
        leadin.append(line)
    slugs = [match.group("slug") for match in _MODEL_LINK_RE.finditer("\n".join(leadin))]
    if slugs:
        return slugs
    return [section.anchor]


def _clean_cell(text: str) -> str:
    """a cell's text: devsite tags read as the spaces a tag boundary is in the
    rendered cell, whitespace collapsed (cells hard-wrap with trailing spaces)."""
    return " ".join(_DEVSITE_TAG_RE.sub(" ", text).split())


def _parse_table(lines: list[str]) -> _Table | None:
    """a `{% table %}` block's rows: `* cell` bullets whose wrapped lines join
    the cell, `---` lines splitting the row groups; None with no row at all."""
    groups: list[list[list[str]]] = []
    cells: list[list[str]] = []
    for line in lines:
        if _ROW_SEPARATOR_RE.match(line):
            if cells:
                groups.append(cells)
            cells = []
        elif (cell := _CELL_RE.match(line)) is not None:
            cells.append([cell.group("text")])
        elif line.strip() and cells:
            cells[-1].append(line.strip())
    if cells:
        groups.append(cells)
    if not groups:
        return None

    def cell_text(raw_lines: list[str]) -> str:
        return _clean_cell(" ".join(raw_lines))

    return _Table(
        header=[cell_text(cell) for cell in groups[0]],
        rows=[[cell_text(cell) for cell in group] for group in groups[1:]],
    )


def _section_tables(section: _Section) -> Iterator[tuple[str | None, _Table]]:
    """the section's tables with the title of the tab each sits in (None outside
    any tab)."""
    tab: str | None = None
    table_lines: list[str] | None = None
    for line in markdown_lines(section.body):
        if table_lines is not None:
            if _TABLE_CLOSE_RE.match(line):
                parsed = _parse_table(table_lines)
                if parsed is not None:
                    yield (tab, parsed)
                table_lines = None
            else:
                table_lines.append(line)
            continue
        if (tab_open := _TAB_OPEN_RE.match(line)) is not None:
            tab = tab_open.group("title")
        elif _TAB_CLOSE_RE.match(line) or _TABS_OPEN_RE.match(line) or _TABS_CLOSE_RE.match(line):
            tab = None
        elif _TABLE_OPEN_RE.match(line):
            table_lines = []


def _section_prose(section: _Section) -> str:
    """the section body outside its `{% table %}` blocks, lines joined: the
    prose a phrase scan reads (the old html surface read paragraphs, never
    cells)."""
    prose: list[str] = []
    in_table = False
    for line in markdown_lines(section.body):
        if _TABLE_OPEN_RE.match(line):
            in_table = True
        elif _TABLE_CLOSE_RE.match(line):
            in_table = False
        elif not in_table and line.strip():
            prose.append(line.strip())
    return " ".join(prose)


def _is_token_table(table: _Table) -> bool:
    """whether the table prices tokens: the paid header plus an input-price row."""
    if not any(_PAID_HEADER in cell for cell in table.header):
        return False
    return any(
        row and (row[0].startswith("Input price") or row[0].startswith("Text input price"))
        for row in table.rows
    )


def detect(cfg: ProviderCfg) -> list[str]:
    text = fetch_text(cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    token_sections = 0
    for section in _sections(text):
        if not any(_is_token_table(table) for _, table in _section_tables(section)):
            continue
        token_sections += 1
        for slug in _slugs(section):
            if slug not in seen:
                seen.add(slug)
                ids.append(slug)
    if not token_sections:
        raise FetchError(f"no token pricing tables found on {cfg.detector_url}")
    return ids

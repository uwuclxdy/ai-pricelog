"""detect databricks foundation-model-serving model ids from the pricing page.

reads https://www.databricks.com/product/pricing/foundation-model-serving
(static server-rendered html). the per-token rates live in two tables,
the standard and the priority one, each pinned by its `Input | Output |
Cache read` sub-header row and its tier span spelling (the standard span
read "Standard Pay Per Token (DBU Per 1M Tokens)" until the page dropped
the qualifier on 2026-10-06; both spellings stay pinned). a tier span may
sit in the table's own <caption> or in the nearest preceding heading that
owns the table (the table is the first table after the heading), but only
on a one-row `Model | Input | Output | Cache read` thead; the folded span
still must equal a pinned spelling, and a caption and owning heading that
fold to different pinned tiers raise. both tables share display names, so a
tier is never guessed: `_model_tables` reads each tier off its pinned
span, and the table read as standard carries a content guard (see
_guard_standard). a table's rows are the <tr> elements whose nearest table
is this table, thead rows aside; a nested table's rows never count. the
per-hour tables never match: the Provisioned Throughput table
names reservation terms in its sub-header, and the Batch Inference table
carries no sub-header at all; a table that misses the pin but whose own
rows (own thead rows included) name Input | Output | Cache read as three
consecutive cells and a mapped display raises instead of vanishing. the
page carries display names only ("Kimi K3", "GTE"), so each row's canonical
ids resolve through the display-name mappings: the standard table's names ->
the openrouter id spelling minus its vendor prefix (measured against the
stored openrouter id set 2026-08-29), the priority table's names -> the
same with a "-priority" suffix. the "GLM-5.2, 5.3" row carries one rate
pair covering both store ids. the ⌖ marker (regional-processing uplift,
per the page's footnote 4) strips off the name. rate cells read numeric
DBU amounts or "-" (unpriced); a row with a "-" input is known unpriced
and skipped, "-" output reads as a zero output rate (embedding rows bill
input only); an unpriced row that is plainly a label warns on the soft
line. rows outside these shapes (odd cell counts, unknown rate-cell text,
unmapped names) are additive drift: detection skips them with a warning
(plan #22). a row that misses the four-cell shape, or whose input cell is
no rate, is a section row and warns on the soft parse-skip line only when
its own subtree is plainly a label: it holds no graphic element (img, svg,
picture, object, embed, input, canvas, iframe, video) nor an element whose
ARIA role is img, no element carrying an alt, aria-label, aria-labelledby
or title, and no nested table, and either its own visible text is empty,
it repeats the Model | Input | Output | Cache read header row (its own
cells and its own text both fold to it), or it has exactly one non-empty
own cell and its own text holds no Unicode digit and names no mapped
display; every other odd row keeps the detect skip. a row's own subtree
leaves out a nested row an omitted </tr> leaves inside it, so such a label
stays soft while the nested row prices.
the scraper stays strict for the matched row, so a drifted price column
cannot read as a missing model. a page whose per-token tables or priced
rows are gone still raises. zero-rate rows stay emitted (the scraper
decides); the scraper's dedup_keys maps the page's undated deepseek
spellings back to the dated store spellings their rows live under.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from functools import cache

from bs4 import BeautifulSoup, NavigableString, Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import (
    FetchError,
    fetch_soup,
    fold_heading,
    own_cells,
    own_rows,
    own_table_rows,
)

log = logging.getLogger(__name__)

# the second header row of the watched tables; fold_heading tolerates case,
# whitespace and &/and drift
_TABLE_HEADERS = ("Input", "Output", "Cache read")
_FOLDED_TABLE_HEADERS = tuple(fold_heading(cell) for cell in _TABLE_HEADERS)
_STANDARD_SPANS = frozenset(
    fold_heading(span)
    for span in (
        "Standard Pay Per Token (DBU Per 1M Tokens)",
        "Pay Per Token (DBU Per 1M Tokens)",
    )
)
_PRIORITY_SPANS = frozenset({fold_heading("Priority Pay Per Token (DBU Per 1M Tokens)")})
_RATE_RE = re.compile(r"^\d+(?:\.\d+)?$")
_DASH = "-"
_UPLIFT = "⌖"  # the ⌖ regional-uplift marker glued onto some names
_ONE_ROW_HEADER_CELLS = ("Model", "Input", "Output", "Cache read")
_FOLDED_ONE_ROW_HEADER = tuple(fold_heading(cell) for cell in _ONE_ROW_HEADER_CELLS)
_HEADING_NAMES = ("h1", "h2", "h3", "h4", "h5", "h6")
_GRAPHIC_NAMES = ("img", "svg", "picture", "object", "embed", "input", "canvas", "iframe", "video")
_NAME_ATTRS = ("alt", "aria-label", "aria-labelledby", "title")

# display name -> canonical ids, standard table. the ids are the stored
# openrouter id set's spellings minus the vendor prefix
# ("moonshotai/kimi-k3" -> "kimi-k3"), measured 2026-08-29; the 2026-09-05
# page restructure renamed several displays ("GPT-OSS-120B", "Qwen 3 80B
# Instruct" = the stored qwen3-next-80b id), dropped the deepseek snapshot
# dates, and merged GLM-5.2 and GLM-5.3 into one row at their shared rate
# pair.
_DISPLAY_IDS: dict[str, tuple[str, ...]] = {
    "Kimi K3": ("kimi-k3",),
    "Kimi K2.7": ("kimi-k2.7",),
    "GLM-5.2, 5.3": ("glm-5.2", "glm-5.3"),
    "GLM-5.3 Flash": ("glm-5.3-flash",),
    "Inkling": ("inkling",),
    "DeepSeek V4 Pro": ("deepseek-v4-pro",),
    "DeepSeek V4.1 Flash": ("deepseek-v4.1-flash",),
    "DeepSeek V4 Flash": ("deepseek-v4-flash",),
    "Qwen 3.5 122B": ("qwen3.5-122b-a10b",),
    "Qwen 3 80B Instruct": ("qwen3-next-80b-a3b-instruct",),
    "GPT-OSS-120B": ("gpt-oss-120b",),
    "GPT-OSS-20B": ("gpt-oss-20b",),
    "Llama 4 Maverick": ("llama-4-maverick",),
    "Llama 3.3 70B": ("llama-3.3-70b-instruct",),
    "Gemma 3 12B": ("gemma-3-12b-it",),
    "Llama 3.1 8B": ("llama-3.1-8b-instruct",),
    "Qwen 3 0.6B Embedding": ("qwen3-embedding-0.6b",),
    "GTE": ("gte",),
    "BGE Large": ("bge-large",),
}

# the priority table re-lists a subset of the models at priority rates,
# under the base display spellings (no "(Priority)" annotation); since the
# 2026-09-21 page change it carries the merged GLM row too, covering both
# "-priority" ids at the one rate pair like the standard table's merged row
_PRIORITY_DISPLAYS: dict[str, tuple[str, ...]] = {
    "Kimi K3": ("kimi-k3-priority",),
    "GLM-5.2, 5.3": ("glm-5.2-priority", "glm-5.3-priority"),
    "GLM-5.3 Flash": ("glm-5.3-flash-priority",),
    "Qwen 3.5 122B": ("qwen3.5-122b-a10b-priority",),
}

# the display names only the standard table lists (the priority table
# re-lists a subset under the same spellings); _guard_standard's evidence.
_STANDARD_ONLY_NAMES = frozenset(_DISPLAY_IDS) - frozenset(_PRIORITY_DISPLAYS)

# every display name either map holds; a table naming one is a pricing-table
# candidate for the off-pin/nested check.
_KNOWN_DISPLAYS = frozenset(_DISPLAY_IDS) | frozenset(_PRIORITY_DISPLAYS)


@cache
def _page(url: str) -> BeautifulSoup:
    """fetch and parse the page; cached per url so the scraper reuses this fetch."""
    return fetch_soup(url)


def _model_tables(soup: BeautifulSoup, url: str) -> list[tuple[Tag, bool]]:
    """the per-token tables in page order, each paired with its tier (True = priority).

    a table pins when its thead holds exactly two header rows and an own
    row exists, and the second header row folds to Input | Output | Cache
    read; the per-hour tables never match (the Provisioned Throughput table
    names reservation terms in its sub-header, and the Batch Inference
    table carries no sub-header). a one-row `Model | Input | Output | Cache
    read` thead pins through its <caption> or the nearest preceding heading
    that owns it (the table is the first table after the heading) instead.
    a table missing the pin raises only when it looks like a pricing table:
    its own cells carry a pinned tier span (a nested table's cells aside)
    and one of its own rows (thead included) has a first cell naming a mapped display, or
    a caption/heading span that folds to no pinned spelling and a mapped
    display, or the sub-header (own rows, thead included) and a mapped
    display. a top-level table carrying a pinned span raises off-pin, a
    nested one raises its own message, a top-level one naming the
    sub-header raises the unpinned message, a caption/heading span outside
    the pinned spellings raises the unreadable-span message, and a caption
    and an owning heading folding to different pinned tiers raise. a
    table whose span and sub-header both drift carries no pinned span and
    no sub-header, so it reads like the per-hour tables. raises also: no
    table matches, a tier span row outside the header shape, a span outside
    the pinned spellings, a tier read twice, no standard table. the table
    read as standard carries a content guard (_guard_standard) on every
    page.
    """
    tables: list[tuple[Tag, bool]] = []
    for table in soup.find_all("table"):
        if table.find_parent("table") is not None:
            span = _pinned_span(table) or _caption_heading_span(table, url)
            if span is not None and _names_known_model(table):
                raise FetchError(f"pay-per-token table {span!r} nested in another table on {url}")
            if _names_sub_header(table) and _names_known_model(table):
                raise FetchError(f"pay-per-token table nested in another table on {url}")
            continue
        if _structural_pin(table):
            tables.append((table, _is_priority_table(table, url)))
            continue
        span = _caption_heading_span(table, url)
        if span is not None:
            priority = _tier(span)
            if priority is not None:
                tables.append((table, priority))
                continue
            if _names_known_model(table):
                raise FetchError(f"unreadable pay-per-token tier span {span!r} on {url}")
        span = _pinned_span(table)
        if span is not None and _names_known_model(table):
            raise FetchError(f"pay-per-token table {span!r} off the sub-header pin on {url}")
        if _names_sub_header(table) and _names_known_model(table):
            raise FetchError(
                f"unpinned table naming Input | Output | Cache read and a mapped model on {url}"
            )
    if not tables:
        raise FetchError(f"no foundation-model-serving dbu table on {url}")
    for priority, tier in ((False, "standard"), (True, "priority")):
        if sum(1 for _table, table_priority in tables if table_priority is priority) > 1:
            raise FetchError(f"two pay-per-token tables read as the {tier} tier on {url}")
    if all(table_priority for _table, table_priority in tables):
        raise FetchError(f"no standard pay-per-token table on {url}")
    _guard_standard(next(table for table, priority in tables if not priority), url)
    return tables


def _structural_pin(table: Tag) -> bool:
    """whether the table pins: an own row, a two-row thead, and a second
    header row whose own <th> cells fold to Input | Output | Cache read."""
    thead = table.find("thead", recursive=False)
    if thead is None or next(own_rows(table), None) is None:
        return False
    header_rows = thead.find_all("tr", recursive=False)
    if len(header_rows) != 2:
        return False
    cells = [
        cell.get_text(" ", strip=True) for cell in own_cells(header_rows[1]) if cell.name == "th"
    ]
    return tuple(fold_heading(cell) for cell in cells[:3]) == _FOLDED_TABLE_HEADERS


def _pinned_span(table: Tag) -> str | None:
    """the first of the table's own cells (a nested table's cells aside) folding
    to a pinned tier span."""
    for cell in table.find_all(["th", "td"]):
        if cell.find_parent("table") is not table:
            continue
        span = fold_heading(cell.get_text(" ", strip=True))
        if span in _STANDARD_SPANS or span in _PRIORITY_SPANS:
            return span
    return None


def _one_row_thead(table: Tag) -> bool:
    """whether the thead's one row carries the Model | Input | Output | Cache
    read shape as its own <th> cells."""
    thead = table.find("thead", recursive=False)
    if thead is None:
        return False
    rows = thead.find_all("tr", recursive=False)
    if len(rows) != 1:
        return False
    cells = [cell.get_text(" ", strip=True) for cell in own_cells(rows[0]) if cell.name == "th"]
    return len(cells) == 4 and tuple(fold_heading(cell) for cell in cells) == _FOLDED_ONE_ROW_HEADER


def _folded_text(node: Tag | None) -> str | None:
    """the node's visible text folded, or None when the node is absent or blank."""
    if node is None:
        return None
    return fold_heading(node.get_text(" ", strip=True)) or None


def _tier(span: str | None) -> bool | None:
    """the tier a folded span names: True for priority, False for standard, None
    outside the pinned spellings."""
    if span in _PRIORITY_SPANS:
        return True
    if span in _STANDARD_SPANS:
        return False
    return None


def _caption_heading_span(table: Tag, url: str) -> str | None:
    """the folded tier span a one-row thead table carries in its caption or
    the nearest preceding heading that owns it; None when the shape or text
    is absent. a caption and an owning heading naming different pinned tiers
    raise: reading the caption alone would silently take its tier."""
    if not _one_row_thead(table):
        return None
    caption = _folded_text(table.find("caption", recursive=False))
    heading = table.find_previous(_HEADING_NAMES)
    if heading is not None and heading.find_next("table") is not table:
        heading = None
    heading_span = _folded_text(heading)
    caption_tier = _tier(caption)
    heading_tier = _tier(heading_span)
    if caption_tier is not None and heading_tier is not None and caption_tier != heading_tier:
        raise FetchError(
            f"caption {caption!r} and heading {heading_span!r} name different tiers on {url}"
        )
    return caption if caption is not None else heading_span


def _names_known_model(table: Tag) -> bool:
    """whether one of the table's own rows (own thead rows included) has a first
    cell naming a mapped display."""
    for row in own_table_rows(table):
        cells = own_cells(row)
        if cells and _display_name(cells[0]) in _KNOWN_DISPLAYS:
            return True
    return False


def _names_sub_header(table: Tag) -> bool:
    """whether one of the table's own rows (own thead rows included) folds to
    Input | Output | Cache read as three consecutive cells, wherever the row
    starts."""
    thead = table.find("thead", recursive=False)
    rows: list[Tag] = thead.find_all("tr", recursive=False) if thead is not None else []
    rows.extend(own_rows(table))
    for row in rows:
        cells = own_cells(row)
        folded = tuple(fold_heading(cell.get_text(" ", strip=True)) for cell in cells)
        if any(folded[i : i + 3] == _FOLDED_TABLE_HEADERS for i in range(len(folded) - 2)):
            return True
    return False


def _folded_span(table: Tag) -> str | None:
    """the second own cell of the first row whose nearest table is this table,
    folded; th or td, wherever that row sits."""
    first_row = next(own_table_rows(table), None)
    if first_row is None:
        return None
    cells = own_cells(first_row)
    return fold_heading(cells[1].get_text(" ", strip=True)) if len(cells) >= 2 else None


def _is_priority_table(table: Tag, url: str) -> bool:
    """whether a watched table is the priority one, read off its tier span.

    the first row's second cell names the tier; the folded span (case,
    whitespace and &/and tolerant, like the sub-header pin) must equal a
    pinned spelling, or the table raises.
    """
    span = _folded_span(table)
    if span is None:
        raise FetchError(f"tier span row outside the header shape on {url}")
    priority = _tier(span)
    if priority is None:
        raise FetchError(f"unreadable pay-per-token tier span {span!r} on {url}")
    return priority


def _guard_standard(table: Tag, url: str) -> None:
    """fail a standard-tier table carrying no readable priced standard-only row.

    a table read as the standard tier must price at least one of the
    standard-only display names in a readable rate cell: a relabelled
    priority table's rows would otherwise price the base ids at priority
    rates, and a genuine standard table pricing none of them is a page
    break. evidence is a four-cell row whose input cell reads as a rate; a
    "-", odd-cell or unreadable-input row counts for nothing, and the
    output and cache cells are never read. known window: a relabelled
    priority table that has grown a priced standard-only name before
    _PRIORITY_DISPLAYS maps it still reads as standard; with the labels
    swapped and the priority tier grown, the real standard table reads as
    priority and prices the "-priority" ids at standard rates.
    """
    for row in own_rows(table):
        cells = own_cells(row)
        if len(cells) != 4 or _try_rate(cells[1]) is None:
            continue
        if _display_name(cells[0]) in _STANDARD_ONLY_NAMES:
            return
    raise FetchError(
        f"pay-per-token table read as the standard tier carries no readable"
        f" priced standard-only row on {url}"
    )


def _row_cells(row: Tag, url: str) -> list[Tag]:
    cells = own_cells(row)
    if len(cells) != 4:
        raise FetchError(
            f"row outside the pricing shape on {url}: {row.get_text(' ', strip=True)!r}"
        )
    return cells


def _stripped(text: str) -> str:
    """the text with every non-alphanumeric character removed (letters and digits kept)."""
    return "".join(char for char in text if char.isalnum())


def _folded_letters(text: str) -> str:
    """the text folded onto its base letters: compatibility forms and accents removed."""
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )


def _names_stripped_display(text: str) -> bool:
    """whether the text names a mapped display: its base letters in order, only
    non-alphanumeric characters between them, bounded by non-alphanumeric characters."""
    folded = _folded_letters(text)
    return any(
        re.search(
            r"(?<![^\W_])"
            + r"[\W_]*".join(map(re.escape, _stripped(_folded_letters(name))))
            + r"(?![^\W_])",
            folded,
        )
        for name in _KNOWN_DISPLAYS
    )


def _section_row(row: Tag, cells: list[Tag]) -> str | None:
    """the row's section label, or None when the row may price a model.

    the detect gate sends here every row outside the four-cell shape and
    every four-cell row whose input cell is no rate. the row is a section
    row only when its own subtree is plainly a label: it holds no graphic
    element nor an element whose ARIA role is img, no element carrying an
    alt, aria-label, aria-labelledby or title, and no nested table, and
    either its own visible text is empty, its own cells and its own text
    both fold to the Model | Input | Output | Cache read header, or exactly
    one own cell has non-empty text and its own text holds no Unicode digit
    and names no mapped display. a nested row an omitted </tr> leaves
    inside this one is no part of its own subtree. the label is the row's
    name cell (its first own cell's text, so a rate cell never names it),
    a repeated header row's own text, or blank when the row has no cells.
    everything else returns None and keeps the detect skip.
    """
    own = [node for node in row.find_all(True) if node.find_parent("tr") is row]
    if (
        any(node.name in _GRAPHIC_NAMES or node.get("role") == "img" for node in own)
        or any(node.name == "table" for node in own)
        or any(node.has_attr(attr) for node in own for attr in _NAME_ATTRS)
    ):
        return None
    text = _cell_text(row)
    name = _cell_text(cells[0]).strip() if cells else ""
    if not text:
        return name
    folded = tuple(fold_heading(cell.get_text(" ", strip=True)) for cell in cells)
    if folded == _FOLDED_ONE_ROW_HEADER and fold_heading(text) == " ".join(_FOLDED_ONE_ROW_HEADER):
        return text
    non_empty = [cell for cell in cells if _cell_text(cell).strip()]
    if (
        len(non_empty) == 1
        and not any(char.isdigit() for char in text)
        and not _names_stripped_display(text)
    ):
        return name
    return None


def _cell_text(cell: Tag) -> str:
    """the cell's (or row's) visible text, nested rows and tables, comments, scripts
    and styles excluded."""
    parts: list[str] = []
    for child in cell.children:
        if isinstance(child, Tag):
            if child.name in ("table", "tr"):
                continue
            parts.append(_cell_text(child))
        elif type(child) is NavigableString:
            parts.append(str(child))
    return " ".join(part.strip() for part in parts if part.strip())


def _try_rate(cell: Tag) -> float | None:
    """the cell's DBU amount; every non-numeric shape reads as None."""
    text = cell.get_text(" ", strip=True)
    if text == _DASH:
        return None
    match = _RATE_RE.fullmatch(text)
    return float(match.group(0)) if match is not None else None


def _rate(cell: Tag, url: str) -> float | None:
    """strict: as _try_rate, but a cell outside the known shapes raises.

    the known shapes are a numeric amount and "-" (unpriced); anything else
    is a page-shape break, so a drifted rate column cannot silently read
    as an unpriced row.
    """
    text = cell.get_text(" ", strip=True)
    rate = _try_rate(cell)
    if rate is not None or text == _DASH:
        return rate
    raise FetchError(f"unreadable dbu rate cell {text!r} on {url}")


def _display_name(cell: Tag) -> str:
    """the cell's display name, ⌖ uplift marker stripped."""
    return cell.get_text(" ", strip=True).replace(_UPLIFT, "").strip()


def parse_id(cell: Tag, url: str, priority: bool = False) -> tuple[str, ...]:
    """the row's canonical ids for its display name; unknown names raise."""
    name = _display_name(cell)
    model_ids = (_PRIORITY_DISPLAYS if priority else _DISPLAY_IDS).get(name)
    if model_ids is None:
        raise FetchError(f"unmapped model name {name!r} on {url}")
    return model_ids


def detect(cfg: ProviderCfg) -> list[str]:
    """per-token-priced model ids, standard table then priority; unpriced rows skip."""
    soup = _page(cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    for table, priority in _model_tables(soup, cfg.detector_url):
        for row in own_rows(table):
            cells = own_cells(row)
            if len(cells) != 4 or _try_rate(cells[1]) is None:
                section = _section_row(row, cells)
                if section is not None:
                    log.warning(
                        "parse skip for %s: section row %r on %s",
                        cfg.key,
                        section,
                        cfg.detector_url,
                    )
                    continue
            try:
                cells = _row_cells(row, cfg.detector_url)
                if _rate(cells[1], cfg.detector_url) is None:
                    continue  # a "-" input cell: no per-token pricing
                _rate(cells[2], cfg.detector_url)
                _rate(cells[3], cfg.detector_url)
                model_ids = parse_id(cells[0], cfg.detector_url, priority=priority)
            except FetchError as exc:
                log.warning("detect skip for %s: %s", cfg.key, exc)
                continue
            for model_id in model_ids:
                if model_id not in seen:
                    seen.add(model_id)
                    ids.append(model_id)
    if not ids:
        raise FetchError(f"no per-token model rows on {cfg.detector_url}")
    return ids

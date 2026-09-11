"""Render the static pricing page onto the dist tree.

`render_site` writes `index.html` beside the json surface `build_dist` already
publishes, plus the `site/` assets the page links. The page carries the flat
export in a script island and renders the table in the browser, so a reader
needs no build step and the page makes no network call. The table inside
`<noscript>` is the server-rendered floor: it carries every entry, which is both
what a reader without javascript gets and what the coverage test reads.

The asset tree is committed beside this module rather than vendored at build
time: the publish job runs on a bare checkout.
"""

from __future__ import annotations

import html
import shutil
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

from ai_pricelog.store import _atomic_write

SITE_DIR = "site"

_ASSETS = Path(__file__).with_name("site_assets")

_DASH = "–"

# a page with no icon link ships a 404 for /favicon.ico
_FAVICON = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'"
    "%3E%3Ccircle cx='8' cy='8' r='7' fill='%2368BBEF'/%3E%3C/svg%3E"
)

# screen layout only: every component on the page comes from components.css.
# `html:not(.js)` is the only rule that can hide the interactive half, so a
# browser running the module keeps whatever display the components give it.
_PAGE_STYLE = """
  html:not(.js) .js-only { display: none; }
  .page { padding-block: var(--space-8) var(--space-16); }
  .stack { display: flex; flex-direction: column; gap: var(--space-8); }
  .toolbar .field { max-width: 190px; }
  .toolbar .field.wide { max-width: 320px; }
"""

# first in <head>, so the theme lands before the stylesheet paints
_HEAD_SCRIPT = """
  document.documentElement.classList.add('js');
  var saved = null;
  try { saved = localStorage.getItem('pricelog-theme'); } catch (e) { saved = null; }
  if (saved) document.documentElement.dataset.theme = saved;
"""

# reveals the interactive half's fallback only when the page's own module never
# reported in: a module that dies leaves an empty table with no explanation,
# and this mark is the only thing that tells the two apart
_READY_SCRIPT = """
  addEventListener('load', function () {
    if (document.documentElement.dataset.site === "ready") return;
    var fallback = document.getElementById('app-fallback');
    if (fallback) fallback.hidden = false;
  });
"""

_SORT_ICON = (
    '<span class="th-sort-icon" aria-hidden="true">'
    '<svg class="sort-rest" aria-hidden="true"><use href="#i-sort"/></svg>'
    '<svg class="sort-dir" aria-hidden="true"><use href="#i-chevron-up"/></svg>'
    "</span>"
)

# the sortable columns of the interactive table: key, label, cell class
_COLUMNS = (
    ("name", "model", ""),
    ("vendor", "vendor", ""),
    ("input", "input", "num-col"),
    ("cache_read", "cached input", "num-col"),
    ("output", "output", "num-col"),
)

# the static table's columns, one header per cell it renders
_STATIC_COLUMNS = (
    "model",
    "vendor",
    "source",
    "input",
    "cached input",
    "output",
    "observed",
)


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _rate_text(value: object) -> str:
    """A rate at the shortest form that round-trips it.

    The page's own renderer applies the same rule to the same json number, so
    the two tables print one rate one way; a test pins that agreement over
    every rate the export carries.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return _DASH
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _rates(entry: Mapping[str, object]) -> Mapping[str, object]:
    rates = entry.get("rates")
    return rates if isinstance(rates, Mapping) else {}


def _model_key(entry: Mapping[str, object]) -> str:
    return f"{entry.get('source')}/{entry.get('model_id')}"


def _static_row(entry: Mapping[str, object]) -> str:
    rates = _rates(entry)
    name = entry.get("name")
    name = name if isinstance(name, str) and name else str(entry.get("model_id"))
    removed = entry.get("removed_at")
    tag = f' <span class="tag tag-danger">removed {_esc(removed)}</span>' if removed else ""
    vendor = entry.get("vendor")
    cells = (
        f'<td><span class="table-name">{_esc(name)}</span>{tag}'
        f'<div class="td-sub">{_esc(entry.get("model_id"))}</div></td>',
        f"<td>{_esc(vendor) if vendor else _DASH}</td>",
        f"<td>{_esc(entry.get('source'))}</td>",
        f'<td class="num-col">{_rate_text(rates.get("input"))}</td>',
        f'<td class="num-col">{_rate_text(rates.get("cache_read"))}</td>',
        f'<td class="num-col">{_rate_text(rates.get("output"))}</td>',
        f"<td>{_esc(entry.get('observed_at'))}</td>",
    )
    # data-key is the export's own key, so the coverage test reads each
    # rendered entry back by identity and never by a substring of its cells
    return f'<tr data-key="{_esc(_model_key(entry))}">' + "".join(cells) + "</tr>"


def _page_header(payload: Mapping[str, object], entry_count: int, source_count: int) -> str:
    updated = _esc(payload.get("updated_at"))
    return "".join(
        [
            '<header class="page-header">\n',
            '<div class="page-header-body">\n',
            '<div class="label">genai pricing index</div>\n',
            '<h1 class="page-title">what every watched model costs</h1>\n',
            '<p class="page-meta">\n',
            '<span class="page-meta-item">prices last updated ',
            f'<time datetime="{updated}">{updated}</time></span>\n',
            f'<span class="page-meta-item">{entry_count} models</span>\n',
            f'<span class="page-meta-item">{source_count} sources</span>\n',
            "</p>\n",
            "</div>\n",
            '<button class="btn btn-icon" data-theme-toggle aria-pressed="false"'
            ' aria-label="switch to light theme">\n',
            '<svg class="icon-sun" aria-hidden="true"><use href="#i-sun"/></svg>\n',
            '<svg class="icon-moon" aria-hidden="true"><use href="#i-moon"/></svg>\n',
            "</button>\n",
            "</header>\n",
        ]
    )


def _toolbar() -> str:
    return "".join(
        [
            '<div class="toolbar js-only">\n',
            '<div class="field wide">\n',
            '<label class="field-label" for="q">search name or vendor</label>\n',
            '<div class="input-wrap has-icon">\n',
            '<span class="input-icon">'
            '<svg aria-hidden="true"><use href="#i-search"/></svg></span>\n',
            '<input class="input" id="q" type="search" autocomplete="off"'
            ' placeholder="deepseek, anthropic">\n',
            "</div>\n",
            "</div>\n",
            '<span class="grow"></span>\n',
            '<p class="field-hint" id="model-count"></p>\n',
            "</div>\n",
        ]
    )


def _publish() -> ModuleType:
    """The `publish` module, imported at call time.

    `publish` imports this one at its own top level, so a module-scope import
    here would close the cycle. The two readers below are the only places this
    module needs anything from it.
    """
    from ai_pricelog import publish

    return publish


def _app_fallback() -> str:
    """What a reader gets when the page's own modules never finish starting.

    Rendered hidden and revealed by the load-time check: the interactive half is
    filled by the very script that would reveal it, so a markup that shipped it
    visible would show an error to every reader whose page came up fine.
    """
    export = f"flat-v{_publish().FLAT_VERSION}.json"
    return (
        '<p class="empty-state js-only" id="app-fallback" hidden>'
        "part of this page did not load. reload, or read "
        f'<a href="{export}">the export</a>.</p>\n'
    )


def _models_table() -> str:
    cells = ['<th class="cell-select" scope="col"><span class="sr-only">compare</span></th>']
    for key, label, extra in _COLUMNS:
        classes = f' class="{extra}"' if extra else ""
        cells.append(
            f'<th{classes} scope="col" aria-sort="none">'
            f'<button type="button" class="th-sort" data-sort="{key}">'
            f"{_esc(label)}{_SORT_ICON}</button></th>"
        )
    return "".join(
        [
            '<div class="table-wrap js-only" id="models">\n',
            '<table id="models-table">\n',
            '<caption class="sr-only">every model in the pricing index</caption>\n',
            f"<thead><tr>{''.join(cells)}</tr></thead>\n",
            '<tbody id="models-body"></tbody>\n',
            "</table>\n",
            "</div>\n",
        ]
    )


def _session_card() -> str:
    return "".join(
        [
            '<section class="card js-only">\n',
            '<div class="card-header">\n',
            "<div>\n",
            '<div class="card-title">session</div>\n',
            '<div class="card-subtitle" id="session-note"></div>\n',
            "</div>\n",
            '<span class="tag tag-data" id="rate-line" hidden></span>\n',
            "</div>\n",
            '<div class="toolbar">\n',
            _token_field("calc-input", "input tokens", "1"),
            _token_field("calc-cached", "cached input", "0"),
            _token_field("calc-output", "output tokens", "0"),
            '<div class="field">\n',
            '<label class="field-label" for="calc-day">priced on</label>\n',
            '<input class="input" id="calc-day" type="date">\n',
            "</div>\n",
            '<div class="field">\n',
            '<label class="field-label" for="calc-rate">your rate, $ per mtok</label>\n',
            '<input class="input" id="calc-rate" type="number" inputmode="decimal"'
            ' min="0" step="0.01" placeholder="optional">\n',
            "</div>\n",
            "</div>\n",
            '<p class="empty-state" id="session-empty">'
            "select a model in the table to price a session against it</p>\n",
            '<div class="table-wrap" id="session-wrap" hidden>\n',
            '<table id="session-table">\n',
            '<caption class="sr-only">the selected models, cheapest first</caption>\n',
            '<thead><tr><th scope="col">model</th>'
            '<th class="num-col" scope="col">session</th>'
            '<th class="num-col" scope="col">vs cheapest</th></tr></thead>\n',
            '<tbody id="session-body"></tbody>\n',
            "</table>\n",
            "</div>\n",
            "</section>\n",
        ]
    )


def _token_field(element_id: str, label: str, value: str) -> str:
    return (
        '<div class="field">\n'
        f'<label class="field-label" for="{element_id}">{_esc(label)}</label>\n'
        f'<input class="input" id="{element_id}" type="number" inputmode="numeric"'
        f' min="0" step="1000" value="{value}">\n'
        "</div>\n"
    )


def _static_table(rows: str) -> str:
    head = "".join(f'<th scope="col">{_esc(label)}</th>' for label in _STATIC_COLUMNS)
    return "".join(
        [
            "<noscript>\n",
            '<p class="section-lede">search, sorting and the comparison need javascript.'
            " every model is listed below, cheapest axes included.</p>\n",
            '<div class="table-wrap">\n',
            '<table id="models-static">\n',
            '<caption class="sr-only">every model in the flat export</caption>\n',
            f"<thead><tr>{head}</tr></thead>\n",
            f"<tbody>{rows}</tbody>\n",
            "</table>\n",
            "</div>\n",
            "</noscript>\n",
        ]
    )


def _island(payload: Mapping[str, object]) -> str:
    """The page's data island: the flat export's own serializer, compact, with
    `<` escaped so a model name can never close the script element.

    The island's bytes come from the one serializer the export file itself is
    written with, so the two cannot describe different data.
    """
    text = _publish().flat_text(payload, compact=True).removesuffix("\n").replace("<", "\\u003c")
    return f'<script type="application/json" id="flat-data">{text}</script>\n'


def _document(payload: Mapping[str, object], rows: str, entry_count: int, source_count: int) -> str:
    """The page. The sprite is inlined verbatim as `<body>`'s first child: a
    cross-document `<use>` is not dependable, and nothing else may sit in that
    slot."""
    return "".join(
        [
            "<!DOCTYPE html>\n",
            '<html lang="en" data-theme="dark">\n',
            "<head>\n",
            '<meta charset="UTF-8">\n',
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n',
            f'<link rel="icon" href="{_FAVICON}">\n',
            "<title>genai pricing index</title>\n",
            f"<script>{_HEAD_SCRIPT}</script>\n",
            f'<link rel="stylesheet" href="{SITE_DIR}/tokens.css">\n',
            f'<link rel="stylesheet" href="{SITE_DIR}/components.css">\n',
            f'<link rel="stylesheet" href="{SITE_DIR}/cursor.css">\n',
            f"<style>{_PAGE_STYLE}</style>\n",
            "</head>\n",
            "<body>\n",
            (_ASSETS / "icons.svg").read_text(encoding="utf-8"),
            '<a class="skip-link" href="#main">skip to content</a>\n',
            '<main id="main" class="page">\n',
            _page_header(payload, entry_count, source_count),
            '<div class="stack">\n',
            _toolbar(),
            _app_fallback(),
            _models_table(),
            _session_card(),
            _static_table(rows),
            "</div>\n",
            "</main>\n",
            '<div class="toast-stack" id="toast-stack"></div>\n',
            _island(payload),
            f"<script>{_READY_SCRIPT}</script>\n",
            f'<script type="module" src="{SITE_DIR}/cursor.js"></script>\n',
            f'<script type="module" src="{SITE_DIR}/ui.js"></script>\n',
            f'<script type="module" src="{SITE_DIR}/app.js"></script>\n',
            "</body>\n",
            "</html>\n",
        ]
    )


def _copy_assets(dest: Path) -> None:
    for source in sorted(_ASSETS.rglob("*")):
        if source.is_file():
            target = dest / source.relative_to(_ASSETS)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def render_site(flat_payload: Mapping[str, object], out: Path) -> None:
    """Write the page and its assets under `out`, beside the json surface.

    `flat_payload` is the object `publish.build_flat` wrote the export file
    from, so the island and the file cannot disagree on the data.
    """
    entries = flat_payload.get("entries")
    entries = (
        [entry for entry in entries if isinstance(entry, Mapping)]
        if isinstance(entries, list)
        else []
    )
    rows = "\n".join(_static_row(entry) for entry in entries)
    sources = {str(entry.get("source")) for entry in entries}
    _atomic_write(
        _document(flat_payload, rows, len(entries), len(sources)),
        out / "index.html",
    )
    _copy_assets(out / SITE_DIR)

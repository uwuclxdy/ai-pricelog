"""scrape per-token pricing from the baseten pricing page.

same Model | Input | Cache Input | Output grid as detection; the header
labels are server-rendered on the page itself, and the amounts are USD per
1M tokens -> /1e6. Input -> input_cost, Cache Input -> cache_read, Output
-> output_cost; a cache cell rendering "-" (no cached-input rate for the
model) yields cache_read None. cells render twice (desktop and mobile
duplicates); only the desktop wrapper is read, its anchor text is dropped
(the output cell's Try Model API button label never joins the amount
scan), and a cell with an unexpected amount count is a page-shape break
(FetchError), so a silent misread cannot ship. a row whose Input, Cache
Input and Output cells all render "-" is unpriced: scrape returns None for
it, but only beside priced rows — when no model row on the page carries an
amount or an unreadable amount-shaped token the page is a shape break
(FetchError "no priced model rows"), so an all-dash page stays loud instead
of reading every row as unpriced. an Output cell rendering "-" beside a
priced Input prices output 0.0: an input-only model's free output is a
real zero, and openrouter lists those ids at completion 0. a row whose
Input cell renders "-" beside priced cells is a shape break. rows
key by the /library/ slug. rows the match scan passes over with a
malformed name cell (odd desktop renders, odd links, out-of-charset slugs)
are additive drift detection already reported.

None = the model id is not on the page, or its row reads unpriced (all
three price cells "-") while another model row carries an amount.
FetchError = the fetch failed, the page has no Model APIs table, no model
row on the page carries an amount or an amount-shaped token, a matched cell
carries an unreadable amount, or a matched cell carries an unexpected
amount count.
"""

from __future__ import annotations

from copy import copy

from bs4 import Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.baseten_page import _desktop, _model_id, _model_rows
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, amount_scan, fetch_soup, unreadable_rate_error


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    rows = _model_rows(fetch_soup(cfg.scraper_url), cfg.scraper_url)
    if not any(_row_has_amount(cells, cfg.scraper_url) for cells in rows):
        raise FetchError(f"no priced model rows on {cfg.scraper_url}")
    for cells in rows:
        try:
            if _model_id(cells[0], cfg.scraper_url) != model_id:
                continue
        except FetchError:
            continue  # additive drift; detect already reported the row
        return _pricing(cells, model_id, cfg.scraper_url)
    return None


def _row_has_amount(cells: list[Tag], url: str) -> bool:
    """whether any price column of a model row carries an amount; an
    unreadable amount-shaped token counts as carried, so the all-dash guard
    fires only when the page has nothing amount-shaped at all, and an odd
    render (no desktop wrapper) contributes nothing here — the matched row
    still raises in _pricing."""
    for cell in cells[1:]:
        try:
            text = _rate_text(_desktop(cell, url))
        except FetchError:
            continue
        amounts, malformed = amount_scan(text, before="$")
        if amounts or malformed:
            return True
    return False


def _pricing(cells: list[Tag], model_id: str, url: str) -> Pricing | None:
    if len(cells) != 4:
        raise FetchError(
            f"malformed pricing row for {model_id} on {url}: {len(cells)} cells, want 4"
        )
    columns = [_desktop(cells[i], url) for i in (1, 2, 3)]
    if all(_unpriced(cell) for cell in columns):
        return None
    input_cost = _dollars(columns[0], "input", model_id, url)
    output_cost = 0.0 if _unpriced(columns[2]) else _dollars(columns[2], "output", model_id, url)
    return Pricing(
        input_cost_per_token=input_cost,
        output_cost_per_token=output_cost,
        mode="chat",
        cache_read_cost_per_token=_cache_read(columns[1], model_id, url),
    )


def _rate_text(cell: Tag) -> str:
    """the desktop wrapper's text with anchor text dropped: the output
    cell's Try Model API button label never joins the amount scan."""
    cell = copy(cell)
    for anchor in cell.find_all("a"):
        anchor.extract()
    return cell.get_text(" ", strip=True)


def _unpriced(cell: Tag) -> bool:
    """a column cell reading "-" with no amount: the column is unpriced."""
    text = _rate_text(cell)
    amounts, _ = amount_scan(text, before="$")
    return text == "-" and not amounts


def _dollars(cell: Tag, column: str, model_id: str, url: str) -> float:
    """per-token dollars of a column cell; an odd amount count -> FetchError."""
    text = _rate_text(cell)
    amounts, malformed = amount_scan(text, before="$")
    if malformed:
        raise unreadable_rate_error(text, model_id, url)
    if len(amounts) != 1:
        raise FetchError(
            f"malformed {column} cell for {model_id} on {url}: {len(amounts)} amounts, want 1"
        )
    return float(amounts[0].replace(",", "")) / 1e6


def _cache_read(cell: Tag, model_id: str, url: str) -> float | None:
    text = _rate_text(cell)
    amounts, malformed = amount_scan(text, before="$")
    if text == "-" and not amounts:
        return None
    if malformed:
        raise unreadable_rate_error(text, model_id, url)
    if len(amounts) != 1:
        raise FetchError(
            f"malformed cache input cell for {model_id} on {url}: "
            f"{len(amounts)} amounts, want 1 or '-'"
        )
    # a real $0.00 cell stays 0.0 (free cache reads), never collapses to None
    return float(amounts[0].replace(",", "")) / 1e6

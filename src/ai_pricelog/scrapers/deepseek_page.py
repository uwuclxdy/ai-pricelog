"""scrape per-token pricing for deepseek models.

same table as detection. pricing rows are keyed by their label cell
(1M INPUT TOKENS (CACHE MISS) / 1M OUTPUT TOKENS / 1M INPUT TOKENS (CACHE
HIT)) and split into OFF-PEAK and PEAK subrows. the OFF-PEAK value becomes the
default price and the PEAK value the scheduled overrides, with the schedule
footnote ("Peak hours are 01:00 - 04:00 and 06:00 - 10:00 UTC, Monday through
Friday") parsed into window bounds and weekday days. labels without a PEAK
subrow are flat (no peak fields). peak subrows without the footnote are a
scrape failure: the entry builder requires windows with peak prices. CACHE HIT
parses like CACHE MISS into the cache-read fields: OFF-PEAK ->
cache_read_cost_per_token, PEAK -> peak_cache_read_cost_per_token. values are
USD per 1M tokens -> /1e6.
max_tokens_out comes from the MAX OUTPUT row ("MAXIMUM: 384K" -> 384 *
1024) and max_tokens_in from the CONTEXT LENGTH row ("1M" -> 1024 * 1024);
either row may span all model columns as one merged cell, in which case the
single value applies to every model.

the "Monday through Friday" clause turns into weekday day-sets on the
windows; absent, the windows apply every day, and any other weekday wording
in the footnote paragraph raises. the beijing-time weekend rule
(billing-rules id deepseek-weekend-off-peak, effective 2026-08-23) equals
UTC-day weekdays only while every window ends by 16:00 UTC (beijing
midnight); with the clause present, a window past that raises instead of
silently mis-scheduling.

the search/fetch guide (api-docs.deepseek.com/guides/search) supplies the
per-request search and fetch fees (USD per the Unit cell's N successful
requests, 1,000 on the live page); a missing or unreadable fee, or an
unrecognized unit, is a scrape failure.

None = the model id is not on the page, or a needed price is missing.
FetchError = the fetch failed, the page has no MODEL header table, a
price cell carries an amount the grammar cannot read, a token-count cell
is unreadable, or the guide fee or its unit is missing or unreadable.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.deepseek_page import _model_table, header_ids
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import (
    FetchError,
    amount_scan,
    extract_tables,
    fetch_soup,
    fold_heading,
    unreadable_rate_error,
)

_CACHE_MISS = "1M INPUT TOKENS (CACHE MISS)"
_CACHE_HIT = "1M INPUT TOKENS (CACHE HIT)"
_OUTPUT = "1M OUTPUT TOKENS"
_MARKERS = ("OFF-PEAK", "PEAK")
_GUIDE_URL = "https://api-docs.deepseek.com/guides/search"
_K_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*K\b", re.IGNORECASE)
_M_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*M\b", re.IGNORECASE)
_MAX_COUNT_DIGITS = 12
_FOOTNOTE_PATTERN = re.compile(
    r"Peak hours are (\d{2}:\d{2}) - (\d{2}:\d{2}) and (\d{2}:\d{2}) - (\d{2}:\d{2}) UTC"
)
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# any weekday mention that is not the recognized clause: full names (plural
# forms included, so "weekdays" and "Tuesdays" raise too) plus abbreviations
# so "Mon-Fri" spellings raise. \b keeps "thu" from matching inside words
# like "thus"; full names match whole words, never their abbreviations alone
_WEEKDAY_WORD = re.compile(
    r"\b(mon|tue|wed|thu|fri|sat|sun|weekdays?|mondays?|tuesdays?|wednesdays?"
    r"|thursdays?|fridays?|saturdays?|sundays?)\b"
)
# the weekend rule (billing-rules.json id deepseek-weekend-off-peak) bills
# saturday-sunday beijing time at the off-peak rate; rows carrying the weekday
# schedule stamp that date so consumers clamp historical sessions correctly
_WEEKEND_RULE_EFFECTIVE = "2026-08-23"


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    soup = fetch_soup(cfg.scraper_url)
    tables = extract_tables(soup)
    table = _model_table(tables, cfg.scraper_url)
    ids = header_ids(table)
    if model_id not in ids:
        return None
    prices = _pricing_cells(table[1:], ids.index(model_id))
    off_input = _dollars(prices.get(_CACHE_MISS, {}).get("OFF-PEAK"), model_id, cfg.scraper_url)
    off_output = _dollars(prices.get(_OUTPUT, {}).get("OFF-PEAK"), model_id, cfg.scraper_url)
    off_cache_read = _dollars(prices.get(_CACHE_HIT, {}).get("OFF-PEAK"), model_id, cfg.scraper_url)
    if off_input is None or off_output is None:
        return None
    peak_input = _dollars(prices.get(_CACHE_MISS, {}).get("PEAK"), model_id, cfg.scraper_url)
    peak_output = _dollars(prices.get(_OUTPUT, {}).get("PEAK"), model_id, cfg.scraper_url)
    peak_cache_read = _dollars(prices.get(_CACHE_HIT, {}).get("PEAK"), model_id, cfg.scraper_url)
    if peak_input is None and peak_output is None and peak_cache_read is None:
        return Pricing(
            input_cost_per_token=off_input / 1e6,
            output_cost_per_token=off_output / 1e6,
            mode="chat",
            max_tokens_in=_window_tokens(
                table[1:], ids, model_id, "CONTEXT LENGTH", _M_PATTERN, 1024 * 1024
            ),
            max_tokens_out=_window_tokens(table[1:], ids, model_id, "MAX OUTPUT", _K_PATTERN, 1024),
            cache_read_cost_per_token=_per_token(off_cache_read),
            fees=_guide_fees(fetch_soup(_GUIDE_URL), _GUIDE_URL),
        )
    if peak_input is None or peak_output is None:
        return None
    peak_windows, peak_days = _peak_schedule(soup, cfg.scraper_url)
    return Pricing(
        input_cost_per_token=off_input / 1e6,
        output_cost_per_token=off_output / 1e6,
        mode="chat",
        max_tokens_in=_window_tokens(
            table[1:], ids, model_id, "CONTEXT LENGTH", _M_PATTERN, 1024 * 1024
        ),
        max_tokens_out=_window_tokens(table[1:], ids, model_id, "MAX OUTPUT", _K_PATTERN, 1024),
        cache_read_cost_per_token=_per_token(off_cache_read),
        peak_input_cost_per_token=peak_input / 1e6,
        peak_output_cost_per_token=peak_output / 1e6,
        peak_windows=peak_windows,
        peak_cache_read_cost_per_token=_per_token(peak_cache_read),
        effective_at=_WEEKEND_RULE_EFFECTIVE if peak_days else None,
        peak_days=peak_days,
        timezone="Asia/Shanghai",
        fees=_guide_fees(fetch_soup(_GUIDE_URL), _GUIDE_URL),
    )


def _pricing_cells(rows: list[list[str]], column: int) -> dict[str, dict[str, str]]:
    """label -> marker -> price cell text for the model's column."""
    prices: dict[str, dict[str, str]] = {}
    label: str | None = None
    for row in rows:
        label_cells = [cell for cell in row if cell.startswith("1M ")]
        if label_cells:
            label = label_cells[0]
        for marker in _MARKERS:
            if marker not in row:
                continue
            values = row[row.index(marker) + 1 :]
            if label is not None and column < len(values):
                prices.setdefault(label, {})[marker] = values[column]
            break
    return prices


def _peak_schedule(
    soup: BeautifulSoup, url: str
) -> tuple[tuple[tuple[int, int], ...], tuple[str, ...]]:
    """The footnote's peak windows as HHMM int pairs and their weekday days.

    "Monday through Friday" (or its absence) keys the day-set: weekdays, or
    every day. any other weekday wording in the footnote paragraph raises.
    the beijing-day equivalence from the module docstring holds only while
    every window ends by 16:00 UTC; with the clause present, a window past
    that raises. without it, windows past the boundary stay expressible
    (every-day schedules need no weekday equivalence).
    """
    node = soup.find(string=_FOOTNOTE_PATTERN)
    if node is None:
        raise FetchError(f"peak price rows without a schedule footnote on {url}")
    paragraph = node.parent.get_text(" ", strip=True)
    match = _FOOTNOTE_PATTERN.search(paragraph)
    first_start, first_end, second_start, second_end = match.groups()
    windows = (
        (_hhmm(first_start), _hhmm(first_end)),
        (_hhmm(second_start), _hhmm(second_end)),
    )
    tail = paragraph[match.end() :].casefold()
    if "monday through friday" in tail:
        days = _WEEKDAYS[:5]
    elif _WEEKDAY_WORD.search(tail) is not None:
        raise FetchError(
            f"unrecognized peak weekday clause on {url}: {tail.strip()!r};"
            " fix: re-verify the schedule footnote"
        )
    else:
        days = ()
    if days:
        for start, end in windows:
            if end > 1600:
                raise FetchError(
                    f"peak window {start:04d}-{end:04d} on {url} ends after 16:00 UTC,"
                    " past the beijing-day boundary the weekday clause assumes;"
                    " fix: re-verify the schedule footnote"
                )
    return windows, days


def _hhmm(clock: str) -> int:
    """'01:30' -> 130."""
    return int(clock[:2]) * 100 + int(clock[3:])


def _window_tokens(
    rows: list[list[str]],
    ids: list[str],
    model_id: str,
    label: str,
    pattern: re.Pattern[str],
    multiplier: int,
) -> int:
    for row in rows:
        if not row or row[0] != label:
            continue
        cells = row[1:]
        if len(cells) == len(ids):
            # one cell per model column: the model takes its own cell's value;
            # a cell without a matching value yields 0, never another model's
            cell = cells[ids.index(model_id)]
            match = pattern.search(cell)
            if match is None:
                return 0
            return _scaled_tokens(match.group(1), multiplier, cell, model_id)
        # merged cell(s) spanning the model columns: the first value applies
        # to every model
        for cell in cells:
            match = pattern.search(cell)
            if match is not None:
                return _scaled_tokens(match.group(1), multiplier, cell, model_id)
        return 0
    return 0


def _scaled_tokens(value: str, multiplier: int, cell: str, model_id: str) -> int:
    """a K/M count as tokens; a digit run past the bound is a page-shape
    break, never an int() failure."""
    if len(value.replace(".", "")) > _MAX_COUNT_DIGITS:
        raise FetchError(f"unreadable token count {cell!r} for {model_id}")
    return int(float(value)) * multiplier


def _dollars(text: str | None, model_id: str, url: str) -> float | None:
    """the cell's first readable dollar amount; an amount the grammar cannot
    read is a page-shape break. None when the cell holds no amount."""
    if text is None:
        return None
    amounts, malformed = amount_scan(text, before="$")
    if malformed:
        raise unreadable_rate_error(text, model_id, url)
    return float(amounts[0].replace(",", "")) if amounts else None


def _per_token(dollars: float | None) -> float | None:
    """USD per 1M tokens -> USD per token."""
    return None if dollars is None else dollars / 1e6


def _guide_fees(soup: BeautifulSoup, url: str) -> dict[str, float]:
    """the search + fetch per-request fees from the guide's API/Unit/Price table.

    each row's price cell is USD per the row's own Unit cell ("Per 1,000
    successful requests" -> /1000 per request). either fee missing, a cell
    carrying an amount the grammar cannot read, or an unrecognized unit, is a
    page-shape break.
    """
    for table in extract_tables(soup):
        if not table or not table[0]:
            continue
        if [fold_heading(cell) for cell in table[0]] != ["api", "unit", "price"]:
            continue
        fees: dict[str, float] = {}
        for row in table[1:]:
            if len(row) < 3:
                continue
            key = fold_heading(row[0])
            if key not in ("search", "fetch") or key in fees:
                continue
            divisor = _guide_divisor(row[1], url)
            amounts, malformed = amount_scan(row[2], before="$")
            if malformed or len(amounts) != 1:
                raise unreadable_rate_error(row[2], key, url)
            fees[key] = float(amounts[0].replace(",", "")) / divisor
        missing = [key for key in ("search", "fetch") if key not in fees]
        if missing:
            raise FetchError(f"missing {', '.join(missing)} fee on {url}")
        return fees
    raise FetchError(f"no API/Unit/Price billing table on {url}")


_GUIDE_UNIT_RE = re.compile(r"^per\s+([\d,.]*)\s+successful requests$", re.IGNORECASE)


def _guide_divisor(cell: str, url: str) -> float:
    """the per-N divisor the Unit cell states ("Per 1,000 successful requests" -> 1000).

    a cell that is not the "per <N> successful requests" shape, or whose N the
    amount grammar cannot read, is a shape break, never a silent rescale.
    """
    match = _GUIDE_UNIT_RE.match(cell.strip())
    if match is None:
        raise FetchError(f"unrecognized guide unit {cell!r} on {url}")
    amounts, malformed = amount_scan(match.group(1))
    if malformed or len(amounts) != 1:
        raise FetchError(f"unrecognized guide unit {cell!r} on {url}")
    return float(amounts[0].replace(",", ""))

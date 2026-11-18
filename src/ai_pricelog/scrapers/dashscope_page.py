"""scrape Model Studio token pricing from Alibaba's international pricing page.

reads https://www.alibabacloud.com/help/en/model-studio/model-pricing (static
html). the detector's `international_rows` walks the pricing tables (header
labels, split spans, row alignment, the International scope); the scraper
prices the first such row whose id equals the requested one and whose cells
both read an amount. an unpriced row is not a verdict: a later table may
carry the same id with real prices, and a page with no such row returns None
(no entry beats a wrong one; the pipeline retries next run).

a price cell records the rate in force. a plain cell yields its first
amount (`$`, or the `USD` suffix the audio rows print). a promo cell
carries an `NN% off` marker: when it prints two amounts and the list label
(`Original`, `List price`) attaches to one, the other is the charged rate
(the zai and minimax precedent); a second amount with no list label, or one
on another priced axis (cache, peak), names no single charged rate and
raises; when it prints only the labelled list amount (`Original$0.4 (20% off
for a limited time)`, `List price $0.4 Limited-time 20% off`), the rate is
list x (100 - NN) / 100. the percent runs to the whole token, so `1000%` and
`1,000%` are past the cap; every `%` in a cell that carries an amount must
start an `NN% off` token, so one split across elements (`1 000%`), one glued
to its amount (`$0.420%`) and a notation the parser does not read
(`50% discount`) are page-shape breaks. a list-labelled amount with no
discount marker
names no charged rate; a promo cell naming two different discounts
(`Original$0.276 (limited-time 60% off for off-peak usage) 20% off during
peak hours`), two different list amounts, a list label that places no
amount, or an amount the grammar cannot read is a page-shape break
(FetchError).

a cell may print a peak amount beside an off-peak amount (`Peak $0.3
Off-peak $0.15`). the peak table's note states the off-peak hours and their
`(UTC+N)` offset in one sentence (`off-peak hours are from 22:00 to 08:00 the
next day (UTC+8)`), optionally stating the peak hours first (`Peak hours are
from 08:00 to 22:00 (UTC+8), and off-peak hours are from ...`), and those must
agree with the off-peak half's complement; a `peak hours are from` statement
anywhere else raises. the sentence reads its peak half only in that form,
first and joined by `, and `, so a peak half worded any other way is not read
and the off-peak half derives the window alone. the off-peak amount becomes the
base rate and the peak amount an override over the rest of the day on the UTC
clock, split into two same-day entries where the peak window wraps midnight
(the row contract's `window` pair is same-day). the note is read from the
whole page, not the row's table, so one note binds every scheduled row on the
page; a second scheduled table with its own note in another wording is not
seen and takes this one's window. any cell that prints `peak` in any form
(`Peak:`, `(peaks)`, `Offpeak`, a hyphen-prefixed label) takes the schedule
path, so a label whose amount is not `$`, a suffix amount, a discount or list
marker beside the pair, or a peak word in promo prose raises rather than read
as the all-day rate; a row whose two cells do not both print the pair, and a
page that lacks that sentence, words it any other way, or names more than one
schedule are page-shape breaks (FetchError). USD per
1M tokens -> /1e6. the page carries no context window, so the max_tokens
fields stay 0 (the entry builder omits them).
"""

from __future__ import annotations

import re
from decimal import Decimal

from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.dashscope_page import cell_amounts, international_rows
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup, unreadable_rate_error

# a percent token starts behind neither an amount's digit, separator or `$`,
# nor a number one space back: every `%` in a priced cell starts such a token
_DISCOUNT_RE = re.compile(r"(?<![\d.,$])(?<![\d.,]\s)(\d[\d,]*(?:\.\d+)?)\s*%\s*off", re.IGNORECASE)
_LIST_LABEL_RE = re.compile(r"Original|List price", re.IGNORECASE)
_LIST_AMOUNT_RE = re.compile(
    r"(?:Original|List price)\s*\$([0-9][0-9,]*(?:\.[0-9]+)?)", re.IGNORECASE
)
# a price cell naming another priced axis beside the marker leaves which
# amount the discount applies to unknown; a peak word never reaches this
# grammar from `scrape`, since `_scheduled_amounts` takes every cell that
# names one, raising unless it is the exact pair
_SECOND_AXIS_RE = re.compile(r"\bCached?\b", re.IGNORECASE)
# a peak cell labels its two `$` amounts; the look-behind keeps `Off-peak` from
# reading as a `Peak` label
_PEAK_AMOUNT_RE = re.compile(r"(?<![-\w])Peak\s*\$([0-9][0-9,]*(?:\.[0-9]+)?)", re.IGNORECASE)
_OFF_PEAK_AMOUNT_RE = re.compile(r"\bOff-peak\s*\$([0-9][0-9,]*(?:\.[0-9]+)?)", re.IGNORECASE)
# any `peak` in a cell starts the schedule check, so a cell spelling the pair
# any other way (`Peaks`, `Offpeak`, a glued label) raises instead of reading
# one amount as the all-day rate
_SCHEDULE_LABEL_RE = re.compile(r"peak", re.IGNORECASE)
# the peak table's note: `off-peak hours are from 22:00 to 08:00 the next day
# (UTC+8)`, optionally with the peak hours stated first (`Peak hours are from
# 08:00 to 22:00 (UTC+8), and off-peak hours are from ...`). the look-behind
# keeps a hyphen-prefixed label (`x-peak hours are from ...`) from reading as
# that peak half; the sentence prints an explicit `+N` offset, and a zone
# written any other way, or a note in another table's wording, is not read
_OFF_PEAK_HOURS_RE = re.compile(
    r"(?:(?<![-\w])peak hours are from (\d{1,2}):(\d{2}) to (\d{1,2}):(\d{2})"
    r" \(UTC\+(\d{1,2})\), and )?"
    r"off-peak hours are from (\d{1,2}):(\d{2}) to (\d{1,2}):(\d{2})"
    r"(?: the next day)? \(UTC\+(\d{1,2})\)",
    re.IGNORECASE,
)
# the peak half counts only as the off-peak sentence's own first clause; a
# `peak hours are from` statement anywhere else raises rather than ignore the
# statement. the look-behind keeps `Off-peak hours are from` from counting
_PEAK_HOURS_CLAUSE_RE = re.compile(r"(?<![-\w])peak hours are from", re.IGNORECASE)
_DAY_MINUTES = 24 * 60


def _rate_in_force(cell: str, model_id: str, url: str) -> float | None:
    """the cell's charged per-1M amount; None when the cell holds no amount."""
    amounts, malformed = cell_amounts(cell)
    if malformed:
        raise unreadable_rate_error(cell, model_id, url)
    if not amounts:
        return None
    values = [Decimal(amount.replace(",", "")) for amount in amounts]
    list_values = [Decimal(text.replace(",", "")) for text in _LIST_AMOUNT_RE.findall(cell)]
    labelled = _LIST_LABEL_RE.search(cell) is not None
    # a cell may print runs of whitespace; the marker's look-behind measures
    # one space, so fold them before counting the tokens
    probe = " ".join(cell.split())
    markers = _DISCOUNT_RE.findall(probe)
    if probe.count("%") != len(markers):
        raise unreadable_rate_error(cell, model_id, url)
    discounts = set(markers)
    if not discounts:
        # the label says the amount is not what the page charges, and no
        # marker gives the discount
        if labelled:
            raise unreadable_rate_error(cell, model_id, url)
        return float(values[0])
    if len(discounts) > 1:
        raise FetchError(f"promo cell {cell!r} names more than one rate for {model_id} on {url}")
    if len(values) == 2:
        if not list_values:
            # no list label or a label that places no amount: neither amount
            # is known to be the charged one
            raise unreadable_rate_error(cell, model_id, url)
        if len(set(list_values)) > 1 or list_values[0] not in values:
            raise unreadable_rate_error(cell, model_id, url)
        others = [value for value in values if value != list_values[0]]
        if not others or _SECOND_AXIS_RE.search(cell):
            raise unreadable_rate_error(cell, model_id, url)
        return float(others[-1])
    percent = Decimal(discounts.pop().replace(",", ""))
    if len(values) == 1 and list_values == values and percent <= 100:
        return float(values[0] * (100 - percent) / 100)
    raise unreadable_rate_error(cell, model_id, url)


def _scheduled_amounts(cell: str, model_id: str, url: str) -> tuple[float, float] | None:
    """the cell's (off-peak, peak) per-1M amounts; None when it names no peak rate.

    any cell containing `peak` starts the check; one that does not spell the
    exact pair is a page-shape break rather than a plain or promo price. one
    labelled amount without the other, a discount or list marker, a third
    amount, or an amount the grammar cannot read is a page-shape break too.
    """
    if _SCHEDULE_LABEL_RE.search(cell) is None:
        return None
    peak_amounts = _PEAK_AMOUNT_RE.findall(cell)
    off_peak_amounts = _OFF_PEAK_AMOUNT_RE.findall(cell)
    amounts, malformed = cell_amounts(cell)
    if (
        malformed
        or "%" in cell
        or _LIST_LABEL_RE.search(cell) is not None
        or len(peak_amounts) != 1
        or len(off_peak_amounts) != 1
        or len(amounts) != 2
    ):
        raise unreadable_rate_error(cell, model_id, url)
    return float(Decimal(off_peak_amounts[0].replace(",", ""))), float(
        Decimal(peak_amounts[0].replace(",", ""))
    )


def _peak_windows(soup: BeautifulSoup, model_id: str, url: str) -> tuple[tuple[int, int], ...]:
    """the peak windows on the UTC clock, derived from the peak table's note.

    the note's one sentence states the off-peak window and its `(UTC+N)`
    offset; peak hours are the rest of the day, or the sentence's own peak
    hours, which must agree. the note is looked up page-wide, so it binds
    every scheduled row on the page. the sentence's peak half counts only in
    its first-clause `, and ` form: a `peak hours are from` statement
    elsewhere raises, while a peak half worded any other way is not read. a
    peak window past midnight splits into two same-day entries. a page
    without that sentence, or with two different schedules stated, is a
    page-shape break.
    """
    page = " ".join(soup.get_text(" ").split())
    matches = list(_OFF_PEAK_HOURS_RE.finditer(page))
    if len(_PEAK_HOURS_CLAUSE_RE.findall(page)) != sum(
        match.group(1) is not None for match in matches
    ):
        raise FetchError(
            f"peak hours stated on {url} outside the off-peak hours note for"
            f" {model_id}; fix: re-verify the schedule note"
        )
    schedules = {_utc_peak_windows(match, model_id, url) for match in matches}
    if not schedules:
        raise FetchError(
            f"peak and off-peak cells for {model_id} without an off-peak hours note"
            f" on {url}; fix: re-verify the pricing page's schedule note"
        )
    if len(schedules) > 1:
        raise FetchError(
            f"peak and off-peak cells for {model_id} read more than one off-peak"
            f" schedule on {url}: {sorted(schedules)};"
            " fix: re-verify the pricing page's schedule notes"
        )
    return schedules.pop()


def _utc_peak_windows(match: re.Match[str], model_id: str, url: str) -> tuple[tuple[int, int], ...]:
    """the off-peak note's complement in UTC, as same-day HHMM window pairs.

    a note that states the peak hours too raises unless they equal that
    complement.
    """
    (
        peak_hour,
        peak_minute,
        peak_end_hour,
        peak_end_minute,
        peak_zone_hours,
        start_hour,
        start_minute,
        end_hour,
        end_minute,
        zone_hours,
    ) = match.groups()
    text = match.group(0)
    offset = _zone_minutes(zone_hours, text, model_id, url)
    off_peak_start = (
        _clock_minutes(start_hour, start_minute, text, model_id, url) - offset
    ) % _DAY_MINUTES
    off_peak_end = (
        _clock_minutes(end_hour, end_minute, text, model_id, url) - offset
    ) % _DAY_MINUTES
    if off_peak_start == off_peak_end:
        raise FetchError(
            f"off-peak hours {text!r} for {model_id} on {url} cover the whole day,"
            " leaving no peak hours; fix: re-verify the pricing page's schedule note"
        )
    # peak runs from the off-peak window's end to its start
    peak = _same_day_windows(off_peak_end, off_peak_start)
    if peak_hour is not None:
        peak_offset = _zone_minutes(peak_zone_hours, text, model_id, url)
        stated = _same_day_windows(
            (_clock_minutes(peak_hour, peak_minute, text, model_id, url) - peak_offset)
            % _DAY_MINUTES,
            (_clock_minutes(peak_end_hour, peak_end_minute, text, model_id, url) - peak_offset)
            % _DAY_MINUTES,
        )
        if stated != peak:
            raise FetchError(
                f"peak hours {text!r} for {model_id} on {url} disagree with the"
                " off-peak hours' complement; fix: re-verify the schedule note"
            )
    return peak


def _same_day_windows(start: int, end: int) -> tuple[tuple[int, int], ...]:
    """a UTC clock span as same-day HHMM window pairs; a wrap past midnight splits."""
    if start < end:
        return ((_hhmm(start), _hhmm(end)),)
    upper = (_hhmm(start), 2400)
    return (upper, (0, _hhmm(end))) if end else (upper,)


def _zone_minutes(zone: str, text: str, model_id: str, url: str) -> int:
    if int(zone) > 14:
        raise FetchError(
            f"unreadable schedule zone {text!r} for {model_id} on {url};"
            " fix: re-verify the schedule note"
        )
    return int(zone) * 60


def _clock_minutes(hour: str, minute: str, text: str, model_id: str, url: str) -> int:
    if int(hour) > 23 or int(minute) > 59:
        raise FetchError(
            f"unreadable schedule clock {text!r} for {model_id} on {url};"
            " fix: re-verify the schedule note"
        )
    return int(hour) * 60 + int(minute)


def _hhmm(minutes: int) -> int:
    hours, rest = divmod(minutes, 60)
    return hours * 100 + rest


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    soup = fetch_soup(cfg.scraper_url)
    for row in international_rows(soup, cfg.scraper_url):
        if row.model_id != model_id:
            continue
        input_schedule = _scheduled_amounts(row.input_cell, model_id, cfg.scraper_url)
        output_schedule = _scheduled_amounts(row.output_cell, model_id, cfg.scraper_url)
        if (input_schedule is None) != (output_schedule is None):
            raise FetchError(
                f"mixed peak and off-peak cells for {model_id} on {cfg.scraper_url}:"
                f" input {row.input_cell!r}, output {row.output_cell!r};"
                " fix: re-verify the pricing table"
            )
        if input_schedule is not None and output_schedule is not None:
            input_off_peak, input_peak = input_schedule
            output_off_peak, output_peak = output_schedule
            return Pricing(
                input_cost_per_token=input_off_peak / 1e6,
                output_cost_per_token=output_off_peak / 1e6,
                mode="chat",
                peak_input_cost_per_token=input_peak / 1e6,
                peak_output_cost_per_token=output_peak / 1e6,
                peak_windows=_peak_windows(soup, model_id, cfg.scraper_url),
                timezone="UTC",
            )
        input_amount = _rate_in_force(row.input_cell, model_id, cfg.scraper_url)
        output_amount = _rate_in_force(row.output_cell, model_id, cfg.scraper_url)
        if input_amount is None or output_amount is None:
            continue
        return Pricing(input_amount / 1e6, output_amount / 1e6, mode="chat")
    return None

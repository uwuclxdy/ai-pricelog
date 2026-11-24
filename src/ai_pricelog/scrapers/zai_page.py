"""scrape per-token pricing for z.ai glm models.

same per-token tables as detection (Text + Vision Models). columns Model |
Input | Cached Input | Cached Input Storage | Output: Input -> input_cost,
Cached Input -> cache_read_cost_per_token, Output -> output_cost, USD per
1M -> /1e6. cells without a dollar amount: "Free" and "Limited-time Free"
are zero rates (free is a price), "-" -> None (skip until priced). a promo
cell renders the struck-through list price before the charged one
(`<del>$0.15</del> $0.075`), so the LAST readable dollar amount is the rate
in force; a cell whose amount the grammar cannot read raises. the page
carries no context window -> the max_tokens fields stay 0.
rows match case-insensitively (detection lowercases; the page keeps
GLM-4.7-FlashX).

a table without the Cached Input column is a page-shape break (FetchError):
silently returning None there reads as a cache-read rate drop in the diff.

the quota notice (a watched announce channel, `usage-revision.md`) prices
glm plan consumption with peak/off-peak quota multipliers the pricing page
never carries; scraped models attach them as `window_rates` entries
(`quota_multiplier` only, no rate keys). a failed notice fetch leaves the
entries off for the run (the announce pass records the outage); a notice
whose clause shape broke raises, so a drifted multiplier never drops
silently.

None = the model id is not on the page or a price cell carries no dollar
amount and no free marker. FetchError = the fetch failed, the page has no
per-token tables, the model's table lacks the Cached Input column, a price
cell carries an amount the grammar cannot read, or the quota notice
carries an unparseable clause shape (among them a peak clock outside
00:00-23:59, a clause end of exactly 24:00 aside, a quoted offset past
UTC+14, a zero-length peak clause, or a peak clause wrapping the notice's
midnight whose UTC window still crosses UTC midnight) or repeated sections
that disagree (a model's multipliers, or the peak lines' UTC schedule).
"""

from __future__ import annotations

import re
from functools import cache

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.zai_page import _token_model_tables
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import (
    FetchError,
    amount_scan,
    fetch_soup,
    fetch_text,
    fold_heading,
    unreadable_rate_error,
)

# fold-equal column lookups, never raw spellings: the detector admits a
# recased header, and a raw Cached Input check there false-raises the
# missing-column FetchError instead of scraping
_FOLDED_INPUT = fold_heading("Input")
_FOLDED_OUTPUT = fold_heading("Output")
_FOLDED_CACHED_INPUT = fold_heading("Cached Input")

# the quota notice (a watched announce channel) prices glm plan consumption
# with peak/off-peak quota multipliers; the pricing page carries no peak
# columns, so the scraper reads the multipliers from the notice and attaches
# them as window_rates entries. the base 1x off-peak multiplier is implicit
# and drops; any other off-peak multiplier lands as a whole-day entry, the
# peak multiplier on the peak-hours entries (two when the utc window straddles
# utc midnight).
_USAGE_REVISION_SUFFIX = "usage-revision.md"
_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
# a clause's heading is a `**X**:` span opening its block or sentence: after
# the text start, a line break, a `- ` or `* ` list marker, a tag's closing
# `>` (optional whitespace) or a sentence end. its span to the rate marker
# crosses no sentence end and no other `**...**:` span, so a bold span earlier
# in the notice (the plan-rule list) never claims a later clause, and a clause
# with no such heading fails the marker count. the notice quotes the
# flagship's clause and leaves the flash clause unquoted, so the quote marks
# are optional on both ends
_QUOTA_CLAUSE_RE = re.compile(
    r"(?:\A|(?<=\n)|(?<=[-*] )|(?<=[.!?] )|>\s*)"
    r"\*\*([^*]+)\*\*:(?:(?![.!?] |\*\*[^*]+\*\*:).)*?API calls consume quota at a rate of "
    r'"?(\d+(?:\.\d+)?)× during off-peak hours and (\d+(?:\.\d+)?)× during peak hours'
)
_PEAK_HOURS_RE = re.compile(
    r"Peak hours: ([A-Za-z]+) to ([A-Za-z]+), (\d{1,2}):(\d{2})[–—-](\d{1,2}):(\d{2})"
    r" Singapore Standard Time \(UTC\+(\d{1,2})\)"
)


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    tables = _token_model_tables(fetch_soup(cfg.scraper_url), cfg.scraper_url)
    for table in tables:
        header = table[0]
        row = next(
            (
                candidate
                for candidate in table[1:]
                if candidate and candidate[0].strip().lower() == model_id.lower()
            ),
            None,
        )
        if row is None:
            continue
        folded = [fold_heading(cell) for cell in header]
        if _FOLDED_CACHED_INPUT not in folded:
            raise FetchError(
                f"malformed pricing table for {model_id} on {cfg.scraper_url}: "
                "no Cached Input column"
            )
        if len(row) < len(header):
            raise FetchError(f"malformed pricing row for {model_id} on {cfg.scraper_url}")
        input_cost = _dollars(row[folded.index(_FOLDED_INPUT)], model_id, cfg.scraper_url)
        output_cost = _dollars(row[folded.index(_FOLDED_OUTPUT)], model_id, cfg.scraper_url)
        if input_cost is None or output_cost is None:
            return None
        cache_read = _dollars(row[folded.index(_FOLDED_CACHED_INPUT)], model_id, cfg.scraper_url)
        window_rates = _quota_window_rates(cfg, model_id)
        return Pricing(
            input_cost_per_token=input_cost / 1e6,
            output_cost_per_token=output_cost / 1e6,
            mode="chat",
            cache_read_cost_per_token=cache_read / 1e6 if cache_read is not None else None,
            window_rates=window_rates,
            # the notice quotes Singapore time; _peak_schedule subtracts the
            # offset, so the entries are UTC clock windows
            timezone="UTC" if window_rates else None,
        )
    return None


def _usage_revision_url(cfg: ProviderCfg) -> str | None:
    """the quota notice url among the configured announce channels, or None."""
    return next((url for url in cfg.announce_urls if url.endswith(_USAGE_REVISION_SUFFIX)), None)


@cache
def _notice_text(url: str) -> str:
    """fetch and cache the quota notice; cached per url so every model scrape
    in one run shares the fetch."""
    return fetch_text(url)


def _day_range(start: str, end: str, url: str) -> list[str]:
    try:
        first = _WEEKDAYS.index(start.casefold())
        last = _WEEKDAYS.index(end.casefold())
    except ValueError as exc:
        raise FetchError(
            f"unrecognized weekday range in the zai quota notice on {url}: {start} to {end}"
        ) from exc
    if last < first:
        raise FetchError(
            f"weekday range runs backward in the zai quota notice on {url}: {start} to {end}"
        )
    return list(_WEEKDAYS[first : last + 1])


def _days_one_weekday_back(days: list[str]) -> list[str]:
    """the day set one weekday earlier, in calendar order, each day once.

    a range whose shifted form wraps the week (monday..sunday -> all seven)
    holds every weekday exactly once.
    """
    return sorted(
        {_WEEKDAYS[(_WEEKDAYS.index(day) - 1) % 7] for day in days},
        key=_WEEKDAYS.index,
    )


def _peak_schedule(text: str, url: str) -> tuple[tuple[list[str], list[int]], ...] | None:
    """the notice's peak hours as (day-set, [start, end] utc hhmm) parts.

    None when the notice carries no peak-hours line; a `Peak hours:` label
    with no line the grammar reads is a page-shape break. the notice repeats
    the line per plan section, so every line the grammar reads must convert
    to one utc schedule, and lines that disagree raise; a label the grammar
    does not read beside a readable line is not read.
    """
    matches = list(_PEAK_HOURS_RE.finditer(text))
    if not matches:
        if "Peak hours:" in text:
            raise FetchError(f"unrecognized peak-hours clause in the zai quota notice on {url}")
        return None
    first, *rest = matches
    schedule = _peak_parts(first, url)
    for match in rest:
        if _peak_parts(match, url) != schedule:
            raise FetchError(
                f"peak-hours lines in the zai quota notice on {url} disagree:"
                f" {first.group(0)!r} vs {match.group(0)!r}; fix: re-verify the notice's"
                " peak hours"
            )
    return schedule


def _peak_parts(match: re.Match[str], url: str) -> tuple[tuple[list[str], list[int]], ...]:
    """one peak-hours line as (day-set, [start, end] utc hhmm) parts.

    the clause quotes the notice's own clock, so a start before the offset
    hour lands on the previous utc day: a window wholly on it shifts the day
    set back one weekday, and a window straddling utc midnight splits into a
    [start, 2400] part on the shifted set and a [0, end] part on the
    notice's own set. an end landing exactly on utc midnight stores 2400. a
    quoted offset past UTC+14 raises: no zone lies there. an hour past 23
    (an end of exactly 24:00 is the notice day's end, not a clock) raises
    because the mod-24 conversion would fold it into a plausible window; a
    minute past 59, or a part whose start is not before its end, raises
    instead of leaving validate.py to refuse the row far from the clause
    that broke it; a zero-length clause raises because at the offset hour it
    would store a whole-day [0, 2400] window validate.py accepts.
    """
    days = _day_range(match.group(1), match.group(2), url)
    offset = int(match.group(7))
    if offset > 14:
        raise FetchError(
            f"peak-hours clause in the zai quota notice on {url} quotes UTC+{offset}, past"
            " UTC+14; fix: re-verify the notice's zone"
        )
    clock_pair = match.string[match.start(3) : match.end(6)]
    start_hour = int(match.group(3))
    start_minute = int(match.group(4))
    end_hour = int(match.group(5))
    end_minute = int(match.group(6))
    end_is_day_end = end_hour == 24 and end_minute == 0
    if (
        start_hour > 23
        or start_minute > 59
        or end_minute > 59
        or (end_hour > 23 and not end_is_day_end)
    ):
        raise FetchError(
            f"peak-hours clause {clock_pair} in the zai quota notice on {url} names a"
            " clock outside 00:00-23:59; fix: re-verify the notice's peak hours"
        )
    if (start_hour, start_minute) == (end_hour, end_minute):
        raise FetchError(
            f"peak-hours clause {clock_pair} in the zai quota notice on {url} names a"
            " zero-length window; fix: re-verify the notice's peak hours"
        )
    start_clock = ((start_hour - offset) % 24) * 100 + start_minute
    end_clock = ((end_hour - offset) % 24) * 100 + end_minute
    if start_hour >= offset:
        parts = ((days, [start_clock, 2400 if end_clock == 0 else end_clock]),)
    else:
        shifted = _days_one_weekday_back(days)
        if end_hour < offset or end_clock == 0:
            # the end lands on the previous utc day, or exactly on a utc
            # midnight, stored as 2400 (the end-of-day form validate.py
            # accepts); a notice-wrap clause whose start falls before the
            # offset hour lands here too, and the part check refuses it
            parts = ((shifted, [start_clock, 2400 if end_clock == 0 else end_clock]),)
        else:
            parts = (
                (shifted, [start_clock, 2400]),
                (days, [0, end_clock]),
            )
    for _, (part_start, part_end) in parts:
        if part_start >= part_end:
            raise FetchError(
                f"peak-hours clause {clock_pair} in the zai quota notice on {url} converts"
                f" to a UTC window [{part_start}, {part_end}] whose start is not before"
                " its end; fix: re-verify the notice's peak hours"
            )
    return parts


def _quota_entries(text: str, url: str) -> dict[str, tuple[dict[str, object], ...]]:
    """model slug -> window_rates entries from the notice's quota clauses.

    every clause marker must parse: a new multiplier shape raises instead of
    silently dropping, and clauses without a peak-hours line raise too (the
    peak multiplier would land nowhere). the notice repeats a model's clause
    per plan section, so a model whose clauses state different multipliers
    raises instead of taking either.
    """
    peak = _peak_schedule(text, url)
    clauses = list(_QUOTA_CLAUSE_RE.finditer(text))
    if text.count("consume quota at a rate of") != len(clauses):
        raise FetchError(f"unrecognized quota clause in the zai quota notice on {url}")
    if clauses and peak is None:
        raise FetchError(f"zai quota notice on {url}: quota clauses without a peak-hours line")
    multipliers: dict[str, tuple[float, float]] = {}
    for match in clauses:
        model_id = match.group(1).strip().casefold()
        stated = (float(match.group(2)), float(match.group(3)))
        first = multipliers.setdefault(model_id, stated)
        if stated != first:
            raise FetchError(
                f"the zai quota notice on {url} gives {model_id!r} disagreeing quota"
                f" multipliers: {first[0]}× off-peak and {first[1]}× peak in one clause,"
                f" {stated[0]}× and {stated[1]}× in another; fix: re-verify the notice"
            )
    entries: dict[str, tuple[dict[str, object], ...]] = {}
    for model_id, (off_peak, on_peak) in multipliers.items():
        model_entries: list[dict[str, object]] = []
        if off_peak != 1.0:
            # the base 1x multiplier is implicit; anything else rides a
            # whole-day entry
            model_entries.append({"quota_multiplier": off_peak})
        for days, window in peak:
            entry: dict[str, object] = {"quota_multiplier": on_peak}
            entry["days"] = days
            entry["window"] = window
            model_entries.append(entry)
        entries[model_id] = tuple(model_entries)
    return entries


def _quota_window_rates(cfg: ProviderCfg, model_id: str) -> tuple[dict[str, object], ...]:
    """the model's quota-multiplier entries from the notice, or () when none.

    a failed notice fetch yields no entries this run (the announce pass
    records the outage and the next scrape re-attaches them); a parsed
    notice whose clause shape broke raises.
    """
    notice_url = _usage_revision_url(cfg)
    if notice_url is None:
        return ()
    try:
        text = _notice_text(notice_url)
    except FetchError:
        return ()
    return _quota_entries(text, notice_url).get(model_id.casefold(), ())


def _dollars(text: str, model_id: str, url: str) -> float | None:
    """the cell's rate: the last readable dollar amount, or 0.0 for a free
    marker.

    a promo cell lists the struck-through price before the charged one, so
    the last amount wins; a cell whose amount the grammar cannot read is a
    page-shape break; a cell with no amount reads as a zero rate when it
    carries a free marker ("Free", "Limited-time Free"), else as unpriced.
    """
    amounts, malformed = amount_scan(text, before="$")
    if malformed:
        raise unreadable_rate_error(text, model_id, url)
    if amounts:
        return float(amounts[-1].replace(",", ""))
    if "free" in text.casefold():
        return 0.0
    return None

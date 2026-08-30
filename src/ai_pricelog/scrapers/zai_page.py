"""scrape per-token pricing for z.ai glm models.

same per-token tables as detection (Text + Vision Models). columns Model |
Input | Cached Input | Cached Input Storage | Output: Input -> input_cost,
Cached Input -> cache_read_cost_per_token, Output -> output_cost, USD per
1M -> /1e6. cells without a dollar amount: "Free" and "Limited-time Free"
are zero rates (free is a price), "-" -> None (skip until priced). a promo
cell renders the struck-through list price before the charged one
(`<del>$0.15</del> $0.075`), so the LAST dollar amount is the rate in
force. the page carries no context window -> the max_tokens fields stay 0.
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
per-token tables, the model's table lacks the Cached Input column, or the
quota notice carries an unparseable clause shape.
"""

from __future__ import annotations

import re
from functools import cache

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.zai_page import _token_model_tables
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup, fetch_text

_PRICE_PATTERN = re.compile(r"\$(\d+(?:\.\d+)?)")

# the quota notice (a watched announce channel) prices glm plan consumption
# with peak/off-peak quota multipliers; the pricing page carries no peak
# columns, so the scraper reads the multipliers from the notice and attaches
# them as window_rates entries. the base 1x off-peak multiplier is implicit
# and drops; any other off-peak multiplier lands as a whole-day entry, the
# peak multiplier as the peak-hours entry.
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
# the notice quotes the flagship's clause and leaves the flash clause
# unquoted, so the quote marks are optional on both ends
_QUOTA_CLAUSE_RE = re.compile(
    r"\*\*([^*]+)\*\*:.*?API calls consume quota at a rate of "
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
        if "Cached Input" not in header:
            raise FetchError(
                f"malformed pricing table for {model_id} on {cfg.scraper_url}: "
                "no Cached Input column"
            )
        if len(row) < len(header):
            raise FetchError(f"malformed pricing row for {model_id} on {cfg.scraper_url}")
        input_cost = _dollars(row[header.index("Input")])
        output_cost = _dollars(row[header.index("Output")])
        if input_cost is None or output_cost is None:
            return None
        cache_read = _dollars(row[header.index("Cached Input")])
        return Pricing(
            input_cost_per_token=input_cost / 1e6,
            output_cost_per_token=output_cost / 1e6,
            mode="chat",
            cache_read_cost_per_token=cache_read / 1e6 if cache_read is not None else None,
            window_rates=_quota_window_rates(cfg, model_id),
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


def _peak_schedule(text: str, url: str) -> tuple[list[str], list[int]] | None:
    """(weekday day-set, [start, end] utc hhmm) of the notice's peak hours.

    None when the notice carries no peak-hours line; a present line outside
    the known shape is a page-shape break.
    """
    match = _PEAK_HOURS_RE.search(text)
    if match is None:
        if "Peak hours:" in text:
            raise FetchError(f"unrecognized peak-hours clause in the zai quota notice on {url}")
        return None
    days = _day_range(match.group(1), match.group(2), url)
    offset = int(match.group(7))
    start_clock = ((int(match.group(3)) - offset) % 24) * 100 + int(match.group(4))
    end_clock = ((int(match.group(5)) - offset) % 24) * 100 + int(match.group(6))
    return days, [start_clock, end_clock]


def _quota_entries(text: str, url: str) -> dict[str, tuple[dict[str, object], ...]]:
    """model slug -> window_rates entries from the notice's quota clauses.

    every clause marker must parse: a new multiplier shape raises instead of
    silently dropping, and clauses without a peak-hours line raise too (the
    peak multiplier would land nowhere).
    """
    peak = _peak_schedule(text, url)
    clauses = list(_QUOTA_CLAUSE_RE.finditer(text))
    if text.count("consume quota at a rate of") != len(clauses):
        raise FetchError(f"unrecognized quota clause in the zai quota notice on {url}")
    if clauses and peak is None:
        raise FetchError(f"zai quota notice on {url}: quota clauses without a peak-hours line")
    entries: dict[str, tuple[dict[str, object], ...]] = {}
    for match in clauses:
        model_id = match.group(1).strip().casefold()
        off_peak = float(match.group(2))
        on_peak = float(match.group(3))
        model_entries: list[dict[str, object]] = []
        if off_peak != 1.0:
            # the base 1x multiplier is implicit; anything else rides a
            # whole-day entry
            model_entries.append({"quota_multiplier": off_peak})
        entry: dict[str, object] = {"quota_multiplier": on_peak}
        entry["days"] = peak[0]
        entry["window"] = peak[1]
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


def _dollars(text: str) -> float | None:
    """the cell's rate: the last dollar amount, or 0.0 for a free marker.

    a promo cell lists the struck-through price before the charged one, so
    the last amount wins; a cell with no amount reads as a zero rate when
    it carries a free marker ("Free", "Limited-time Free"), else as
    unpriced.
    """
    matches = _PRICE_PATTERN.findall(text)
    if matches:
        return float(matches[-1])
    if "free" in text.casefold():
        return 0.0
    return None

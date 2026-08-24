"""Drift refresh for tracked models (todo #6/#7).

Each run re-scrapes the watched providers' tracked models and diffs the live
rates against the target yml. A drift becomes a draft PR:

- flat entry, flat live, rate changed -> dated conditional append, the
  target's own never-overwrite pattern (old rates stay the unconstrained
  first entry, new rates land in a dated entry at the end)
- flat entry, live page split-priced -> block conversion to the split list
  form
- list entry, any drift -> block replacement: the target's constraint schema
  is a strict XOR of start_date and time-window, so a dated rate-change entry
  cannot express a split schedule, and the deviation is named in the PR body
  (todo #6/#7 decision)
- tiered mapping, flat live, base rate changed -> dated append whose new
  entry carries the live base with the old tier steps unchanged; the
  scraper cannot see tier prices, so the PR body names the carry-over
  risk (todo #4 decision)

Entries whose shape cannot be compared (malformed tier objects, missing
prices, a tiered entry with a split-priced live page) skip drift rather than
guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from autopr_genai_prices import yml
from autopr_genai_prices.config import ProviderCfg
from autopr_genai_prices.openrouter import OpenrouterModel
from autopr_genai_prices.pr import UpdateSpec
from autopr_genai_prices.pricing import Pricing

RATE_COMMENT = "rate change; effective date unknown, set to the day the watchdog verified it"


@dataclass(frozen=True)
class Drift:
    action: str  # "none" | "dated_append" | "conversion" | "replace" | "tiered_append"
    note: str


@dataclass(frozen=True)
class EntryValues:
    input_mtok: float | None
    output_mtok: float | None
    constraint: str | None  # None | "date:<iso>" | "time:<start>-<end>"


def compare(prices_view: object, pricing: Pricing) -> Drift:
    """Whether freshly scraped pricing drifts from a tracked entry's prices."""
    live_split = pricing.peak_input_cost_per_token is not None
    if isinstance(prices_view, dict):
        old = _flat(prices_view)
        if old is None:
            tiered = _tiered(prices_view)
            if tiered is None:
                return Drift("none", "entry prices are tiered or unparseable")
            if live_split:
                return Drift("none", "tiered entry, live page is split-priced; uncomparable")
            if _same(tiered, pricing):
                return Drift("none", "rates match the tiered base")
            return Drift("tiered_append", "tiered base rate changed")
        if live_split:
            return Drift("conversion", "flat entry, live page is split-priced")
        if _same(old, pricing):
            return Drift("none", "rates match")
        return Drift("dated_append", "rate changed")
    if not isinstance(prices_view, list) or not prices_view:
        return Drift("none", "entry prices are unparseable")
    entries = [_entry(item) for item in prices_view]
    if any(entry is None for entry in entries):
        return Drift("none", "a prices entry is tiered or unparseable")
    entries = [entry for entry in entries if entry is not None]
    if live_split:
        if _split_matches(entries, pricing):
            return Drift("none", "rates match")
        return Drift("replace", "split rates drifted")
    dated = [
        entry for entry in entries if entry.constraint and entry.constraint.startswith("date:")
    ]
    if dated:
        current = _current(dated, entries)
        if current is not None and _same(current, pricing):
            return Drift("none", "rates match")
        return Drift("dated_append", "rate changed")
    return Drift("replace", "page dropped the split schedule")


def _flat(prices: dict) -> EntryValues | None:
    input_mtok = prices.get("input_mtok")
    output_mtok = prices.get("output_mtok")
    for value in (input_mtok, output_mtok):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            return None  # tiered or malformed: cannot compare
    return EntryValues(input_mtok, output_mtok, None)


def _tier_base(value: object) -> float | None:
    """A price key's flat rate, or a tier object's base rate.

    Both spellings answer the same question for the compare: what a request
    inside the base tier pays. Anything else (a malformed tier object, a
    non-numeric value) returns None.
    """
    if isinstance(value, dict):
        value = value.get("base")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _tiered(prices: dict) -> EntryValues | None:
    """The base rates of a tiered mapping, or None when one side is unreadable.

    Only input and output drive the verdict: tier steps and other keys
    (cache_read_mtok, requests_kcount, ...) carry over by text in the append
    and never participate in the compare.
    """
    input_mtok = _tier_base(prices.get("input_mtok"))
    output_mtok = _tier_base(prices.get("output_mtok"))
    if input_mtok is None or output_mtok is None:
        return None
    return EntryValues(input_mtok, output_mtok, None)


def _entry(item: object) -> EntryValues | None:
    if not isinstance(item, dict):
        return None
    prices = item.get("prices")
    if not isinstance(prices, dict):
        return None
    flat = _flat(prices)
    if flat is None:
        return None
    constraint = item.get("constraint")
    if constraint is None:
        return flat
    if not isinstance(constraint, dict):
        return None
    if "start_date" in constraint:
        # yaml parses an unquoted date into datetime.date; str() is the iso form
        return EntryValues(flat.input_mtok, flat.output_mtok, f"date:{constraint['start_date']}")
    if "start_time" in constraint and "end_time" in constraint:
        return EntryValues(
            flat.input_mtok,
            flat.output_mtok,
            f"time:{_time_label(constraint['start_time'])}-{_time_label(constraint['end_time'])}",
        )
    return None


def _time_label(value: object) -> str:
    """A time-window endpoint in the scraper's spelling (01:00:00Z).

    yaml parses an unquoted `01:00:00Z` into a tz-aware datetime.time whose
    isoformat reads `01:00:00+00:00`; the scraper's peak windows carry the Z
    form, so both sides must normalize to it.
    """
    if isinstance(value, str):
        return value
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return text.replace("+00:00", "Z")


def _num(value: float | int | None) -> float | None:
    return None if value is None else round(float(value), 6)


def _same(entry: EntryValues, pricing: Pricing) -> bool:
    live_input = yml.to_mtok(pricing.input_cost_per_token)
    live_output = yml.to_mtok(pricing.output_cost_per_token)
    return _num(entry.input_mtok) == _num(live_input) and _num(entry.output_mtok) == _num(
        live_output
    )


def _split_matches(entries: list[EntryValues], pricing: Pricing) -> bool:
    unconstrained = [entry for entry in entries if entry.constraint is None]
    if len(unconstrained) != 1 or not _same(unconstrained[0], pricing):
        return False
    timed = {entry.constraint: entry for entry in entries if entry.constraint}
    peak_input = yml.to_mtok(pricing.peak_input_cost_per_token)
    peak_output = yml.to_mtok(pricing.peak_output_cost_per_token)
    if len(timed) != len(pricing.peak_windows):
        return False
    for start, end in pricing.peak_windows:
        entry = timed.get(f"time:{start}-{end}")
        if entry is None:
            return False
        if _num(entry.input_mtok) != _num(peak_input) or _num(entry.output_mtok) != _num(
            peak_output
        ):
            return False
    return True


def _current(dated: list[EntryValues], entries: list[EntryValues]) -> EntryValues | None:
    """The entry that prices a request today: last active dated entry, else the base.

    Time-window entries are ignored: a list mixing timed and dated entries
    resolves per request hour, so no single entry prices "today". no watched
    yml mixes the two shapes, so the approximation only ever sees dated-only
    lists (where it matches the resolver's reversed scan exactly).
    """
    today = date.today().isoformat()
    active = [
        entry
        for entry in dated
        if entry.constraint and entry.constraint.removeprefix("date:") <= today
    ]
    if active:
        return active[-1]
    for entry in entries:
        if entry.constraint is None:
            return entry
    return None


def old_values(prices_view: object) -> tuple[float | None, float | None]:
    """The entry's base rates (flat, unconstrained, or tiered), for the PR body table."""
    if isinstance(prices_view, dict):
        flat = _flat(prices_view) or _tiered(prices_view)
        return (flat.input_mtok, flat.output_mtok) if flat else (None, None)
    if isinstance(prices_view, list):
        for item in prices_view:
            entry = _entry(item)
            if entry is not None and entry.constraint is None:
                return entry.input_mtok, entry.output_mtok
    return None, None


def _tracked_cache_reads(prices_view: object) -> tuple[float | None, float | None]:
    """The tracked entry's cache-read rates: (base, peak).

    A rewrite re-emits the prices block, so every key the old block carried
    must survive: the base rate comes from the unconstrained entry (or the
    flat mapping), the peak rate from the last timed entry.
    """
    if isinstance(prices_view, dict):
        return _mapping_values(prices_view).get("cache_read_mtok"), None
    if not isinstance(prices_view, list):
        return None, None
    base: float | None = None
    peak: float | None = None
    for item in prices_view:
        entry = _entry(item)
        if entry is None:
            continue
        cache_read = _cache_read(item)
        if entry.constraint is None:
            base = cache_read
        elif entry.constraint.startswith("time:"):
            peak = cache_read
    return base, peak


def _tracked_peak(
    prices_view: object,
) -> tuple[float | None, float | None, tuple[tuple[str, str], ...]]:
    """The tracked entry's peak schedule: last timed entry's rates and all windows.

    Surfaces a window change in the PR body: a replace with unchanged rates
    but a moved schedule would otherwise show identical old/new numbers.
    """
    if not isinstance(prices_view, list):
        return None, None, ()
    timed: list[tuple[str, str, float | None, float | None]] = []
    for item in prices_view:
        entry = _entry(item)
        if entry is None or not entry.constraint or not entry.constraint.startswith("time:"):
            continue
        start, end = entry.constraint.removeprefix("time:").split("-", 1)
        timed.append((start, end, entry.input_mtok, entry.output_mtok))
    if not timed:
        return None, None, ()
    windows = tuple((start, end) for start, end, _inp, _out in timed)
    _start, _end, peak_input, peak_output = timed[-1]
    return peak_input, peak_output, windows


def build_update_spec(
    pcfg: ProviderCfg,
    vendor_text: str,
    entry: yml.TrackedModel,
    pricing: Pricing,
    drift: Drift,
    checked: str,
    or_text: str,
    or_yml: yml.ProviderYml,
    or_models: list[OpenrouterModel],
) -> UpdateSpec:
    """Assemble one UpdateSpec from a drift verdict and the openrouter mirror state."""
    old_section = yml.prices_section_text(vendor_text, entry.id)
    if old_section is None:
        raise ValueError(f"model '{entry.id}': entry has no `prices:` section text")
    base_cache, peak_cache = _tracked_cache_reads(entry.prices)
    if drift.action == "dated_append":
        prices_section = yml.dated_append_section(
            old_section,
            pricing.input_cost_per_token,
            pricing.output_cost_per_token,
            checked,
            RATE_COMMENT,
            cache_read_mtok=openrouter_current(entry.prices).get("cache_read_mtok"),
        )
        deviation = (
            "the target's never-overwrite rule is followed: the old rates stay as the "
            "unconstrained first entry, the new rates land in a dated entry at the end. "
            "the tracked cache-read rate is carried into the new entry unchanged"
        )
        case = "rate_change"
    elif drift.action == "tiered_append":
        prices_section = yml.tiered_dated_append_section(
            old_section,
            pricing.input_cost_per_token,
            pricing.output_cost_per_token,
            checked,
            RATE_COMMENT,
        )
        deviation = (
            "tiered rate change: the new base rates land in a dated entry that carries "
            "the old tier steps unchanged. the scraper sees only flat base rates, so "
            "tier prices may have moved with the base; verify the tiers before marking "
            "ready"
        )
        case = "rate_change"
    elif drift.action == "conversion":
        prices_section = yml.prices_section(
            pricing, cache_read_mtok=base_cache, peak_cache_read_mtok=peak_cache
        )
        deviation = (
            "structural conversion: the flat block is replaced by the split list form, "
            "the schedule coming from the page footnote. the XOR constraint schema "
            "cannot express a dated split transition; if the split predates this entry "
            "the old block was wrong at write (the target's correction case), otherwise "
            "this deviates from never-overwrite, named here"
        )
        case = "conversion"
    else:  # replace
        prices_section = yml.prices_section(
            pricing, cache_read_mtok=base_cache, peak_cache_read_mtok=peak_cache
        )
        deviation = (
            "the block is replaced in place: the target's constraint schema is a strict "
            "XOR of start_date and time-window, so a dated rate-change entry cannot "
            "express a split schedule. the schedule is re-emitted from the page "
            "footnote, so the peak windows themselves can change beyond the rates; "
            "this deviates from the never-overwrite rule, named here"
        )
        case = "replace"
    old_input, old_output = old_values(entry.prices)
    old_peak_input, old_peak_output, old_peak_windows = _tracked_peak(entry.prices)
    slug = f"{pcfg.or_prefix}/{entry.id.lower()}"
    or_prices_section, or_note = _mirror(slug, checked, or_text, or_yml, or_models)
    return UpdateSpec(
        model_id=entry.id,
        case=case,
        prices_section=prices_section,
        deviation=deviation,
        old_input_mtok=old_input,
        old_output_mtok=old_output,
        old_peak_input_mtok=old_peak_input,
        old_peak_output_mtok=old_peak_output,
        old_peak_windows=old_peak_windows,
        input_mtok=yml.to_mtok(pricing.input_cost_per_token),
        output_mtok=yml.to_mtok(pricing.output_cost_per_token),
        peak_input_mtok=(
            yml.to_mtok(pricing.peak_input_cost_per_token)
            if pricing.peak_input_cost_per_token is not None
            else None
        ),
        peak_output_mtok=(
            yml.to_mtok(pricing.peak_output_cost_per_token)
            if pricing.peak_output_cost_per_token is not None
            else None
        ),
        peak_windows=pricing.peak_windows,
        start_date=checked,
        or_prices_section=or_prices_section,
        or_note=or_note,
    )


def _mirror(
    slug: str,
    checked: str,
    or_text: str,
    or_yml: yml.ProviderYml,
    or_models: list[OpenrouterModel],
) -> tuple[str | None, str]:
    """The openrouter.yml half of a drift PR.

    The API is openrouter's own rate source: a dated append happens only when
    the API already lists rates that differ from the tracked entry. A model
    the API does not list, or an entry the yml does not track, defers with a
    note (the follow-up pass owns entries the yml does not track).
    """
    or_model = None
    for model in or_models:
        if model.id == slug:
            or_model = model
            break
    if or_model is None:
        return (
            None,
            f"`{slug}` is not listed on the OpenRouter models API; openrouter.yml is untouched",
        )
    tracked = next(
        (model for model in or_yml.models if not model.removed and model.id == slug), None
    )
    if tracked is None:
        return (
            None,
            f"`{slug}` is not tracked in openrouter.yml; the follow-up pass handles it",
        )
    if or_rates_match(tracked, or_model):
        return (
            None,
            f"`{slug}` in openrouter.yml already matches the API rates; no openrouter change",
        )
    section = or_drift_section(slug, checked, or_text, or_model)
    if section is None:
        return None, f"`{slug}` in openrouter.yml has no prices section to rewrite"
    return section, f"`{slug}` in openrouter.yml updated from the OpenRouter models API"


def or_rates_match(tracked: yml.TrackedModel, or_model: OpenrouterModel) -> bool:
    """Whether the tracked openrouter entry matches the api's current rates."""
    current = openrouter_current(tracked.prices)
    return (
        _num(current.get("input_mtok")) == _num(or_model.input_mtok)
        and _num(current.get("output_mtok")) == _num(or_model.output_mtok)
        and _num(current.get("cache_read_mtok")) == _num(or_model.cache_read_mtok)
    )


def or_drift_section(
    slug: str, checked: str, or_text: str, or_model: OpenrouterModel
) -> str | None:
    """The dated-append section for a tracked openrouter entry that drifted.

    The same emission as the vendor-pr mirror, for the follow-up pass's lag
    case: the api caught up with the tracked entry after the vendor pr
    merged. Returns None when the entry carries no prices section to rewrite.
    """
    old_section = yml.prices_section_text(or_text, slug)
    if old_section is None:
        return None
    return yml.dated_append_section(
        old_section,
        (or_model.input_mtok or 0.0) / 1e6,
        (or_model.output_mtok or 0.0) / 1e6,
        checked,
        RATE_COMMENT,
        cache_read_mtok=or_model.cache_read_mtok,
        # the API lists no rates -> the entry turns free from this date. a
        # zero figure would violate the target's Gt(0) schema and the build
        # would fail every run forever
        free=or_model.input_mtok is None,
    )


def openrouter_current(prices_view: object) -> dict[str, float | None]:
    """The openrouter entry's effective rates: flat mapping or last active dated entry.

    Both engines resolve a list backwards, so the last dated entry with a
    start_date <= today wins; an active-free list falls back to the
    unconstrained base.
    """
    if isinstance(prices_view, dict):
        return _mapping_values(prices_view)
    if not isinstance(prices_view, list):
        return {}
    base: dict[str, float | None] = {}
    active: dict[str, float | None] | None = None
    today = date.today().isoformat()
    for item in prices_view:
        entry = _entry(item)
        if entry is None:
            continue
        values = {
            "input_mtok": entry.input_mtok,
            "output_mtok": entry.output_mtok,
            "cache_read_mtok": _cache_read(item),
        }
        if entry.constraint and entry.constraint.startswith("date:"):
            if entry.constraint.removeprefix("date:") <= today:
                active = values
        elif entry.constraint is None:
            base = values
    return active if active is not None else base


def _cache_read(item: object) -> float | None:
    if not isinstance(item, dict) or not isinstance(item.get("prices"), dict):
        return None
    value = item["prices"].get("cache_read_mtok")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _mapping_values(prices: dict) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    for key in ("input_mtok", "output_mtok", "cache_read_mtok"):
        value = prices.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            values[key] = None
        else:
            values[key] = value
    return values

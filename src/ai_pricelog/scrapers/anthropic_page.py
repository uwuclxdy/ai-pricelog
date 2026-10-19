"""scrape claude per-token pricing from the anthropic pricing markdown twin.

same model table as detection (the header is pinned in the detector).
five rate columns read as USD per 1M tokens: Base Input -> input, 5m
Cache Writes -> the default write tier, 1h Cache Writes -> the 1h write
tier, Cache Hits & Refreshes -> cache read, Output -> output, each /1e6.
a rate cell must carry exactly one dollar amount (ASCII digits, commas
only in proper three-digit groups, an optional decimal part, and nothing
numeric glued after it); no readable amount, more than one readable
amount, one readable amount beside a malformed amount, or one past a sane
length is a page-shape break (FetchError, never ValueError). the page
carries no context window, so the max_tokens fields stay 0 (the entry
builder omits them).

a prompt-length tier (Claude Haiku 5.5) prices one model in two
model-table rows, read by the detector's `split_name`; they fold into one
id and scrape as the "up to" row's base rates plus one window_rates entry
at min_tokens N carrying the "over" row's rates, placed before any
fast-mode entries. an incomplete or inconsistent set (a lone tier row, a
mismatched N, a duplicate tier row, a tier row beside an untiered row for
the id) raises FetchError naming the model, the rows found, the untiered
count and the url; so does more than one untiered row folding into the
requested id.

the fast-mode table (folded header Model | Input | Output) prices the
request-body speed:"fast" premium: $ per MTok input/output, first-party
only, full context, stacking with caching and data-residency multipliers,
never batch. a model cell may join two names with " / " (the row covers
both), and a row applying to the requested id attaches the rates as a
window_rates entry keyed on the request mode. the fast table absent is
additive drift: the base Pricing still ships, with no entries and a
warning. a fast-table row whose every name yields no model id (an empty
slug) raises every scrape, naming the row; a fast name whose stem holds a
non-ASCII non-space character, or whose slug is empty or names no
model-table row, is drift, skipped with a per-name warning that carries
the provider key so the health step classes it, while the row still
applies to its matching names.

a failing model-table row raises only the scrape of the model its name's
leading shape names. a row with an empty name or a letterless stem (its
tier paren dropped) raises every scrape, unless the tier it carries pairs
with exactly one model's tier row, in which case that one model's tier
check counts the nameless row and raises its pair error. a fast row whose
name carries a prompt-length tier raises for that model, as does more
than one fast row for one model.

None = no model-table row names the requested model id. FetchError = the
fetch failed, the page carries no model pricing table, or a row that
raises for the requested model fails.
"""

from __future__ import annotations

import logging

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.anthropic_page import (
    _SANE_TOKEN_LENGTH,
    TABLE_HEADER,
    _fast_name_non_ascii,
    _letterless,
    _name_id,
    _name_tier,
    _own_model_id,
    _RowError,
    check_row,
    model_table,
    split_name,
)
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import (
    FetchError,
    amount_scan,
    extract_markdown_tables,
    fetch_text,
    fold_heading,
    unreadable_rate_error,
)

log = logging.getLogger(__name__)

_FAST_HEADER = ["Model", "Input", "Output"]
_FAST_FOLDED_HEADER = [fold_heading(cell) for cell in _FAST_HEADER]
# the two covered models share one cell, split on the literal separator
_FAST_NAME_SPLIT = " / "
_FAST_MODE = "fast"


def _amount(cell: str, model_id: str, url: str) -> float:
    """the cell's single dollar amount; no readable amount, more than one
    readable amount, one readable amount beside a malformed amount (an
    amount-shaped "$" the amount grammar cannot read), or an amount past a
    sane length is a page-shape break."""
    readable, malformed = amount_scan(cell, before="$")
    if len(readable) != 1 or malformed or len(readable[0]) > _SANE_TOKEN_LENGTH:
        raise unreadable_rate_error(cell, model_id, url)
    return float(readable[0].replace(",", ""))


def _fast_table(text: str) -> list[list[str]] | None:
    """the fast-mode table among the page's tables; None when absent.

    the folded Model | Input | Output header is what tells it from every
    other two- and three-column table the page carries; a header with no
    data rows reads as absent.
    """
    for table in extract_markdown_tables(text):
        if table and [fold_heading(cell) for cell in table[0]] == _FAST_FOLDED_HEADER:
            return table if len(table) > 2 else None
    return None


def _fast_window_rates(
    text: str, model_id: str, url: str, main_ids: set[str], key: str
) -> tuple[dict[str, object], ...]:
    """the model's fast-mode window_rates entries, () when none apply.

    `main_ids` is every id the model table carries, so a fast-table row
    naming an unknown model is told from a row for other known models: a
    row whose every name yields no model id at all raises every scrape,
    while a name whose stem holds a non-ASCII non-space character, or
    whose slug is empty or names no model-table row, is drift, skipped
    with a per-name warning. a row whose name carries a prompt-length tier
    raises for the model(s) its name names.
    """
    table = _fast_table(text)
    if table is None:
        log.warning("fast-mode pricing table absent for %s on %s", model_id, url)
        return ()
    entries: list[dict[str, object]] = []
    applied: list[str] = []
    for row in table[2:]:
        names = [name.strip() for name in row[0].split(_FAST_NAME_SPLIT)]
        slugs = [_name_id(name) for name in names]
        if not any(slugs):
            raise FetchError(
                f"fast-mode row {row!r} on {url} names no model, so it fails every"
                " model's scrape; fix: give the row a model name or teach the anthropic"
                " scraper this fast-table layout"
            )
        non_ascii = [_fast_name_non_ascii(name) for name in names]
        ids = ["" if bad else slug for slug, bad in zip(slugs, non_ascii, strict=True)]
        known = [slug in main_ids for slug in ids]
        applies = model_id in ids
        for name, is_known in zip(names, known, strict=True):
            if not is_known:
                log.warning(
                    "fast-mode name %r names no model in the pricing table for %s on %s",
                    name,
                    key,
                    url,
                )
        if len(row) != len(_FAST_HEADER):
            if applies:
                raise FetchError(f"row outside the fast-mode shape on {url}: {row!r}")
            continue
        if not applies:
            continue
        for name in names:
            if _name_tier(name) is not None:
                raise FetchError(
                    f"fast-mode row {row[0]!r} carries a prompt-length tier on {url}; "
                    "fix: teach the anthropic scraper fast-mode tiers"
                )
        applied.append(row[0])
        entries.append(
            {
                "mode": _FAST_MODE,
                "input_mtok": _amount(row[1], model_id, url),
                "output_mtok": _amount(row[2], model_id, url),
            }
        )
    if len(applied) > 1:
        raise FetchError(
            f"more than one fast-mode row for {model_id!r} on {url}: {applied!r}; "
            "fix: teach the anthropic scraper which fast row prices the model"
        )
    return tuple(entries)


# model-table column index -> the pricing axis; `_pricing` and `_tier_entry`
# read the five rate columns through it, so the column map lives once
_COLUMN_AXES = {
    1: "input",
    2: "cache_write",
    3: "cache_write_1h",
    4: "cache_read",
    5: "output",
}


def _amounts(row: list[str], model_id: str, url: str) -> dict[str, float]:
    """the row's five rate cells as axis -> USD per 1M tokens."""
    return {axis: _amount(row[col], model_id, url) for col, axis in _COLUMN_AXES.items()}


def _pricing(
    row: list[str], model_id: str, url: str, window_rates: tuple[dict[str, object], ...]
) -> Pricing:
    """the base Pricing from one model-table row, with the given window_rates."""
    amounts = _amounts(row, model_id, url)
    return Pricing(
        input_cost_per_token=amounts["input"] / 1e6,
        output_cost_per_token=amounts["output"] / 1e6,
        mode="chat",
        cache_read_cost_per_token=amounts["cache_read"] / 1e6,
        cache_write_cost_per_token=amounts["cache_write"] / 1e6,
        cache_write_1h_cost_per_token=amounts["cache_write_1h"] / 1e6,
        window_rates=window_rates,
    )


def _tier_entry(row: list[str], threshold: int, model_id: str, url: str) -> dict[str, object]:
    """the over-threshold row as a window_rates entry (the xai long-context shape)."""
    amounts = _amounts(row, model_id, url)
    return {
        "min_tokens": threshold,
        "input_mtok": amounts["input"],
        "output_mtok": amounts["output"],
        "cache_read_mtok": amounts["cache_read"],
        "cache_write_mtok": amounts["cache_write"],
        "cache_write_1h_mtok": amounts["cache_write_1h"],
    }


def _tiered_rows(rows: list[list[str]], url: str) -> dict[tuple[str, int], set[str]]:
    """every (kind, threshold) a named tier row carries -> the set of model
    ids carrying it, read tolerantly so a broken row never raises here."""
    by_tier: dict[tuple[str, int], set[str]] = {}
    for row in rows:
        try:
            check_row(row, url)
            slug, tier = split_name(row[0], url)
        except FetchError:
            continue
        if tier is not None:
            by_tier.setdefault(tier, set()).add(slug)
    return by_tier


def _paired_tier_model(
    name: str, tiered: dict[tuple[str, int], set[str]]
) -> tuple[str, tuple[str, int]] | None:
    """the single (model id, tier) a letterless tier row pairs with, or None
    when none or several do or its tier is unreadable; pairing is the
    complementary kind at the same threshold."""
    try:
        tier = _name_tier(name)
    except FetchError:
        return None
    if tier is None:
        return None
    kind, threshold = tier
    paired_kind = "over" if kind == "up to" else "up to"
    siblings = tiered.get((paired_kind, threshold), ())
    if len(siblings) != 1:
        return None
    return next(iter(siblings)), tier


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    text = fetch_text(cfg.scraper_url)
    url = cfg.scraper_url
    rows = model_table(text, url)[2:]
    tiered_rows = _tiered_rows(rows, url)
    # main_ids (which the fast table reads against) holds every row that parses
    main_ids: set[str] = set()
    tiered: list[tuple[tuple[str, int], list[str], bool]] = []
    plain: list[list[str]] = []
    for row in rows:
        try:
            check_row(row, url)
            slug, tier = split_name(row[0], url)
        except FetchError as exc:
            if not row or not row[0]:
                raise FetchError(f"row outside the pricing shape on {url}: {row!r}") from None
            if _letterless(row[0]):
                if len(row) == len(TABLE_HEADER):
                    paired = _paired_tier_model(row[0], tiered_rows)
                    if paired is not None:
                        paired_id, paired_tier = paired
                        if paired_id == model_id:
                            tiered.append((paired_tier, row, False))
                        continue
                raise FetchError(f"row outside the pricing shape on {url}: {row!r}") from None
            own_id = exc.model_id if isinstance(exc, _RowError) else None
            if own_id is None:
                own_id = _own_model_id(row[0])
            if own_id == model_id:
                raise
            continue
        main_ids.add(slug)
        if slug != model_id:
            continue
        if tier is None:
            plain.append(row)
        else:
            tiered.append((tier, row, True))
    if not tiered and not plain:
        return None
    if not tiered:
        if len(plain) > 1:
            raise FetchError(
                f"more than one untiered row for {model_id!r} on {url}: "
                f"{[row[0] for row in plain]!r}; fix: teach the anthropic "
                "scraper which row prices the model"
            )
        return _pricing(
            plain[0], model_id, url, _fast_window_rates(text, model_id, url, main_ids, cfg.key)
        )
    up_to = [(tier, row) for tier, row, named in tiered if named and tier[0] == "up to"]
    over = [(tier, row) for tier, row, named in tiered if named and tier[0] == "over"]
    nameless = [row for _tier, row, named in tiered if not named]
    if nameless or not (
        len(up_to) == 1 and len(over) == 1 and up_to[0][0][1] == over[0][0][1] and not plain
    ):
        raise FetchError(
            f"prompt-length tier rows for {model_id!r} on {url} are not one "
            f"'up to N' + 'over N' pair: found {[row[0] for _, row, _ in tiered]!r} "
            f"beside {len(plain)} untiered row(s); fix: teach the anthropic scraper "
            f"the page's tier layout"
        )
    threshold = up_to[0][0][1]
    base_row = up_to[0][1]
    over_row = over[0][1]
    return _pricing(
        base_row,
        model_id,
        url,
        (_tier_entry(over_row, threshold, model_id, url),)
        + _fast_window_rates(text, model_id, url, main_ids, cfg.key),
    )

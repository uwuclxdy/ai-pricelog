"""scrape per-token chat and image-generation pricing from the openai platform pricing page.

chat rows come from the standard tier island (see the detector for the
shape): [model, input, cached read, cache write?, output], dollars per 1M
tokens. input, cached read, cache write (the default 5m tier on
five-column rows) and output parse into Pricing. image-generation models
(the image section's standard-pane island; see the detector) carry one
Image and one Text row each, its cells sitting under the island's
headings and mapped by name, never by position (the live page moved
"Output" ahead of "Cached input" on 2026-10-21). the Text row's Input,
Cached input and Output cells price input, cached read and the output
axis; the Image row's Input and Output cells price image and
image_output, and its output fills the output axis when the Text row
carries none (its "-" output cell: the model has no text-output rate).
the Image row's cached-input cell has no rate axis and is dropped. a
heading this module cannot place on a group it prices is drift it must not
guess: FetchError names the heading. "null" and "-" cells mean the model
has no such rate. the batch pane repeats the image ids at discounted
rates; each covered model carries them as a window_rates entry keyed on
the request mode the pane's own data-value names, its rates read from
the pane's own cells (never derived from the standard rates: the page
rounds). a batch
group that cannot price every axis the standard one prices drops its
entry with a warning rather than shipping a partial override (an absent
axis inherits the base rate, so a partial entry would silently price
that axis at standard). the batch pane absent is additive drift: no
entry and a warning. max_tokens stays unset: the tables carry no context
column (the page prints context as a name annotation, not a field). chat
rows and image groups the match scan passes over are additive drift
detection already reported; the image group's modality rows are read
here alone, so a group whose rows carry no matching Image or Text row is
reported by this module (a warning names the missing label) before it
returns None. the matched row's cells are strict, so an unreadable rate
raises (plan #22) and never reads as unpriced. an id present in both the
chat and image tables is a page-structure anomaly and raises.

None = the model id is not on the page, or its rows carry no input or
output rate. FetchError = the fetch failed, the page has no standard
pricing table, a matched row carries an unreadable rate, a heading this
module cannot decode or map, a standard-pane heading set missing
Modality, Input, Output, or Cached input, a batch-pane heading set
missing Modality (the row label identifies the row), or a matched row
whose cell count disagrees with the heading set. any other rate heading
the batch pane lacks only drops its override, with a warning, and the
standard price stands. a headings-less island does not stop detection
(the group ids need no headings; see the detector), but this module
cannot price one of its groups without them.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.openai_page import (
    _BATCH_PANE,
    _group_id,
    _image_batch_pane,
    _image_standard_pane,
    _row_id,
    _standard_rows,
)
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup, fold_heading

log = logging.getLogger(__name__)

# the image table's headings, folded the way the rest of the repo compares
# pinned headers: the live page moved Output ahead of Cached input, so a
# cell's position says nothing and only its heading names the rate
_MODEL_HEADING = fold_heading("Model")
_LABEL_HEADING = fold_heading("Modality")
_INPUT_HEADING = fold_heading("Input")
_CACHED_INPUT_HEADING = fold_heading("Cached input")
_OUTPUT_HEADING = fold_heading("Output")
_STANDARD_HEADINGS = ("Modality", "Input", "Output", "Cached input")
_BATCH_HEADINGS = ("Modality",)
_ROW_HEADINGS = frozenset(fold_heading(heading) for heading in _STANDARD_HEADINGS)


def _rate(value, model_id: str, url: str) -> float | None:
    """the cell's per-1M-token rate; null/"-" means the model has no such rate."""
    if value is None or value == "-":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raise FetchError(f"unreadable rate {value!r} for {model_id} on {url}")


def _chat_row(rows: list[list], model_id: str, url: str) -> list | None:
    """the id's standard-tier row, or None; off-shape rows are drift detect reported."""
    for row in rows:
        try:
            if _row_id(row, url) != model_id:
                continue
        except FetchError:
            continue  # additive drift; detect already reported the row
        return row
    return None


def _image_group(groups: list[dict], model_id: str, url: str) -> dict | None:
    """the id's image group, or None; off-shape groups are drift detect reported."""
    for group in groups:
        try:
            if _group_id(group, url) != model_id:
                continue
        except FetchError:
            continue  # additive drift; detect already reported the group
        return group
    return None


def _heading_label(heading, url: str) -> str:
    """a heading's text: a plain label, or the label inside the page's tooltip-heading object."""
    label = heading
    if isinstance(heading, dict):
        tooltip = heading.get("__pricingTooltipHeading")
        label = tooltip.get("label") if isinstance(tooltip, dict) else None
    if not isinstance(label, str) or not label:
        raise FetchError(f"unreadable pricing heading on {url}: {heading!r}")
    return label


def _row_columns(
    headings: tuple[object, ...], required: tuple[str, ...], model_id: str, url: str
) -> dict[str, int]:
    """the row-cell index under each folded heading; the Model column names
    the group's own id, so it takes no cell.

    a heading this module cannot decode or map is a FetchError naming the
    heading: guessing its axis or dropping the cell would misprice the row
    silently. `required` names the columns the caller prices from: the
    standard pane needs every rate, while the batch pane needs only the
    label that identifies its rows, so a rate heading it drops falls
    through to the override-drop warning.
    """
    columns: dict[str, int] = {}
    for heading in headings:
        label = _heading_label(heading, url)
        folded = fold_heading(label)
        if folded == _MODEL_HEADING:
            continue
        if folded not in _ROW_HEADINGS:
            raise FetchError(f"unmapped pricing heading {label!r} for {model_id!r} on {url}")
        columns[folded] = len(columns)
    for heading in required:
        if fold_heading(heading) not in columns:
            raise FetchError(
                f"image pricing headings without {heading!r} for {model_id!r} on {url}"
            )
    return columns


def _modality_row(
    group: dict, label: str, columns: dict[str, int], model_id: str, url: str
) -> dict[str, object] | None:
    """the group's row for `label`, its cells keyed by folded heading.

    a group carrying rows but none for `label` is drift only this module
    sees: detect reads group ids, never rows, so the warning lands here.
    """
    rows = group.get("rows")
    if not isinstance(rows, list):
        raise FetchError(f"group for {model_id!r} without rows on {url}: {group!r}")
    label_column = columns[_LABEL_HEADING]
    for row in rows:
        if not isinstance(row, list) or len(row) <= label_column:
            continue
        if row[label_column] != label:
            continue
        if len(row) != len(columns):
            raise FetchError(
                f"image row for {model_id!r} with {len(row)} cells against"
                f" {len(columns)} columns on {url}: {row!r}"
            )
        return {heading: row[column] for heading, column in columns.items()}
    if rows:
        log.warning(
            "scrape for openai: group %r carries no %r row on %s: %r",
            model_id,
            label,
            url,
            rows,
        )
    return None


def _pricing_from_group(
    group: dict, columns: dict[str, int], model_id: str, url: str
) -> tuple[Pricing | None, tuple[str, ...]]:
    """the group's Image/Text rows mapped by heading onto the chat and image
    rate axes, with the axis keys the mapping priced (the batch entry needs
    the same set).

    an axis the mapping left unpriced names the row the modality rows failed
    to fill, in build order, so a batch pane that cannot price them all drops
    its entry naming what is missing.
    """
    text = _modality_row(group, "Text", columns, model_id, url)
    image = _modality_row(group, "Image", columns, model_id, url)
    if text is None:
        text_input = text_output = cache_read = None
    else:
        text_input = _rate(text.get(_INPUT_HEADING), model_id, url)
        text_output = _rate(text.get(_OUTPUT_HEADING), model_id, url)
        cache_read = _rate(text.get(_CACHED_INPUT_HEADING), model_id, url)
    if image is None:
        image_input = image_output = None
    else:
        image_input = _rate(image.get(_INPUT_HEADING), model_id, url)
        image_output = _rate(image.get(_OUTPUT_HEADING), model_id, url)
    # the Text output is the model's output rate; the Image row's output
    # prices output tokens on the image axis and fills the axis when the
    # Text row carries none
    output_cost = text_output if text_output is not None else image_output
    missing = tuple(
        axis
        for axis, cost in (
            ("input", text_input),
            ("output", output_cost),
            ("image", image_input),
            ("image_output", image_output),
        )
        if cost is None
    )
    if missing:
        return None, missing
    return (
        Pricing(
            text_input / 1e6,
            output_cost / 1e6,
            mode="chat",
            cache_read_cost_per_token=(cache_read / 1e6 if cache_read is not None else None),
            image_cost_per_token=image_input / 1e6,
            image_output_cost_per_token=image_output / 1e6,
        ),
        (),
    )


def _batch_entry(
    group: dict, columns: dict[str, int], model_id: str, url: str, standard: Pricing
) -> dict[str, object] | None:
    """the group's batch-mode window_rates entry, or None when it cannot be
    priced whole.

    the entry is dropped, never shipped partial: an absent axis inherits the
    base rate, so a partial entry would silently price the missing axes at
    the standard rates. `standard` is the standard group's own pricing, so a
    batch pane that prices an axis the standard one leaves unpriced still
    ships it, and one that drops an axis the standard prices does not.
    """
    pricing, missing = _pricing_from_group(group, columns, model_id, url)
    if (
        pricing is not None
        and standard.cache_read_cost_per_token is not None
        and pricing.cache_read_cost_per_token is None
    ):
        missing = (*missing, "cache_read")
    if missing:
        log.warning(
            "scrape for openai: batch group for %r prices no %s on %s; skipping the batch override",
            model_id,
            "/".join(missing),
            url,
        )
        return None
    rates = {
        "input_mtok": pricing.input_cost_per_token * 1e6,
        "output_mtok": pricing.output_cost_per_token * 1e6,
        "image_mtok": pricing.image_cost_per_token * 1e6,
        "image_output_mtok": pricing.image_output_cost_per_token * 1e6,
    }
    if pricing.cache_read_cost_per_token is not None:
        rates["cache_read_mtok"] = pricing.cache_read_cost_per_token * 1e6
    return {"mode": _BATCH_PANE, **rates}


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    soup = fetch_soup(cfg.scraper_url)
    chat_row = _chat_row(_standard_rows(soup, cfg.scraper_url), model_id, cfg.scraper_url)
    standard_pane = _image_standard_pane(soup, cfg.scraper_url)
    image_group = (
        _image_group(standard_pane.groups, model_id, cfg.scraper_url)
        if standard_pane is not None
        else None
    )
    if chat_row is not None and image_group is not None:
        raise FetchError(
            f"{model_id!r} appears in both the chat and image pricing tables on {cfg.scraper_url}"
        )
    if standard_pane is not None and image_group is not None:
        columns = _row_columns(
            standard_pane.headings, _STANDARD_HEADINGS, model_id, cfg.scraper_url
        )
        pricing, _ = _pricing_from_group(image_group, columns, model_id, cfg.scraper_url)
        if pricing is None:
            return None
        batch_pane = _image_batch_pane(soup, cfg.scraper_url)
        if batch_pane is None:
            log.warning(
                "scrape for openai: no image-generation batch pane on %s; %r keeps the"
                " standard rates",
                cfg.scraper_url,
                model_id,
            )
            return pricing
        # the pane covering a subset of the standard ids is normal page
        # evolution: no entry, no warning
        batch_group = _image_group(batch_pane.groups, model_id, cfg.scraper_url)
        if batch_group is None:
            return pricing
        batch_columns = _row_columns(
            batch_pane.headings, _BATCH_HEADINGS, model_id, cfg.scraper_url
        )
        entry = _batch_entry(batch_group, batch_columns, model_id, cfg.scraper_url, pricing)
        if entry is None:
            return pricing
        return replace(pricing, window_rates=(entry,))
    if chat_row is None:
        return None
    input_cost = _rate(chat_row[1], model_id, cfg.scraper_url)
    cache_read = _rate(chat_row[2], model_id, cfg.scraper_url)
    cache_write = _rate(chat_row[3], model_id, cfg.scraper_url) if len(chat_row) == 5 else None
    output_cost = _rate(chat_row[-1], model_id, cfg.scraper_url)
    if input_cost is None or output_cost is None:
        return None
    return Pricing(
        input_cost / 1e6,
        output_cost / 1e6,
        mode="chat",
        cache_read_cost_per_token=(cache_read / 1e6 if cache_read is not None else None),
        cache_write_cost_per_token=(cache_write / 1e6 if cache_write is not None else None),
    )

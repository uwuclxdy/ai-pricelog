"""scrape per-token chat and image-generation pricing from the openai platform pricing page.

chat rows come from the standard tier island (see the detector for the
shape): [model, input, cached read, cache write?, output], dollars per 1M
tokens. input, cached read, cache write (the default 5m tier on
five-column rows) and output parse into Pricing. image-generation models
(the image section's standard-pane island; see the detector) carry one
Image and one Text row [label, input, cached input, output] each: the
Text row prices input, cached read and the output axis, the Image row
prices image and image_output, and the Image row's output fills the
output axis when the Text row carries none (its "-" output cell: the
model has no text-output rate). the Image row's cached-input cell has no
rate axis and is dropped. "null" and "-" cells mean the model has no such
rate. max_tokens stays unset: the tables carry no context column (the
page prints context as a name annotation, not a field). chat rows and
image groups the match scan passes over are additive drift detection
already reported; the image group's modality rows are read here alone,
so a group whose rows carry no matching Image or Text row is reported
by this module (a warning names the missing label) before it returns
None. the matched row's cells are strict, so an unreadable rate raises
(plan #22) and never reads as unpriced. an id present in both the chat
and image tables is a page-structure anomaly and raises.

None = the model id is not on the page, or its rows carry no input or
output rate. FetchError = the fetch failed, the page has no standard
pricing table, or the matched row carries an unreadable rate.
"""

from __future__ import annotations

import logging

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.openai_page import (
    _group_id,
    _image_standard_groups,
    _row_id,
    _standard_rows,
)
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup

log = logging.getLogger(__name__)


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


def _modality_row(group: dict, label: str, model_id: str, url: str) -> list | None:
    """the group's [label, input, cached input, output] row for `label`.

    a group carrying rows but none for `label` is drift only this module
    sees: detect reads group ids, never rows, so the warning lands here.
    """
    rows = group.get("rows")
    if not isinstance(rows, list):
        raise FetchError(f"group for {model_id!r} without rows on {url}: {group!r}")
    for row in rows:
        if isinstance(row, list) and len(row) == 4 and row[0] == label:
            return row
    if rows:
        log.warning(
            "scrape for openai: group %r carries no %r row on %s: %r",
            model_id,
            label,
            url,
            rows,
        )
    return None


def _pricing_from_group(group: dict, model_id: str, url: str) -> Pricing | None:
    """the group's Image/Text rows mapped onto the chat and image rate axes."""
    text = _modality_row(group, "Text", model_id, url)
    image = _modality_row(group, "Image", model_id, url)
    text_input = _rate(text[1], model_id, url) if text is not None else None
    text_output = _rate(text[3], model_id, url) if text is not None else None
    cache_read = _rate(text[2], model_id, url) if text is not None else None
    image_input = _rate(image[1], model_id, url) if image is not None else None
    image_output = _rate(image[3], model_id, url) if image is not None else None
    # the Text output is the model's output rate; the Image row's output
    # prices output tokens on the image axis and fills the axis when the
    # Text row carries none
    output_cost = text_output if text_output is not None else image_output
    if text_input is None or image_input is None or output_cost is None:
        return None
    return Pricing(
        text_input / 1e6,
        output_cost / 1e6,
        mode="chat",
        cache_read_cost_per_token=(cache_read / 1e6 if cache_read is not None else None),
        image_cost_per_token=image_input / 1e6,
        image_output_cost_per_token=(image_output / 1e6 if image_output is not None else None),
    )


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    soup = fetch_soup(cfg.scraper_url)
    chat_row = _chat_row(_standard_rows(soup, cfg.scraper_url), model_id, cfg.scraper_url)
    groups = _image_standard_groups(soup, cfg.scraper_url)
    image_group = _image_group(groups, model_id, cfg.scraper_url) if groups is not None else None
    if chat_row is not None and image_group is not None:
        raise FetchError(
            f"{model_id!r} appears in both the chat and image pricing tables on {cfg.scraper_url}"
        )
    if image_group is not None:
        return _pricing_from_group(image_group, model_id, cfg.scraper_url)
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

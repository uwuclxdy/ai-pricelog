"""scrape per-token chat pricing from the deepinfra pricing page.

the per-token tables (Model | Context | $ per 1M input tokens | $ per 1M
output tokens | Actions) price each model per 1M tokens. the input cell
holds one amount, or two as "$base / $cached cached" when the model bills
cache reads; the output cell holds exactly one. a model badged with a
limited-time discount prints the list amount and the charged amount in each
cell: both runs sit in one wrapper span the cell holds alone, the list run
first in a span the page labels "List price", and the charged run is the
rate in force, so the row records the discounted price the page bills
today. any other markup that names a list price in a price cell is a
page-shape break (FetchError), never a read. the context cell ("1024k") ->
max_tokens_in, k counted as 1024 (the repo convention); a `-` cell, the
page's no-context marker, leaves max_tokens_in None. rows key by the
model-cell link's last path segment, lowercased, the detector's id. a
matched cell pair in any other amount shape, an amount the grammar cannot
read, or an unreadable context, is a page-shape break (FetchError), so a
silent misread cannot ship. rows the match scan passes over with a
link-less or out-of-charset model cell are additive drift detection
already reported.

None = the model id is not on the page. FetchError = the fetch failed, the
page has no per-token model table, or a matched cell carries an unexpected
shape.
"""

from __future__ import annotations

import re

from bs4 import Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.deepinfra_page import _model_tables, _row_id, _table_rows
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import (
    MAX_COUNT_DIGITS,
    FetchError,
    amount_scan,
    fetch_soup,
    unreadable_rate_error,
)

_CONTEXT_RE = re.compile(rf"^(\d{{1,{MAX_COUNT_DIGITS}}})k$")
_LIST_PRICE = {"aria-label": "List price"}


def _charged(
    cell: Tag, amounts: list[str], listed_count: int, model_id: str, url: str
) -> list[str]:
    """the charged run of a discounted cell.

    the page prints one wrapper span holding two spans, the list run first in
    the span labelled "List price", the charged run second, and the cell holds
    the wrapper alone; the cell's amounts split into those two runs. any other
    arrangement, or a second list-price mention in the cell, is a page shape
    no capture shows, so it raises instead of reading a side.
    """
    labels = cell.find_all("span", attrs=_LIST_PRICE)
    wrapper = labels[0].parent if len(labels) == 1 else None
    pair = wrapper.find_all(recursive=False) if wrapper is not None else []
    runs = [amount_scan(span.get_text(" ", strip=True), before="$")[0] for span in pair]
    if (
        len(amounts) != 2 * listed_count
        or wrapper is None
        or cell.contents != [wrapper]
        or wrapper.name != "span"
        or len(wrapper.contents) != 2
        or len(pair) != 2
        or pair[0] is not labels[0]
        or pair[1].name != "span"
        or any(span.find(True) is not None for span in pair)
        or str(cell).casefold().count("list") != 1
        or runs != [amounts[:listed_count], amounts[listed_count:]]
    ):
        raise FetchError(
            f"malformed discounted cell for {model_id} on {url}: "
            f"{len(labels)} span(s) labelled 'List price' over {len(amounts)} "
            f"amount(s); want the cell to hold one wrapper span alone, the list "
            f"run first and the charged run second, each a span of plain text "
            f"holding {listed_count} amount(s), and no other list mention"
        )
    return amounts[listed_count:]


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    soup = fetch_soup(cfg.scraper_url)
    tables = _model_tables(soup)
    if not tables:
        raise FetchError(f"no per-token model table on {cfg.scraper_url}")
    for table in tables:
        for row in _table_rows(table):
            if not row:
                continue
            try:
                if _row_id(row[0], cfg.scraper_url) != model_id:
                    continue
            except FetchError:
                continue  # additive drift; detect already reported the row
            if len(row) < 4:
                raise FetchError(f"malformed row for {model_id} on {cfg.scraper_url}")
            input_text = row[2].get_text(" ", strip=True)
            output_text = row[3].get_text(" ", strip=True)
            input_amounts, input_malformed = amount_scan(input_text, before="$")
            output_amounts, output_malformed = amount_scan(output_text, before="$")
            if input_malformed:
                raise unreadable_rate_error(input_text, model_id, cfg.scraper_url)
            if output_malformed:
                raise unreadable_rate_error(output_text, model_id, cfg.scraper_url)
            if any(cell.find("span", attrs=_LIST_PRICE) for cell in row[2:4]):
                input_amounts = _charged(row[2], input_amounts, 2, model_id, cfg.scraper_url)
                output_amounts = _charged(row[3], output_amounts, 1, model_id, cfg.scraper_url)
            elif "list" in f"{row[2]}{row[3]}".casefold():
                raise FetchError(
                    f"malformed discounted cell for {model_id} on {cfg.scraper_url}: "
                    "a list price outside the labelled span"
                )
            if len(input_amounts) == 2:
                input_cost, cache_read = (
                    float(amount.replace(",", "")) for amount in input_amounts
                )
            elif len(input_amounts) == 1:
                input_cost, cache_read = float(input_amounts[0].replace(",", "")), None
            else:
                raise FetchError(
                    f"malformed input cell for {model_id} on {cfg.scraper_url}: "
                    f"{len(input_amounts)} amounts, want 1 or 2"
                )
            if len(output_amounts) != 1:
                raise FetchError(
                    f"malformed output cell for {model_id} on {cfg.scraper_url}: "
                    f"{len(output_amounts)} amounts, want 1"
                )
            context = row[1].get_text(" ", strip=True)
            if context == "-":
                max_tokens_in = None
            else:
                context_match = _CONTEXT_RE.fullmatch(context)
                if context_match is None:
                    raise FetchError(
                        f"unreadable context {context!r} for {model_id} on {cfg.scraper_url}"
                    )
                max_tokens_in = int(context_match.group(1)) * 1024
            return Pricing(
                input_cost / 1e6,
                float(output_amounts[0].replace(",", "")) / 1e6,
                mode="chat",
                max_tokens_in=max_tokens_in,
                cache_read_cost_per_token=(cache_read / 1e6 if cache_read is not None else None),
            )
    return None

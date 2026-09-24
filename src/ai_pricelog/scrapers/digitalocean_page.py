"""scrape per-token serverless pricing from the digitalocean docs page.

same per-model tables as detection. a Serverless Inference cell is a
span.gen-ai-pricing-matrix (role=table): a header row naming the columns
(Processing mode, Prompt length, Input, Output, Cache write (5m), Cache
write (1h), Cache read) and one data row per processing mode. the
standard rate is the first Standard row carrying both an input and an
output amount (tiered models price the "<= 272K tokens" row first);
later prompt-length rows are long-context tiers the index has no slot
for and are dropped. when no Standard row carries both, the first
Standard row with a priced input and an explicit rate-less output cell
(N/A, "-", empty) prices output 0.0: an input-only model bills input
tokens only, so its free output is a real zero (the litellm convention,
google's embedding rows); a matrix without an Output column at all is a
shape break, never an input-only model, and a matrix whose Standard rows
carry no priced input stays one too. the
cache-read rate is the chosen row's Cache read cell; a matrix without
the column (or with an N/A cell) carries no cache rate. the Cache write
columns are write rates the index skips (owner ruling 2026-09-18; todo
46). a mode row prices its own stored id, the base id with the mode's
slug appended, so "claude-opus-5-fast-mode" reads the Fast Mode row and
"claude-opus-5" the Standard row. a matrix whose columns lack the pinned
labels, whose chosen row carries no input amount, or whose rate cells
hold unparseable text is a page-shape break (FetchError), so a silent
misread cannot ship.

None = the model id is not among the in-scope rows (image models are out
of scope, and a mode row the page no longer carries reads absent).
FetchError = the fetch failed, the page has no per-model serverless
table, or a matched matrix carries an unexpected shape.
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.digitalocean_page import (
    _MODE_LABEL,
    _column_index,
    _matrix_rows,
    _normalize_id,
    _priced_rows,
)
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup

_AMOUNT_RE = re.compile(r"^\$(\d+(?:\.\d+)?)$")
_NONE_CELLS = frozenset({"n/a", "-", ""})


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    requested = _normalize_id(model_id)
    for name, matrix in _priced_rows(fetch_soup(cfg.scraper_url), cfg.scraper_url):
        labels, data_rows = _matrix_rows(matrix, cfg.scraper_url)
        mode_col = _column_index(labels, _MODE_LABEL, cfg.scraper_url)
        input_only: tuple[float, float | None] | None = None
        for row in data_rows:
            slug = _normalize_id(row[mode_col])
            candidate = name if slug == "standard" else f"{name}-{slug}"
            if candidate != requested:
                continue
            input_cost, output_cost, cache_read = _row_rates(
                labels, row, requested, cfg.scraper_url
            )
            if input_cost is not None and output_cost is not None:
                return Pricing(
                    input_cost_per_token=input_cost / 1e6,
                    output_cost_per_token=output_cost / 1e6,
                    mode="chat",
                    cache_read_cost_per_token=cache_read / 1e6 if cache_read is not None else None,
                )
            if slug != "standard":
                raise FetchError(
                    f"no per-1M input/output rates for {requested} on {cfg.scraper_url}"
                )
            if input_cost is not None and input_only is None:
                # an input-only Standard row: the page prices no output
                # (free output); a later row carrying both still wins
                input_only = (input_cost, cache_read)
        if input_only is not None:
            input_cost, cache_read = input_only
            return Pricing(
                input_cost_per_token=input_cost / 1e6,
                output_cost_per_token=0.0,
                mode="chat",
                cache_read_cost_per_token=cache_read / 1e6 if cache_read is not None else None,
            )
        if name == requested:
            raise FetchError(f"no per-1M input/output rates for {requested} on {cfg.scraper_url}")
    return None


def _row_rates(
    labels: tuple[str, ...], row: tuple[str, ...], model_id: str, url: str
) -> tuple[float | None, float | None, float | None]:
    """(input, output, cache_read) per-1M dollars from one matrix data row.

    a matrix without an Output column is a shape break, never an input-only
    model: only an explicit N/A (or blank) output cell prices output 0.0.
    """
    if "output" not in labels:
        raise FetchError(f"pricing matrix without an 'output' column on {url}")
    return (
        _cell_amount(labels, row, "input", model_id, url),
        _cell_amount(labels, row, "output", model_id, url),
        _cell_amount(labels, row, "cache read", model_id, url),
    )


def _cell_amount(
    labels: tuple[str, ...], row: tuple[str, ...], label: str, model_id: str, url: str
) -> float | None:
    """one rate cell's per-1M dollars; a missing column or an N/A cell is None."""
    try:
        text = row[labels.index(label)]
    except ValueError:
        return None
    if text.casefold() in _NONE_CELLS:
        return None
    match = _AMOUNT_RE.fullmatch(text)
    if match is None:
        raise FetchError(f"unparseable rate cell {text!r} for {model_id} on {url}")
    return float(match.group(1))

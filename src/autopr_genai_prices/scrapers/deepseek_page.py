"""scrape per-token pricing for deepseek models.

same table as detection. pricing rows are keyed by their label cell
(1M INPUT TOKENS (CACHE MISS) / 1M OUTPUT TOKENS) and split into OFF-PEAK
and PEAK subrows; the PEAK subrow's value is taken, falling back to OFF-PEAK
only when a label carries no PEAK subrow (module policy: peak pricing, the
price a human verifier would quote). 1M INPUT TOKENS (CACHE HIT) is
cache-hit pricing and ignored. values are USD per 1M tokens -> /1e6.
max_tokens comes from the MAX OUTPUT row ("MAXIMUM: 384K" -> 384 * 1024);
that row may span all model columns as one merged cell, in which case the
single value applies to every model.

None = the model id is not on the page, or a needed price is missing.
FetchError = the fetch failed or the page has no MODEL header table.
"""

import re

from autopr_genai_prices.config import ProviderCfg
from autopr_genai_prices.detectors.deepseek_page import _model_table
from autopr_genai_prices.pricing import Pricing
from autopr_genai_prices.web import extract_tables, fetch_soup

_CACHE_MISS = "1M INPUT TOKENS (CACHE MISS)"
_OUTPUT = "1M OUTPUT TOKENS"
_MARKERS = ("OFF-PEAK", "PEAK")
_PRICE_PATTERN = re.compile(r"\$(\d+(?:\.\d+)?)")
_MAX_OUTPUT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*K\b", re.IGNORECASE)


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    tables = extract_tables(fetch_soup(cfg.scraper_url))
    table = _model_table(tables, cfg.scraper_url)
    ids = [cell.strip() for cell in table[0][1:]]
    if model_id not in ids:
        return None
    prices = _pricing_cells(table[1:], ids.index(model_id))
    input_cost = _dollars(_peak(prices.get(_CACHE_MISS, {})))
    output_cost = _dollars(_peak(prices.get(_OUTPUT, {})))
    if input_cost is None or output_cost is None:
        return None
    return Pricing(
        input_cost_per_token=input_cost / 1e6,
        output_cost_per_token=output_cost / 1e6,
        mode="chat",
        max_tokens=_max_tokens(table[1:], ids, model_id),
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


def _peak(cells: dict[str, str]) -> str | None:
    peak = cells.get("PEAK")
    return peak if peak is not None else cells.get("OFF-PEAK")


def _max_tokens(rows: list[list[str]], ids: list[str], model_id: str) -> int:
    for row in rows:
        if not row or row[0] != "MAX OUTPUT":
            continue
        cells = row[1:]
        if len(cells) == len(ids):
            # one cell per model column: the model takes its own cell's value;
            # a cell without a K value yields 0, never another model's value
            match = _MAX_OUTPUT_PATTERN.search(cells[ids.index(model_id)])
            return int(float(match.group(1))) * 1024 if match else 0
        # merged cell(s) spanning the model columns: the first K value applies
        # to every model
        for cell in cells:
            match = _MAX_OUTPUT_PATTERN.search(cell)
            if match:
                return int(float(match.group(1))) * 1024
        return 0
    return 0


def _dollars(text: str | None) -> float | None:
    if text is None:
        return None
    match = _PRICE_PATTERN.search(text)
    return float(match.group(1)) if match else None

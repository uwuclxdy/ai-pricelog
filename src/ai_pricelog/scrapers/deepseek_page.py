"""scrape per-token pricing for deepseek models.

same table as detection. pricing rows are keyed by their label cell
(1M INPUT TOKENS (CACHE MISS) / 1M OUTPUT TOKENS / 1M INPUT TOKENS (CACHE
HIT)) and split into OFF-PEAK and PEAK subrows. the OFF-PEAK value becomes the
default price and the PEAK value the peak fields, with the schedule footnote
("Peak hours are 01:00 - 04:00 and 06:00 - 10:00 UTC") parsed into
peak_windows pairs. labels without a PEAK subrow are flat (no peak fields).
peak subrows without the footnote are a scrape failure: the entry builder
requires windows with peak prices. CACHE HIT parses like CACHE MISS into the
cache-read fields: OFF-PEAK -> cache_read_cost_per_token, PEAK ->
peak_cache_read_cost_per_token. values are USD per 1M tokens -> /1e6.
max_tokens_out comes from the MAX OUTPUT row ("MAXIMUM: 384K" -> 384 *
1024) and max_tokens_in from the CONTEXT LENGTH row ("1M" -> 1024 * 1024);
either row may span all model columns as one merged cell, in which case the
single value applies to every model.

None = the model id is not on the page, or a needed price is missing.
FetchError = the fetch failed or the page has no MODEL header table.
"""

import re

from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.deepseek_page import _model_table
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, extract_tables, fetch_soup

_CACHE_MISS = "1M INPUT TOKENS (CACHE MISS)"
_CACHE_HIT = "1M INPUT TOKENS (CACHE HIT)"
_OUTPUT = "1M OUTPUT TOKENS"
_MARKERS = ("OFF-PEAK", "PEAK")
_PRICE_PATTERN = re.compile(r"\$(\d+(?:\.\d+)?)")
_K_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*K\b", re.IGNORECASE)
_M_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*M\b", re.IGNORECASE)
_FOOTNOTE_PATTERN = re.compile(
    r"Peak hours are (\d{2}:\d{2}) - (\d{2}:\d{2}) and (\d{2}:\d{2}) - (\d{2}:\d{2}) UTC"
)


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    soup = fetch_soup(cfg.scraper_url)
    tables = extract_tables(soup)
    table = _model_table(tables, cfg.scraper_url)
    ids = [cell.strip() for cell in table[0][1:]]
    if model_id not in ids:
        return None
    prices = _pricing_cells(table[1:], ids.index(model_id))
    off_input = _dollars(prices.get(_CACHE_MISS, {}).get("OFF-PEAK"))
    off_output = _dollars(prices.get(_OUTPUT, {}).get("OFF-PEAK"))
    off_cache_read = _dollars(prices.get(_CACHE_HIT, {}).get("OFF-PEAK"))
    if off_input is None or off_output is None:
        return None
    peak_input = _dollars(prices.get(_CACHE_MISS, {}).get("PEAK"))
    peak_output = _dollars(prices.get(_OUTPUT, {}).get("PEAK"))
    peak_cache_read = _dollars(prices.get(_CACHE_HIT, {}).get("PEAK"))
    if peak_input is None and peak_output is None and peak_cache_read is None:
        return Pricing(
            input_cost_per_token=off_input / 1e6,
            output_cost_per_token=off_output / 1e6,
            mode="chat",
            max_tokens_in=_window_tokens(
                table[1:], ids, model_id, "CONTEXT LENGTH", _M_PATTERN, 1024 * 1024
            ),
            max_tokens_out=_window_tokens(table[1:], ids, model_id, "MAX OUTPUT", _K_PATTERN, 1024),
            cache_read_cost_per_token=_per_token(off_cache_read),
        )
    if peak_input is None or peak_output is None:
        return None
    return Pricing(
        input_cost_per_token=off_input / 1e6,
        output_cost_per_token=off_output / 1e6,
        mode="chat",
        max_tokens_in=_window_tokens(
            table[1:], ids, model_id, "CONTEXT LENGTH", _M_PATTERN, 1024 * 1024
        ),
        max_tokens_out=_window_tokens(table[1:], ids, model_id, "MAX OUTPUT", _K_PATTERN, 1024),
        cache_read_cost_per_token=_per_token(off_cache_read),
        peak_input_cost_per_token=peak_input / 1e6,
        peak_output_cost_per_token=peak_output / 1e6,
        peak_windows=_peak_windows(soup, cfg.scraper_url),
        peak_cache_read_cost_per_token=_per_token(peak_cache_read),
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


def _peak_windows(soup: BeautifulSoup, url: str) -> tuple[tuple[str, str], ...]:
    """The schedule footnote's two peak windows as ("HH:MM:SSZ", "HH:MM:SSZ") pairs."""
    match = _FOOTNOTE_PATTERN.search(soup.get_text(" ", strip=True))
    if match is None:
        raise FetchError(f"peak price rows without a schedule footnote on {url}")
    first_start, first_end, second_start, second_end = match.groups()
    return (
        (f"{first_start}:00Z", f"{first_end}:00Z"),
        (f"{second_start}:00Z", f"{second_end}:00Z"),
    )


def _window_tokens(
    rows: list[list[str]],
    ids: list[str],
    model_id: str,
    label: str,
    pattern: re.Pattern[str],
    multiplier: int,
) -> int:
    for row in rows:
        if not row or row[0] != label:
            continue
        cells = row[1:]
        if len(cells) == len(ids):
            # one cell per model column: the model takes its own cell's value;
            # a cell without a matching value yields 0, never another model's
            match = pattern.search(cells[ids.index(model_id)])
            return int(float(match.group(1))) * multiplier if match else 0
        # merged cell(s) spanning the model columns: the first value applies
        # to every model
        for cell in cells:
            match = pattern.search(cell)
            if match:
                return int(float(match.group(1))) * multiplier
        return 0
    return 0


def _dollars(text: str | None) -> float | None:
    if text is None:
        return None
    match = _PRICE_PATTERN.search(text)
    return float(match.group(1)) if match else None


def _per_token(dollars: float | None) -> float | None:
    """USD per 1M tokens -> USD per token."""
    return None if dollars is None else dollars / 1e6

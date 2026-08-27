"""scrape per-token serverless pricing from the digitalocean docs page.

same per-model tables as detection. a Serverless Inference cell is a
span.gen-ai-pricing-grid of label/value span pairs: one or more
input/output groups ("Input/output tokens", tiered "Prompts ≤272K tokens"
groups) and usually a "Prompt caching" group. the first group carrying an
input AND output rate is the standard rate: input lines read "per 1M
input tokens", output lines "per 1M output tokens", or both read "per 1M
tokens" in input-then-output order (digitalocean-hosted rows). later
groups are long-context tiers the index has no slot for and are dropped.
the cache-read rate is the "per 1M cache read" line of the caching group;
a caching group whose only rate line is a bare "per 1M tokens" amount is
the digitalocean-hosted spelling of the same rate. cache-creation lines
are write rates, not read rates, and are skipped. a grid whose groups do
not yield an input/output pair, whose spans go out of label/value
pairing, or whose caching group carries an unrecognizable shape is a
page-shape break (FetchError), so a silent misread cannot ship.

None = the model id is not among the in-scope rows (image models are out
of scope). FetchError = the fetch failed, the page has no per-model
serverless table, or a matched grid carries an unexpected shape.
"""

from __future__ import annotations

import re

from bs4 import Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.digitalocean_page import _normalize_id, _priced_rows
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError, fetch_soup

_AMOUNT = r"\$(\d+(?:\.\d+)?)"
_INPUT_LINE_RE = re.compile(_AMOUNT + r" per 1M input tokens")
_OUTPUT_LINE_RE = re.compile(_AMOUNT + r" per 1M output tokens")
_CACHE_READ_LINE_RE = re.compile(_AMOUNT + r" per 1M cache read")
_PLAIN_LINE_RE = re.compile(_AMOUNT + r" per 1M tokens")


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    rows = _priced_rows(fetch_soup(cfg.scraper_url), cfg.scraper_url)
    for name, grid in rows:
        if name != _normalize_id(model_id):
            continue
        input_cost, output_cost, cache_read = _parse_grid(grid, model_id, cfg.scraper_url)
        return Pricing(
            input_cost_per_token=input_cost / 1e6,
            output_cost_per_token=output_cost / 1e6,
            mode="chat",
            cache_read_cost_per_token=cache_read / 1e6 if cache_read is not None else None,
        )
    return None


def _parse_grid(grid: Tag, model_id: str, url: str) -> tuple[float, float, float | None]:
    """(input, output, cache_read) per-1M dollars from a pricing grid cell."""
    groups = _grid_groups(grid, model_id, url)
    base: tuple[float, float] | None = None
    cache_read: float | None = None
    for label, value in groups:
        input_match = _INPUT_LINE_RE.search(value)
        output_match = _OUTPUT_LINE_RE.search(value)
        if base is None and input_match and output_match:
            base = (float(input_match.group(1)), float(output_match.group(1)))
        elif base is None:
            amounts = _PLAIN_LINE_RE.findall(value)
            if len(amounts) >= 2:
                base = (float(amounts[0]), float(amounts[1]))
        if cache_read is None and "cach" in label.casefold():
            cache_match = _CACHE_READ_LINE_RE.search(value)
            if cache_match:
                cache_read = float(cache_match.group(1))
            else:
                amounts = _PLAIN_LINE_RE.findall(value)
                if len(amounts) == 1:
                    cache_read = float(amounts[0])
                else:
                    raise FetchError(
                        f"unparseable caching group for {model_id} on {url}: {value!r}"
                    )
    if base is None:
        raise FetchError(f"no per-1M input/output rates for {model_id} on {url}")
    return base[0], base[1], cache_read


def _grid_groups(grid: Tag, model_id: str, url: str) -> list[tuple[str, str]]:
    """the grid's label/value span pairs; odd span counts are shape breaks."""
    spans = grid.find_all("span", recursive=False)
    if len(spans) % 2:
        raise FetchError(f"malformed pricing grid for {model_id} on {url}: {len(spans)} spans")
    groups: list[tuple[str, str]] = []
    for index in range(0, len(spans), 2):
        label = spans[index].get_text(" ", strip=True)
        value = spans[index + 1].get_text(" ", strip=True)
        if "$" in label or "$" not in value:
            raise FetchError(f"malformed pricing grid for {model_id} on {url}: span pairing broke")
        groups.append((label, value))
    return groups

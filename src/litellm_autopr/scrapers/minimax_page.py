"""scrape MiniMax pay-as-you-go pricing.

reads https://platform.minimax.io/docs/guides/pricing-paygo.md (static markdown).
token-priced tables have a header `Model | Input | Output | ...` (caching
columns ignored). MiniMax-M3 rows live in Standard/Priority tab variants and
are split by context size; we take the first M3 row, which is the Standard
tab's <=512k row. price cells like `~~$0.60~~ $0.30 / M tokens` carry a
strikethrough original plus the current price: we take the LAST dollar amount
in the cell. dollars per 1M tokens -> divided by 1e6. the page carries no
context window, so max_tokens stays 0 (the entry builder omits it).
"""

import re

from litellm_autopr.config import ProviderCfg
from litellm_autopr.detectors.minimax_page import _markdown_tables
from litellm_autopr.pricing import Pricing
from litellm_autopr.web import FetchError, fetch_text

_AMOUNT_RE = re.compile(r"\$(\d+(?:\.\d+)?)")
_MODEL_RE = re.compile(r"\*\*(.+?)\*\*")


def _last_amount(cell: str) -> float | None:
    amounts = _AMOUNT_RE.findall(cell)
    return float(amounts[-1]) if amounts else None


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    text = fetch_text(cfg.scraper_url)
    pricing_tables = [
        table
        for table in _markdown_tables(text)
        if table[0][0] == "Model" and "Input" in table[0] and "Output" in table[0]
    ]
    if not pricing_tables:
        raise FetchError(f"no pricing tables found on {cfg.scraper_url}")
    for table in pricing_tables:
        input_idx = table[0].index("Input")
        output_idx = table[0].index("Output")
        for row in table[2:]:
            match = _MODEL_RE.search(row[0])
            if not match or match.group(1) != model_id:
                continue
            if len(row) <= max(input_idx, output_idx):
                return None
            input_amount = _last_amount(row[input_idx])
            output_amount = _last_amount(row[output_idx])
            if input_amount is None or output_amount is None:
                return None
            return Pricing(input_amount / 1e6, output_amount / 1e6, mode="chat", max_tokens=0)
    return None

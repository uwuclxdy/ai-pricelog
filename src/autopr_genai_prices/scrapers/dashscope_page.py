"""scrape Model Studio token pricing from Alibaba's international pricing page.

reads https://www.alibabacloud.com/help/en/model-studio/model-pricing (static
html). pricing tables start with a `Model ID` header cell; the price columns
are the cells whose header starts with `Input price` / `Output price`. tables
whose output column is split carry a sub-header row (`Non-Thinking mode` /
`Thinking mode` cells under the output span); we take the Non-Thinking
sub-column. a row matches when the first whitespace token of its first cell
equals the requested id; tiered continuation rows (`256K<Token<=1M`) carry no
id and are skipped. the `Deployment scope` cell must contain `International`:
rows scoped to Chinese mainland / Global / Japan / US are skipped for now (no
entry beats a wrong one; the pipeline retries next run). price cells like
`List price $0.4 Limited-time 20% off` yield the first `$` float; USD per 1M
tokens -> /1e6. the page carries no context window, so max_tokens stays 0
(the entry builder omits it).
"""

import re

from autopr_genai_prices.config import ProviderCfg
from autopr_genai_prices.pricing import Pricing
from autopr_genai_prices.web import FetchError, extract_tables, fetch_soup

_AMOUNT_RE = re.compile(r"\$(\d+(?:\.\d+)?)")


def _column(header: list[str], prefix: str) -> int | None:
    for index, cell in enumerate(header):
        if cell.startswith(prefix):
            return index
    return None


def _first_amount(cell: str) -> float | None:
    match = _AMOUNT_RE.search(cell)
    return float(match.group(1)) if match else None


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    tables = extract_tables(fetch_soup(cfg.scraper_url))
    if not any(table and table[0] and table[0][0].startswith("Model ID") for table in tables):
        raise FetchError(f"no pricing tables found on {cfg.scraper_url}")
    for table in tables:
        if not table or not table[0] or not table[0][0].startswith("Model ID"):
            continue
        header = table[0]
        input_idx = _column(header, "Input price")
        output_idx = _column(header, "Output price")
        if input_idx is None or output_idx is None:
            continue
        rows = table[1:]
        sub_offset = 0
        if rows and rows[0] and rows[0][0].startswith(("Non-Thinking mode", "Thinking mode")):
            sub_offset = _column(rows[0], "Non-Thinking")
            if sub_offset is None:
                continue
            rows = rows[1:]
        for row in rows:
            if not row or not row[0]:
                continue
            if row[0].split()[0] != model_id:
                continue
            if len(row) <= 1 or "International" not in row[1]:
                continue
            if len(row) <= max(input_idx, output_idx + sub_offset):
                # a short row is not a verdict: a later table may carry the
                # same id with full columns
                continue
            input_amount = _first_amount(row[input_idx])
            output_amount = _first_amount(row[output_idx + sub_offset])
            if input_amount is None or output_amount is None:
                # an unpriced row is not a verdict either: a later table may
                # carry the same id with real prices
                continue
            return Pricing(input_amount / 1e6, output_amount / 1e6, mode="chat", max_tokens=0)
    return None

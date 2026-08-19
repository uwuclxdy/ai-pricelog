"""detect sonar model ids on the perplexity pricing page.

the page (https://docs.perplexity.ai/guides/pricing) carries several tables:
search-context request fees, pro search tiers, embeddings, agent-api costs,
and the Token Pricing table. only Token Pricing is watched: the table whose
header row holds "Input Tokens ($/1M)" and "Output Tokens ($/1M)". ids are
the Model column cells normalized to litellm key form (lowercase, whitespace
runs -> "-"): the page spells "Sonar Pro", litellm keys it
perplexity/sonar-pro. cells that do not normalize to a bare lowercase-dash
id (empty cells, footnote suffixes) are skipped rather than emitted as ids.
the embeddings and request-fee tables are out of scope. a page with no such
table is a parse failure (FetchError).
"""

import re

from litellm_autopr.config import ProviderCfg
from litellm_autopr.web import FetchError, extract_tables, fetch_soup

_INPUT_HEADER = "Input Tokens ($/1M)"
_OUTPUT_HEADER = "Output Tokens ($/1M)"
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def detect(cfg: ProviderCfg) -> list[str]:
    table = _token_pricing_table(extract_tables(fetch_soup(cfg.detector_url)), cfg.detector_url)
    ids: list[str] = []
    for row in table[1:]:
        if not row:
            continue
        normalized = _normalize_id(row[0])
        if _ID_PATTERN.fullmatch(normalized):
            ids.append(normalized)
    if not ids:
        raise FetchError(f"no model ids in the token pricing table on {cfg.detector_url}")
    return ids


def _token_pricing_table(tables: list[list[list[str]]], url: str) -> list[list[str]]:
    for table in tables:
        if table and table[0] and _INPUT_HEADER in table[0] and _OUTPUT_HEADER in table[0]:
            return table
    raise FetchError(f"no token pricing table on {url}")


def _normalize_id(cell: str) -> str:
    return re.sub(r"\s+", "-", cell.strip()).lower()

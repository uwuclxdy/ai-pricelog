"""detect model ids on the deepseek api-docs pricing page.

the page (https://api-docs.deepseek.com/quick_start/pricing) is a docusaurus
static html page with a single table. its header row's first cell is "MODEL"
and every remaining header cell is a raw model id. rows keyed by BASE URL /
MODEL VERSION / THINKING MODE / CONTEXT LENGTH / MAX OUTPUT / FEATURES /
PRICING are not model rows. header cells that do not look like model ids are
skipped; a page whose MODEL row carries no id is a parse failure (FetchError).
"""

import re

from litellm_autopr.config import ProviderCfg
from litellm_autopr.web import FetchError, extract_tables, fetch_soup

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]*$")


def detect(cfg: ProviderCfg) -> list[str]:
    tables = extract_tables(fetch_soup(cfg.detector_url))
    header = _model_table(tables, cfg.detector_url)[0]
    ids = [cell.strip() for cell in header[1:] if _ID_PATTERN.fullmatch(cell.strip())]
    if not ids:
        raise FetchError(f"no model ids in the MODEL header row on {cfg.detector_url}")
    return ids


def _model_table(tables: list[list[list[str]]], url: str) -> list[list[str]]:
    for table in tables:
        if table and table[0] and table[0][0].strip() == "MODEL":
            return table
    raise FetchError(f"no MODEL header table on {url}")

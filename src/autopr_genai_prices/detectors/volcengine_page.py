"""detect volcengine doubao model ids from the model plaza page.

the plaza (ai.volcengine.com/model) is server-rendered div cards with no
tables. ids are matched over the tag-stripped page text; the negative
lookahead keeps seedance (video) and seedream (image) cards out. repeated
matches are deduplicated in first-seen order. a page whose text carries no
doubao-seed id at all is a parse failure (the page moved or was redesigned),
raised as FetchError instead of a silent empty list.
"""

import re
from functools import cache

from autopr_genai_prices.config import ProviderCfg
from autopr_genai_prices.web import FetchError, fetch_soup

_ID_RE = re.compile(r"doubao-seed(?!ream|ance)[a-z0-9.-]+")


@cache
def _page(url: str) -> str:
    """tag-stripped page text; cached per url so the scraper reuses this fetch."""
    return fetch_soup(url).get_text(" ", strip=True)


def detect(cfg: ProviderCfg) -> list[str]:
    text = _page(cfg.detector_url)
    ids = _ID_RE.findall(text)
    if not ids:
        raise FetchError(f"no doubao-seed model ids found on {cfg.detector_url}")
    return list(dict.fromkeys(ids))

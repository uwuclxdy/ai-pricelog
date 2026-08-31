"""detect text-generation model ids from Alibaba's Model Studio CN page.

reads https://help.aliyun.com/zh/model-studio/text-generation-model/ (static
html). every table has a header row whose first cell is the `模型 ID` column
label; each data row's first cell carries one or more model ids (a primary id
plus snapshot versions behind a `查看快照版本` collapsible). the detector
takes the whitespace tokens of the first cell matching
`^[a-z0-9][a-z0-9.-]*$` case-insensitively and returns them case-preserved
(third-party names like `MiniMax-M3` keep their page spelling). the page
mixes recommended and third-party models; litellm's dashscope namespace
tracks them all. resold first-party ids (models dashscope carries that
another watched source owns) are excluded here, so a dashscope copy never
shadows the owning source's row in a first-match-wins consumer. dedupe
preserves page order.
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, extract_tables, fetch_soup

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$", re.IGNORECASE)

# dashscope resells these ids; the owning source (deepseek / zai / moonshot)
# is the authoritative price, so the resold copy stays out of the store.
_RESOLD_IDS = frozenset(
    {
        "deepseek-v3.2",
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "glm-5.1",
        "glm-5.2",
        "kimi-k2.7-code",
    }
)


def detect(cfg: ProviderCfg) -> list[str]:
    tables = extract_tables(fetch_soup(cfg.detector_url))
    if not tables:
        raise FetchError(f"no tables found on {cfg.detector_url}")
    ids: list[str] = []
    seen: set[str] = set()
    for table in tables:
        for row in table[1:]:
            if not row or not row[0]:
                continue
            for token in row[0].split():
                if _ID_RE.fullmatch(token) and token not in _RESOLD_IDS and token not in seen:
                    seen.add(token)
                    ids.append(token)
    if not ids:
        raise FetchError(f"no model ids matched on {cfg.detector_url}")
    return ids

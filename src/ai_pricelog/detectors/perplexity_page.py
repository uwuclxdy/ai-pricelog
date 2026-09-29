"""detect perplexity model ids on the agent-api model catalog.

the page (https://docs.perplexity.ai/docs/agent-api/models) carries one
pricing table per served vendor, all sharing the header Model | Input
($/1M) | Output ($/1M) | Cache read ($/1M) | Service tiers | Docs, pinned
on the folded Input/Output/Cache read trio (web.fold_heading). row ids are
vendor-prefixed slugs (`perplexity/sonar`); only `perplexity/` rows are
perplexity's own models, and the prefix strips to the stored spelling the
store keys on (`perplexity/sonar` -> `sonar`). the catalog's other
perplexity-hosted rows are resold models (zai / moonshot / nvidia own
them) and are excluded here at the source, `_RESOLD_IDS`-style
(detectors/dashscope_page.py), so they never become candidates and never
need curation; other vendors' rows never become candidates either. cells
that do not normalize to a bare id (empty cells, footnote suffixes) and
rows with tiered long-context cells (`2.00 (<=272k) 4.00 (>272k)`, other
vendors) pass under the scan. a page with no pinned table or no
perplexity row is a parse failure (FetchError).
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, extract_tables, fetch_soup, fold_heading

_INPUT_HEADER = "Input ($/1M)"
_OUTPUT_HEADER = "Output ($/1M)"
_CACHE_READ_HEADER = "Cache read ($/1M)"
_FOLDED_INPUT_HEADER = fold_heading(_INPUT_HEADER)
_FOLDED_OUTPUT_HEADER = fold_heading(_OUTPUT_HEADER)
_FOLDED_CACHE_READ_HEADER = fold_heading(_CACHE_READ_HEADER)
_VENDOR_PREFIX = "perplexity/"
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]*$")

# the catalog's other perplexity-hosted rows are resold: zai (glm), moonshot
# (kimi), nvidia (nemotron) own them, and each is priced on watched sources
# (zai, moonshot, deepinfra/openrouter), so a perplexity copy would shadow
# the authoritative row (dashscope _RESOLD_IDS precedent)
_RESOLD_IDS = frozenset(
    {
        "glm-5.3",
        "glm-5.3-flash",
        "kimi-k3",
        "nemotron-3-ultra-550b-a55b",
    }
)


def detect(cfg: ProviderCfg) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for table in _catalog_tables(extract_tables(fetch_soup(cfg.detector_url)), cfg.detector_url):
        for row in table[1:]:
            if not row:
                continue
            stored_id = _stored_id(row[0])
            if stored_id is not None and stored_id not in seen:
                seen.add(stored_id)
                ids.append(stored_id)
    if not ids:
        raise FetchError(f"no perplexity model ids on {cfg.detector_url}")
    return ids


def _catalog_tables(tables: list[list[list[str]]], url: str) -> list[list[list[str]]]:
    matched = []
    for table in tables:
        if not table or not table[0]:
            continue
        folded = [fold_heading(cell) for cell in table[0]]
        if (
            _FOLDED_INPUT_HEADER in folded
            and _FOLDED_OUTPUT_HEADER in folded
            and _FOLDED_CACHE_READ_HEADER in folded
        ):
            matched.append(table)
    if not matched:
        raise FetchError(f"no agent-api pricing table on {url}")
    return matched


def _stored_id(cell: str) -> str | None:
    """the store spelling a catalog model cell maps to, or None to skip it."""
    normalized = re.sub(r"\s+", "-", cell.strip()).lower()
    if not normalized.startswith(_VENDOR_PREFIX):
        return None
    model_id = normalized.removeprefix(_VENDOR_PREFIX)
    if not _ID_PATTERN.fullmatch(model_id) or model_id in _RESOLD_IDS:
        return None
    return model_id

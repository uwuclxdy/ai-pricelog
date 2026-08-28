"""detect claude model ids from the anthropic pricing markdown twin.

reads https://platform.claude.com/docs/en/about-claude/pricing.md (the
machine-readable surface llms.txt advertises). the "Model pricing" table
carries Model | Base Input Tokens | 5m Cache Writes | 1h Cache Writes |
Cache Hits & Refreshes | Output Tokens; the header is pinned exactly, so
a column rename is a page-shape break (FetchError) and the tier tables
further down the page (fast mode, batch, long context) never match. the
first column is a display name: a trailing parenthesized annotation
carrying a markdown link ("[retired, except on ...](...)") is stripped,
while a paren without a link ("(Fast)") is part of the name. names slug
lowercase with non-alphanumeric runs collapsed to dashes ("Claude Opus
4.1" -> claude-opus-4-1).
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, extract_markdown_tables, fetch_text

TABLE_HEADER = [
    "Model",
    "Base Input Tokens",
    "5m Cache Writes",
    "1h Cache Writes",
    "Cache Hits & Refreshes",
    "Output Tokens",
]

_ANNOTATION_RE = re.compile(r"\s*\(([^()]*(?:\([^()]*\))?[^()]*)\)\s*$")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _slug(name: str) -> str:
    """the display name's model id; a link-carrying annotation drops off."""
    match = _ANNOTATION_RE.search(name)
    if match is not None and "](" in match.group(1):
        name = name[: match.start()]
    return _NON_ALNUM_RE.sub("-", name.lower()).strip("-")


def model_table(text: str, url: str) -> list[list[str]]:
    """the "Model pricing" table; anything else on the page is a shape break."""
    for table in extract_markdown_tables(text):
        if table and table[0] == TABLE_HEADER:
            return table
    raise FetchError(f"no model pricing table on {url}")


def check_row(row: list[str], url: str) -> None:
    if len(row) != len(TABLE_HEADER) or not row[0]:
        raise FetchError(f"row outside the pricing shape on {url}: {row!r}")


def detect(cfg: ProviderCfg) -> list[str]:
    text = fetch_text(cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    for row in model_table(text, cfg.detector_url)[2:]:
        check_row(row, cfg.detector_url)
        model_id = _slug(row[0])
        if model_id not in seen:
            seen.add(model_id)
            ids.append(model_id)
    if not ids:
        raise FetchError(f"no model rows in the model pricing table on {cfg.detector_url}")
    return ids

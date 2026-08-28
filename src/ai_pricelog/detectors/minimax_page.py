"""detect MiniMax language models from the models-intro page.

reads https://platform.minimax.io/docs/guides/models-intro.md (static markdown).
language tables list each model as a markdown link in the first cell; only ids
matching ^MiniMax-M[\\w.-]+$ qualify, which keeps the language tables and
excludes the audio/video/music sections. ids are returned as written on the
page: the docs spell some legacy models with `-highspeed` where litellm's file
has `-lightning`; the human verifier reconciles that drift.
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, extract_markdown_tables, fetch_text

_ID_RE = re.compile(r"^MiniMax-M[\w.-]+$")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def detect(cfg: ProviderCfg) -> list[str]:
    text = fetch_text(cfg.detector_url)
    tables = extract_markdown_tables(text)
    if not tables:
        raise FetchError(f"no markdown tables found on {cfg.detector_url}")
    ids: list[str] = []
    seen: set[str] = set()
    for table in tables:
        for row in table[2:]:
            if not row or not row[0]:
                continue
            match = _LINK_RE.search(row[0])
            name = match.group(1) if match else ""
            if _ID_RE.fullmatch(name) and name not in seen:
                seen.add(name)
                ids.append(name)
    if not ids:
        raise FetchError(f"no model ids matched on {cfg.detector_url}")
    return ids

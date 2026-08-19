"""detect MiniMax language models from the models-intro page.

reads https://platform.minimax.io/docs/guides/models-intro.md (static markdown).
language tables list each model as a markdown link in the first cell; only ids
matching ^MiniMax-M[\\w.-]+$ qualify, which keeps the language tables and
excludes the audio/video/music sections. ids are returned as written on the
page: the docs spell some legacy models with `-highspeed` where litellm's file
has `-lightning`; the human verifier reconciles that drift.
"""

import re

from litellm_autopr.config import ProviderCfg
from litellm_autopr.web import FetchError, fetch_text

_ID_RE = re.compile(r"^MiniMax-M[\w.-]+$")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def _markdown_tables(text: str) -> list[list[list[str]]]:
    """split markdown pipe tables into row lists: header, separator, data rows."""
    blocks: list[list[str]] = []
    block: list[str] = []
    for line in text.splitlines():
        if "|" in line:
            block.append(line)
        elif block:
            blocks.append(block)
            block = []
    if block:
        blocks.append(block)
    tables: list[list[list[str]]] = []
    for lines in blocks:
        rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
        if len(rows) >= 2 and all(re.fullmatch(r":?-{3,}:?", cell) for cell in rows[1]):
            tables.append(rows)
    return tables


def detect(cfg: ProviderCfg) -> list[str]:
    text = fetch_text(cfg.detector_url)
    tables = _markdown_tables(text)
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

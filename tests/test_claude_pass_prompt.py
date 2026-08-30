"""The claude pass prompt snapshots domain-knowledge sections for CI, where
docs/ does not exist. This test pins the snapshot against the live sections;
it skips where docs/ is absent (the actions checkout)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / ".github" / "claude-pass" / "prompt.md"
DOMAIN = ROOT / "docs" / "domain-knowledge.md"

SECTIONS = [
    "provider page facts, 2026-08-24 re-probe additions",
    "deepseek page move",
    "deepseek peak schedule",
    "announce channels",
    "scaleway + databricks (added 2026-08-29, todo #17)",
    "dashscope omni split (added 2026-08-30)",
]


def _section_body(text: str, title: str, level: str) -> str:
    """The lines of the `##/### title` section, blank edges stripped."""
    pattern = re.compile(rf"^{level} {re.escape(title)}\s*$", re.M)
    match = pattern.search(text)
    assert match is not None, f"section {title!r} not found"
    rest = text[match.end() :]
    next_heading = re.search(r"^#{2,3} ", rest, re.M)
    body = rest[: next_heading.start()] if next_heading else rest
    return body.strip()


@pytest.mark.parametrize("title", SECTIONS)
def test_quirks_snapshot_matches_domain(title: str) -> None:
    if not DOMAIN.exists():
        pytest.skip("docs/ not present (ci checkout)")
    prompt_body = _section_body(PROMPT.read_text(), title, "###")
    domain_body = _section_body(DOMAIN.read_text(), title, "##")
    assert prompt_body == domain_body, (
        f"claude pass prompt section {title!r} drifted from domain-knowledge; "
        "re-copy the section verbatim"
    )

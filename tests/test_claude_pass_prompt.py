"""The CI claude pass reads `.github/claude-pass/prompt.md` on a checkout with no
docs/ tree, so the prompt carries every fact the pass needs. These pin the surfaces
a rename or a schema change would otherwise break silently."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / ".github" / "claude-pass" / "prompt.md"


def _section_body(text: str, title: str) -> str:
    """The lines of the `## title` section, blank edges stripped."""
    pattern = re.compile(rf"^## {re.escape(title)}\s*$", re.M)
    match = pattern.search(text)
    assert match is not None, f"section {title!r} not found"
    rest = text[match.end() :]
    next_heading = re.search(r"^#{2,3} ", rest, re.M)
    body = rest[: next_heading.start()] if next_heading else rest
    return body.strip()


def test_row_schema_carries_the_current_vocabulary() -> None:
    # the pass judges rows against this section; a schema change that leaves
    # it stale sends the next review against a dead shape
    schema = _section_body(PROMPT.read_text(), "row schema")
    for term in (
        "overrides",
        "min_tokens",
        "fx_rate",
        "quota_multiplier",
        "rates",
        "fees",
        "limits",
        "provenance",
        "final price snapshot",
        "zero price is a price",
    ):
        assert term in schema, f"row schema section lost {term!r}; update it"


def test_prompt_names_the_automerge_surface() -> None:
    # the merge job runs the automerge script under the manual's rules; a
    # rename of either breaks the pass cold
    text = PROMPT.read_text()
    assert "ai-pricelog-automerge" in text
    assert ".github/claude-pass/automerge.md" in text


def test_needs_human_comment_pings_the_owner() -> None:
    # the ping line is the notification mechanism: the pass posts as the bot,
    # so the @-mention is what reaches the owner
    ping = "@uwuclxdy need help wit this"
    assert ping in PROMPT.read_text()
    manual = (ROOT / ".github" / "claude-pass" / "automerge.md").read_text()
    assert ping in manual

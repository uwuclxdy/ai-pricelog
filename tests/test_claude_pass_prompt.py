"""The CI claude pass reads `.github/claude-pass/prompt.md` on a checkout with no
docs/ tree, so the prompt carries every fact the pass needs. These pin the surfaces
a rename or a schema change would otherwise break silently."""

from __future__ import annotations

import re
import tomllib
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


def _h2_body(text: str, title: str) -> str:
    """The `## title` section whole, subsections included, to the next `## `."""
    start = re.search(rf"^## {re.escape(title)}\s*$", text, re.M)
    assert start is not None, f"section {title!r} not found"
    rest = text[start.end() :]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def _h3_body(text: str, title: str) -> str:
    """The `### title` subsection, to the next heading of the same depth or up."""
    start = re.search(rf"^### {re.escape(title)}\s*$", text, re.M)
    assert start is not None, f"subsection {title!r} not found"
    rest = text[start.end() :]
    nxt = re.search(r"^#{2,3} ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


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
    # the merge job names the automerge script and its manual; a rename of
    # either breaks the pass cold
    text = PROMPT.read_text()
    assert "ai-pricelog-automerge" in text
    assert ".github/claude-pass/automerge.md" in text


def test_prompt_carries_the_disposition_markers() -> None:
    # the merge-verified step reads these exact machine lines off the pass's
    # PR comments; a reworded marker silently strands every verified PR
    text = PROMPT.read_text()
    assert "automerge: yes" in text
    assert "automerge: no" in text
    assert "merge verified PRs" in text


def test_needs_human_comment_pings_the_owner() -> None:
    # the ping line is the notification mechanism: the pass posts as the bot,
    # so the @-mention is what reaches the owner
    ping = "@uwuclxdy need help wit this"
    assert ping in PROMPT.read_text()
    manual = (ROOT / ".github" / "claude-pass" / "automerge.md").read_text()
    assert ping in manual


def test_every_watched_provider_has_page_facts_or_an_exempt_entry() -> None:
    # the pass judges rows for every watched provider on a checkout with no
    # docs/ tree: each needs page-facts context in this prompt or a named
    # exempt entry, and a provider section that lands with neither reds here
    providers = tomllib.loads((ROOT / "providers.toml").read_text(encoding="utf-8"))
    quirks = _h2_body(PROMPT.read_text(encoding="utf-8"), "domain quirks")
    announce_at = quirks.find("### announce channels")
    assert announce_at != -1, "the announce inventory moved; repin the page-facts zone"
    page_facts = quirks[:announce_at]
    exempt = _h3_body(quirks, "no page quirk")
    for key in providers:
        covered = re.search(
            rf"^(?:#{{3,4}} .*\b{re.escape(key)}\b|- {re.escape(key)}\b)", page_facts, re.M
        )
        exempted = re.search(rf"^- {re.escape(key)}\b", exempt, re.M)
        assert covered or exempted, (
            f"provider {key!r} has neither page facts nor an exempt entry in the pass prompt"
        )

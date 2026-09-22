"""The CI claude pass reads `.github/claude-pass/prompt.md` on a checkout with no
docs/ tree, so the prompt carries every fact the pass needs. These pin the surfaces
a rename or a schema change would otherwise break silently."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / ".github" / "claude-pass" / "prompt.md"
HUMAN_PROMPT = ROOT / ".github" / "claude-pass" / "human-pr-prompt.md"
REVIEW_WF = ROOT / ".github" / "workflows" / "review.yml"


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


def test_human_pr_prompt_carries_the_review_contract() -> None:
    # review.yml runs this prompt on human PRs, read-only, on a checkout with
    # no docs/ tree; the one-comment contract, the read-only rule and the
    # machine marker are the row's contract, and the disclosure string is the
    # pipeline skip marker — a reword on either side breaks the skip
    text = HUMAN_PROMPT.read_text()
    assert "exactly one comment" in text
    assert "edit that comment in place" in text
    assert "never Edit" in text
    assert "pr-review:" in text
    assert "pr-review: <head sha reviewed>" in text
    assert "opened automatically by the [GitHub Action]" in text


def test_review_workflow_names_the_prompt_and_stays_read_only() -> None:
    # review.yml is the human-prompt's only consumer, and its allowedTools
    # list is the read-only contract's enforcement: an Edit that creeps in
    # turns the row's read-only review into a branch-editing one
    text = REVIEW_WF.read_text()
    assert "human-pr-prompt.md" in text
    assert "opened automatically by the [GitHub Action]" in text
    tools = re.search(r"--allowedTools(.+)", text)
    assert tools is not None, "review.yml lost its --allowedTools line"
    assert '"Edit"' not in tools.group(1)
    assert '"Read" "Bash(gh:*)" "Bash(git:*)" "WebFetch" "WebSearch"' in tools.group(1)
    # the always-run verify step is the hung-pass net: a pass killed by its
    # timeout posts no warning of its own, so the step checks the one durable
    # signal — the comment's pr-review machine line for this head — and warns
    # (never fails) when it never landed
    assert "name: verify the review comment landed" in text
    assert "if: ${{ always() && !cancelled() }}" in text
    assert "pr-review: $head" in text


def test_prompt_carries_the_openrouter_fetch_and_identity_rules():
    # the pass's false absence verdicts (2026-09-22, PRs 333/337) came from
    # WebFetch extraction over the ~750KB payload and a substring id match
    # (PR 331's kwaipilot read); these rules are the fix's prompt half
    schema = _section_body(PROMPT.read_text(), "row schema")
    assert "curl -fsSL" in schema
    assert "exact id equality" in schema
    assert "never absence evidence" in schema
    assert "never substring-match an id" in schema


def test_prompt_settles_the_absence_file_lifecycle():
    # a branch deleting state/absence/<source>.json is the documented
    # cleanup of landed removals; PR 331's pass misread it as lost delistings
    job = _section_body(PROMPT.read_text(), "your job")
    assert "documented cleanup" in job


def test_output_contract_pins_one_comment_per_pr():
    # PR 331 got a yes marker and a contradicting no as a second comment;
    # the contract is one comment, edited in place when a verdict overturns
    contract = _section_body(PROMPT.read_text(), "output contract")
    assert "EDIT that comment" in contract
    assert "one comment, one disposition marker per PR" in contract

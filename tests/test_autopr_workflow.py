"""pins on the autopr workflow's run-shape surfaces.

the 2026-09-22 double dispatch (a late fallback mark 14s before the box
timer) raced two runs into duplicate PRs, a stale-ref merge failure and a
stranded queue, so the guards that serialize and refresh the runs are
pinned here: a rewrite of the workflow file that drops one reds the suite
instead of silently reopening the class.
"""

from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

import pytest

AUTOPR_WF = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "autopr.yml"
REVIEW_WF = AUTOPR_WF.parent / "review.yml"
PASS_WORKFLOWS = (AUTOPR_WF, REVIEW_WF)


def test_autopr_serializes_duplicate_dispatches():
    # the fallback script prices a duplicate dispatch as a no-op, which only
    # holds while the concurrency group keeps it from overlapping the live run
    text = AUTOPR_WF.read_text()
    assert re.search(
        r"^concurrency:\n\s+group: autopr\n\s+cancel-in-progress: false",
        text,
        re.M,
    ), "autopr lost its concurrency group; duplicate dispatches race again"


def test_merge_step_writes_its_rc_marker():
    # the health step's deduped `merge step failed` ping reads this marker;
    # a step killed before it writes reads as dead, never as clean
    text = AUTOPR_WF.read_text()
    assert 'echo "$merge_rc" > /tmp/merge.rc' in text
    assert "--merge-alive" in text and "--merge-dead" in text


def test_merge_step_runs_after_a_failed_pass():
    # the pass step is continue-on-error, so a killed pass leaves the job green
    # unless the merge still runs and the dead-pass tripwire reds it; the
    # `if: always()` gate is what lets the merge read the pass's dispositions
    # after a pass death. pin it: a decoy mutant dropping the gate passed the
    # workflow test, and a dropped gate strands every yes-marked PR
    body = _step(AUTOPR_WF.read_text(), "merge verified PRs")
    assert re.search(r"^        if: always\(\)$", body, re.M), (
        "the merge step lost its if: always(); a dead pass would strand its verdicts"
    )


def test_pass_may_fetch_sources_full_body():
    # WebFetch extraction over the ~750KB openrouter payload silently omits
    # records and produced false absence verdicts (2026-09-22, PRs 333/337);
    # the pass's presence checks need curl for the full body and jq/uv to
    # parse it by exact id equality
    tools = re.search(r"--allowedTools(.+)", AUTOPR_WF.read_text())
    assert tools is not None, "autopr lost its --allowedTools line"
    for tool in ('"Bash(curl:*)"', '"Bash(jq:*)"', '"Bash(uv:*)"'):
        assert tool in tools.group(1), f"the pass lost {tool}; absence checks degrade to WebFetch"


@pytest.mark.parametrize("workflow", PASS_WORKFLOWS, ids=lambda path: path.name)
def test_pass_reads_model_from_a_variable_and_base_url_from_a_secret(workflow: Path):
    # the model stays a variable so its value stays readable in the logs; the
    # base URL is a repo secret
    text = workflow.read_text()
    assert "CLAUDE_MODEL: ${{ vars.ANTHROPIC_MODEL }}" in text
    assert "CLAUDE_BASE_URL: ${{ secrets.ANTHROPIC_BASE_URL }}" in text
    assert "secrets.ANTHROPIC_MODEL" not in text
    assert "vars.ANTHROPIC_BASE_URL" not in text


@pytest.mark.parametrize("workflow", PASS_WORKFLOWS, ids=lambda path: path.name)
def test_pass_refuses_an_unset_model(workflow: Path):
    # an unset model used to fall through to the CLI's default model, the
    # priciest tier, on a budgeted key: the pass refuses instead, which the
    # dead-pass check reds and pings
    text = workflow.read_text()
    guard = re.search(r'\[ -n "\$CLAUDE_MODEL" \] \|\| \{[^}\n]*exit 1; \}', text)
    assert guard is not None, f"{workflow.name} lost the unset-model refusal"
    assert guard.start() < text.index("claude -p"), "the refusal must run before the pass"
    assert '[ -n "$CLAUDE_MODEL" ] && export' not in text


def test_pass_runs_on_the_review_queue():
    # the pass judges up to the 10 oldest PRs that carry no disposition yet,
    # listed by the merge script, so a PR an earlier pass never judged queues
    # again; the run-changed marker only knew about this run's own PRs
    text = AUTOPR_WF.read_text()
    assert "ai-pricelog-merge-verified --awaiting-review" in text
    assert 'echo "## PRs awaiting review"' in text
    assert ".run-changed" not in text
    # the -s queue guard must be the pass step's own: the bare literal occurs
    # three times, so pin it inside that step's run block, before claude -p
    block = re.search(
        r"name: claude review pass\b.*?run: \|\n(?P<body>.*?)(?=\n      - name:|\n  smoke:|\Z)",
        text,
        re.S,
    )
    assert block is not None, "the claude review pass step lost its run block"
    body = block.group("body")
    assert re.search(r"^[ \t]*\[ -s /tmp/review-queue\.txt \] \|\| \{", body, re.M), (
        "the pass step lost its -s queue guard; an empty queue must skip the pass"
    )
    assert body.find("[ -s /tmp/review-queue.txt ]") < body.find("claude -p")


def _step(text: str, name: str) -> str:
    """the `- name: <name>` step's lines, up to the next step or job."""
    match = re.search(
        rf"^      - name: {re.escape(name)}\n(?P<body>.*?)(?=^      - name: |^  \S|\Z)",
        text,
        re.M | re.S,
    )
    assert match is not None, f"autopr lost its {name!r} step"
    return match.group("body")


@pytest.mark.parametrize("name", ["list PRs awaiting review", "claude review pass"])
def test_queue_steps_run_after_a_failed_watchdog(name: str):
    # the queue is decoupled from this run's own output: a red watchdog step
    # (a git, gh or config failure, or a crash) must still list and judge the
    # PRs earlier passes left
    body = _step(AUTOPR_WF.read_text(), name)
    assert re.search(r"^        if: \$\{\{ !cancelled\(\) \}\}$", body, re.M), (
        f"the {name!r} step lost its !cancelled() gate"
    )


def _pass_guards(text: str, queue: Path) -> str:
    """the pass step's shell up to the CLI install, reading `queue` as its queue file."""
    run = re.search(
        r"^        run: \|\n(?P<script>.*?)^          npm install ",
        _step(text, "claude review pass"),
        re.M | re.S,
    )
    assert run is not None, "the claude review pass step lost its run block or its CLI install"
    return textwrap.dedent(run.group("script")).replace("/tmp/review-queue.txt", str(queue))


def _list_outcome_env(text: str, outcome: str) -> dict[str, str]:
    """the pass step's env entries a runner fills with the list step's outcome."""
    list_id = re.search(r"^        id: (\S+)$", _step(text, "list PRs awaiting review"), re.M)
    if list_id is None:
        return {}
    entry = rf"^          (\w+): \$\{{\{{ steps\.{re.escape(list_id.group(1))}\.outcome \}}\}}$"
    return dict.fromkeys(re.findall(entry, _step(text, "claude review pass"), re.M), outcome)


@pytest.mark.parametrize(
    ("outcome", "queued", "stdout"),
    [
        (
            "failure",
            "",
            "listing the PRs awaiting review failed, so the review queue is unknown;"
            " skipping the claude pass\n",
        ),
        ("success", "", "no PR awaits review; skipping the claude pass\n"),
        ("failure", "459 pricelog/openrouter-12345678\n", ""),
    ],
    ids=["failed-listing", "empty-queue", "listed-queue"],
)
def test_pass_skip_line_tells_a_failed_listing_from_an_empty_queue(
    tmp_path: Path, outcome: str, queued: str, stdout: str
):
    # a failed listing leaves the queue file as empty as an empty queue does,
    # so only the list step's outcome tells them apart: the skip line must
    # never call an unknown queue empty. a listed PR runs the pass whatever the
    # outcome: the dead-pass gate reads the same non-empty file as a due pass
    text = AUTOPR_WF.read_text()
    queue = tmp_path / "review-queue.txt"
    queue.write_text(queued)
    guards = tmp_path / "guards.sh"
    guards.write_text(_pass_guards(text, queue))
    proc = subprocess.run(
        ["bash", "-e", str(guards)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "CLAUDE_MODEL": "m", **_list_outcome_env(text, outcome)},
    )
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, stdout, "")

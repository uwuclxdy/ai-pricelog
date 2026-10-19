"""provider-health check: surface per-provider failures from the run log.

reads the watchdog run log, extracts per-provider issue lines, compares
them with the previous autopr run's log (fetched through the gh cli),
writes a ::warning:: annotation for this run's issues, and opens one
github issue per provider that failed hard in two consecutive runs (the
@-mention is what reaches the owner). hard = the detector or a scrape
raised, so the provider is blind or its rows are rejected; soft = detect,
parse and row-build skips and validation rejects (additive drift, the
provider stays alive). every reader (the issue rules, the checked set, the
hold marker) matches only at a log line's message start — after the
optional `gh run view --log` prefix and basicConfig's `LEVEL:logger:`
prefix — so page text that lands inside a logged name (a detect-skip or
traceback line's tail) never reads as the run's own line. a provider the
run's `providers checked:` line names,
with no hard failure logged for it, closes its own `provider broken: <key>`
issue (recovery); a held or seed-skipped run, or a run that crashed before
its providers, logs no checked line, so it closes and opens no provider
issue (its hold still logs a `::warning::`). the pass state flags sync the
`review pass dead` ping issue: opened when the pass died with PRs
awaiting review, closed on a later clean pass. the merge state flags
sync the `merge step failed` ping the same way: opened when the merge
step failed, closed by a later run whose merge step finishes clean. the
merge step runs every run, so a transient failure's ping closes on a
later clean run, while a deterministic refusal reds every later run
until it is resolved; the ping is what ends that silence.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

ISSUE_PREFIX = "provider broken: "
PASS_DEAD_TITLE = "review pass dead"
MERGE_DEAD_TITLE = "merge step failed"

# the detect-stage skip line every detector logs; the pipeline watches for it
# live (absence suppression) and this module parses it from the run log, so
# the contract has one owner
DETECT_SKIP = re.compile(r"detect skip for (\S+):")

# the message prefix of the one line pipeline.run logs once its provider loop
# and openrouter pass finish, naming every provider key the run attempted; this
# module parses it, so the checked-set contract has one owner
CHECKED_PROVIDERS = "providers checked:"

# the lines a run that ran no provider logs; the pipeline writes them through
# these constants and this module parses them, so a held run's warning names
# the reason (the DETECT_SKIP precedent)
HOLD_PENDING_SCAN = "pending scan failed; opening no pr this run"
HOLD_SEED_PR = "store empty at load and the seed pr is still open; skipping the run"

# (pattern, class, fixed provider key or None when the pattern carries the key)
_RULES: tuple[tuple[re.Pattern[str], str, str | None], ...] = (
    (re.compile(r"detector for (\S+) failed"), "hard", None),
    (re.compile(r"scraper module for (\S+) failed"), "hard", None),
    (re.compile(r"priced detection for (\S+) failed"), "hard", None),
    (re.compile(r"scraper (\S+) failed for \S+"), "hard", None),
    (re.compile(r"refresh scrape failed for \S+ \((\S+)\)"), "hard", None),
    (re.compile(r"openrouter fetch failed"), "hard", "openrouter"),
    (re.compile(r"entry \S+ failed validation for (\S+):"), "soft", None),
    (re.compile(r"entry \S+ failed row build for (\S+):"), "soft", None),
    (re.compile(r"parse skip for (\S+):"), "soft", None),
    (re.compile(r"refresh for \S+ skipped in (\S+):"), "soft", None),
    # the page-written name sits between "fast-mode name " and the phrase, so
    # the key is read from the message's own tail (the url is the last token)
    (
        re.compile(r"fast-mode name .* names no model in the pricing table for (\S+) on \S+$"),
        "soft",
        None,
    ),
    (DETECT_SKIP, "soft", None),
)

# a run-log line's prefixes, left to right: the optional `gh run view --log`
# field triple (`<job>\t<step>\t<timestamp> `), then basicConfig's
# `LEVEL:logger:` prefix. everything after is the message the health readers
# match, anchored at its start; a traceback line carries no LEVEL:logger:
# prefix and matches nothing.
_LOG_LINE_PREFIX = re.compile(r"^(?:[^\t\n]*\t[^\t\n]*\t\S+ )?[A-Z]+:[\w.]+:")


def _message(line: str) -> str | None:
    """the log message after the run-log prefixes, or None when the line has
    no LEVEL:logger: prefix (a traceback line)."""
    match = _LOG_LINE_PREFIX.match(line)
    return line[match.end() :] if match is not None else None


def parse_log(lines: Iterable[str]) -> dict[str, dict[str, list[str]]]:
    """per provider -> {"hard": [...], "soft": [...]} of matched log lines."""
    issues: dict[str, dict[str, list[str]]] = {}
    for line in lines:
        message = _message(line)
        if message is None:
            continue
        for pattern, cls, fixed in _RULES:
            match = pattern.match(message)
            if match is None:
                continue
            key = fixed if fixed is not None else match.group(1)
            issues.setdefault(key, {"hard": [], "soft": []})[cls].append(line.strip())
            break
    return issues


def hold_reason(lines: Iterable[str]) -> str | None:
    """The reason this run's log shows no provider ran, or None when one did.

    A held run (the pending hold or the empty-store seed skip) is not provider
    evidence, so its `::warning::` names the reason instead of the issue list.
    The reason is the full log message: the pending hold's cause rides it, and
    the seed skip's message is exactly `HOLD_SEED_PR`.
    """
    for line in lines:
        message = _message(line)
        if message is None:
            continue
        if message.startswith(HOLD_PENDING_SCAN):
            return message
        if message.startswith(HOLD_SEED_PR):
            return message
    return None


def checked_providers(lines: Iterable[str]) -> frozenset[str]:
    """The provider keys the run's checked line names, or empty when it has none.

    pipeline.run logs one `providers checked:` line once its provider loop and
    openrouter pass finish; a held, seed-skipped or crashed run logs none, so
    its checked set is empty and close_recovered closes nothing.
    """
    for line in lines:
        message = _message(line)
        if message is not None and message.startswith(CHECKED_PROVIDERS):
            return frozenset(message[len(CHECKED_PROVIDERS) :].split())
    return frozenset()


def warning(now: dict[str, dict[str, list[str]]]) -> str | None:
    """the ::warning:: for this run's issues, or None when the run is clean."""
    hard = sorted(key for key, issue in now.items() if issue["hard"])
    soft = sorted(key for key, issue in now.items() if issue["soft"] and not issue["hard"])
    parts: list[str] = []
    if hard:
        parts.append("hard failures: " + ", ".join(hard))
    if soft:
        parts.append("skips: " + ", ".join(soft))
    return "::warning::" + escape_command_data("; ".join(parts)) if parts else None


def escape_command_data(text: str) -> str:
    """Escape text as workflow-command data, the way actions/toolkit's `escapeData` does.

    `%` goes first, so the `%0D` and `%0A` escapes that follow are never escaped again.
    """
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def providers_to_ping(
    now: dict[str, dict[str, list[str]]], prev: dict[str, dict[str, list[str]]]
) -> set[str]:
    """providers with a hard failure in both runs: the two-consecutive gate."""
    return {key for key, issue in now.items() if issue["hard"] and prev.get(key, {}).get("hard")}


def _gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True).stdout


def _created(run: dict) -> datetime | None:
    """the run's created_at as UTC, or None when it is missing or unparseable."""
    created = run.get("created_at")
    if not created:
        return None
    try:
        return datetime.fromisoformat(created)
    except ValueError:
        return None


def weekly_smoke(repo: str) -> str | None:
    """the newest monday dispatch whose smoke job ran, green or a warning.

    every autopr run is a workflow_dispatch (the workflow is dispatch-only).
    the hourly timer and the cron fallback dispatch with `scheduled=true`, so
    their smoke job is skipped; the weekly monday 05:17 fire (and any other
    manual-shaped dispatch) runs it. so the newest completed monday run whose
    smoke job is not skipped is the fire; a fire that wrongly gained
    `scheduled=true` reads as "no monday run whose smoke ran" and warns.
    """
    raw = _gh(["api", f"repos/{repo}/actions/workflows/autopr.yml/runs?per_page=100"])
    try:
        runs = json.loads(raw)["workflow_runs"]
    except (json.JSONDecodeError, KeyError):
        return None
    monday: list[tuple[datetime, dict]] = []
    for run in runs:
        created = _created(run)
        if created is not None and created.isoweekday() == 1:
            monday.append((created, run))
    if not monday:
        return None
    monday.sort(key=lambda pair: pair[0], reverse=True)
    if monday[0][1].get("status") != "completed":
        # the newest monday dispatch is still running (its smoke job runs in
        # parallel); judge it on a later run, never red on its own run
        return None
    for _, run in monday:
        if run.get("status") != "completed":
            continue
        run_id = run.get("id")
        if run_id is None:
            continue
        jobs_raw = _gh(["api", f"repos/{repo}/actions/runs/{run_id}/jobs"])
        try:
            jobs = json.loads(jobs_raw)["jobs"]
        except (json.JSONDecodeError, KeyError):
            return None
        smoke = next((job for job in jobs if job.get("name") == "smoke"), None)
        if smoke is None:
            return f"weekly moonshot smoke probe did not run: run {run_id} has no smoke job"
        if smoke.get("conclusion") == "skipped":
            continue
        if smoke.get("conclusion") == "success":
            return None
        return (
            f"weekly moonshot smoke probe failed: run {run_id} concluded {smoke.get('conclusion')}"
        )
    return "weekly moonshot smoke probe skipped: no monday dispatch ran its smoke job"


def previous_run(repo: str, current_run_id: str) -> tuple[str, Iterable[str]] | None:
    """the previous completed autopr run whose log is provider evidence
    (a held run is skipped), as (id, log lines), or None."""
    raw = _gh(["api", f"repos/{repo}/actions/workflows/autopr.yml/runs?per_page=10"])
    try:
        runs = json.loads(raw)["workflow_runs"]
    except (json.JSONDecodeError, KeyError):
        return None
    for run in runs:
        if str(run["id"]) == current_run_id or run["status"] != "completed":
            continue
        proc = subprocess.Popen(
            ["gh", "run", "view", str(run["id"]), "--log"],
            stdout=subprocess.PIPE,
            text=True,
        )
        lines = [line for line in proc.stdout if line]
        if hold_reason(lines) is not None:
            continue
        return str(run["id"]), lines
    return None


def open_issues(
    repo: str,
    now: dict[str, dict[str, list[str]]],
    prev: dict[str, dict[str, list[str]]],
    run_url: str,
    prev_run_url: str,
) -> list[str]:
    """one issue per provider that failed hard twice; existing open issues skip."""
    open_titles = set(
        _gh(
            ["issue", "list", "--state", "open", "--json", "title", "--jq", ".[].title"]
        ).splitlines()
    )
    created: list[str] = []
    for key in sorted(providers_to_ping(now, prev)):
        title = f"{ISSUE_PREFIX}{key}"
        if title in open_titles:
            continue
        body = (
            f"@uwuclxdy `{key}` failed in [this run]({run_url})"
            f" and [the previous run]({prev_run_url}).\n\n"
            "last errors:\n"
        )
        body += "\n".join(f"- `{line}`" for line in now[key]["hard"][-6:])
        _gh(["issue", "create", "--title", title, "--body", body])
        created.append(title)
    return created


def _open_issue_rows() -> list[tuple[int, str]] | None:
    """(number, title) of the open issues, or None when the gh call fails.

    None is distinct from []: a failed listing must never read as "no issue
    open", or the dedupe would create duplicates on every dead run.
    """
    raw = _gh(["issue", "list", "--state", "open", "--json", "number,title"])
    try:
        rows = json.loads(raw)
        return [(int(row["number"]), str(row["title"])) for row in rows]
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def close_recovered(now: dict[str, dict[str, list[str]]], checked: frozenset[str]) -> list[str]:
    """close open provider-broken issues whose provider this run checked and passed.

    an issue closes only when the run's checked line names its key and the run
    logged no hard failure for it; a provider the run never checked (a held,
    crashed or seed-skipped run checks none) says nothing about recovery, and a
    provider that flaps re-opens on the next two-consecutive streak.
    """
    rows = _open_issue_rows()
    if rows is None:
        return []
    closed: list[str] = []
    for number, title in rows:
        if not title.startswith(ISSUE_PREFIX):
            continue
        key = title[len(ISSUE_PREFIX) :]
        if key not in checked:
            continue
        if now.get(key, {}).get("hard"):
            continue
        _gh(
            [
                "issue",
                "close",
                str(number),
                "--comment",
                f"recovered: `{key}` detects and scrapes clean again",
            ]
        )
        closed.append(title)
    return closed


def sync_pass_dead_issue(pass_state: str | None, run_url: str) -> str | None:
    """open or close the pass-death ping issue; None when nothing changed.

    pass_state: "alive" (the pass finished clean with PRs awaiting review),
    "dead" (it exited nonzero or never ran to completion), or None (no PR
    awaited review, so the pass never ran and the issue is left alone).
    """
    if pass_state is None:
        return None
    rows = _open_issue_rows()
    if rows is None:
        return None
    numbers = [number for number, title in rows if title == PASS_DEAD_TITLE]
    if pass_state == "dead" and not numbers:
        _gh(
            [
                "issue",
                "create",
                "--title",
                PASS_DEAD_TITLE,
                "--body",
                f"@uwuclxdy the claude review pass died with PRs awaiting review "
                f"on [this run]({run_url}): the queued PRs stay unjudged and "
                "queue again on the next pass; yes-marked PRs still merge.\n\n"
                "read the pass log in the run, then rotate the ANTHROPIC_API_KEY "
                "secret or fix the ANTHROPIC_MODEL / ANTHROPIC_BASE_URL repo "
                "variables (an unset ANTHROPIC_MODEL makes the pass refuse).",
            ]
        )
        return "opened"
    if pass_state == "alive" and numbers:
        for number in numbers:
            _gh(
                [
                    "issue",
                    "close",
                    str(number),
                    "--comment",
                    "the pass completed clean on a run with PRs awaiting review; closing",
                ]
            )
        return "closed"
    return None


def sync_merge_dead_issue(merge_state: str | None, run_url: str) -> str | None:
    """open or close the merge-failure ping issue; None when nothing changed.

    merge_state: "alive" (the merge step finished clean), "dead" (it exited
    nonzero or never wrote its rc marker), or None (the caller passed no
    merge state, so the issue is left alone).
    """
    if merge_state is None:
        return None
    rows = _open_issue_rows()
    if rows is None:
        return None
    numbers = [number for number, title in rows if title == MERGE_DEAD_TITLE]
    if merge_state == "dead" and not numbers:
        _gh(
            [
                "issue",
                "create",
                "--title",
                MERGE_DEAD_TITLE,
                "--body",
                f"@uwuclxdy the merge step failed on [this run]({run_url}): "
                "read its error line. the PRs stay open, and a later run whose "
                "merge step finishes clean closes this issue.",
            ]
        )
        return "opened"
    if merge_state == "alive" and numbers:
        for number in numbers:
            _gh(
                [
                    "issue",
                    "close",
                    str(number),
                    "--comment",
                    "the merge step completed clean; closing",
                ]
            )
        return "closed"
    return None


def _usage() -> str:
    return (
        f"usage: {Path(sys.argv[0]).name} <run-log>"
        " [--pass-alive|--pass-dead] [--merge-alive|--merge-dead]"
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not 1 <= len(args) <= 3:
        print(_usage(), file=sys.stderr)
        return 2
    pass_state: str | None = None
    merge_state: str | None = None
    for arg in args[1:]:
        if arg in ("--pass-alive", "--pass-dead") and pass_state is None:
            pass_state = arg.removeprefix("--pass-")
        elif arg in ("--merge-alive", "--merge-dead") and merge_state is None:
            merge_state = arg.removeprefix("--merge-")
        else:
            print(_usage(), file=sys.stderr)
            return 2
    lines = Path(args[0]).read_text(encoding="utf-8").splitlines()
    now = parse_log(lines)
    checked = checked_providers(lines)
    held = hold_reason(lines)
    if held is not None:
        print(f"::warning::{escape_command_data(held)}")
    else:
        annotation = warning(now)
        if annotation is not None:
            print(annotation)
    repo = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if repo and run_id:
        run_url = f"https://github.com/{repo}/actions/runs/{run_id}"
        pass_action = sync_pass_dead_issue(pass_state, run_url)
        if pass_action is not None:
            print(f"::warning::{pass_action} issue {PASS_DEAD_TITLE}")
        merge_action = sync_merge_dead_issue(merge_state, run_url)
        if merge_action is not None:
            print(f"::warning::{merge_action} issue {MERGE_DEAD_TITLE}")
        for title in close_recovered(now, checked):
            print(f"::warning::closed issue {escape_command_data(title)}")
        previous = previous_run(repo, run_id)
        if previous is not None:
            prev_id, prev_lines = previous
            created = open_issues(
                repo,
                now,
                parse_log(prev_lines),
                run_url,
                f"https://github.com/{repo}/actions/runs/{prev_id}",
            )
            for title in created:
                print(f"::warning::opened issue {escape_command_data(title)}")
        smoke_warning = weekly_smoke(repo)
        if smoke_warning is not None:
            print(f"::warning::{escape_command_data(smoke_warning)}")
    return 0

"""provider-health check: surface per-provider failures from the run log.

reads the watchdog run log, extracts per-provider issue lines, compares
them with the previous autopr run's log (fetched through the gh cli),
writes a ::warning:: annotation for this run's issues, and opens one
github issue per provider that failed hard in two consecutive runs (the
@-mention is what reaches the owner). hard = the detector or a scrape
raised, so the provider is blind or its rows are rejected; soft = detect,
parse and row-build skips and validation rejects (additive drift, the
provider stays alive). a provider that passed this run closes its own
`provider broken: <key>` issue (recovery). the pass state flags sync the
`review pass dead` ping issue: opened when the pass died on a
data-changing run, closed on the next clean data-changing pass. the merge
state flags sync the `merge step failed` ping the same way: a refused
merge reds every later data-changing run on the same failure until a
human resolves it, so the ping is what ends the silence.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

ISSUE_PREFIX = "provider broken: "
PASS_DEAD_TITLE = "review pass dead"
MERGE_DEAD_TITLE = "merge step failed"

# the detect-stage skip line every detector logs; the pipeline watches for it
# live (absence suppression) and this module parses it from the run log, so
# the contract has one owner
DETECT_SKIP = re.compile(r"detect skip for (\S+):")

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
    (DETECT_SKIP, "soft", None),
)


def parse_log(lines: Iterable[str]) -> dict[str, dict[str, list[str]]]:
    """per provider -> {"hard": [...], "soft": [...]} of matched log lines."""
    issues: dict[str, dict[str, list[str]]] = {}
    for line in lines:
        for pattern, cls, fixed in _RULES:
            match = pattern.search(line)
            if match is None:
                continue
            key = fixed if fixed is not None else match.group(1)
            issues.setdefault(key, {"hard": [], "soft": []})[cls].append(line.strip())
            break
    return issues


def warning(now: dict[str, dict[str, list[str]]]) -> str | None:
    """the ::warning:: for this run's issues, or None when the run is clean."""
    hard = sorted(key for key, issue in now.items() if issue["hard"])
    soft = sorted(key for key, issue in now.items() if issue["soft"] and not issue["hard"])
    parts: list[str] = []
    if hard:
        parts.append("hard failures: " + ", ".join(hard))
    if soft:
        parts.append("skips: " + ", ".join(soft))
    return "::warning::" + "; ".join(parts) if parts else None


def providers_to_ping(
    now: dict[str, dict[str, list[str]]], prev: dict[str, dict[str, list[str]]]
) -> set[str]:
    """providers with a hard failure in both runs: the two-consecutive gate."""
    return {key for key, issue in now.items() if issue["hard"] and prev.get(key, {}).get("hard")}


def _gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True).stdout


def previous_run(repo: str, current_run_id: str) -> tuple[str, Iterable[str]] | None:
    """the previous completed autopr run as (id, log lines), or None."""
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
        return str(run["id"]), (line for line in proc.stdout if line)
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


def close_recovered(now: dict[str, dict[str, list[str]]]) -> list[str]:
    """close open provider-broken issues whose provider passed this run.

    an issue closes only when this run saw no hard failure for its key; a
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

    pass_state: "alive" (the pass finished clean on a data-changing run),
    "dead" (it exited nonzero or never ran to completion), or None (the
    run changed nothing, so the pass never ran and the issue is left alone).
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
                f"@uwuclxdy the claude review pass died on [this run]({run_url}): "
                "the run's new rows got no review and no merge, and the PR "
                "queue piles up until the pass is fixed.\n\n"
                "rotate ANTHROPIC_API_KEY and fix or clear ANTHROPIC_BASE_URL / "
                "ANTHROPIC_MODEL.",
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
                    "the pass completed clean on a data-changing run; closing",
                ]
            )
        return "closed"
    return None


def sync_merge_dead_issue(merge_state: str | None, run_url: str) -> str | None:
    """open or close the merge-failure ping issue; None when nothing changed.

    merge_state: "alive" (the merge step finished clean on a data-changing
    run), "dead" (it exited nonzero or never wrote its rc marker), or None
    (the run changed nothing, so the step never ran the script and the issue
    is left alone).
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
                "its error line names the branch and the fix, the PRs stay "
                "open, and every later data-changing run reds on the same "
                "failure until it is resolved.",
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
                    "the merge step completed clean on a data-changing run; closing",
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
    now = parse_log(Path(args[0]).read_text(encoding="utf-8").splitlines())
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
        for title in close_recovered(now):
            print(f"::warning::closed issue {title}")
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
                print(f"::warning::opened issue {title}")
    return 0

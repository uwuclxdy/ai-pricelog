"""provider-health check: surface per-provider failures from the run log.

reads the watchdog run log, extracts per-provider issue lines, compares
them with the previous autopr run's log (fetched through the gh cli),
writes a ::warning:: annotation for this run's issues, and opens one
github issue per provider that failed hard in two consecutive runs (the
@-mention is what reaches the owner). hard = the detector or a scrape
raised, so the provider is blind or its rows are rejected; soft = detect
skips and validation rejects (additive drift, the provider stays alive
and the mapping-candidate flow covers the skips).
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

# (pattern, class, fixed provider key or None when the pattern carries the key)
_RULES: tuple[tuple[re.Pattern[str], str, str | None], ...] = (
    (re.compile(r"detector for (\S+) failed"), "hard", None),
    (re.compile(r"scraper module for (\S+) failed"), "hard", None),
    (re.compile(r"priced detection for (\S+) failed"), "hard", None),
    (re.compile(r"scraper (\S+) failed for \S+"), "hard", None),
    (re.compile(r"refresh scrape failed for \S+ \((\S+)\)"), "hard", None),
    (re.compile(r"openrouter fetch failed"), "hard", "openrouter"),
    (re.compile(r"entry \S+ failed validation for (\S+):"), "soft", None),
    (re.compile(r"refresh for \S+ skipped in (\S+):"), "soft", None),
    (re.compile(r"detect skip for (\S+):"), "soft", None),
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
        parts.append("detect skips: " + ", ".join(soft))
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


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(f"usage: {Path(sys.argv[0]).name} <run-log>", file=sys.stderr)
        return 2
    now = parse_log(Path(args[0]).read_text(encoding="utf-8").splitlines())
    annotation = warning(now)
    if annotation is not None:
        print(annotation)
    repo = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if repo and run_id:
        previous = previous_run(repo, run_id)
        if previous is not None:
            prev_id, prev_lines = previous
            created = open_issues(
                repo,
                now,
                parse_log(prev_lines),
                f"https://github.com/{repo}/actions/runs/{run_id}",
                f"https://github.com/{repo}/actions/runs/{prev_id}",
            )
            for title in created:
                print(f"::warning::opened issue {title}")
    return 0

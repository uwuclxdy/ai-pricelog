"""Merge the PRs the claude pass marked `automerge: yes`.

the pass posts one machine-readable disposition per PR comment (the marker
line `automerge: yes` / `automerge: no`, the last line of the body) and never
merges: a pass killed after posting its verdicts (observed 2026-09-11, run
34592012203: verdict comment 11:24, timeout kill 11:35, automerge never ran,
the run green) stranded its verified PRs. the workflow's merge step runs this
script after the pass: it reads the run log for this run's PR numbers, reads
each open PR's comments for the pass's marker, and hands the eligible
branches to ai-pricelog-automerge in PR-number order (the merge order). the
pure halves are network-free; main() owns the network, health.py's shape.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

from ai_pricelog import automerge, pr

# the pipeline logs each opened PR as `opened pr for <source>: <url>`; only a
# /pull/ url is a PR, a run-report url on the same line shape is not
_OPENED_PR_LINE = re.compile(r"opened pr for \S+: \S*/pull/(\d+)\s*$")

# the marker the pass ends every PR comment with: one whole line
_DISPOSITION_LINE = re.compile(r"automerge: (yes|no)")


def parse_pr_urls(text: str) -> list[int]:
    """This run's PR numbers, in order of appearance; noise lines tolerated."""
    numbers: list[int] = []
    for line in text.splitlines():
        match = _OPENED_PR_LINE.search(line)
        if match is not None:
            numbers.append(int(match.group(1)))
    return numbers


def parse_disposition(comments: Iterable[tuple[str, str]], bot_login: str) -> bool | None:
    """The last bot comment carrying a marker line decides; None = no marker."""
    disposition: bool | None = None
    for author, body in comments:
        if author != bot_login:
            continue
        marker = _marker_line(body)
        if marker is not None:
            disposition = marker
    return disposition


def _marker_line(body: str) -> bool | None:
    marker: bool | None = None
    for line in body.splitlines():
        match = _DISPOSITION_LINE.fullmatch(line.strip())
        if match is not None:
            marker = match.group(1) == "yes"
    return marker


def eligible_branches(
    open_prs: Iterable[tuple[int, str]],
    run_pr_numbers: Iterable[int],
    dispositions: Mapping[int, bool | None],
) -> list[str]:
    """The merge order: run PRs the pass marked yes, oldest PR number first.

    a PR is eligible when its number is in this run's set, its head ref is a
    `pricelog/` branch that is not the seed, and the pass's disposition is
    True. no comment, no marker, or `automerge: no` all leave it out: the
    conservative default is to never merge.
    """
    run_set = set(run_pr_numbers)
    eligible = sorted(
        (number, head_ref)
        for number, head_ref in open_prs
        if number in run_set
        and head_ref.startswith("pricelog/")
        and head_ref != automerge.SEED_BRANCH
        and dispositions.get(number) is True
    )
    return [head_ref for _number, head_ref in eligible]


def _open_prs(runner: pr.PrRunner, repo_root: Path) -> list[tuple[int, str]]:
    """(number, head ref) for every open PR, one gh call."""
    out = runner.run(
        ["gh", "pr", "list", "--state", "open", "--limit", "100", "--json", "number,headRefName"],
        cwd=repo_root,
    )
    try:
        entries = json.loads(out)
    except json.JSONDecodeError as exc:
        raise pr.PrError(f"gh pr list returned invalid json: {exc.msg}") from exc
    if not isinstance(entries, list):
        raise pr.PrError("gh pr list returned a non-list json value")
    open_prs: list[tuple[int, str]] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("number"), int):
            continue
        open_prs.append((entry["number"], str(entry.get("headRefName") or "")))
    return open_prs


def _pr_comments(runner: pr.PrRunner, repo_root: Path, number: int) -> list[tuple[str, str]]:
    """(author, body) pairs for one PR's comments, oldest first."""
    out = runner.run(["gh", "pr", "view", str(number), "--json", "comments"], cwd=repo_root)
    try:
        entries = json.loads(out)["comments"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise pr.PrError(f"gh pr view {number} returned an unexpected shape: {exc}") from exc
    if not isinstance(entries, list):
        raise pr.PrError(f"gh pr view {number} returned a non-list comments value")
    comments = [entry for entry in entries if isinstance(entry, dict)]
    pairs: list[tuple[str, str]] = []
    for entry in sorted(comments, key=lambda item: str(item.get("createdAt") or "")):
        author = entry.get("author") or {}
        pairs.append((str(author.get("login") or ""), str(entry.get("body") or "")))
    return pairs


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(f"usage: {Path(sys.argv[0]).name} <run-log>", file=sys.stderr)
        return 2
    run_prs = parse_pr_urls(Path(args[0]).read_text(encoding="utf-8"))
    if not run_prs:
        print("no opened PRs in the run log; nothing to merge")
        return 0
    runner = pr.PrRunner()
    repo_root = Path.cwd()
    try:
        bot_login = runner.run(["gh", "api", "user", "--jq", ".login"], cwd=repo_root).strip()
        run_set = set(run_prs)
        open_prs = _open_prs(runner, repo_root)
        dispositions = {
            number: parse_disposition(_pr_comments(runner, repo_root, number), bot_login)
            for number, _head_ref in open_prs
            if number in run_set
        }
        branches = eligible_branches(open_prs, run_prs, dispositions)
        if not branches:
            print("no PR marked automerge: yes; nothing to merge")
            return 0
        base = pr.default_branch(runner, repo_root)
        sha, results = automerge.merge_branches(branches, repo_root, runner, base, push=True)
    except (automerge.AutoMergeError, pr.PrError) as exc:
        # the script's own semantics: every PR stays open, nothing retried
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for result in results:
        print(f"merged {result.branch} ({result.appended} rows) as {result.commit[:7]}")
    print(f"pushed {sha[:7]} to {base}, branch refs deleted")
    return 0

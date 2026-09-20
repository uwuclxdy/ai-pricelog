"""Merge the PRs the claude pass marked `automerge: yes`.

the pass posts one machine-readable disposition per PR comment (the marker
line `automerge: yes` / `automerge: no`, the last line of the body) and never
merges. the workflow's merge step runs this script after the pass: it reads
every open `pricelog/` PR's comments for the pass's marker and hands the
eligible branches to ai-pricelog-automerge in PR-number order (the merge
order). a pass killed after posting its verdicts (observed 2026-09-11, run
34592012203: verdict comment 11:24, timeout kill 11:35, automerge never ran,
the run green) stranded its verified PRs, and a failed merge step strands
them too (observed 2026-09-18: the 11:00 run's merge push rejected
`fetch first`, its 8 yes-marked PRs merged by hand) — reading dispositions
of every open pricelog PR, whatever run posted them, lets a later
data-changing run's merge step pick the stranded ones up. the pure halves
are network-free; main() owns the network, health.py's shape.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

from ai_pricelog import automerge, pr

# the marker the pass ends every PR comment with: one whole line
_DISPOSITION_LINE = re.compile(r"automerge: (yes|no)")


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


def _pricelog_head(head_ref: str) -> bool:
    """A head ref the merge step may touch: `pricelog/` and not the seed."""
    return head_ref.startswith("pricelog/") and head_ref != automerge.SEED_BRANCH


def _present_refs(
    runner: pr.PrRunner, repo_root: Path, heads: list[str]
) -> tuple[list[str], list[str]]:
    """Split head refs into those whose branch still resolves on the remote.

    A sibling run can merge a PR and delete its branch while github has not
    closed the PR yet, so the open list names a ref with nothing behind it.
    its rows are already landed (or its branch is gone for good), so it must
    skip the merge rather than red the whole run (observed 2026-09-20: the
    19:00 run red'd on an 18:55 PR mid-close, stranding the newer PR).

    The remote is queried, never the checkout's stale tracking refs: the
    workflow fetched at checkout time, minutes before this runs, so a ref
    pushed or deleted by a sibling since then is invisible to `rev-parse`.
    A remote or auth error raises and reds the run rather than reading as
    "nothing to merge".
    """
    present: list[str] = []
    gone: list[str] = []
    for head in heads:
        out = runner.run(["git", "ls-remote", "origin", head], cwd=repo_root).strip()
        (present if out else gone).append(head)
    return present, gone


def eligible_branches(
    open_prs: Iterable[tuple[int, str]],
    dispositions: Mapping[int, bool | None],
) -> list[str]:
    """The merge order: open pricelog PRs the pass marked yes, oldest first.

    a PR is eligible when its head ref is a `pricelog/` branch that is not
    the seed and the pass's disposition is True — which run posted the
    marker is irrelevant, so a yes-marked PR a failed merge step stranded
    still merges on a later run's merge step. no comment, no marker, or
    `automerge: no` all leave it out: the conservative default is to never
    merge.
    """
    eligible = sorted(
        (number, head_ref)
        for number, head_ref in open_prs
        if _pricelog_head(head_ref) and dispositions.get(number) is True
    )
    return [head_ref for _number, head_ref in eligible]


def _open_prs(runner: pr.PrRunner, repo_root: Path) -> list[tuple[int, str]]:
    """(number, head ref) for every open PR, one gh call.

    the limit is the stranded-pickup completeness bound: an open PR beyond
    it is never re-read.
    """
    out = runner.run(
        ["gh", "pr", "list", "--state", "open", "--limit", "1000", "--json", "number,headRefName"],
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
    if args:
        print(f"usage: {Path(sys.argv[0]).name}", file=sys.stderr)
        return 2
    runner = pr.PrRunner()
    repo_root = Path.cwd()
    try:
        open_prs = _open_prs(runner, repo_root)
        candidates = [
            (number, head_ref) for number, head_ref in open_prs if _pricelog_head(head_ref)
        ]
        if not candidates:
            print("no open pricelog PRs; nothing to merge")
            return 0
        present, gone = _present_refs(runner, repo_root, [head for _number, head in candidates])
        for head in gone:
            print(f"skipping {head}: branch ref deleted, PR mid-close")
        candidates = [c for c in candidates if c[1] in present]
        if not candidates:
            print("no open pricelog PR with a live branch; nothing to merge")
            return 0
        bot_login = runner.run(["gh", "api", "user", "--jq", ".login"], cwd=repo_root).strip()
        dispositions = {
            number: parse_disposition(_pr_comments(runner, repo_root, number), bot_login)
            for number, _head_ref in candidates
        }
        branches = eligible_branches(candidates, dispositions)
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

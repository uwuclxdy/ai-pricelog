"""Union-merge pipeline PR branches onto the default branch.

the claude pass invokes this after its review: `ai-pricelog-automerge
<branch>...`, branches in merge order, oldest PR first. one merge commit
per branch; the two-parent commit makes the branch head an ancestor of the
default branch, which github reads as a merged PR. the pass passes only
branches it verified, and this module re-checks each branch mechanically:

- the branch is a `pricelog/` automation branch, never the seed branch
- the branch changes only pipeline files (history, index, README, announce,
  absence, billing-rules plus its test pin)
- the history lands as an exact-line union: every HEAD line survives, the
  branch's lines not already present append in branch order. a key-based
  union drops same-day update rows, so the merge dedupes exact lines only
- index.json and the README stats regenerate from the union via the same
  codepath the pipeline uses (`store.write_index`, `stats.render`)
- announce.json and absence.json keep HEAD's copy on intermediate merges;
  the last (newest) branch's copies land with the final merge

the push and the ref deletions happen only after every merge commit landed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ai_pricelog import models, pr, stats, store
from ai_pricelog.absence import ABSENCE_FILE
from ai_pricelog.announce import ANNOUNCE_FILE, BILLING_RULES_FILE
from ai_pricelog.pipeline import HISTORY_FILE, INDEX_FILE, README_FILE

PIPELINE_FILES = frozenset(
    {
        HISTORY_FILE,
        INDEX_FILE,
        README_FILE,
        ANNOUNCE_FILE,
        ABSENCE_FILE,
        BILLING_RULES_FILE,
        "tests/test_billing_rules.py",
    }
)

SEED_BRANCH = "pricelog/seed"


class AutoMergeError(Exception):
    """the merge stopped; the message names the branch and the fix."""


@dataclass(frozen=True)
class MergeResult:
    branch: str
    commit: str
    appended: int


def _branch_text(runner: pr.PrRunner, repo_root: Path, branch: str, path: str) -> str:
    return runner.run(["git", "show", f"origin/{branch}:{path}"], cwd=repo_root)


def _line_union(head: list[str], branch: list[str]) -> list[str]:
    """head's lines, then the branch lines not already present, in branch order."""
    seen = set(head)
    union = list(head)
    for line in branch:
        if line not in seen:
            seen.add(line)
            union.append(line)
    return union


def _check_branches(branches: list[str], repo_root: Path, runner: pr.PrRunner) -> None:
    for branch in branches:
        if branch == SEED_BRANCH:
            raise AutoMergeError(f"branch {branch}: the seed PR is human-only, never automerge it")
        if not branch.startswith("pricelog/"):
            raise AutoMergeError(f"branch {branch}: not a pricelog automation branch")
        paths = set(
            runner.run(
                ["git", "diff", "--name-only", "HEAD", f"origin/{branch}"],
                cwd=repo_root,
            ).splitlines()
        )
        outside = sorted(paths - PIPELINE_FILES)
        if outside:
            raise AutoMergeError(
                f"branch {branch}: changes {outside}; only pipeline files may ride"
                " an automerged branch"
            )
    if runner.run(["git", "status", "--porcelain"], cwd=repo_root).strip():
        raise AutoMergeError("worktree is dirty; the merge needs a clean tree")


def merge_branches(
    branches: list[str],
    repo_root: Path,
    runner: pr.PrRunner,
    base: str,
    push: bool = True,
) -> tuple[str, list[MergeResult]]:
    """Union-merge each branch onto HEAD, then push and delete the refs.

    `branches` is the merge order: oldest PR first, newest last (its
    announce/absence snapshots are the freshest of the run). a failure
    anywhere leaves the refs in place and raises; nothing is pushed.
    """
    if not branches:
        raise AutoMergeError("no branches given; nothing to merge")
    _check_branches(branches, repo_root, runner)
    # the runner checkout carries no git identity; the merge commits need one
    pr.ensure_author(repo_root, runner)

    results: list[MergeResult] = []
    for number, branch in enumerate(branches):
        last = number == len(branches) - 1
        merge = subprocess.run(
            # --no-ff forces the two-parent commit; --no-commit alone
            # fast-forwards a descendant branch and moves HEAD onto it
            ["git", "merge", "--no-ff", "--no-commit", f"origin/{branch}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if "already up to date" in merge.stdout:
            raise AutoMergeError(
                f"branch {branch}: already merged into HEAD; drop it from the merge list"
            )
        # an exit code 1 with CONFLICT lines is the expected sibling-branch
        # state on the data files; anything else is a real merge failure
        if merge.returncode not in (0, 1) or (
            merge.returncode == 1 and "conflict" not in merge.stdout.lower()
        ):
            raise AutoMergeError(
                f"branch {branch}: git merge failed: {merge.stdout.strip()} {merge.stderr.strip()}"
            )

        # HEAD's copies come from git, never the worktree: the in-flight merge
        # left conflict markers in the conflicted files
        head_text = runner.run(["git", "show", f"HEAD:{HISTORY_FILE}"], cwd=repo_root)
        union = _line_union(
            head_text.splitlines(),
            _branch_text(runner, repo_root, branch, HISTORY_FILE).splitlines(),
        )
        union_text = "\n".join(union) + ("\n" if union else "")
        (repo_root / HISTORY_FILE).write_text(union_text, encoding="utf-8")

        rows = store.parse(union_text, HISTORY_FILE)
        store.write_index(rows, repo_root / INDEX_FILE)
        readme_path = repo_root / README_FILE
        readme_text = runner.run(["git", "show", f"HEAD:{README_FILE}"], cwd=repo_root)
        readme_path.write_text(
            stats.render(
                readme_text,
                stats.compute(rows, models.load_models(repo_root / models.MODELS_FILE)),
            ),
            encoding="utf-8",
        )
        if last:
            (repo_root / ANNOUNCE_FILE).write_text(
                _branch_text(runner, repo_root, branch, ANNOUNCE_FILE), encoding="utf-8"
            )
            (repo_root / ABSENCE_FILE).write_text(
                _branch_text(runner, repo_root, branch, ABSENCE_FILE), encoding="utf-8"
            )

        runner.run(
            [
                "git",
                "add",
                "--",
                HISTORY_FILE,
                INDEX_FILE,
                README_FILE,
                ANNOUNCE_FILE,
                ABSENCE_FILE,
                BILLING_RULES_FILE,
                "tests/test_billing_rules.py",
            ],
            cwd=repo_root,
        )
        # the staged tree must carry no conflict markers (a file both sides
        # changed that this merge does not own would stage them)
        runner.run(["git", "diff", "--cached", "--check"], cwd=repo_root)
        appended = len(union) - len(head_text.splitlines())
        # the merge commit keeps the branch's own subject: the repo convention
        # for burst merges is one commit per branch, subject as the branch's
        subject = runner.run(
            ["git", "log", "--format=%s", "-1", f"origin/{branch}"], cwd=repo_root
        ).strip()
        runner.run(
            ["git", "commit", "-m", subject or f"merge: {branch}"],
            cwd=repo_root,
        )
        commit = runner.run(["git", "rev-parse", "HEAD"], cwd=repo_root).strip()
        results.append(MergeResult(branch, commit, appended))

    if runner.run(["git", "status", "--porcelain"], cwd=repo_root).strip():
        raise AutoMergeError("the merged tree is not clean; nothing was pushed")
    for branch in branches:
        # the auto-mark precondition: every merged branch head must be an
        # ancestor of the push target, or github leaves its PR open
        try:
            runner.run(
                ["git", "merge-base", "--is-ancestor", f"origin/{branch}", "HEAD"],
                cwd=repo_root,
            )
        except pr.PrError:
            raise AutoMergeError(
                f"branch {branch}: its head is not an ancestor of the merge result;"
                " refusing the push, its PR would not auto-mark merged"
            ) from None
    sha = runner.run(["git", "rev-parse", "HEAD"], cwd=repo_root).strip()
    if not push:
        return sha, results

    runner.run(["git", "push", "origin", f"HEAD:refs/heads/{base}"], cwd=repo_root)
    for result in results:
        try:
            runner.run(["git", "push", "origin", "--delete", result.branch], cwd=repo_root)
        except pr.PrError:
            print(
                f"warning: remote branch cleanup for {result.branch} failed",
                file=sys.stderr,
            )
    return sha, results


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="ai-pricelog-automerge",
        description="union-merge pipeline PR branches onto the default branch",
    )
    parser.add_argument(
        "branches",
        nargs="+",
        help="pricelog branches in merge order: oldest first, newest last",
    )
    parser.add_argument(
        "--base",
        help="the default branch to push to (default: gh's defaultBranchRef)",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="land the merge commits locally; skip the push and the ref deletions",
    )
    args = parser.parse_args()
    repo_root = Path.cwd()
    runner = pr.PrRunner()
    try:
        base = args.base or pr.default_branch(runner, repo_root)
        sha, results = merge_branches(args.branches, repo_root, runner, base, push=not args.no_push)
    except (AutoMergeError, pr.PrError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for result in results:
        print(f"merged {result.branch} ({result.appended} rows) as {result.commit[:7]}")
    if args.no_push:
        print(f"landed {sha[:7]} locally, nothing pushed")
    else:
        print(f"pushed {sha[:7]} to {base}, branch refs deleted")
    return 0

"""Union-merge pipeline PR branches onto the default branch.

the claude pass invokes this after its review: `ai-pricelog-automerge
<branch>...`, branches in merge order, oldest PR first. one merge commit
per branch; the two-parent commit makes the branch head an ancestor of the
default branch, which github reads as a merged PR. the pass passes only
branches it verified, and this module re-checks each branch mechanically:

- the branch is a `pricelog/` automation branch, never the seed branch
- the branch changes only pipeline files (the per-source history shards,
  the state/announce and state/absence trees, billing-rules plus its test pin)
- the pipeline files are committed and nothing else is staged: every stage
  names its paths, so unrelated dirt in the checkout cannot ride the merge
- each shard the branch touched lands as an exact-line union: every HEAD
  line survives, the branch's lines not already present append in branch
  order. a key-based union drops same-day update rows, so the merge dedupes
  exact lines only. the union then re-sorts on (model_id, observed_at), the
  order every shard writer holds, so a merged shard still puts a new row
  beside its siblings in the review diff
- index.json regenerates here, from the merged shards, so the served index
  is correct when the push lands rather than whenever a workflow next runs.
  reindex.yml still covers a human push; whether THIS push also triggers it
  depends on which credential git picks for it, which nothing here pins
- the README stats stay stale until the publish job owns their regen
- the announce tree takes the last (newest) branch's copy with the final
  merge; a source's absence file lands on that source's branch, so the merge
  accumulates them without a last-branch copy

the push and the ref deletions happen only after every merge commit landed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ai_pricelog import models, pr, store, validate
from ai_pricelog.absence import ABSENCE_DIR
from ai_pricelog.announce import ANNOUNCE_DIR, BILLING_RULES_FILE

SHARD_DIR = store.SHARD_DIR
INDEX_FILE = store.INDEX_FILE

PIPELINE_EXACT_FILES = frozenset(
    {
        BILLING_RULES_FILE,
        "tests/test_billing_rules.py",
    }
)
PIPELINE_STATE_DIRS = (ANNOUNCE_DIR, ABSENCE_DIR)

SEED_BRANCH = "pricelog/seed"


class AutoMergeError(Exception):
    """the merge stopped; the message names the branch and the fix."""


@dataclass(frozen=True)
class MergeResult:
    branch: str
    commit: str
    appended: int


def _branch_text(runner: pr.PrRunner, repo_root: Path, branch: str, path: str) -> str:
    """The branch's copy of a path; a path the branch never had reads as empty."""
    try:
        return runner.run(["git", "show", f"origin/{branch}:{path}"], cwd=repo_root)
    except pr.PrError:
        return ""


def _sorted_lines(lines: list[str], branch: str, path: str) -> list[str]:
    """The union re-sorted on (model_id, observed_at), reordering bytes only.

    The lines carry their original serialization, so sorting indices instead
    of re-serializing keeps a merged shard byte-comparable with what its
    writers produced. The pass is authorized to hand-edit a branch row, so a
    line it cannot read stops the merge by name rather than by traceback.
    """
    try:
        rows = store.parse("\n".join(lines), path)
        if len(rows) != len(lines):
            raise ValueError(f"{len(lines)} line(s) parsed as {len(rows)} row(s)")
        order = sorted(range(len(lines)), key=lambda index: store._shard_order(rows[index]))
    except (ValueError, KeyError, IndexError) as exc:
        raise AutoMergeError(
            f"branch {branch}: {path} does not read as sorted rows: {exc};"
            " fix: the offending line on the branch, one json object per line"
            " carrying model_id and observed_at"
        ) from exc
    return [lines[index] for index in order]


def _head_text(runner: pr.PrRunner, repo_root: Path, path: str) -> str:
    """HEAD's copy of a shard; a shard HEAD never had reads as empty."""
    try:
        return runner.run(["git", "show", f"HEAD:{path}"], cwd=repo_root)
    except pr.PrError:
        return ""


def _branch_tree_paths(
    runner: pr.PrRunner, repo_root: Path, branch: str, tree_dir: str
) -> list[str]:
    """The files one branch carries under a state directory, in tree order."""
    return [
        path
        for path in runner.run(
            ["git", "ls-tree", "-r", "--name-only", f"origin/{branch}", f"{tree_dir}/"],
            cwd=repo_root,
        ).splitlines()
        if path
    ]


def _replace_tree(runner: pr.PrRunner, repo_root: Path, branch: str, tree_dir: str) -> None:
    """Set the worktree's copy of a state directory to the branch's copy.

    The branch's tree is the complete snapshot; files it no longer carries are
    pruned, so a removed channel or cleared source stops appearing here.
    """
    named: set[str] = set()
    for path in _branch_tree_paths(runner, repo_root, branch, tree_dir):
        (repo_root / path).write_text(
            _branch_text(runner, repo_root, branch, path), encoding="utf-8"
        )
        named.add(path)
    tree = repo_root / tree_dir
    for path in tree.rglob("*"):
        if path.is_file() and path.relative_to(repo_root).as_posix() not in named:
            path.unlink()
    for path in sorted(tree.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def _branch_diff_paths(runner: pr.PrRunner, repo_root: Path, branch: str) -> list[str]:
    """The paths one branch changed since the merge base.

    three-dot: what the BRANCH changed since the merge base. two-dot also lists
    a file HEAD gained and the branch never had, and `git show
    origin/<branch>:<that path>` then raises mid-merge.
    """
    return runner.run(
        ["git", "diff", "--name-only", f"HEAD...origin/{branch}"], cwd=repo_root
    ).splitlines()


def _branch_shard_paths(runner: pr.PrRunner, repo_root: Path, branch: str) -> list[str]:
    """The shard paths one branch changed, relative to HEAD."""
    return sorted(
        path
        for path in _branch_diff_paths(runner, repo_root, branch)
        if path.startswith(SHARD_DIR + "/")
    )


def _union_models(head_text: str, branch_text: str) -> str:
    """HEAD's model catalog plus the branch's additions.

    A branch entry lands only when HEAD claims none of its `(source, model_id)`
    pairs, whatever canonical id claims them. that preserves the coverage
    invariant: a human twin merge on HEAD deletes a seeded id, and an older
    branch still carrying that id must not resurrect it.
    """
    head = json.loads(head_text) if head_text else {"version": models.CATALOG_VERSION, "models": {}}
    branch_data = json.loads(branch_text)
    merged = dict(head.get("models") or {})
    head_claims = {
        (source, model_id)
        for entry in merged.values()
        for source, ids in (entry.get("sources") or {}).items()
        for model_id in ids
    }
    for canonical, entry in (branch_data.get("models") or {}).items():
        claims = {
            (source, model_id)
            for source, ids in (entry.get("sources") or {}).items()
            for model_id in ids
        }
        if claims & head_claims:
            continue
        merged[canonical] = entry
        head_claims |= claims
    return (
        json.dumps(
            {"version": models.CATALOG_VERSION, "models": merged},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _line_union(head: list[str], branch: list[str]) -> list[str]:
    """head's lines, then the branch lines not already present, in branch order."""
    seen = set(head)
    union = list(head)
    for line in branch:
        if line not in seen:
            seen.add(line)
            union.append(line)
    return union


def _is_pipeline_path(path: str) -> bool:
    """A path the merge owns: shards, the announce/absence trees, or exact pipeline files.

    The shard rule mirrors `store.shard_name`: exactly one segment under the
    directory. The announce rule allows index.json plus a two-segment
    ``<source>/<slug>.md`` file; the absence rule allows one ``<source>.json``
    file per source.
    """
    if path in PIPELINE_EXACT_FILES or path == INDEX_FILE or path == models.MODELS_FILE:
        return True
    prefix = SHARD_DIR + "/"
    if path.startswith(prefix) and "/" not in path[len(prefix) :]:
        return True
    announce_prefix = ANNOUNCE_DIR + "/"
    if path.startswith(announce_prefix):
        rest = path[len(announce_prefix) :]
        if rest == "index.json":
            return True
        return rest.count("/") == 1 and rest.endswith(".md")
    absence_prefix = ABSENCE_DIR + "/"
    if path.startswith(absence_prefix):
        rest = path[len(absence_prefix) :]
        return "/" not in rest and rest.endswith(".json")
    return False


def _uncommitted(runner: pr.PrRunner, repo_root: Path) -> list[str]:
    """Uncommitted state that could ride into a merge commit.

    the merge stages by path and `git commit` writes the whole index, so only
    a dirty pipeline file or an already staged change can reach the commit. a
    CI checkout carries unrelated dirt every run: `uv run` rewrites `uv.lock`
    when the runner's resolver config differs from the one that wrote it, and
    `__pycache__` dirs appear under any import.
    """
    staged = runner.run(["git", "diff", "--cached", "--name-only"], cwd=repo_root).splitlines()
    dirty = runner.run(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            SHARD_DIR,
            INDEX_FILE,
            models.MODELS_FILE,
            *sorted(PIPELINE_EXACT_FILES),
            *PIPELINE_STATE_DIRS,
        ],
        cwd=repo_root,
    ).splitlines()
    return [f"staged {path}" for path in staged] + [line.strip() for line in dirty]


def _check_branches(branches: list[str], repo_root: Path, runner: pr.PrRunner) -> None:
    for branch in branches:
        if branch == SEED_BRANCH:
            raise AutoMergeError(f"branch {branch}: the seed PR is human-only, never automerge it")
        if not branch.startswith("pricelog/"):
            raise AutoMergeError(f"branch {branch}: not a pricelog automation branch")
        paths = set(
            # three-dot for the same reason as _branch_shard_paths: two-dot
            # counts what HEAD gained since the branch forked, so every PR
            # older than one burst would read as changing that burst's files
            runner.run(
                ["git", "diff", "--name-only", f"HEAD...origin/{branch}"],
                cwd=repo_root,
            ).splitlines()
        )
        outside = sorted(path for path in paths if not _is_pipeline_path(path))
        if outside:
            raise AutoMergeError(
                f"branch {branch}: changes {outside}; only pipeline files may ride"
                " an automerged branch"
            )
    uncommitted = _uncommitted(runner, repo_root)
    if uncommitted:
        raise AutoMergeError(
            "the merge needs the pipeline files committed and nothing staged: "
            + "; ".join(uncommitted)
        )


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
        appended = 0
        for shard_path in _branch_shard_paths(runner, repo_root, branch):
            head_text = _head_text(runner, repo_root, shard_path)
            union = _line_union(
                head_text.splitlines(),
                _branch_text(runner, repo_root, branch, shard_path).splitlines(),
            )
            appended += len(union) - len(head_text.splitlines())
            union = _sorted_lines(union, branch, shard_path)
            union_text = "\n".join(union) + ("\n" if union else "")
            (repo_root / shard_path).write_text(union_text, encoding="utf-8")

        changed = set(_branch_diff_paths(runner, repo_root, branch))
        models_changed = models.MODELS_FILE in changed
        if models_changed:
            (repo_root / models.MODELS_FILE).write_text(
                _union_models(
                    _head_text(runner, repo_root, models.MODELS_FILE),
                    _branch_text(runner, repo_root, branch, models.MODELS_FILE),
                ),
                encoding="utf-8",
            )

        # the merge owns the served index: reindex.yml runs on push, and
        # whether this push triggers a workflow depends on which credential
        # git picks for it. regenerating here needs no answer to that
        store.write_index(
            store.load_shards(repo_root / SHARD_DIR),
            repo_root / INDEX_FILE,
            validate.load_schema_keys(repo_root).version,
        )

        if last:
            _replace_tree(runner, repo_root, branch, ANNOUNCE_DIR)

        add_paths = [
            SHARD_DIR,
            INDEX_FILE,
            BILLING_RULES_FILE,
            "tests/test_billing_rules.py",
        ]
        if models_changed:
            add_paths.append(models.MODELS_FILE)
        runner.run(["git", "add", "--", *add_paths], cwd=repo_root)
        for state_dir in PIPELINE_STATE_DIRS:
            pr.stage_tree(runner, repo_root, state_dir)
        # the staged tree must carry no conflict markers (a file both sides
        # changed that this merge does not own would stage them)
        runner.run(["git", "diff", "--cached", "--check"], cwd=repo_root)
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

    leftover = _uncommitted(runner, repo_root)
    if leftover:
        raise AutoMergeError(
            "the merged pipeline files are not clean; nothing was pushed: " + "; ".join(leftover)
        )
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

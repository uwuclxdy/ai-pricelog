"""Union-merge pipeline PR branches onto the default branch.

the ci `merge verified PRs` step invokes this after the claude pass posts
its dispositions: `ai-pricelog-automerge <branch>...`, branches in merge
order, oldest PR first. one merge commit per branch; the two-parent commit
makes the branch head an ancestor of the default branch, which github reads
as a merged PR. the step passes only branches the pass marked
`automerge: yes`, and this module re-checks each branch mechanically:

- the branch is a `pricelog/` automation branch, never the seed branch
- the branch changes only pipeline files (the per-source history shards,
  the state/announce and state/absence trees, billing-rules plus its test pin)
- each shard line the union appends passes `validate_row` before it lands:
  the pass is authorized to hand-edit a branch row, so the merge is the one
  path a shape the contract forbids can take into the store, and a refused
  line stops the merge by name. HEAD's own lines are exempt, they already
  sit in the append-only store
- the pipeline files are committed and nothing else is staged: every stage
  names its paths, so unrelated dirt in the checkout cannot ride the merge
- each shard the branch touched lands as an exact-line union: every HEAD
  line survives, the branch's lines not already present append in branch
  order. a key-based union drops same-day update rows, so the merge dedupes
  exact lines only. the union then re-sorts on (model_id, observed_at), the
  order every shard writer holds, so a merged shard still puts a new row
  beside its siblings in the review diff
- the README stats and the dist branch belong to publish.yml, which fires on
  a push to the default branch; the merge regenerates no derived file at all
- the announce tree resolves per channel against the burst base: each url
  lands from the last branch that changed it, so a branch whose run failed a
  channel's fetch (and carries the base's stale entry) never reverts the
  fresh prose an earlier branch of the burst landed; the newest branch's
  index owns the url set, so a url that left the config is deleted. a
  source's absence file lands on that source's branch and the merge takes
  each file from the newest branch that carries it

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
from ai_pricelog.announce import ANNOUNCE_DIR, ANNOUNCE_INDEX, BILLING_RULES_FILE, channel_files

SHARD_DIR = store.SHARD_DIR

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


def _validate_appended(
    appended: list[str], branch_text: str, *, branch: str, path: str, keys: validate.SchemaKeys
) -> None:
    """Every line the partition appends must pass validate_row before it lands.

    The partition arrives from _appended_lines, the one implementation the
    union and this validation both read, so a dedupe change there cannot leave
    the validated set diverging from the appended set. store.parse reads the
    branch's own copy, so a json error names the branch line the fix
    instruction points at. a line HEAD holds stays exempt: it already sits in
    the append-only store. the pass is authorized to hand-edit a branch row,
    so the exact-line partition is the one path a contract-breaking shape can
    take into the store.
    """
    branch_lines = branch_text.splitlines()
    label = f"origin/{branch}:{path}"
    try:
        rows = store.parse(branch_text, label)
    except ValueError as exc:
        raise AutoMergeError(
            f"branch {branch}: {exc}. do not retry: report the error and leave every PR open"
        ) from exc
    if len(rows) != len(branch_lines):
        # store.parse's one-row-per-line contract is what pairs lines to rows
        raise AutoMergeError(
            f"branch {branch}: {label}: {len(branch_lines)} line(s) parsed as"
            f" {len(rows)} row(s); fix: the offending line on the branch, one json"
            " object per line"
        )
    new = set(appended)
    for number, (line, row) in enumerate(zip(branch_lines, rows, strict=False), start=1):
        if line not in new:
            continue
        try:
            validate.validate_row(row, keys)
        except ValueError as exc:
            raise AutoMergeError(
                f"branch {branch}: {label} line {number} fails the row contract:"
                f" {exc}. do not retry: report the error and leave every PR open"
            ) from exc


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


def _announce_index(
    runner: pr.PrRunner, repo_root: Path, rev: str, label: str
) -> dict[str, dict[str, dict[str, str]]] | None:
    """The parsed announce index at a revision; None when the revision carries none.

    The pass is authorized to hand-edit a branch's announce tree, so an index
    that does not read as source -> url -> entry stops the merge by name
    rather than by traceback, and every entry's file must match the path the
    index's own urls derive (the rule ``announce.load_snapshot`` enforces), so
    a hand-edited file field cannot point the merge's write outside the
    announce tree.
    """
    try:
        text = runner.run(["git", "show", f"{rev}:{ANNOUNCE_INDEX}"], cwd=repo_root)
    except pr.PrError:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AutoMergeError(f"{label}: {ANNOUNCE_INDEX} is not valid json: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise AutoMergeError(f"{label}: {ANNOUNCE_INDEX} must be an object")
    for source, urls in data.items():
        if not isinstance(urls, dict):
            raise AutoMergeError(
                f"{label}: {ANNOUNCE_INDEX} source {source!r} must map to an object"
            )
        derived = channel_files(source, urls.keys())
        for url, entry in urls.items():
            if not isinstance(entry, dict) or not all(
                isinstance(entry.get(key), str) for key in ("file", "sha256", "fetched")
            ):
                raise AutoMergeError(
                    f"{label}: {ANNOUNCE_INDEX} entry {source!r}/{url!r} must carry"
                    " 'file', 'sha256' and 'fetched' as strings"
                )
            if entry["file"] != derived[url]:
                raise AutoMergeError(
                    f"{label}: {ANNOUNCE_INDEX} entry {source!r}/{url!r} file"
                    f" {entry['file']!r} does not match the derived path {derived[url]!r}"
                )
    return data


def _merge_announce(
    runner: pr.PrRunner,
    repo_root: Path,
    branch: str,
    base_sha: str,
    base_index: dict[str, dict[str, dict[str, str]]],
    burst: list[tuple[str, dict[str, dict[str, dict[str, str]]]]],
) -> None:
    """Lay the burst's announce tree over the worktree, resolved per channel.

    The url set comes from the newest branch's index, the newest config the
    burst observed: a url it no longer carries is deleted. Each url lands from
    the last branch of the burst whose index carries a sha256 differing from
    the base's — a branch whose run failed that channel's fetch keeps the
    base's stale entry and must not revert the fresh prose an earlier branch
    landed (observed 2026-09-11 on PRs 180-184) — and from the base itself
    when no branch changed it. Shas compare from the index entries, never the
    file bytes: the wrap shape may differ while the prose is identical. A url
    absent from the base counts as differing, so a branch always wins one the
    newest index carries; the base wins only urls it already holds unchanged.

    Each channel file lands at the newest index's path, the one the merged
    url set derives (slug collisions rename with the set), with the winner's
    bytes; the resolved index.json serializes exactly as
    ``announce.save_snapshot`` writes it or the merge diff turns whole-file;
    files the resolution no longer names are pruned.
    """
    resolved: dict[str, dict[str, dict[str, str]]] = {}
    named = {ANNOUNCE_INDEX}
    for source, urls in burst[-1][1].items():
        for url, newest_entry in urls.items():
            base_entry = base_index.get(source, {}).get(url)
            winner_rev, winner_entry = base_sha, base_entry
            for rev, index in burst:
                candidate = index.get(source, {}).get(url)
                if candidate is None or candidate["sha256"] == (base_entry or {}).get("sha256"):
                    continue
                winner_rev, winner_entry = rev, candidate
            file = winner_entry["file"]
            try:
                text = runner.run(["git", "show", f"{winner_rev}:{file}"], cwd=repo_root)
            except pr.PrError as exc:
                raise AutoMergeError(
                    f"branch {branch}: announce channel {source!r}/{url!r} file {file!r}"
                    f" is missing from {winner_rev}"
                ) from exc
            (repo_root / newest_entry["file"]).write_text(text, encoding="utf-8")
            named.add(newest_entry["file"])
            resolved.setdefault(source, {})[url] = {
                "file": newest_entry["file"],
                "sha256": winner_entry["sha256"],
                "fetched": winner_entry["fetched"],
            }
    (repo_root / ANNOUNCE_INDEX).write_text(
        json.dumps(resolved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tree = repo_root / ANNOUNCE_DIR
    for path in tree.rglob("*"):
        if path.is_file() and path.relative_to(repo_root).as_posix() not in named:
            path.unlink()
    for path in sorted(tree.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def _merge_absence(runner: pr.PrRunner, repo_root: Path, branch: str) -> None:
    """Lay the branch's absence files over the worktree, newest carrier wins.

    Each source's ``state/absence/<source>.json`` lands on that source's own
    branch, so files this branch does not carry stay as an earlier branch (or
    HEAD) left them. Git reports add/add conflicts on the files its run did
    carry (cross-run counters diverge), and this write resolves them with the
    branch's copy: merge order is oldest first, so the newest carrier's file
    is the last write. A file whose entries cleared is not carried by the
    branch at all (save_absence deletes it), and HEAD's stale copy keeps
    tracking until the next run rewrites it — the same skip-and-retry the
    pipeline itself uses for state.
    """
    for path in _branch_tree_paths(runner, repo_root, branch, ABSENCE_DIR):
        (repo_root / path).write_text(
            _branch_text(runner, repo_root, branch, path), encoding="utf-8"
        )


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


def _appended_lines(head: list[str], branch: list[str]) -> list[str]:
    """The branch lines HEAD does not hold, in branch order, first occurrence only."""
    seen = set(head)
    appended: list[str] = []
    for line in branch:
        if line not in seen:
            seen.add(line)
            appended.append(line)
    return appended


def _is_pipeline_path(path: str) -> bool:
    """A path the merge owns: shards, the announce/absence trees, or exact pipeline files.

    The shard rule mirrors `store.shard_name`: exactly one segment under the
    directory. The announce rule allows index.json plus a two-segment
    ``<source>/<slug>.md`` file; the absence rule allows one ``<source>.json``
    file per source.
    """
    if path in PIPELINE_EXACT_FILES or path == models.MODELS_FILE:
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


def _check_checkout(repo_root: Path, runner: pr.PrRunner, base: str) -> None:
    """Refuse a merge run from a checkout that is not the base branch.

    Every pricelog branch is a descendant of the base, so a merge started
    from one pushes as a fast-forward: the branch's own unverified commits
    ride into the default branch's history. The sanctioned states are a
    checkout at the remote base tip (a detached CI checkout included) and a
    checkout on the base branch itself, which a local ``--no-push`` run
    advances past it.
    """
    try:
        base_tip = runner.run(
            ["git", "rev-parse", "--verify", "--quiet", f"origin/{base}"], cwd=repo_root
        ).strip()
    except pr.PrError:
        # no origin ref to compare against: the push would fail loudly anyway
        return
    head = runner.run(["git", "rev-parse", "HEAD"], cwd=repo_root).strip()
    branch = runner.run(["git", "branch", "--show-current"], cwd=repo_root).strip()
    if head == base_tip or branch == base:
        return
    raise AutoMergeError(
        f"checkout is on {branch or head[:7]}, not {base}; run the merge from the default branch"
    )


def merge_branches(
    branches: list[str],
    repo_root: Path,
    runner: pr.PrRunner,
    base: str,
    push: bool = True,
) -> tuple[str, list[MergeResult]]:
    """Union-merge each branch onto HEAD, then push and delete the refs.

    `branches` is the merge order: oldest PR first, newest last (each announce
    channel lands from the last branch that changed it, each absence file from
    the newest branch that carries it). a failure anywhere leaves the refs in
    place and raises; nothing is pushed.
    """
    if not branches:
        raise AutoMergeError("no branches given; nothing to merge")
    _check_branches(branches, repo_root, runner)
    _check_checkout(repo_root, runner, base)
    # the runner checkout carries no git identity; the merge commits need one
    pr.ensure_author(repo_root, runner)
    keys = validate.load_schema_keys(repo_root)

    # the burst base, captured once before the first merge commit advances
    # HEAD: every per-channel announce resolution compares against the tree
    # the burst started from
    base_sha = runner.run(["git", "rev-parse", "HEAD"], cwd=repo_root).strip()
    base_index = _announce_index(runner, repo_root, base_sha, f"base {base_sha[:7]}") or {}
    burst: list[tuple[str, dict[str, dict[str, dict[str, str]]]]] = []

    results: list[MergeResult] = []
    for branch in branches:
        merge = subprocess.run(
            # --no-ff forces the two-parent commit; --no-commit alone
            # fast-forwards a descendant branch and moves HEAD onto it
            ["git", "merge", "--no-ff", "--no-commit", f"origin/{branch}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        # git prints "Already up to date." (capital A); match case-insensitively
        # or a merged branch falls through to a bare `git commit` failure
        if "already up to date" in merge.stdout.lower():
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
            head_lines = _head_text(runner, repo_root, shard_path).splitlines()
            branch_text = _branch_text(runner, repo_root, branch, shard_path)
            new_lines = _appended_lines(head_lines, branch_text.splitlines())
            appended += len(new_lines)
            _validate_appended(new_lines, branch_text, branch=branch, path=shard_path, keys=keys)
            union = _sorted_lines([*head_lines, *new_lines], branch, shard_path)
            union_text = "\n".join(union) + ("\n" if union else "")
            (repo_root / shard_path).write_text(union_text, encoding="utf-8")

        # cross-run bursts carry different announce snapshots and absence
        # counters per branch (the 2026-09-07 shape): git then reports
        # add/add conflicts on the state files, so both state trees are
        # resolved by writing the merged content over the worktree before
        # the by-path stage
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

        # the announce tree resolves per channel against the burst base: a
        # branch whose run failed a channel's fetch carries the base's stale
        # entry for it, and the newest branch's whole-tree write would revert
        # the fresh prose an earlier branch of the burst landed. a branch
        # carrying no index.json at all skips the announce step: its tree
        # cannot name a url set
        branch_index = _announce_index(runner, repo_root, f"origin/{branch}", f"branch {branch}")
        if branch_index is not None:
            burst.append((f"origin/{branch}", branch_index))
            _merge_announce(runner, repo_root, branch, base_sha, base_index, burst)
        _merge_absence(runner, repo_root, branch)
        add_paths = [
            SHARD_DIR,
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

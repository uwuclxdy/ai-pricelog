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
- a branch that deletes a pipeline file the merge reads or stages from the
  branch side (a history shard, data/catalog/models.json,
  data/catalog/billing-rules.json, state/announce/index.json,
  tests/test_billing_rules.py, or a channel's .md its own index still names)
  is refused by name before the first merge commit, from the branch's diff
  against its merge base with --no-renames, so a rename reads as the old
  path's deletion: a deleted copy reaches the merge as absent or unstageable,
  and no pipeline run deletes one; the two kinds it does delete on its own
  branches (an absence file, a dropped channel's .md with its index entry)
  keep merging. a branch carrying no announce index has no url set to drop
  channels by, so its deletion of a .md the index in effect at its merge
  names is refused too, and so is its addition or edit of any announce file
  while that index names channels: the announce step resolves channel files
  only through a branch's own index, so either lands out of step with it.
  the deletion check takes no file from an index-carrying sibling merging
  after the branch: that sibling's announce step rewrites every file its own
  index names and prunes the rest, so its merge resolves a file the deletion
  removes. the addition or edit refusal holds whatever merges after: an
  index-carrying sibling merging first rewrote an edited file, so the
  branch's own merge conflicts on it, and an added file lands outside the
  index in effect at that merge
- every other branch-side file the merge reads is read in the pre-flight the
  same way: a pipeline path the branch carries as a symlink or submodule is
  refused by name (`git show` would hand the merge a link target or a commit
  as file bytes), so is an indexed channel .md the branch's tree lacks, each
  catalog copy the union will parse (the branch's models.json and its merge
  base's, the branch's billing-rules.json and HEAD's) parses first, the
  billing rules the union would land pass the committed loader's own rule
  check (`announce.check_billing_rules`), and each channel or absence file it
  copies from the branch decodes as UTF-8 text
- each shard line the union appends passes `validate_row` in the pre-flight:
  the pass is authorized to hand-edit a branch row, so the merge is the one
  path a shape the contract forbids can take into the store, and a refused
  line stops the run by name before any branch merges. each date field it
  checks (`observed_at`, `effective_at`, `provenance.fx_rate_date`) must be
  ASCII digits naming a real calendar day, since the schema's pattern pins
  the shape only. HEAD's own lines are exempt, they already sit in the
  append-only store
- every line the merge stages with the branch's own bytes (a shard line the
  union appends, a channel or absence file it copies, the billing pin while
  the rules stay unchanged) passes the staged merge's `git diff --check`
  against HEAD in the pre-flight, refused by file and line; the catalog files
  and the announce index land re-serialized, outside that check
- what can still stop the merge after `git merge --no-commit` staged: a
  base-side copy the pre-flight does not read (the base's announce index
  naming a channel file the base tree lacks, a HEAD shard row the union
  cannot sort, a HEAD channel, absence or billing-pin copy that is not UTF-8
  text, a pipeline file the base lacks that the merge stages by path); a
  whitespace error in bytes the base already carries that a merge stages
  again; the conflict markers git leaves in the billing pin when HEAD and a
  branch both changed it while the rules stayed unchanged, or in an announce
  file HEAD and a branch carrying no index both changed while no index in
  effect names a channel; a channel file written into a source directory the
  in-flight tree lacks (an earlier merge of the burst pruned it); a merge base
  that moved because the branch shares commits with an earlier branch of the
  burst; and git's own failures. after the last merge commit, the README stats
  refresh can still refuse the push on an input the pre-flight does not
  check (among them the README's stats blocks, and a HEAD-side catalog or
  shard input the pre-flight leaves alone, which the refresh's own read
  refuses: a models.json HEAD lacks, or carries emptied or at another
  version, that no branch's diff names, a HEAD row missing a field the stats read or
  whose observed_at names no calendar day), and so can the clean-tree and
  ancestry checks, leaving the merge commits local
- the catalog the burst lands (the models.json union run over the branches
  in merge order, what the README stats refresh loads after the last merge
  commit) passes the catalog loader's own entry check
  (`models.check_model_entries`) in the pre-flight, each entry named by the
  branch whose union landed it or by HEAD; and it still claims every key
  HEAD's shards store that HEAD's catalog claims, so a branch edit the union
  lands that leaves such a key unclaimed is refused by key, and a source swap
  it lands merges by hand, unless a later branch of the burst claims the key
  again
- each branch pre-flights two bounds before anything lands: the churn gate
  (at most 50 models created, 50 removed, 500 rows appended vs the burst
  base) returns an `unsafe` refusal naming the counts, and every appended
  price row must carry a catalog claim in the catalog the burst lands (the
  merge's own models.json union run over the branches in merge order), so a
  row whose seed rides a needs-human sibling, or whose entry the union drops,
  cannot land unclaimed. `--human` (never passed by CI) waives the churn
  bounds and logs the waived counts; the claim check has no waiver, and a
  removal row is exempt because its claim predates it
- the pipeline files are committed and nothing else is staged: every stage
  names its paths, so unrelated dirt in the checkout cannot ride the merge
- each shard the branch touched lands as an exact-line union: every HEAD
  line survives, the branch's lines not already present append in branch
  order. a key-based union drops same-day update rows, so the merge dedupes
  exact lines only. the union then re-sorts on (model_id, observed_at), the
  order every shard writer holds, so a merged shard still puts a new row
  beside its siblings in the review diff
- the README stats refresh rides the final merge commit as an amend (the push
  stays one merge commit per branch): a pushed head whose stats lag the store
  reds the stats recompute test (observed 2026-09-11, 39c8ee4 -> 6be85a9).
  the dist branch stays publish.yml's outright
- the announce tree resolves per channel against the burst base: each url
  lands from the last branch that changed it, so a branch whose run failed a
  channel's fetch (and carries the base's stale entry) never reverts the
  fresh prose an earlier branch of the burst landed; the url set is the
  newest branch's channels plus a channel only the base holds that no branch
  carries, so a channel the base gained after the branches were cut survives
  and a url that left the config is deleted; a channel the merge step holds
  (its PR was flagged needs-human) stays at the base copy until a ruling
  lands. a source's absence file lands on that source's branch: each changed
  copy lands unless HEAD's copy comes from a newer run (the two run stamps
  are compared on every merge), so a held older-run PR never reverts newer
  absence counters
- billing-rules.json and its test pin resolve by union: the pass appends the
  same confirmed rule to every branch it judges after the confirmation, so
  the union dedupes rules by id (HEAD's copy wins) and recomputes the
  `len(rules) == N` pin from the landed count

a merged branch's ref deletion happens only after every merge commit landed and
the push succeeded; an already-merged branch's ref is deleted on the skip path,
before any merge commit, when its rows are provably on origin/<base>.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_pricelog import models, pr, publish, store, validate
from ai_pricelog.absence import ABSENCE_DIR
from ai_pricelog.announce import (
    ANNOUNCE_DIR,
    ANNOUNCE_INDEX,
    BILLING_RULES_FILE,
    channel_files,
    check_billing_rules,
)

SHARD_DIR = store.SHARD_DIR

PIPELINE_EXACT_FILES = frozenset(
    {
        BILLING_RULES_FILE,
        "tests/test_billing_rules.py",
    }
)
PIPELINE_STATE_DIRS = (ANNOUNCE_DIR, ABSENCE_DIR)
_PIPELINE_PATHSPECS = (
    SHARD_DIR,
    models.MODELS_FILE,
    *sorted(PIPELINE_EXACT_FILES),
    *PIPELINE_STATE_DIRS,
)

# git tree modes: a regular blob, plain or executable; anything else at a path
# the merge reads (a symlink's target, a gitlink's commit) reaches it through
# `git show` as if it were the file's bytes
_REGULAR_FILE_MODES = frozenset({"100644", "100755"})
_NON_REGULAR_KINDS = {"120000": "symlink", "160000": "submodule"}

# the fix clause of a catalog-file refusal, by the revision whose copy does not read
_FIX_BRANCH_COPY = "correct the named copy on the branch, or close the PR"
_FIX_HEAD_COPY = "correct the named copy on the base branch, then re-run"
_FIX_MERGE_BASE_COPY = "rebase the branch onto a base whose copy parses, or close the PR"

SEED_BRANCH = "pricelog/seed"

# the churn pre-gate bounds, per branch vs the burst base: how many models a
# branch may create (new store keys) or delist (removal rows), and how many
# rows it may append in total. `--human` waives them; the claim check never
# does
MAX_CREATED_MODELS = 50
MAX_REMOVED_MODELS = 50
MAX_APPENDED_ROWS = 500


class AutoMergeError(Exception):
    """the merge stopped; the message names the branch and the fix."""


@dataclass(frozen=True)
class MergeResult:
    branch: str
    commit: str
    appended: int


# the merge step runs hourly, so a single transient git read (a fetch or
# ls-remote blip) must not red a run that would otherwise change nothing; the
# retry is bounded and re-raises on the last attempt on the read path, while
# the ref-deletion path warns instead — a cleanup failure must never red a
# run. the read-only gh reads already retry a 5xx inside pr.PrRunner, so only
# the git commands use this (one retry layer). tests patch _RETRY_DELAYS to
# zero to skip the sleeps.
_RETRY_ATTEMPTS = 3
_RETRY_DELAYS = (5.0, 15.0)


def _retry_read(runner: pr.PrRunner, repo_root: Path, cmd: list[str]) -> str:
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            return runner.run(cmd, cwd=repo_root)
        except pr.PrError:
            if attempt == _RETRY_ATTEMPTS - 1:
                raise
            time.sleep(_RETRY_DELAYS[attempt])
    raise AssertionError("unreachable: the last attempt re-raises")


def _delete_remote_branch(runner: pr.PrRunner, repo_root: Path, branch: str) -> None:
    """Delete one branch's remote ref, retrying a transient failure.

    The deletion is what closes the PR on github, so a final failure warns
    instead of raising: the push already landed, and the next run's skip path
    retries the deletion while the PR is still open.
    """
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            runner.run(["git", "push", "origin", "--delete", branch], cwd=repo_root)
            return
        except pr.PrError:
            if attempt == _RETRY_ATTEMPTS - 1:
                print(f"warning: remote branch cleanup for {branch} failed", file=sys.stderr)
                return
            time.sleep(_RETRY_DELAYS[attempt])


def _branch_text(runner: pr.PrRunner, repo_root: Path, branch: str, path: str) -> str:
    """The branch's copy of a path; a path the branch never had reads as empty.

    the pass is authorized to hand-edit a branch's files, so bytes that do not
    decode as text stop the merge by name rather than by traceback.
    """
    try:
        return runner.run(["git", "show", f"origin/{branch}:{path}"], cwd=repo_root)
    except pr.PrError:
        return ""
    except UnicodeDecodeError as exc:
        raise AutoMergeError(
            f"branch {branch}: origin/{branch}:{path} is not UTF-8 text ({exc.reason} at"
            f" byte {exc.start}); fix: re-encode it as UTF-8 on the branch, or close the PR"
        ) from exc


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


def _aligned_branch_rows(
    branch_text: str, *, branch: str, path: str
) -> list[tuple[str, dict[str, object]]]:
    """The branch's copy as (line, row) pairs, one per line, refusing a misparse.

    store.parse reads one json object per line, so the pairing is positional;
    the pre-flight checks and the append validation walk the same pairs, so a
    line none of them can read stops the merge by name wherever it is first
    read, with the same message.
    """
    label = f"origin/{branch}:{path}"
    lines = store.shard_lines(branch_text)
    try:
        rows = store.parse(branch_text, label)
    except ValueError as exc:
        raise AutoMergeError(
            f"branch {branch}: {exc}. do not retry: report the error and leave every PR open"
        ) from exc
    if len(rows) != len(lines):
        raise AutoMergeError(
            f"branch {branch}: {label}: {len(lines)} line(s) parsed as"
            f" {len(rows)} row(s); fix: the offending line on the branch, one json"
            " object per line"
        )
    return list(zip(lines, rows, strict=False))


def _validate_appended(
    appended: list[str], branch_text: str, *, branch: str, path: str, keys: validate.SchemaKeys
) -> None:
    """Every line the partition appends must pass validate_row before it lands.

    The partition arrives from store.appended_lines, the one implementation the
    union and this validation both read, so a dedupe change there cannot leave
    the validated set diverging from the appended set. _aligned_branch_rows
    reads the branch's own copy, so a json error names the branch line the fix
    instruction points at. a line HEAD holds stays exempt: it already sits in
    the append-only store. the pass is authorized to hand-edit a branch row,
    so the exact-line partition is the one path a contract-breaking shape can
    take into the store.
    """
    new = set(appended)
    for number, (line, row) in enumerate(
        _aligned_branch_rows(branch_text, branch=branch, path=path), start=1
    ):
        if line not in new:
            continue
        try:
            validate.validate_row(row, keys)
        except ValueError as exc:
            raise AutoMergeError(
                f"branch {branch}: origin/{branch}:{path} line {number} fails the row contract:"
                f" {exc}. do not retry: report the error and leave every PR open"
            ) from exc


def _check_appended_rows(
    runner: pr.PrRunner, repo_root: Path, branches: list[str], keys: validate.SchemaKeys
) -> None:
    """Validate every line each branch would append, before any git merge.

    the partition is taken against the burst base; every merge keeps all of
    HEAD's lines, so the lines a later merge of the burst appends are a subset
    of these, and a line the merge would append is validated here first: the
    row contract, and the whitespace check the staged merge runs on each line
    it adds (git reports it on the branch's copy; only the partition's lines
    count, since a line it holds back never lands).
    """
    for branch in branches:
        for path in _branch_shard_paths(runner, repo_root, branch):
            branch_text = _branch_text(runner, repo_root, branch, path)
            appended = _appended_lines(
                store.shard_lines(_head_text(runner, repo_root, path)),
                store.shard_lines(branch_text),
            )
            _validate_appended(appended, branch_text, branch=branch, path=path, keys=keys)
            new = set(appended)
            appended_numbers = {
                number
                for number, line in enumerate(store.shard_lines(branch_text), start=1)
                if line in new
            }
            if appended_numbers:
                _refuse_whitespace(
                    branch,
                    [
                        report
                        for report, number in _whitespace_errors(runner, repo_root, branch, [path])
                        if number in appended_numbers
                    ],
                )


def _head_text(runner: pr.PrRunner, repo_root: Path, path: str) -> str:
    """HEAD's copy of a shard; a shard HEAD never had reads as empty."""
    try:
        return runner.run(["git", "show", f"HEAD:{path}"], cwd=repo_root)
    except pr.PrError:
        return ""


def _merge_base_text(runner: pr.PrRunner, repo_root: Path, branch: str, path: str) -> str:
    """The branch's merge base's copy of a path; one it never carried reads as empty.

    the pre-flight parses this copy before any merge, so bytes that do not
    decode as text stop the run by name rather than by traceback.
    """
    sha = runner.run(["git", "merge-base", "HEAD", f"origin/{branch}"], cwd=repo_root).strip()
    try:
        return runner.run(["git", "show", f"{sha}:{path}"], cwd=repo_root)
    except pr.PrError:
        return ""
    except UnicodeDecodeError as exc:
        raise AutoMergeError(
            f"branch {branch}'s merge base: {sha[:7]}:{path} is not UTF-8 text"
            f" ({exc.reason} at byte {exc.start}); fix: {_FIX_MERGE_BASE_COPY}"
        ) from exc


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
        try:
            derived = channel_files(source, urls.keys())
        except ValueError as exc:
            raise AutoMergeError(f"{label}: {ANNOUNCE_INDEX} source {source!r}: {exc}") from exc
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
    held_channels: frozenset[tuple[str, str]] = frozenset(),
) -> None:
    """Lay the burst's announce tree over the worktree, resolved per channel.

    The url set is the newest branch's channels plus a channel only the base
    holds that no branch carries; such a url survives only where the merged
    tree still has its file (the base gained it after every branch was cut),
    and one a branch deleted left the config and is dropped even though the
    base's stale copy still holds it. A url an earlier branch carried but the
    newest does not left the config and is deleted even when the base's stale
    copy still holds it. Each url lands
    from the burst entry with the newest `fetched` date (a same-date tie goes
    to the newest branch), and from the base itself when no branch entry is
    newer: a branch whose run failed that channel's fetch carries a stale
    entry (observed 2026-09-11 on PRs 180-184) and so does a branch cut
    before a later landed refresh (observed 2026-09-21 on PR 283), and
    neither may revert the base's prose. Shas compare from the index entries,
    never the file bytes: the wrap shape may differ while the prose is
    identical. A url absent from the base counts as differing, so a branch
    always wins one the newest index carries; the base wins only urls it
    already holds unchanged.

    Each channel file lands at the newest index's path, the one the merged
    url set derives (slug collisions rename with the set), with the winner's
    bytes; the resolved index.json serializes exactly as
    ``announce.save_snapshot`` writes it or the merge diff turns whole-file;
    files the resolution no longer names are pruned.
    """
    resolved: dict[str, dict[str, dict[str, str]]] = {}
    named = {ANNOUNCE_INDEX}
    newest = burst[-1][1]
    for source in [*newest, *[s for s in base_index if s not in newest]]:
        newest_urls = newest.get(source, {})
        base_urls = base_index.get(source, {})
        for url in [*newest_urls, *[u for u in base_urls if u not in newest_urls]]:
            base_entry = base_urls.get(url)
            newest_entry = newest_urls.get(url)
            if (source, url) in held_channels:
                # a needs-human sibling carries this channel's fresh snapshot;
                # hold it at the base copy until a ruling lands. a channel the
                # base lacks is dropped, so an un-ruled new channel never lands
                if base_entry is not None:
                    file = base_entry["file"]
                    try:
                        text = runner.run(["git", "show", f"{base_sha}:{file}"], cwd=repo_root)
                    except pr.PrError as exc:
                        raise AutoMergeError(
                            f"branch {branch}: announce channel {source!r}/{url!r} file"
                            f" {file!r} is missing from {base_sha}"
                        ) from exc
                    (repo_root / file).write_text(text, encoding="utf-8")
                    named.add(file)
                    resolved.setdefault(source, {})[url] = dict(base_entry)
                continue
            if newest_entry is None:
                # a url only the base holds survives only when the base gained
                # it after every branch was cut; an earlier branch carrying it
                # means it left the config, and the base's stale copy is pruned
                if any(index.get(source, {}).get(url) is not None for _rev, index in burst):
                    continue
                file = base_entry["file"]
                try:
                    text = runner.run(["git", "show", f"{base_sha}:{file}"], cwd=repo_root)
                except pr.PrError as exc:
                    raise AutoMergeError(
                        f"branch {branch}: announce channel {source!r}/{url!r} file"
                        f" {file!r} is missing from {base_sha}"
                    ) from exc
                if not (repo_root / file).exists():
                    # a branch deleted the file, so the channel left the config
                    # while the base still held it: the merged tree lacks it and
                    # the base's stale copy is pruned, never re-written
                    continue
                (repo_root / file).write_text(text, encoding="utf-8")
                named.add(file)
                resolved.setdefault(source, {})[url] = dict(base_entry)
                continue
            winner_rev, winner_entry = base_sha, base_entry
            for rev, index in burst:
                candidate = index.get(source, {}).get(url)
                if candidate is None or candidate["sha256"] == (base_entry or {}).get("sha256"):
                    continue
                winner_fetched = (winner_entry or {}).get("fetched", "")
                if candidate["fetched"] > winner_fetched or (
                    winner_rev != base_sha and candidate["fetched"] == winner_fetched
                ):
                    winner_rev, winner_entry = rev, candidate
            file = winner_entry["file"]
            try:
                text = runner.run(["git", "show", f"{winner_rev}:{file}"], cwd=repo_root)
            except pr.PrError as exc:
                raise AutoMergeError(
                    f"branch {branch}: announce channel {source!r}/{url!r} file {file!r}"
                    f" is missing from {winner_rev}"
                ) from exc
            resolved_file = newest_entry["file"]
            (repo_root / resolved_file).write_text(text, encoding="utf-8")
            named.add(resolved_file)
            resolved.setdefault(source, {})[url] = {
                "file": resolved_file,
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


def _run_stamp(runner: pr.PrRunner, repo_root: Path, rev: str, path: str) -> int | None:
    """The run stamp of ``rev``'s copy of a state file, or None when no commit touches it.

    The stamp is the author date (unix seconds) of the commit that wrote the
    bytes ``rev`` carries. The branch name's ``YYYY-MM-DD-HHMMSS`` stamps the
    run's start and the pipeline commits a few minutes later (measured
    163-304 s), so the commit date is not the name's instant — but runs are
    serialized, so the author-date order of two runs' commits is their run
    order. The author date survives a later amend/rebase/cherry-pick while the
    committer date moves. ``git log -- <path>`` uses the default history
    simplification, which prunes a commit TREESAME to a parent — a merge that
    kept one side's bytes — so the first result is the non-merge commit that
    last wrote the path, including the deletion commit when ``rev`` no longer
    has the file; ``--no-merges`` additionally excludes a merge outright, so a
    non-TREESAME merge can never read as the writer. Reading both sides the
    same way gives the comparison one stamp source and one type.
    """
    text = runner.run(
        ["git", "log", "-1", "--no-merges", "--format=%at", rev, "--", path],
        cwd=repo_root,
    ).strip()
    return int(text) if text else None


def _head_has_path(runner: pr.PrRunner, repo_root: Path, path: str) -> bool:
    """Whether HEAD's tree carries ``path``; false when HEAD deleted it."""
    return bool(
        runner.run(["git", "ls-tree", "--name-only", "HEAD", "--", path], cwd=repo_root).strip()
    )


def _stamp_iso(stamp: int) -> str:
    """A run stamp as UTC ``YYYY-MM-DDTHH:MM:SSZ``, for the keep note."""
    return datetime.fromtimestamp(stamp, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _merge_absence(runner: pr.PrRunner, repo_root: Path, branch: str) -> None:
    """Lay the branch's CHANGED absence files over the worktree, newest run wins.

    Each source's ``state/absence/<source>.json`` lands on that source's own
    branch, so files this branch did not change stay as an earlier branch (or
    HEAD) left them. Tree membership alone is not carrying: a branch cut
    before an earlier burst merge inherits HEAD's pre-merge copy of every
    file, and writing those back reverts the landed counters (observed
    2026-09-13: PR 196's digitalocean bump reverted by five later siblings).
    Git reports add/add conflicts on the files its run did change (cross-run
    counters diverge), and this write resolves each with the winning copy.
    Every changed path — a carried copy or a deletion, a cleared source's
    file is deleted by save_absence — lands unless HEAD's copy comes from a
    newer run: the two run stamps are compared on every merge, and a branch
    whose change is older than the run that last landed the path keeps HEAD's
    copy (printed) instead of reverting it (measured 2026-10-15 in a dry run:
    PRs 490-492 wrote their 03:00 openrouter file over 499's 07:00 one).
    """
    changed = {
        path
        for path in _branch_diff_paths(runner, repo_root, branch)
        if path.startswith(ABSENCE_DIR + "/")
    }
    carried = set(_branch_tree_paths(runner, repo_root, branch, ABSENCE_DIR))
    # git removes the directory when it merges a deletion cleanly and the file
    # was the last one under it; recreate it before either write-back below
    (repo_root / ABSENCE_DIR).mkdir(parents=True, exist_ok=True)
    for path in sorted(changed):
        head_stamp = _run_stamp(runner, repo_root, "HEAD", path)
        branch_stamp = _run_stamp(runner, repo_root, f"origin/{branch}", path)
        if head_stamp is not None and branch_stamp is not None and head_stamp > branch_stamp:
            print(
                f"kept HEAD's {path} over {branch}: HEAD's copy is from a newer run"
                f" ({_stamp_iso(head_stamp)} > {_stamp_iso(branch_stamp)})"
            )
            if _head_has_path(runner, repo_root, path):
                # resolve the in-flight merge's worktree copy (conflict markers
                # or a cleanly merged mix) back to HEAD's bytes
                (repo_root / path).write_text(_head_text(runner, repo_root, path), encoding="utf-8")
            else:
                # HEAD deleted the path; keep the absence so the stage records it
                (repo_root / path).unlink(missing_ok=True)
            continue
        if path in carried:
            (repo_root / path).write_text(
                _branch_text(runner, repo_root, branch, path), encoding="utf-8"
            )
        else:
            # the branch cleared the source, so its tree lacks the file; record
            # the deletion so the stage removes it
            (repo_root / path).unlink(missing_ok=True)


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


def _head_store_keys(runner: pr.PrRunner, repo_root: Path) -> set[tuple[str, str]]:
    """Every (source, model_id) the shards at HEAD hold.

    a row HEAD already stores under a key is a price update or a removal, not
    a new model: the churn pre-gate counts it as appended only. a HEAD line
    that does not parse names the shard rather than tracebacking: the store is
    append-only, so a misparse there predates this merge.
    """
    keys: set[tuple[str, str]] = set()
    for path in runner.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD", SHARD_DIR + "/"], cwd=repo_root
    ).splitlines():
        if not path:
            continue
        text = _head_text(runner, repo_root, path)
        try:
            rows = store.parse(text, f"HEAD:{path}")
        except ValueError as exc:
            raise AutoMergeError(
                f"HEAD: {exc}. do not retry: report the error and leave every PR open"
            ) from exc
        for row in rows:
            source = row.get("source")
            model_id = row.get("model_id")
            if isinstance(source, str) and isinstance(model_id, str):
                keys.add((source, model_id))
    return keys


def _parse_models(text: str, label: str, fix: str) -> dict[str, dict[str, Any]]:
    """One models.json revision's entries, in the shape the claims and the union walk.

    each entry is an object whose `sources` map each source to one id or a
    list of ids. the file's own loader checks the full schema at production
    reads; this holds what the merge dereferences, so a revision that does not
    read refuses by label rather than tracebacking, and the pre-flight runs it
    on every copy the union will read before any git merge.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AutoMergeError(
            f"{label}: {models.MODELS_FILE} is not valid json: {exc.msg}; fix: {fix}"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("models"), dict):
        raise AutoMergeError(
            f"{label}: {models.MODELS_FILE} must carry a 'models' object; fix: {fix}"
        )
    for canonical, entry in data["models"].items():
        sources = entry.get("sources") if isinstance(entry, dict) else None
        if not isinstance(sources, dict) or not all(
            isinstance(ids, str)
            or (isinstance(ids, list) and all(isinstance(model_id, str) for model_id in ids))
            for ids in sources.values()
        ):
            raise AutoMergeError(
                f"{label}: {models.MODELS_FILE} entry {canonical!r} must be an object whose"
                f" 'sources' map each source to one id or a list of ids; fix: {fix}"
            )
    return data["models"]


def _parse_billing_rules(text: str, label: str, fix: str) -> list[dict[str, Any]]:
    """One billing-rules.json revision's rules, each an object keyed by its string id.

    the union dedupes on the id, so that is the shape it reads; the full rule
    schema is the committed loader's check, which the pre-flight runs on the
    rules the union lands (_check_landed_rules).
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AutoMergeError(
            f"{label}: {BILLING_RULES_FILE} is not valid json: {exc.msg}; fix: {fix}"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise AutoMergeError(f"{label}: {BILLING_RULES_FILE} must carry a 'rules' list; fix: {fix}")
    for index, rule in enumerate(data["rules"]):
        if not isinstance(rule, dict) or not isinstance(rule.get("id"), str):
            raise AutoMergeError(
                f"{label}: {BILLING_RULES_FILE} rule {index} must be an object carrying"
                f" a string 'id'; fix: {fix}"
            )
    return data["rules"]


def _catalog_claims(text: str, label: str, fix: str) -> set[tuple[str, str]]:
    """Every (source, model_id) pair one models.json revision claims.

    the claims are what the coverage invariant pins; a revision carrying no
    models.json claims nothing.
    """
    if not text:
        return set()
    return _models_claims(_parse_models(text, label, fix))


def _entry_claims(entry: dict[str, Any]) -> set[tuple[str, str]]:
    """The (source, model_id) pairs one parsed catalog entry claims.

    a source maps to one id as a bare string or to a list of ids, the two
    shapes `models.load_models` reads, so a bare string is one claim.
    """
    return {
        (source, model_id)
        for source, ids in entry["sources"].items()
        for model_id in ([ids] if isinstance(ids, str) else ids)
    }


def _branch_churn(
    runner: pr.PrRunner, repo_root: Path, branch: str, head_keys: set[tuple[str, str]]
) -> tuple[int, int, int]:
    """(appended rows, created models, removed models) the branch adds over HEAD.

    appended counts the exact-line partition the union would land; created
    counts appended price rows whose key HEAD never held; removed counts
    appended removal rows. a row without a source/model_id pair is the append
    validation's problem, never counted as created.
    """
    appended = created = removed = 0
    for path in _branch_shard_paths(runner, repo_root, branch):
        branch_text = _branch_text(runner, repo_root, branch, path)
        new = set(
            _appended_lines(
                store.shard_lines(_head_text(runner, repo_root, path)),
                store.shard_lines(branch_text),
            )
        )
        appended += len(new)
        for line, row in _aligned_branch_rows(branch_text, branch=branch, path=path):
            if line not in new:
                continue
            if row.get("removed") is True:
                removed += 1
                continue
            source = row.get("source")
            model_id = row.get("model_id")
            if (
                isinstance(source, str)
                and isinstance(model_id, str)
                and (source, model_id) not in head_keys
            ):
                created += 1
    return appended, created, removed


def _check_churn(churn: dict[str, tuple[int, int, int]]) -> None:
    """Refuse the run when any branch exceeds a churn bound, naming the counts.

    the refusal is the machine-readable verdict the merge step reds on: the
    PRs stay open and a human reviews. the counts are per branch vs the burst
    base, the diff the pass reviewed.
    """
    for branch, (appended, created, removed) in churn.items():
        if (
            created > MAX_CREATED_MODELS
            or removed > MAX_REMOVED_MODELS
            or appended > MAX_APPENDED_ROWS
        ):
            raise AutoMergeError(
                f"branch {branch}: unsafe: creates {created} model(s) (bound"
                f" {MAX_CREATED_MODELS}), removes {removed} (bound {MAX_REMOVED_MODELS}),"
                f" appends {appended} row(s) (bound {MAX_APPENDED_ROWS}); fix: review"
                " the branch by hand and merge with --human, or close the PR"
            )


def _check_carried_claims(
    runner: pr.PrRunner, repo_root: Path, branches: list[str], claims: set[tuple[str, str]]
) -> None:
    """Every appended price row needs a claim in the catalog the burst lands.

    ``claims`` are the claims of that catalog (_burst_catalog): the pipeline
    seeds each new key on the branch whose PR carries the row, so a seed the
    union lands from any branch of the burst lands with the row (all merge
    commits land before the push, the default branch never sees the
    transient). a claim only a needs-human sibling carries, or one a branch
    carries in an entry the union drops (unchanged against its merge base, or
    overlapping a claim already landed), refuses the merge by name. a removal
    row is exempt: its claim landed with its first price row, and refusing it
    would block a delisting on a coverage gap this merge did not create.
    """
    for branch in branches:
        for path in _branch_shard_paths(runner, repo_root, branch):
            branch_text = _branch_text(runner, repo_root, branch, path)
            new = set(
                _appended_lines(
                    store.shard_lines(_head_text(runner, repo_root, path)),
                    store.shard_lines(branch_text),
                )
            )
            for line, row in _aligned_branch_rows(branch_text, branch=branch, path=path):
                if line not in new or row.get("removed") is True:
                    continue
                source = row.get("source")
                model_id = row.get("model_id")
                if not (isinstance(source, str) and isinstance(model_id, str)):
                    continue  # the append validation names the missing field
                if (source, model_id) not in claims:
                    raise AutoMergeError(
                        f"branch {branch}: appended row {(source, model_id)!r} has no catalog"
                        " claim in the catalog the burst lands (HEAD's entries plus each entry"
                        " the union lands from a branch of the burst); fix: merge the branch"
                        " carrying its seed together with it, or close the PR"
                    )


def _burst_catalog(
    runner: pr.PrRunner, repo_root: Path, branches: list[str], head_keys: set[tuple[str, str]]
) -> str:
    """models.json as the burst lands it: the merge's own union over ``branches`` in order.

    starting from HEAD's copy, each branch whose diff names the catalog (the
    merge loop's `models_changed` test) goes through _branch_union, the call
    the merge loop writes the file with, so the result is the text the last
    catalog-changing merge writes. a copy the diff does not name equals its
    merge base's and lands nothing; it still parses here, so a junk copy
    refuses by name whether or not the union reads it. HEAD's copy parses
    before any branch's copy the union does not read, so a junk base copy is
    the cause reported before such a branch copy.

    the README stats refresh after the last merge commit loads the landed
    file through `models.load_models`, and the default branch's coverage
    check needs a claim for every key its shards store under a source
    `providers.json` names: every landed entry passes the loader's own entry
    check here and every claim HEAD holds for a stored key stays claimed
    (_check_landed_catalog). a HEAD copy no branch's diff names keeps post-merge
    the loader's file-level checks this parse does not run (among them a
    missing, emptied or other-version file), and the module docstring names
    that class. each entry is
    named by the revision that landed it: HEAD, or the last branch whose union
    changed it.
    """
    landed = _head_text(runner, repo_root, models.MODELS_FILE)
    head_models = _parse_models(landed, "HEAD", _FIX_HEAD_COPY) if landed else {}
    current = head_models
    landed_by: dict[str, str] = {}
    dropped_by: dict[tuple[str, str], str] = {}
    for branch in branches:
        if models.MODELS_FILE in _branch_diff_paths(runner, repo_root, branch):
            landed = _branch_union(runner, repo_root, branch, landed)
            unioned = json.loads(landed)["models"]
            landed_by.update(
                (canonical, branch)
                for canonical, entry in unioned.items()
                if current.get(canonical) != entry
            )
            # a later branch can land a dropped claim again, so the branch
            # named is the last one whose union dropped it
            dropped_by.update(
                (claim, branch) for claim in _models_claims(current) - _models_claims(unioned)
            )
            current = unioned
            continue
        branch_text = _branch_text(runner, repo_root, branch, models.MODELS_FILE)
        if branch_text:
            _parse_models(branch_text, f"branch {branch}", _FIX_BRANCH_COPY)
    if landed:
        _check_landed_catalog(landed, landed_by, head_models, head_keys, dropped_by)
    return landed


def _models_claims(entries: dict[str, dict[str, Any]]) -> set[tuple[str, str]]:
    """Every (source, model_id) pair a parsed models map claims."""
    return {claim for entry in entries.values() for claim in _entry_claims(entry)}


def _check_landed_catalog(
    landed: str,
    landed_by: dict[str, str],
    head_models: dict[str, dict[str, Any]],
    head_keys: set[tuple[str, str]],
    dropped_by: dict[tuple[str, str], str],
) -> None:
    """Refuse a landed catalog whose entries the loader refuses or that drops a stored key's claim.

    each entry runs through `models.check_model_entries`, the loader's own
    entry check, so a rule the loader gains reaches this pre-flight too; it
    is named against the branch in ``landed_by`` that landed it, else HEAD.
    then every claim HEAD's catalog holds for a key HEAD's shards store must
    still be claimed: the union lands an entry only when none of its pairs is
    claimed already, so a claim leaves the catalog only when a branch's entry
    replaces the entry of the same canonical id with one claiming none of its
    pairs; the refusal sends that landing to a hand merge, which
    tests/test_catalog.py's coverage check judges.
    """
    entries = json.loads(landed)["models"]
    for canonical, entry in entries.items():
        branch = landed_by.get(canonical)
        label, fix = (f"branch {branch}", _FIX_BRANCH_COPY) if branch else ("HEAD", _FIX_HEAD_COPY)
        try:
            models.check_model_entries({canonical: entry}, f"{label}: {models.MODELS_FILE}")
        except models.MappingError as exc:
            raise AutoMergeError(f"{exc}; fix: {fix}") from exc
    kept = _models_claims(entries)
    for canonical, entry in sorted(head_models.items()):
        for claim in sorted((_entry_claims(entry) & head_keys) - kept):
            raise AutoMergeError(
                f"branch {dropped_by[claim]}: the catalog the burst lands no longer claims"
                f" {claim!r}, a key HEAD's shards store and HEAD's entry {canonical!r}"
                " claims; fix: merge the PR by hand so that tests/test_catalog.py's coverage"
                " check passes on the result, or close the PR"
            )


def _branch_union(runner: pr.PrRunner, repo_root: Path, branch: str, landed: str) -> str:
    """``landed`` with the branch's catalog unioned in, from the copies the union reads."""
    return _union_models(
        landed,
        _branch_text(runner, repo_root, branch, models.MODELS_FILE),
        _merge_base_text(runner, repo_root, branch, models.MODELS_FILE),
        branch,
    )


def _union_models(head_text: str, branch_text: str, base_text: str, branch: str) -> str:
    """HEAD's model catalog plus the entries the branch added or changed.

    A branch entry lands only when the branch added or changed it against its
    merge base (a missing base file counts as empty) AND HEAD claims none of
    its `(source, model_id)` pairs, whatever canonical id claims them. The
    first rule keeps a branch cut before a catalog deletion from restoring the
    deleted entry; the second preserves the coverage invariant: a human twin
    merge on HEAD deletes a seeded id, and a branch seeding the same id must
    not duplicate the claim. Each copy reads through _parse_models: the
    pre-flight runs it on the branch's copy, its merge base's and the burst
    base's before any merge, and a later HEAD copy is this union's own output.
    The claim pre-gate runs this same union over the burst (_burst_catalog),
    so the claims it counts are the ones the merge lands.
    """
    merged = dict(_parse_models(head_text, "HEAD", _FIX_HEAD_COPY)) if head_text else {}
    branch_models = _parse_models(branch_text, f"branch {branch}", _FIX_BRANCH_COPY)
    base_models = (
        _parse_models(base_text, f"branch {branch}'s merge base", _FIX_MERGE_BASE_COPY)
        if base_text
        else {}
    )
    head_claims = _models_claims(merged)
    for canonical, entry in branch_models.items():
        if base_models.get(canonical) == entry:
            continue
        claims = _entry_claims(entry)
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


def _union_billing_rules(head_text: str, branch_text: str, branch: str) -> str:
    """HEAD's rules plus the branch's additions, deduped by rule id.

    The pass writes a confirmed rule onto every branch it judges after the
    confirmation, so a burst carries identical copies of one append; the
    union lands one. HEAD's copy wins an id clash, the `_union_models`
    posture: a human edit of a rule on the base is never resurrected. Both
    copies read through _parse_billing_rules: the pre-flight runs it on the
    branch's copy and the burst base's before any merge, and a later HEAD copy
    is this union's own output.
    """
    merged = list(_parse_billing_rules(head_text, "HEAD", _FIX_HEAD_COPY)) if head_text else []
    seen = {rule["id"] for rule in merged}
    for rule in _parse_billing_rules(branch_text, f"branch {branch}", _FIX_BRANCH_COPY):
        if rule["id"] in seen:
            continue
        merged.append(rule)
        seen.add(rule["id"])
    return json.dumps({"rules": merged}, ensure_ascii=False, indent=2) + "\n"


# the one exact-line partition the pending scan and this merge share, owned by
# store (automerge imports pr, so pr cannot import automerge). tests patch this
# module attribute, so it stays a name the call sites resolve, never a direct
# call.
_appended_lines = store.appended_lines

_BILLING_PIN_RE = re.compile(r"assert len\(rules\) == \d+")

# one `git diff --check` report: `<path>:<line>: <error>`
_CHECK_REPORT = re.compile(r"(?P<path>.+):(?P<line>\d+): ")


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


def _is_merge_read_pipeline_path(path: str) -> bool:
    """A pipeline path whose branch-side copy the merge reads or stages.

    The merge parses or stages each of these from the branch side: a shard
    reaches store.parse (_aligned_branch_rows), the catalog files reach
    json.loads (_union_models, _union_billing_rules, _catalog_claims), the
    announce index reaches json.loads (_announce_index), and the billing pin
    is staged by path. A branch deletion of one is refused: a deleted catalog
    or billing-rules copy reaches json.loads("") and dies mid-merge, a deleted
    shard reads as an empty partition, a deleted index reads as absent (the
    announce step skips, and the staged deletion erases the store's url set),
    and a deleted pin fails the by-path stage. A channel's .md is read by path
    only when that branch's own index names it (_merge_announce), so the
    caller adds the branch's indexed paths to the class, or, for a branch
    carrying no index, the files the index in effect at its merge names (the
    announce step skips it, so its deletion would land under an index entry
    that still names the file): _burst_index_in_effect returns those without
    a later index-carrying sibling's, whose announce step resolves the file
    itself; a pipeline channel drop removes the index entry with the file and
    keeps merging. An absence file keeps merging too:
    save_absence deletes a cleared source's file, and an absent file reads as
    that source's empty counters.
    """
    if not _is_pipeline_path(path):
        return False
    if path.startswith(ABSENCE_DIR + "/"):
        return False
    announce_prefix = ANNOUNCE_DIR + "/"
    if path.startswith(announce_prefix):
        return path == ANNOUNCE_INDEX
    return True


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
        ["git", "status", "--porcelain", "--", *_PIPELINE_PATHSPECS], cwd=repo_root
    ).splitlines()
    return [f"staged {path}" for path in staged] + [line.strip() for line in dirty]


def _check_branches(branches: list[str], repo_root: Path, runner: pr.PrRunner) -> None:
    head_indexed: set[str] | None = None
    for branch in branches:
        if branch == SEED_BRANCH:
            raise AutoMergeError(f"branch {branch}: the seed PR is human-only, never automerge it")
        if not branch.startswith("pricelog/"):
            raise AutoMergeError(f"branch {branch}: not a pricelog automation branch")
        paths = set(
            # three-dot for the same reason as _branch_shard_paths: two-dot
            # counts what HEAD gained since the branch forked, so every PR
            # older than one burst would read as changing that burst's files.
            # --no-renames, the deletion read's posture below: rename detection
            # lists a rename's destination alone, so a rename out of an outside
            # path into a pipeline one would hide the outside half and the
            # outside file would leave main with the merge
            runner.run(
                ["git", "diff", "--name-only", "--no-renames", f"HEAD...origin/{branch}"],
                cwd=repo_root,
            ).splitlines()
        )
        outside = sorted(path for path in paths if not _is_pipeline_path(path))
        if outside:
            raise AutoMergeError(
                f"branch {branch}: changes {outside}; only pipeline files may ride"
                " an automerged branch"
            )
        # a branch HEAD already holds never merges (the skip loop below drops
        # it, and deletes its ref only under push once its rows are on
        # origin/<base>), so no branch-side file of it is read here: reading
        # one would red the run on a stranded branch whose tip index does not
        # parse
        merged = _is_ancestor(runner, repo_root, f"origin/{branch}", "HEAD")
        modes: dict[str, str] = {}
        branch_index = None
        if not merged:
            modes = _branch_file_modes(runner, repo_root, branch)
            # before the index read: a type-changed index reads as bad json
            _refuse_non_regular(branch, paths, modes)
            branch_index = _announce_index(
                runner, repo_root, f"origin/{branch}", f"branch {branch}"
            )
        # a channel's .md is read by path from the branch side when the branch's
        # own index names it, so the indexed paths join the deletion class. a
        # branch carrying no index skips the announce step and stages its
        # deletions and channel edits as they are, so the index in effect at
        # its merge joins the class instead: HEAD's, and the one the last
        # index-carrying sibling merging before it lands. the deletion class
        # takes no file from a later sibling, whose announce step resolves the
        # file itself; the edit refusal keeps every in-effect name, because
        # the branch's own merge conflicts on the file an index-carrying
        # sibling merging before it rewrote
        own_indexed = _indexed_files(branch_index)
        indexed = own_indexed
        deletion_indexed = indexed
        if branch_index is None and not merged:
            if head_indexed is None:
                head_indexed = _indexed_files(_announce_index(runner, repo_root, "HEAD", "HEAD"))
            indexed, deletion_indexed = _burst_index_in_effect(
                runner, repo_root, branches, branch, head_indexed
            )
        # the deletions read from git's diff record against the merge base, never
        # from the branch-side text: a deleted file, an empty file and a file
        # both sides lack all read as empty text there, and --no-renames reads a
        # rename as the old path's deletion. three-dot, like every other read of
        # the branch's diff, so a file HEAD gained since the branch forked must
        # not read as a branch deletion
        deleted = sorted(
            path
            for path in runner.run(
                [
                    "git",
                    "diff",
                    "--name-only",
                    "--no-renames",
                    "--diff-filter=D",
                    f"HEAD...origin/{branch}",
                ],
                cwd=repo_root,
            ).splitlines()
            if _is_merge_read_pipeline_path(path) or path in deletion_indexed
        )
        if deleted:
            raise AutoMergeError(
                f"branch {branch}: deletes {deleted}; the merge reads or stages these"
                " from the branch side and a deleted copy reaches it as absent or"
                " unstageable; fix: restore the file(s) on the branch, or close the PR"
            )
        if merged:
            continue
        # the announce step resolves channel files only through a branch's own
        # index, so a branch carrying none lands its channel edits as git merged
        # them: under an index in effect that names channels, an edited file's
        # sha no longer matches its entry and an added one sits outside it. an
        # index-carrying sibling merging before it rewrote the file, so the
        # branch's own merge conflicts whatever merges after
        if branch_index is None and indexed:
            changed_channels = sorted(
                path for path in paths if path.startswith(ANNOUNCE_DIR + "/") and path in modes
            )
            if changed_channels:
                raise AutoMergeError(
                    f"branch {branch}: carries no {ANNOUNCE_INDEX} but adds or changes"
                    f" {changed_channels} while the index in effect at its merge names"
                    " channel files; the merge resolves channel files only through a"
                    " branch's own index, so these would land out of step with that index;"
                    " fix: revert the named file(s) on the branch, or close the PR"
                )
        # an indexed path neither the branch's tree nor its merge base carries
        # leaves no deletion record, so the index is checked against the tree
        missing = sorted(own_indexed - modes.keys())
        if missing:
            raise AutoMergeError(
                f"branch {branch}: its {ANNOUNCE_INDEX} names {missing} that its tree"
                " lacks; the merge reads each indexed channel file from the branch side;"
                " fix: restore the file(s) on the branch or drop their index entries,"
                " or close the PR"
            )
        _refuse_non_regular(branch, own_indexed, modes)
        _check_branch_catalogs(runner, repo_root, branch, paths)
        # beside the shards' appended lines (checked with the partition), the
        # merge lands these whole with the branch's own bytes: each channel file
        # its own index names (git's merge of its changed ones for a branch
        # carrying no index), each changed absence file, and the billing pin
        # while the rules stay unchanged (else the pin is HEAD's copy re-pinned).
        # the catalog files and the announce index land re-serialized
        copied = own_indexed | {
            path
            for path in paths
            if path in modes
            and (
                path.startswith(ABSENCE_DIR + "/")
                or (branch_index is None and path.startswith(ANNOUNCE_DIR + "/"))
                or (path == "tests/test_billing_rules.py" and BILLING_RULES_FILE not in paths)
            )
        }
        # reading each as text stops undecodable bytes by name (_branch_text)
        # before the whitespace check has git print any of them
        for path in sorted(copied):
            _branch_text(runner, repo_root, branch, path)
        if copied:
            errors = _whitespace_errors(runner, repo_root, branch, sorted(copied))
            _refuse_whitespace(branch, [report for report, _line in errors])


def _whitespace_errors(
    runner: pr.PrRunner, repo_root: Path, branch: str, paths: list[str]
) -> list[tuple[str, int]]:
    """git's whitespace errors in the lines the branch's copies of ``paths`` add over HEAD.

    the merge's staged `git diff --cached --check` stops on any of these in a
    line it adds, after `git merge --no-commit` staged; each comes back as
    git's report (``<path>:<line>: <error>``) with the branch-side line number.
    """
    try:
        runner.run(
            ["git", "diff", "--check", "HEAD", f"origin/{branch}", "--", *paths], cwd=repo_root
        )
    except pr.PrError as exc:
        errors = [
            (line, int(located["line"]))
            for line in exc.stdout.splitlines()
            # git prints the offending line itself under each report, behind a "+"
            if not line.startswith("+") and (located := _CHECK_REPORT.match(line))
        ]
        if not errors:
            raise
        return errors
    return []


def _refuse_whitespace(branch: str, reports: list[str]) -> None:
    if reports:
        raise AutoMergeError(
            f"branch {branch}: lines it adds carry whitespace errors {reports}; the merge"
            " stages them with the branch's own bytes and its staged `git diff --cached"
            " --check` would stop it mid-merge; fix: correct the named line(s) on the"
            " branch, or close the PR"
        )


def _indexed_files(index: dict[str, dict[str, dict[str, str]]] | None) -> set[str]:
    """The channel .md paths one parsed announce index names."""
    return {entry["file"] for urls in (index or {}).values() for entry in urls.values()}


def _branch_index_files(runner: pr.PrRunner, repo_root: Path, branch: str) -> set[str] | None:
    """The channel .md paths one branch's own regular announce index names.

    None when the branch's tree carries no index, or carries one as a symlink
    or other non-file: its own pre-flight refuses that, and no entry lands.
    """
    listing = runner.run(
        ["git", "ls-tree", f"origin/{branch}", "--", ANNOUNCE_INDEX], cwd=repo_root
    ).strip()
    if not listing or listing.split(" ", 1)[0] not in _REGULAR_FILE_MODES:
        return None
    return _indexed_files(
        _announce_index(runner, repo_root, f"origin/{branch}", f"branch {branch}")
    )


def _burst_index_in_effect(
    runner: pr.PrRunner,
    repo_root: Path,
    branches: list[str],
    skip: str,
    head_indexed: set[str],
) -> tuple[set[str], set[str]]:
    """The channel files the announce checks hold against ``skip``'s merge.

    a branch carrying no index skips the announce step, so its channel edits,
    additions and deletions land as git merged them: an edited file's sha no
    longer matches its entry, an added one sits outside it, a deleted one
    strands it. the index in effect at that merge is HEAD's and the one the
    last index-carrying sibling merging before ``skip`` lands; the edit and
    addition refusal reads both names whatever merges after, since an
    index-carrying sibling merging first rewrote an edited file and the
    branch's own merge conflicts on it then.

    the deletion check drops the prior sibling's names while an
    index-carrying sibling merges after ``skip``: that sibling's announce step
    rewrites every file its own index names and prunes the rest, so its merge
    resolves a file the deletion removes. HEAD's names stay.
    """
    position = branches.index(skip)
    prior: set[str] = set()
    for index, branch in enumerate(branches):
        if branch == skip or _is_ancestor(runner, repo_root, f"origin/{branch}", "HEAD"):
            continue
        carried = _branch_index_files(runner, repo_root, branch)
        if carried is None:
            continue
        if index > position:
            return set(head_indexed) | prior, set(head_indexed)
        prior = carried
    in_effect = set(head_indexed) | prior
    return in_effect, in_effect


def _branch_file_modes(runner: pr.PrRunner, repo_root: Path, branch: str) -> dict[str, str]:
    """The git tree mode of every pipeline path the branch's tree carries."""
    listing = runner.run(
        ["git", "ls-tree", "-r", "-z", f"origin/{branch}", "--", *_PIPELINE_PATHSPECS],
        cwd=repo_root,
    )
    modes: dict[str, str] = {}
    for record in listing.split("\0"):
        if record:
            meta, _, path = record.partition("\t")
            modes[path] = meta.split(" ", 1)[0]
    return modes


def _refuse_non_regular(branch: str, paths: set[str], modes: dict[str, str]) -> None:
    """Refuse a branch carrying any of ``paths`` as a symlink, submodule or other non-file.

    every pipeline path is read or staged by the merge from the branch side,
    and `git show` hands a symlink's target or a gitlink's commit to it as if
    they were the file's bytes. a path the branch deleted carries no mode.
    """
    offending = sorted(
        f"{path} ({_NON_REGULAR_KINDS.get(modes[path], f'mode {modes[path]}')})"
        for path in paths
        if path in modes and modes[path] not in _REGULAR_FILE_MODES
    )
    if offending:
        raise AutoMergeError(
            f"branch {branch}: carries {offending} as non-regular files; the merge reads"
            " or stages each from the branch side as a file's bytes; fix: commit each as"
            " a regular file on the branch, or close the PR"
        )


def _check_branch_catalogs(
    runner: pr.PrRunner, repo_root: Path, branch: str, paths: set[str]
) -> None:
    """Parse every catalog copy the merge will parse for this branch, before any merge.

    the merge unions a catalog file only when the branch's diff names it, and
    then reads the branch's copy beside HEAD's (models.json also beside the
    merge base's); an emptied or malformed copy is a change, not a deletion,
    so the deletion check passes it and only this parse stops it.
    """
    if models.MODELS_FILE in paths:
        _parse_models(
            _branch_text(runner, repo_root, branch, models.MODELS_FILE),
            f"branch {branch}",
            _FIX_BRANCH_COPY,
        )
        base_text = _merge_base_text(runner, repo_root, branch, models.MODELS_FILE)
        if base_text:
            _parse_models(base_text, f"branch {branch}'s merge base", _FIX_MERGE_BASE_COPY)
    if BILLING_RULES_FILE in paths:
        branch_text = _branch_text(runner, repo_root, branch, BILLING_RULES_FILE)
        _parse_billing_rules(branch_text, f"branch {branch}", _FIX_BRANCH_COPY)
        head_text = _head_text(runner, repo_root, BILLING_RULES_FILE)
        if head_text:
            _check_landed_rules(
                _parse_billing_rules(head_text, "HEAD", _FIX_HEAD_COPY), "HEAD", _FIX_HEAD_COPY
            )
        # the rules the merge lands, never the branch's raw list: the union
        # drops a duplicate id and a stale copy of a rule HEAD holds
        _check_landed_rules(
            json.loads(_union_billing_rules(head_text, branch_text, branch))["rules"],
            f"branch {branch}",
            _FIX_BRANCH_COPY,
        )


def _check_landed_rules(rules: list[Any], label: str, fix: str) -> None:
    """Refuse rules the committed loader refuses, by the loader's own rule check.

    announce.load_billing_rules runs this check on the default branch's file,
    so a rule it refuses would land a file the loader cannot read. The check
    labels each schema error itself; an input it does not type-check first
    (a non-string date or timezone, a timezone that is no zone key) raises
    the stdlib's own error unlabeled, so the label is added there.
    """
    file_label = f"{label}: {BILLING_RULES_FILE}"
    try:
        check_billing_rules(rules, file_label)
    except (TypeError, ValueError) as exc:
        message = str(exc)
        if not message.startswith(f"{file_label}: "):
            message = f"{file_label}: {message}"
        raise AutoMergeError(f"{message}; fix: {fix}") from exc


def _is_ancestor(runner: pr.PrRunner, repo_root: Path, a: str, b: str) -> bool:
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", a, b],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode not in (0, 1):
        raise AutoMergeError(f"git merge-base --is-ancestor {a[:7]} {b[:7]} failed: {proc.stderr}")
    return proc.returncode == 0


def _check_checkout(repo_root: Path, runner: pr.PrRunner, base: str) -> None:
    """Refuse a merge run from a checkout that is not at or ahead of the base tip.

    Every pricelog branch is a descendant of the base, so a merge started
    from one pushes as a fast-forward: the branch's own unverified commits
    ride into the default branch's history. The sanctioned states are a
    checkout at the remote base tip (a detached CI checkout included) and a
    local ``--no-push`` run that has advanced past it. A checkout BEHIND the
    tip merges over rows that already landed upstream (the push rejects
    non-fast-forward afterwards, observed 2026-09-18 and 2026-09-22), so it
    is refused by name rather than by a failed push.
    """
    try:
        base_tip = runner.run(
            ["git", "rev-parse", "--verify", "--quiet", f"origin/{base}"], cwd=repo_root
        ).strip()
    except pr.PrError:
        # no origin ref to compare against: the push would fail loudly anyway
        return
    head = runner.run(["git", "rev-parse", "HEAD"], cwd=repo_root).strip()
    if head == base_tip:
        return
    branch = runner.run(["git", "branch", "--show-current"], cwd=repo_root).strip()
    if branch != base:
        raise AutoMergeError(
            f"checkout is on {branch or head[:7]}, not {base};"
            " run the merge from the default branch"
        )
    if _is_ancestor(runner, repo_root, base_tip, head):
        # the one sanctioned lag-free deviation: a local --no-push run that
        # has advanced the base past its remote tip
        return
    state = "behind" if _is_ancestor(runner, repo_root, head, base_tip) else "diverged from"
    raise AutoMergeError(
        f"the checkout is {state} {base}'s remote tip {base_tip[:7]}: merging here would"
        " drop the rows that landed upstream; fix: git pull and re-run"
    )


def merge_branches(
    branches: list[str],
    repo_root: Path,
    runner: pr.PrRunner,
    base: str,
    push: bool = True,
    human: bool = False,
    held_channels: frozenset[tuple[str, str]] = frozenset(),
) -> tuple[str, list[MergeResult]]:
    """Union-merge each branch onto HEAD, then push and delete the refs.

    `branches` is the merge order: oldest PR first, newest last (each announce
    channel lands from the burst entry with the newest fetched date, and each
    absence file a branch changed lands unless HEAD's copy comes from a newer
    run, so a held older-run branch never reverts newer counters). every
    branch pre-flights the branch-side files the merge reads, its appended
    rows, the churn bounds (waived with a logged count under `human`), the
    landed catalog's entry and stored-key checks and the catalog-claim check
    (none of the three ever waived) before the first git merge. a branch
    whose tip HEAD already holds (the state a failed branch-ref cleanup
    strands: the merge landed, the PR stayed open) is dropped with a skip line,
    its remote ref deleted under push once its rows are provably on
    origin/<base> — that deletion closes the PR — and an all-dropped burst
    returns (HEAD, []) with nothing merged or pushed.
    any other failure leaves the surviving branches' refs in place and raises;
    nothing is pushed.
    """
    if not branches:
        raise AutoMergeError("no branches given; nothing to merge")
    # refs first: every check below and the merges themselves read origin/*
    # refs, and the checkout fetched at job start minutes ago (a local clone
    # can be arbitrarily stale) — a branch a sibling run or a human pushed
    # since then is invisible to them (observed 2026-09-22: the merge died
    # `unknown revision` on a concurrent run's ref). the base rides along so
    # _check_checkout reads the true tip
    _retry_read(runner, repo_root, ["git", "fetch", "origin", base, *branches])
    # checkout-state refusals report the real cause of a stopped rerun, so they
    # come before every branch-side read, the staged leftover first of all: a
    # run that raised after `git merge --no-commit` leaves MERGE_HEAD and
    # staged files behind, and the `git pull` a behind checkout's refusal asks
    # for fails while that merge is unconcluded
    uncommitted = _uncommitted(runner, repo_root)
    if uncommitted:
        raise AutoMergeError(
            "the merge needs the pipeline files committed and nothing staged: "
            + "; ".join(uncommitted)
        )
    # then the checkout: a branch of a checkout behind origin/<base> may have
    # landed upstream, and every branch-side read below answers for that
    # landed state, so the checkout is the real cause to report
    _check_checkout(repo_root, runner, base)
    _check_branches(branches, repo_root, runner)
    # a branch whose tip HEAD already holds (the state a failed branch-ref
    # cleanup strands: the merge landed, the PR stayed open) drops out here:
    # git merge would answer "Already up to date." and red the run. under
    # push the skip deletes the ref — that deletion is what closes the
    # stranded PR — and a failed deletion warns for the next run to retry.
    # the deletion needs the branch landed on origin/<base>, never HEAD
    # alone: a checkout ahead of origin/<base> (the sanctioned --no-push
    # rerun state) holds rows upstream has never seen, so deleting there
    # would close a PR whose rows never landed (measured 2026-11-06); that
    # ref is kept by name for a pushing run
    kept: list[str] = []
    for branch in branches:
        if _is_ancestor(runner, repo_root, f"origin/{branch}", "HEAD"):
            print(f"skipping {branch}: already merged into HEAD")
            if push and _is_ancestor(runner, repo_root, f"origin/{branch}", f"origin/{base}"):
                _delete_remote_branch(runner, repo_root, branch)
            elif push:
                print(
                    f"keeping {branch}: its rows are not on origin/{base} yet;"
                    " the ref stays until a pushing run lands them"
                )
            continue
        kept.append(branch)
    if not kept:
        return runner.run(["git", "rev-parse", "HEAD"], cwd=repo_root).strip(), []
    branches = kept
    # the runner checkout carries no git identity; the merge commits need one
    pr.ensure_author(repo_root, runner)
    _check_appended_rows(runner, repo_root, branches, validate.load_schema_keys(repo_root))
    head_keys = _head_store_keys(runner, repo_root)
    churn = {branch: _branch_churn(runner, repo_root, branch, head_keys) for branch in branches}
    if human:
        for branch, (appended, created, removed) in churn.items():
            if (
                created > MAX_CREATED_MODELS
                or removed > MAX_REMOVED_MODELS
                or appended > MAX_APPENDED_ROWS
            ):
                print(
                    f"waived churn bounds for {branch}: creates {created} model(s) (bound"
                    f" {MAX_CREATED_MODELS}), removes {removed} (bound {MAX_REMOVED_MODELS}),"
                    f" appends {appended} row(s) (bound {MAX_APPENDED_ROWS})"
                )
    else:
        _check_churn(churn)
    _check_carried_claims(
        runner,
        repo_root,
        branches,
        _catalog_claims(
            _burst_catalog(runner, repo_root, branches, head_keys), "HEAD", _FIX_HEAD_COPY
        ),
    )

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
            head_lines = store.shard_lines(_head_text(runner, repo_root, shard_path))
            branch_text = _branch_text(runner, repo_root, branch, shard_path)
            new_lines = _appended_lines(head_lines, store.shard_lines(branch_text))
            appended += len(new_lines)
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
                _branch_union(
                    runner, repo_root, branch, _head_text(runner, repo_root, models.MODELS_FILE)
                ),
                encoding="utf-8",
            )
        if BILLING_RULES_FILE in changed:
            # the pass appends the same confirmed rule to every branch it
            # judges, so git merge add/add-conflicts the identical append and
            # staging the conflicted file would stage markers; both files
            # resolve by union, the pin recomputed from the landed count
            rules_text = _union_billing_rules(
                _head_text(runner, repo_root, BILLING_RULES_FILE),
                _branch_text(runner, repo_root, branch, BILLING_RULES_FILE),
                branch,
            )
            (repo_root / BILLING_RULES_FILE).write_text(rules_text, encoding="utf-8")
            head_pin = _head_text(runner, repo_root, "tests/test_billing_rules.py")
            count = len(json.loads(rules_text)["rules"])
            (repo_root / "tests" / "test_billing_rules.py").write_text(
                _BILLING_PIN_RE.sub(f"assert len(rules) == {count}", head_pin),
                encoding="utf-8",
            )

        # the announce tree resolves per channel: the burst entry with the
        # newest fetched date wins, a same-date tie goes to the newest
        # branch, and the base wins every tie — so a stale branch (a failed
        # fetch, or one cut before a later landed refresh) never reverts a
        # channel. a branch carrying no index.json at all skips the announce
        # step: its tree cannot name a url set
        branch_index = _announce_index(runner, repo_root, f"origin/{branch}", f"branch {branch}")
        if branch_index is not None:
            burst.append((f"origin/{branch}", branch_index))
            _merge_announce(runner, repo_root, branch, base_sha, base_index, burst, held_channels)
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
        # the pass's hand-edit commits can carry their whole message as one
        # line with literal \n\n escapes (a double-escaped -m); forwarded
        # verbatim, the merge commit aborts as empty (measured 2026-09-20,
        # PR 261). keep the true subject only.
        subject = (
            runner.run(["git", "log", "--format=%s", "-1", f"origin/{branch}"], cwd=repo_root)
            .split("\\n", 1)[0]
            .strip()
        )
        if not subject:
            subject = f"chore(data): merge {branch}"
        runner.run(
            ["git", "commit", "-m", subject or f"merge: {branch}"],
            cwd=repo_root,
        )
        commit = runner.run(["git", "rev-parse", "HEAD"], cwd=repo_root).strip()
        results.append(MergeResult(branch, commit, appended))

    # the pushed head carries the refreshed README stats: the burst appended
    # rows, so the committed stats are stale by construction and ci on the
    # raw merge commit reds the stats recompute test (observed 2026-09-11,
    # 39c8ee4 -> 6be85a9, and again 2026-09-20). the refresh rides the final
    # merge commit as an amend, so the push stays exactly one merge commit
    # per branch. publish's refresh step remains the safety net for pushes
    # that bypass the merge.
    # a KeyError from stats.compute is left unwrapped on purpose: a row
    # missing its source/model_id/observed_at reds the ci recompute test on
    # the default branch long before any merge reaches here, and the
    # traceback names the missing key better than a README-fix message would
    try:
        publish.refresh_committed(store.load_shards(repo_root / SHARD_DIR), repo_root)
    except (OSError, ValueError) as exc:
        raise AutoMergeError(
            f"refreshing the README stats failed: {exc};"
            " fix: the named input above (the README stats blocks, the store rows,"
            " or the models file), then re-run"
        ) from exc
    if runner.run(["git", "status", "--porcelain", "--", "README.md"], cwd=repo_root).strip():
        runner.run(["git", "add", "--", "README.md"], cwd=repo_root)
        runner.run(["git", "commit", "--amend", "--no-edit"], cwd=repo_root)
        head = runner.run(["git", "rev-parse", "HEAD"], cwd=repo_root).strip()
        results[-1] = MergeResult(results[-1].branch, head, results[-1].appended)

    leftover = _uncommitted(runner, repo_root)
    if leftover:
        raise AutoMergeError(
            "the merged pipeline files are not clean; nothing was pushed: " + "; ".join(leftover)
        )
    for branch in branches:
        # every merged branch head must be an ancestor of the push target:
        # the pushed history must contain each PR's tip, which the branch-ref
        # deletion below closes the PR against
        try:
            runner.run(
                ["git", "merge-base", "--is-ancestor", f"origin/{branch}", "HEAD"],
                cwd=repo_root,
            )
        except pr.PrError:
            raise AutoMergeError(
                f"branch {branch}: its head is not an ancestor of the merge result;"
                " refusing the push, its ref deletion would close the PR with"
                " nothing landed"
            ) from None
    sha = runner.run(["git", "rev-parse", "HEAD"], cwd=repo_root).strip()
    if not push:
        return sha, results

    runner.run(["git", "push", "origin", f"HEAD:refs/heads/{base}"], cwd=repo_root)
    for result in results:
        _delete_remote_branch(runner, repo_root, result.branch)
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
    parser.add_argument(
        "--human",
        action="store_true",
        help="merge under human review: waive the churn bounds and log the waived counts",
    )
    args = parser.parse_args()
    repo_root = Path.cwd()
    runner = pr.PrRunner()
    try:
        base = args.base or pr.default_branch(runner, repo_root)
        sha, results = merge_branches(
            args.branches, repo_root, runner, base, push=not args.no_push, human=args.human
        )
    except (AutoMergeError, pr.PrError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for result in results:
        print(f"merged {result.branch} ({result.appended} rows) as {result.commit[:7]}")
    if not results:
        print(f"every branch already merged into {base}; nothing to push")
    elif args.no_push:
        print(f"landed {sha[:7]} locally, nothing pushed")
    else:
        print(f"pushed {sha[:7]} to {base}, branch refs deleted")
    return 0

"""Merge the PRs the claude pass marked `automerge: yes`.

the pass posts one machine-readable disposition per PR comment (the marker
line `automerge: yes <sha>` / `automerge: no <sha>`, the last line of the
body, the sha naming the head the pass judged) and never merges. the
workflow's merge step runs this script after the pass: it reads every open
`pricelog/` PR's comments for the pass's marker and hands the eligible
branches to ai-pricelog-automerge in PR-number order (the merge order). a
verdict binds only to the head it stamps, so a branch pushed after the
verdict is never merged: the merge step skips it by name and the queue
lists it for a fresh pass. main() folds the raw dispositions through
`_bound_dispositions` once, so a stale verdict reads as unjudged for every
consumer — the queue, the merge, the announce hold and the settle question
— and only the stale-yes skip diagnostic sees the raw pair. a pass killed
after posting its verdicts
(observed 2026-09-11, run 34592012203: verdict comment 11:24, timeout kill
11:35, automerge never ran, the run green) stranded its verified PRs, and a
failed merge step strands them too (observed 2026-09-18: the 11:00 run's
merge push rejected `fetch first`, its 8 yes-marked PRs merged by hand) —
reading dispositions of every open pricelog PR, whatever run posted them,
lets a later run's merge step pick the stranded ones up. the workflow's
list step also runs this script with `--awaiting-review` to print the
pricelog PRs the claude pass must judge — the unjudged ones, a verdict
whose stamped sha no longer names the branch's head (the new head is
unjudged), plus a no-marked PR whose every carried announce channel is
settled: the base already holds it, or its newest carrier's verdict is a
bound yes (a verdict's recency is the comment's edit time, `updated_at or
created_at`) — oldest first. the pure halves are network-free; main() owns
the network, health.py's shape.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TextIO

from ai_pricelog import announce, automerge, health, pr

# the marker the pass ends every PR comment with: one whole line, the
# verdict optionally stamped with the head sha it judged (7..64 lowercase
# hex, the git oid spelling)
_DISPOSITION_LINE = re.compile(r"automerge: (yes|no)(?: ([0-9a-f]{7,64}))?")


def parse_disposition(comments: Iterable[tuple[str, str]], bot_login: str) -> bool | None:
    """The last bot comment carrying a marker line decides; None = no marker."""
    return _last_marker(((author, body, "") for author, body in comments), bot_login)[0]


def parse_disposition_at(
    comments: Iterable[tuple[str, str, str]], bot_login: str
) -> tuple[bool | None, str | None, str | None]:
    """The last bot marker's verdict, its stamped head sha, and its comment's edit time.

    The sha is None on a marker posted without one — a verdict bound to no
    head, never merged. The edit time is `updated_at or created_at`: github
    never moves `created_at` on an edit, and the pass edits its existing
    verdict comment on a re-queued PR.
    """
    return _last_marker(comments, bot_login)


def _last_marker(
    comments: Iterable[tuple[str, str, str]], bot_login: str
) -> tuple[bool | None, str | None, str | None]:
    disposition: bool | None = None
    stamped: str | None = None
    at: str | None = None
    for author, body, edited_at in comments:
        if author != bot_login:
            continue
        marker = _marker_line(body)
        if marker is not None:
            disposition, stamped = marker
            at = edited_at or None
    return disposition, stamped, at


def _marker_line(body: str) -> tuple[bool | None, str | None] | None:
    marker: tuple[bool | None, str | None] | None = None
    for line in body.splitlines():
        match = _DISPOSITION_LINE.fullmatch(line.strip())
        if match is not None:
            marker = (match.group(1) == "yes", match.group(2))
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
        out = automerge._retry_read(runner, repo_root, ["git", "ls-remote", "origin", head]).strip()
        (present if out else gone).append(head)
    return present, gone


def _bound(binding: tuple[str, str | None] | None) -> bool:
    """The verdict's stamp names the PR's current head; missing info never binds."""
    if binding is None:
        return False
    head_oid, stamped = binding
    return bool(head_oid) and stamped is not None and stamped == head_oid


def _bound_dispositions(
    dispositions: Mapping[int, bool | None], binding: Mapping[int, tuple[str, str | None]]
) -> dict[int, bool | None]:
    """The verdicts bound to their PR's current head; everything else reads None.

    A verdict whose stamp does not name the current head — a sha-less marker
    included — judged an earlier head, so the new head is unjudged: the
    verdict reads None wherever the queue, the merge, the hold or the settle
    question consumes it. main() builds the map once and every consumer
    takes it; only the stale-yes skip diagnostic reads the raw pair.
    """
    return {
        number: disposition if _bound(binding.get(number)) else None
        for number, disposition in dispositions.items()
    }


def eligible_branches(
    open_prs: Iterable[tuple[int, str]],
    dispositions: Mapping[int, bool | None],
) -> list[str]:
    """The merge order: open pricelog PRs the pass marked bound yes, oldest first.

    `dispositions` is the bound map (`_bound_dispositions`): a verdict whose
    stamp does not name its PR's current head already reads None here. a PR
    is eligible when its head ref is a `pricelog/` branch that is not the
    seed and its disposition is True — which run posted the marker is
    irrelevant, so a yes-marked PR a failed merge step stranded still merges
    on a later run's merge step while its head stays put. no comment, no
    marker, `automerge: no`, or an unbound yes all leave it out: the
    conservative default is to never merge.
    """
    eligible = sorted(
        (number, head_ref)
        for number, head_ref in open_prs
        if _pricelog_head(head_ref) and dispositions.get(number) is True
    )
    return [head_ref for _number, head_ref in eligible]


def _stale_yeses(
    open_prs: Iterable[tuple[int, str]],
    dispositions: Mapping[int, bool | None],
    binding: Mapping[int, tuple[str, str | None]],
) -> list[tuple[str, str | None, str]]:
    """Pricelog yes-marked heads whose stamp does not name the current head."""
    stale: list[tuple[str, str | None, str]] = []
    for number, head_ref in open_prs:
        if not (_pricelog_head(head_ref) and dispositions.get(number) is True):
            continue
        head_oid, stamped = binding.get(number, ("", None))
        if not _bound((head_oid, stamped)):
            stale.append((head_ref, stamped, head_oid))
    return stale


def awaiting_review(
    open_prs: Iterable[tuple[int, str]],
    dispositions: Mapping[int, bool | None],
    limit: int,
    requeue: frozenset[int] = frozenset(),
) -> list[tuple[int, str]]:
    """The pricelog PRs the pass must judge, oldest first, capped at `limit`.

    `dispositions` is the bound map (`_bound_dispositions`): a verdict whose
    stamp no longer names its PR's current head (a sha-less marker included)
    already reads None — the head judged no longer exists, so the new head is
    unjudged. a PR queues when its head is a `pricelog/` branch that is not
    the seed and its disposition is None — no marker at all, only bot
    comments the pass never finished, or an unbound verdict — or its number
    sits in `requeue`: a no-marked PR whose every carried announce channel is
    settled, the base holding it or a newest carrier's verdict being a bound
    yes. a bound yes and a bound no outside `requeue` stay out: the merge
    step owns the one, a human the other.
    """
    queued = sorted(
        (number, head_ref)
        for number, head_ref in open_prs
        if _pricelog_head(head_ref) and (dispositions.get(number) is None or number in requeue)
    )
    return queued[:limit]


def _open_prs(runner: pr.PrRunner, repo_root: Path) -> list[tuple[int, str, str]]:
    """(number, head ref, head oid) for every open PR, one gh call.

    the limit is the stranded-pickup completeness bound: an open PR beyond
    it is never re-read.
    """
    out = runner.run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--limit",
            "1000",
            "--json",
            "number,headRefName,headRefOid",
        ],
        cwd=repo_root,
    )
    try:
        entries = json.loads(out)
    except json.JSONDecodeError as exc:
        raise pr.PrError(f"gh pr list returned invalid json: {exc.msg}") from exc
    if not isinstance(entries, list):
        raise pr.PrError("gh pr list returned a non-list json value")
    open_prs: list[tuple[int, str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("number"), int):
            continue
        open_prs.append(
            (
                entry["number"],
                str(entry.get("headRefName") or ""),
                str(entry.get("headRefOid") or ""),
            )
        )
    return open_prs


def _pr_comments(runner: pr.PrRunner, repo_root: Path, number: int) -> list[tuple[str, str, str]]:
    """(author, body, edit time) triples for one PR's comments, oldest first.

    The REST issue-comments endpoint carries every comment, where
    `gh pr view --json comments` exposes only `createdAt`. The recency stamp
    is the comment's edit time (`updated_at or created_at`), because github
    never moves `created_at` on an edit and the pass edits its existing
    verdict comment on a re-queued PR. `--paginate --slurp` reads every page:
    the endpoint returns comments created-ascending, so a first page alone
    carries the OLDEST hundred and drops the verdict, leaving the PR unjudged
    forever.
    """
    out = runner.run(
        [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            f"repos/{{owner}}/{{repo}}/issues/{number}/comments?per_page=100",
        ],
        cwd=repo_root,
    )
    try:
        pages = json.loads(out)
    except json.JSONDecodeError as exc:
        raise pr.PrError(
            f"gh api issues/{number}/comments returned invalid json: {exc.msg}"
        ) from exc
    if not isinstance(pages, list) or not all(isinstance(page, list) for page in pages):
        raise pr.PrError(f"gh api issues/{number}/comments returned a non-list page value")
    comments = [entry for page in pages for entry in page if isinstance(entry, dict)]
    triples: list[tuple[str, str, str]] = []
    for entry in sorted(
        comments,
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
    ):
        user = entry.get("user") or {}
        triples.append(
            (
                str(user.get("login") or ""),
                str(entry.get("body") or ""),
                str(entry.get("updated_at") or entry.get("created_at") or ""),
            )
        )
    return triples


def _listing(
    runner: pr.PrRunner, repo_root: Path, diag: TextIO
) -> tuple[
    list[tuple[int, str]],
    dict[int, bool | None],
    dict[int, str],
    dict[int, tuple[str, str | None]],
    list[str],
]:
    """Open pricelog PRs whose refs still resolve, plus their dispositions and head binding.

    The listing both mains share: the open list, the deleted-ref skip, the
    bot login and the per-PR comment reads. returns (candidates,
    dispositions, marker_times, binding, gone), candidates in gh list order;
    the maps are empty when no live pricelog PR remains. marker_times holds
    the last bot marker comment's edit time (`updated_at or created_at`)
    per judged PR, the pass's recency, and binding each candidate's pair of
    current head oid and stamped head sha — what the merge step compares to
    the verdict. `diag` receives the skipped-ref lines, so the queue mode
    keeps stdout a machine list.
    """
    open_prs = _open_prs(runner, repo_root)
    heads = {number: head_oid for number, _head_ref, head_oid in open_prs}
    candidates = [
        (number, head_ref) for number, head_ref, _head_oid in open_prs if _pricelog_head(head_ref)
    ]
    if not candidates:
        return [], {}, {}, {}, []
    present, gone = _present_refs(runner, repo_root, [head for _number, head in candidates])
    for head in gone:
        print(f"skipping {head}: branch ref deleted, PR mid-close", file=diag)
    candidates = [c for c in candidates if c[1] in present]
    if not candidates:
        return [], {}, {}, {}, gone
    bot_login = runner.run(["gh", "api", "user", "--jq", ".login"], cwd=repo_root).strip()
    readings = {
        number: parse_disposition_at(_pr_comments(runner, repo_root, number), bot_login)
        for number, _head_ref in candidates
    }
    dispositions = {
        number: disposition for number, (disposition, _stamped, _at) in readings.items()
    }
    marker_times = {
        number: at for number, (_disposition, _stamped, at) in readings.items() if at is not None
    }
    binding = {
        number: (heads[number], stamped)
        for number, (_disposition, stamped, _at) in readings.items()
    }
    return candidates, dispositions, marker_times, binding, gone


def _index_readings(
    runner: pr.PrRunner,
    repo_root: Path,
    candidates: list[tuple[int, str]],
) -> tuple[
    dict[str, dict[str, dict[str, str]]],
    dict[int, dict[str, dict[str, dict[str, str]]]],
    frozenset[int],
]:
    """(base index, per-PR branch index, the numbers whose branch index was unread).

    One index read per candidate, shared by the merge's carrier question and
    the requeue question, so a settled-no read never re-runs `git show` per
    branch. A branch whose index cannot be read or does not exist is unread —
    never carrying nothing, which would settle it vacuously.
    """
    try:
        base_index = automerge._announce_index(runner, repo_root, "HEAD", "base") or {}
    except automerge.AutoMergeError:
        base_index = {}
    indexes: dict[int, dict[str, dict[str, dict[str, str]]]] = {}
    unread: set[int] = set()
    for number, head_ref in candidates:
        try:
            branch_index = automerge._announce_index(
                runner, repo_root, f"origin/{head_ref}", f"branch {head_ref}"
            )
        except automerge.AutoMergeError:
            unread.add(number)
            continue
        if branch_index is None:
            unread.add(number)
            continue
        indexes[number] = branch_index
    return base_index, indexes, frozenset(unread)


def _carriers(
    base_index: dict[str, dict[str, dict[str, str]]],
    indexes: dict[int, dict[str, dict[str, dict[str, str]]]],
) -> dict[tuple[str, str], set[int]]:
    """channel -> the PR numbers carrying it, the merge's own win rule.

    A channel is carried the way the merge itself decides a branch wins it:
    the base lacks the channel, or the branch's entry carries a different sha
    and a newer `fetched` instant. A same-sha entry is a no-op at the merge,
    and a stale copy (an older `fetched`, or a same-instant tie the base wins)
    never reverts the base's channel, so neither carries anything.
    """
    carriers: dict[tuple[str, str], set[int]] = {}
    for number, branch_index in indexes.items():
        for source, urls in branch_index.items():
            for url, entry in urls.items():
                base_entry = base_index.get(source, {}).get(url)
                if base_entry is None or (
                    entry["sha256"] != base_entry["sha256"]
                    and entry["fetched"] > base_entry["fetched"]
                ):
                    carriers.setdefault((source, url), set()).add(number)
    return carriers


def _channel_carriers(
    runner: pr.PrRunner,
    repo_root: Path,
    candidates: list[tuple[int, str]],
) -> tuple[dict[tuple[str, str], set[int]], frozenset[int]]:
    """(channel -> the PR numbers carrying it, the numbers whose index was unread).

    The carriers follow the merge's own win rule (`_carriers`). Every open
    pricelog candidate is read, yes-marked ones included: a ruling on the same
    snapshot can arrive on a PR other than the one that first carried it, so
    the carrier set must name all of them. A branch whose index cannot be read
    or does not exist is returned as unread — never as carrying nothing, which
    would settle it vacuously.
    """
    base_index, indexes, unread = _index_readings(runner, repo_root, candidates)
    return _carriers(base_index, indexes), unread


def _newest_carrier(numbers: set[int], marker_times: Mapping[int, str] | None) -> int:
    """The carrier whose pass marker is newest; an unjudged one ranks below any time.

    With no marker_times the highest PR number wins. A carrier with no marker
    time ranks below every carrier that has one, and equal (or empty) times
    fall back to the PR number, so the ranking stays total.
    """

    def rank(number: int) -> tuple[bool, str, int]:
        at = (marker_times or {}).get(number) or ""
        return (bool(at), at, number)

    return max(numbers, key=rank)


def _held_channels(
    runner: pr.PrRunner,
    repo_root: Path,
    candidates: list[tuple[int, str]],
    dispositions: Mapping[int, bool | None],
    marker_times: Mapping[int, str] | None = None,
) -> frozenset[tuple[str, str]]:
    """(source, url) channels whose newest carrier's verdict is not a bound yes.

    `dispositions` is the bound map (`_bound_dispositions`): a yes whose
    stamp no longer names the branch's head reads None here, so the stale
    verdict releases nothing. The newest pass settles the ruling: a
    channel's carriers are the open pricelog PRs the merge would let win it
    (the base lacks it, or their snapshot is newer than the base's), and the
    carrier whose marker comment is newest decides — the PR number only when
    `marker_times` is not given. A bound-yes-marked carrier releases the
    channel (the ruling landed, so the base's copy moves with the merge); a
    no-marked or unjudged one keeps the channel held at the base copy, so the
    owed ruling is not dropped by a sibling merge landing the same snapshot.
    Holding the whole carried set keeps channels a PR never flagged
    conservative too, and self-heals at the newest carrier's verdict. When
    every candidate is bound-yes-marked no channel can be held, so the
    indexes are not read at all.
    """
    if not any(dispositions.get(number) is not True for number, _head_ref in candidates):
        return frozenset()
    carriers, _unread = _channel_carriers(runner, repo_root, candidates)
    return frozenset(
        channel
        for channel, numbers in carriers.items()
        if dispositions.get(_newest_carrier(numbers, marker_times)) is not True
    )


def _settled_no_heads(
    runner: pr.PrRunner,
    repo_root: Path,
    candidates: list[tuple[int, str]],
    dispositions: Mapping[int, bool | None],
    marker_times: Mapping[int, str] | None = None,
) -> frozenset[int]:
    """No-marked PR numbers whose every carried channel is settled.

    `dispositions` is the bound map (`_bound_dispositions`): only a bound no
    settles, a stale verdict reads None and settles nothing. Carried means
    the branch's own commit range changed the announce file, never what it
    would win now (a sibling merge can already hold the branch's snapshot,
    and that must still settle the no). Each carried channel settles when
    the base already holds it — the same sha, or a same-or-newer fetched
    instant, the merge keeps the base on a tie — or when the newest carrier
    of the channel, ranked by marker time, is bound-yes-marked: that ruling
    landed. A PR whose branch index or diff could not be read is never
    settled (what it carries is unknown), and neither is one carrying no
    channel: its no is not an announce ruling, so re-queueing it would churn
    the slots a human's PR needs.
    """
    base_index, indexes, unread = _index_readings(runner, repo_root, candidates)
    carriers = _carriers(base_index, indexes)
    settled: set[int] = set()
    for number, head_ref in candidates:
        if dispositions.get(number) is not False or number in unread:
            continue
        try:
            carried = _carried_channels(runner, repo_root, head_ref, indexes[number])
        except pr.PrError:
            continue
        if not carried:
            continue
        if all(
            _channel_settled(
                channel, indexes[number], base_index, carriers, dispositions, marker_times
            )
            for channel in carried
        ):
            settled.add(number)
    return frozenset(settled)


def _carried_channels(
    runner: pr.PrRunner,
    repo_root: Path,
    head_ref: str,
    branch_index: dict[str, dict[str, dict[str, str]]],
) -> frozenset[tuple[str, str]]:
    """The (source, url) channels the branch's own commit range changed.

    `_carriers` answers the merge's question — which channels the branch would
    win NOW — so a no PR whose snapshot a sibling already merged reads as
    carrying nothing and never re-queues. The requeue question reads the
    branch's own diff over the announce tree instead, each changed file mapped
    back to its (source, url) through the branch index's own derivation; a
    deleted channel's file names no index entry, so it carries nothing.
    """
    changed = set(
        runner.run(
            [
                "git",
                "diff",
                "--name-only",
                f"HEAD...origin/{head_ref}",
                "--",
                f"{announce.ANNOUNCE_DIR}/",
            ],
            cwd=repo_root,
        ).splitlines()
    )
    carried: set[tuple[str, str]] = set()
    for source, urls in branch_index.items():
        derived = announce.channel_files(source, urls.keys())
        for url in urls:
            if derived[url] in changed:
                carried.add((source, url))
    return frozenset(carried)


def _channel_settled(
    channel: tuple[str, str],
    branch_index: dict[str, dict[str, dict[str, str]]],
    base_index: dict[str, dict[str, dict[str, str]]],
    carriers: dict[tuple[str, str], set[int]],
    dispositions: Mapping[int, bool | None],
    marker_times: Mapping[int, str] | None,
) -> bool:
    """Whether one carried channel's owed ruling is settled.

    `dispositions` is the bound map (`_bound_dispositions`): a stale yes
    settles nothing. Settled when the base already holds it — its entry
    exists and carries the same sha or a same-or-newer fetched instant, so
    the branch's copy lands nothing — or when the newest carrier of the
    channel is bound-yes-marked.
    """
    source, url = channel
    entry = branch_index[source][url]
    base_entry = base_index.get(source, {}).get(url)
    if base_entry is not None and (
        entry["sha256"] == base_entry["sha256"] or base_entry["fetched"] >= entry["fetched"]
    ):
        return True
    return dispositions.get(_newest_carrier(carriers.get(channel, set()), marker_times)) is True


def _fetch_pricelog_refs(runner: pr.PrRunner, repo_root: Path) -> None:
    """One best-effort refresh of the pricelog branch refs before the settle read.

    The queue mode reads each branch's index at `origin/<head>`, and the
    workflow's checkout predates a sibling run's push. The fetch is a single
    attempt, never the merge's retry-with-sleeps read: a failure warns to
    stderr and never reds or delays the listing. The refs stay as the checkout
    left them, where a branch with no live ref reads as unread and never
    settles, so the queue stays conservative.
    """
    try:
        runner.run(
            [
                "git",
                "fetch",
                "origin",
                "+refs/heads/pricelog/*:refs/remotes/origin/pricelog/*",
                "--prune",
            ],
            cwd=repo_root,
        )
    except pr.PrError as exc:
        cause = health.escape_command_data(str(exc))
        print(
            f"::warning::the pricelog ref fetch failed: {cause};"
            " the queue used the refs the checkout fetched",
            file=sys.stderr,
        )


def _usage() -> None:
    print(f"usage: {Path(sys.argv[0]).name} [--awaiting-review <limit>]", file=sys.stderr)


def _dispatch_publish(runner: pr.PrRunner, repo_root: Path, base: str) -> None:
    """Kick publish.yml after the push; a failed dispatch warns, never fails.

    a GITHUB_TOKEN push starts no workflow run, so the published index would
    otherwise wait for the next human push. the push already landed, so a
    failed dispatch only delays the site to the next pushing merge or a
    manual publish.yml dispatch.
    """
    try:
        runner.run(["gh", "workflow", "run", "publish.yml", "--ref", base], cwd=repo_root)
    except pr.PrError as exc:
        cause = health.escape_command_data(str(exc))
        print(
            f"::warning::the publish dispatch failed: {cause}; the published index"
            " waits for the next pushing merge or a manual publish.yml dispatch"
        )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    limit: int | None = None
    if args:
        if len(args) != 2 or args[0] != "--awaiting-review":
            _usage()
            return 2
        try:
            limit = int(args[1])
        except ValueError:
            _usage()
            return 2
        if limit <= 0:
            _usage()
            return 2
    runner = pr.PrRunner()
    repo_root = Path.cwd()
    try:
        candidates, dispositions, marker_times, binding, gone = _listing(
            runner, repo_root, sys.stderr if limit is not None else sys.stdout
        )
        bound_dispositions = _bound_dispositions(dispositions, binding)
        if limit is not None:
            requeue: frozenset[int] = frozenset()
            if any(bound_dispositions.get(number) is not True for number, _head_ref in candidates):
                _fetch_pricelog_refs(runner, repo_root)
                requeue = _settled_no_heads(
                    runner, repo_root, candidates, bound_dispositions, marker_times
                )
            for number, head_ref in awaiting_review(
                candidates, bound_dispositions, limit, requeue=requeue
            ):
                print(f"{number} {head_ref}")
            return 0
        if not candidates:
            if gone:
                print("no open pricelog PR with a live branch; nothing to merge")
            else:
                print("no open pricelog PRs; nothing to merge")
            return 0
        branches = eligible_branches(candidates, bound_dispositions)
        for head_ref, stamped, head_oid in _stale_yeses(candidates, dispositions, binding):
            stamp7 = stamped[:7] if stamped else "none"
            current7 = head_oid[:7] or "none"
            print(f"skipping {head_ref}: head moved since the verdict ({stamp7} -> {current7})")
        if not branches:
            print("no PR with a bound automerge: yes; nothing to merge")
            return 0
        base = pr.default_branch(runner, repo_root)
        held = _held_channels(runner, repo_root, candidates, bound_dispositions, marker_times)
        sha, results = automerge.merge_branches(
            branches, repo_root, runner, base, push=True, held_channels=held
        )
    except (automerge.AutoMergeError, pr.PrError) as exc:
        # the script's own semantics: every PR stays open, nothing merged
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for result in results:
        print(f"merged {result.branch} ({result.appended} rows) as {result.commit[:7]}")
    print(f"pushed {sha[:7]} to {base}, branch refs deleted")
    _dispatch_publish(runner, repo_root, base)
    return 0

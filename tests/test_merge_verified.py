"""merge_verified tests: the pure halves of the disposition-driven merge."""

from __future__ import annotations

import io
import json

import pytest

from ai_pricelog import announce, automerge, merge_verified, pr
from conftest import FakeRunner


def test_parse_disposition_yes():
    comments = [
        ("cldbot", "**claude pass review — verified**\n\nall rows re-read.\n\nautomerge: yes")
    ]
    assert merge_verified.parse_disposition(comments, "cldbot") is True


def test_parse_disposition_no():
    comments = [("@uwuclxdy", "bot wall; nothing to decide\n\nautomerge: no")]
    assert merge_verified.parse_disposition(comments, "@uwuclxdy") is False


def test_parse_disposition_absent_marker_is_none():
    comments = [("cldbot", "**claude pass review — findings**\nno marker here")]
    assert merge_verified.parse_disposition(comments, "cldbot") is None


def test_parse_disposition_last_bot_comment_wins():
    comments = [
        ("cldbot", "automerge: yes"),
        ("human", "automerge: no"),
        ("cldbot", "automerge: no"),
    ]
    assert merge_verified.parse_disposition(comments, "cldbot") is False
    assert merge_verified.parse_disposition(list(reversed(comments)), "cldbot") is True


def test_parse_disposition_ignores_non_bot_authors():
    comments = [("human", "automerge: yes"), ("other", "automerge: no")]
    assert merge_verified.parse_disposition(comments, "cldbot") is None


def test_parse_disposition_requires_a_marker_line():
    # a mid-line mention is prose, not the machine line the merge step reads
    body = "the automerge: yes marker is what the merge step reads"
    assert merge_verified.parse_disposition([("cldbot", body)], "cldbot") is None


def test_parse_disposition_at_reads_the_stamped_head():
    # a verdict is bound to the head it judged; the merge step compares the
    # stamp to the PR's current head
    head = "0123456789abcdef0123456789abcdef01234567"
    comments = [("cldbot", f"**verified**\n\nautomerge: yes {head}", "2026-10-24T10:00:00Z")]
    assert merge_verified.parse_disposition_at(comments, "cldbot") == (
        True,
        head,
        "2026-10-24T10:00:00Z",
    )


def test_eligible_branches_gates_every_refusal():
    open_prs = [
        (191, "pricelog/deepseek-abc12345"),
        (192, "pricelog/seed"),
        (193, "feature/foo"),
        (194, "pricelog/zai-abcdef12"),
        (195, "pricelog/groq-12345678"),
        (196, "pricelog/xai-87654321"),
    ]
    dispositions = {191: True, 192: True, 193: True, 195: None, 196: False}
    assert merge_verified.eligible_branches(open_prs, dispositions) == [
        "pricelog/deepseek-abc12345"
    ]


def test_eligible_branches_merges_a_stranded_older_run_pr():
    # the run that judged 197 failed its merge step; a later run's merge
    # step must still pick the branch up (observed 2026-09-18: the 11:00
    # run's merge push rejected, its 8 yes-marked PRs stranded)
    open_prs = [
        (191, "pricelog/deepseek-abc12345"),
        (197, "pricelog/stale-99999999"),
    ]
    dispositions = {197: True}
    assert merge_verified.eligible_branches(open_prs, dispositions) == ["pricelog/stale-99999999"]


def test_eligible_branches_orders_by_pr_number():
    open_prs = [(192, "pricelog/b-later"), (191, "pricelog/a-earlier")]
    assert merge_verified.eligible_branches(open_prs, {191: True, 192: True}) == [
        "pricelog/a-earlier",
        "pricelog/b-later",
    ]


def test_main_usage_error():
    assert merge_verified.main(["/tmp/run.log"]) == 2


def test_main_no_open_prs_exits_zero_before_comment_reads(monkeypatch, capsys):
    runner = FakeRunner()
    runner.on("pr list", output="[]")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    assert merge_verified.main([]) == 0
    assert capsys.readouterr().out == "no open pricelog PRs; nothing to merge\n"
    assert len(runner.calls) == 1


def test_main_merges_a_stranded_older_run_pr(monkeypatch):
    # the wiring half of the stranded fix: dispositions must be read for
    # pricelog PRs this run did not open, and a yes-marked one handed to
    # the automerge script
    head = "a" * 40
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps(
            [{"number": 197, "headRefName": "pricelog/stale-99999999", "headRefOid": head}]
        ),
    )
    runner.on("api user", output="cldbot\n")
    runner.on(
        "issues/197/comments",
        output=_comments(("cldbot", f"automerge: yes {head}", "2026-09-18T11:00:00Z")),
    )
    runner.on("repo view", output="mommy\n")
    runner.on("pricelog/stale-99999999", output=head + "\n")
    runner.on("workflow run publish.yml", output="")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    calls: list[tuple[list[str], str, bool]] = []

    def _fake_merge(branches, repo_root, runner_arg, base, push, held_channels=None):
        calls.append((branches, base, push))
        return ("f" * 40, [])

    monkeypatch.setattr(automerge, "merge_branches", _fake_merge)
    assert merge_verified.main([]) == 0
    assert calls == [(["pricelog/stale-99999999"], "mommy", True)]


def test_main_skips_a_branch_whose_head_moved_after_the_verdict(monkeypatch, capsys):
    # a yes authorizes the head it judged, never a later push to the branch
    reviewed_head = "b" * 40
    current_head = "c" * 40
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps(
            [
                {
                    "number": 660,
                    "headRefName": "pricelog/moved-12345678",
                    "headRefOid": current_head,
                },
                {
                    "number": 661,
                    "headRefName": "pricelog/bound-87654321",
                    "headRefOid": reviewed_head,
                },
            ]
        ),
    )
    runner.on("api user", output="cldbot\n")
    runner.on(
        "issues/660/comments",
        output=_comments(
            ("cldbot", f"verified\n\nautomerge: yes {reviewed_head}", "2026-10-24T10:00:00Z")
        ),
    )
    runner.on(
        "issues/661/comments",
        output=_comments(
            ("cldbot", f"verified\n\nautomerge: yes {reviewed_head}", "2026-10-24T10:00:00Z")
        ),
    )
    runner.on("HEAD:state/announce/index.json", output="{}")
    runner.on("origin/pricelog/moved-12345678:state/announce/index.json", output="{}")
    runner.on("origin/pricelog/bound-87654321:state/announce/index.json", output="{}")
    runner.on("repo view", output="mommy\n")
    runner.on("pricelog/moved-12345678", output=current_head + "\n")
    runner.on("pricelog/bound-87654321", output=reviewed_head + "\n")
    runner.on("workflow run publish.yml", output="")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    calls: list[list[str]] = []

    def _fake_merge(branches, repo_root, runner_arg, base, push, held_channels=None):
        calls.append(branches)
        return ("f" * 40, [])

    monkeypatch.setattr(automerge, "merge_branches", _fake_merge)
    assert merge_verified.main([]) == 0
    assert calls == [["pricelog/bound-87654321"]]
    out = capsys.readouterr().out
    assert "pricelog/moved-12345678" in out
    assert "head moved" in out


def test_main_skips_an_open_pr_whose_ref_is_deleted(monkeypatch, capsys):
    # a sibling run merged a PR and deleted its branch while github has not
    # closed it yet: the open list still names it, but there is nothing to
    # merge. the run must skip it, never red on the dangling ref (observed
    # 2026-09-20: the 19:00 run red'd on an 18:55 PR mid-close)
    head = "a" * 40
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps(
            [
                {"number": 278, "headRefName": "pricelog/gone-12345678", "headRefOid": head},
                {"number": 279, "headRefName": "pricelog/live-87654321", "headRefOid": head},
            ]
        ),
    )
    runner.on("api user", output="cldbot\n")
    runner.on(
        "issues/278/comments",
        output=_comments(("cldbot", f"automerge: yes {head}", "2026-09-20T19:05:00Z")),
    )
    runner.on(
        "issues/279/comments",
        output=_comments(("cldbot", f"automerge: yes {head}", "2026-09-20T19:05:00Z")),
    )
    runner.on("repo view", output="mommy\n")
    runner.on("pricelog/gone-12345678", output="")
    runner.on("pricelog/live-87654321", output=head + "\trefs/heads/pricelog/live-87654321\n")
    runner.on("workflow run publish.yml", output="")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    calls: list[tuple[list[str], str, bool]] = []

    def _fake_merge(branches, repo_root, runner_arg, base, push, held_channels=None):
        calls.append((branches, base, push))
        return ("f" * 40, [])

    monkeypatch.setattr(automerge, "merge_branches", _fake_merge)
    assert merge_verified.main([]) == 0
    assert calls == [(["pricelog/live-87654321"], "mommy", True)]
    assert "skipping pricelog/gone-12345678" in capsys.readouterr().out


def test_main_propagates_a_remote_error_not_as_gone(monkeypatch):
    # a remote or auth failure must red the run, never read as "nothing to
    # merge" and silently strand verified PRs
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps([{"number": 279, "headRefName": "pricelog/live-87654321"}]),
    )
    runner.on("api user", output="cldbot\n")
    runner.on(
        "issues/279/comments",
        output=_comments(("cldbot", "automerge: yes", "2026-09-20T19:05:00Z")),
    )
    runner.on("repo view", output="mommy\n")
    runner.on(
        "pricelog/live-87654321",
        failure=pr.PrError("fatal: unable to access 'https://github.com': Could not resolve host"),
    )
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    monkeypatch.setattr(automerge, "merge_branches", lambda *a, **k: ("f" * 40, []))
    assert merge_verified.main([]) == 1


def test_main_retries_a_transient_ls_remote_failure(monkeypatch, capsys):
    # one transient ls-remote failure must not red a quiet run: the merge
    # step runs hourly and a network blip on a nothing-to-merge run must stay
    # green, so the read retries once and the ref then reads as gone
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps([{"number": 279, "headRefName": "pricelog/gone-12345678"}]),
    )
    runner.on("pricelog/gone-12345678", output="")
    monkeypatch.setattr(automerge, "_RETRY_DELAYS", (0, 0))
    real_run = runner.run
    calls = 0

    def flaky_run(self, cmd, cwd):
        nonlocal calls
        if "ls-remote" in " ".join(cmd):
            calls += 1
            if calls == 1:
                raise pr.PrError(
                    "fatal: unable to access 'https://github.com': Could not resolve host"
                )
        return real_run(cmd, cwd)

    monkeypatch.setattr(pr.PrRunner, "run", flaky_run)
    assert merge_verified.main([]) == 0
    assert calls == 2
    assert "skipping pricelog/gone-12345678" in capsys.readouterr().out


def _channel_index(sha: str, url: str, file: str, fetched: str = "2026-10-16") -> str:
    return json.dumps({"perplexity": {url: {"file": file, "sha256": sha * 64, "fetched": fetched}}})


def _held_fixture(
    older: tuple[int, str, bool | None],
    *,
    older_carried: bool = True,
    newer_carried: bool = False,
):
    """the base plus an older carrier plus a newer carrier on one channel.

    `older_carried` / `newer_carried` script each branch's own announce diff:
    a branch carries a channel when its commit range changed the channel file,
    which the index comparison alone cannot tell.
    """
    url = "https://example.com/changelog"
    file = announce.channel_files("perplexity", [url])[url]
    older_number, older_head, older_mark = older
    newer_number, newer_head = older_number + 1, older_head.replace("older", "newer")
    runner = FakeRunner()
    runner.on(
        "HEAD:state/announce/index.json",
        output=_channel_index("a", url, file, "2026-10-15"),
    )
    runner.on(
        f"origin/{older_head}:state/announce/index.json", output=_channel_index("b", url, file)
    )
    runner.on(
        f"origin/{newer_head}:state/announce/index.json", output=_channel_index("b", url, file)
    )
    runner.on(
        f"git diff --name-only HEAD...origin/{older_head}",
        output=f"{file}\n" if older_carried else "",
    )
    runner.on(
        f"git diff --name-only HEAD...origin/{newer_head}",
        output=f"{file}\n" if newer_carried else "",
    )
    candidates = [(older_number, older_head), (newer_number, newer_head)]
    dispositions = {older_number: older_mark, newer_number: None}
    return runner, candidates, dispositions, ("perplexity", url)


def test_held_channels_releases_a_channel_a_newer_yes_pr_carries(tmp_path):
    # the newest pass judged the same channel on a newer PR and marked it
    # yes: the owed ruling is made, so the channel is no longer held
    runner, candidates, dispositions, channel = _held_fixture((552, "pricelog/older-no", False))
    dispositions[553] = True
    assert merge_verified._held_channels(runner, tmp_path, candidates, dispositions) == frozenset()


def test_held_channels_holds_when_the_newest_carrier_is_no(tmp_path):
    runner, candidates, dispositions, channel = _held_fixture((552, "pricelog/older-yes", True))
    dispositions[553] = False
    assert merge_verified._held_channels(runner, tmp_path, candidates, dispositions) == frozenset(
        {channel}
    )


def test_held_channels_holds_an_unjudged_newest_carrier(tmp_path):
    runner, candidates, dispositions, channel = _held_fixture((552, "pricelog/older-no", False))
    assert merge_verified._held_channels(runner, tmp_path, candidates, dispositions) == frozenset(
        {channel}
    )


def test_held_channels_holds_a_readable_carrier_beside_an_unread_sibling(tmp_path):
    # the unread branch may be the channel's newest carrier with its ruling
    # unlanded, so a readable bound-yes sibling releases nothing
    url = "https://example.com/changelog"
    file = announce.channel_files("perplexity", [url])[url]
    runner = FakeRunner()
    runner.on(
        "HEAD:state/announce/index.json",
        output=_channel_index("a", url, file, "2026-10-15"),
    )
    runner.on(
        "origin/pricelog/readable-yes:state/announce/index.json",
        output=_channel_index("b", url, file, "2026-10-16"),
    )
    runner.on(
        "origin/pricelog/unread:state/announce/index.json",
        failure=pr.PrError("git show: bad object"),
    )
    candidates = [(552, "pricelog/readable-yes"), (553, "pricelog/unread")]
    dispositions = {552: True, 553: None}
    assert merge_verified._held_channels(runner, tmp_path, candidates, dispositions) == frozenset(
        {("perplexity", url)}
    )


def test_main_holds_a_channel_a_stale_yes_carries(monkeypatch, tmp_path):
    # a yes for an old head neither merges nor releases the announce channel
    # it carries: the newest carrier is unjudged for the current head, so the
    # owed ruling stays held at the base copy
    url = "https://example.com/changelog"
    file = announce.channel_files("perplexity", [url])[url]
    channel = ("perplexity", url)
    old_head = "a" * 40
    stale_head = "b" * 40
    stale_now = "c" * 40
    bound_head = "d" * 40
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps(
            [
                {"number": 552, "headRefName": "pricelog/older-no", "headRefOid": old_head},
                {"number": 553, "headRefName": "pricelog/newer-yes", "headRefOid": stale_now},
                {"number": 554, "headRefName": "pricelog/bound-yes", "headRefOid": bound_head},
            ]
        ),
    )
    runner.on("api user", output="cldbot\n")
    runner.on(
        "issues/552/comments",
        output=_comments(
            ("cldbot", f"needs human\n\nautomerge: no {old_head}", "2026-10-24T10:00:00Z")
        ),
    )
    runner.on(
        "issues/553/comments",
        output=_comments(
            ("cldbot", f"verified\n\nautomerge: yes {stale_head}", "2026-10-24T12:00:00Z")
        ),
    )
    runner.on(
        "issues/554/comments",
        output=_comments(
            ("cldbot", f"verified\n\nautomerge: yes {bound_head}", "2026-10-24T11:00:00Z")
        ),
    )
    runner.on("HEAD:state/announce/index.json", output=_channel_index("a", url, file, "2026-10-15"))
    runner.on(
        "origin/pricelog/older-no:state/announce/index.json", output=_channel_index("b", url, file)
    )
    runner.on(
        "origin/pricelog/newer-yes:state/announce/index.json", output=_channel_index("b", url, file)
    )
    runner.on("origin/pricelog/bound-yes:state/announce/index.json", output="{}")
    runner.on("git diff --name-only HEAD...origin/pricelog/older-no", output=f"{file}\n")
    runner.on("git diff --name-only HEAD...origin/pricelog/newer-yes", output=f"{file}\n")
    runner.on("git diff --name-only HEAD...origin/pricelog/bound-yes", output="")
    for head in ("pricelog/older-no", "pricelog/newer-yes", "pricelog/bound-yes"):
        runner.on(head, output=old_head + "\n")
    runner.on("repo view", output="mommy\n")
    runner.on("workflow run publish.yml", output="")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    calls: list[tuple[list[str], frozenset[tuple[str, str]]]] = []

    def _fake_merge(branches, repo_root, runner_arg, base, push, held_channels=None):
        calls.append((branches, held_channels))
        return ("f" * 40, [])

    monkeypatch.setattr(automerge, "merge_branches", _fake_merge)
    assert merge_verified.main([]) == 0
    assert calls == [(["pricelog/bound-yes"], frozenset({channel}))]


def test_settled_no_heads_requeues_a_no_pr_whose_channel_a_newer_yes_carries(tmp_path):
    # the no PR's only differing channel is settled by the newer yes PR: its
    # reason is gone, so it re-enters the review queue
    runner, candidates, dispositions, _channel = _held_fixture((552, "pricelog/older-no", False))
    dispositions[553] = True
    assert merge_verified._settled_no_heads(
        runner, tmp_path, candidates, dispositions
    ) == frozenset({552})
    assert merge_verified.awaiting_review(
        candidates, dispositions, limit=10, requeue=frozenset({552})
    ) == [(552, "pricelog/older-no")]


def test_settled_no_heads_leaves_a_no_pr_when_the_newest_carrier_is_no(tmp_path):
    runner, candidates, dispositions, _channel = _held_fixture(
        (552, "pricelog/older-yes", True), newer_carried=True
    )
    dispositions[553] = False
    assert (
        merge_verified._settled_no_heads(runner, tmp_path, candidates, dispositions) == frozenset()
    )


def test_settled_no_heads_never_settles_an_unreadable_branch(tmp_path):
    # a no PR whose announce index cannot be read is unknown, never settled
    url = "https://example.com/changelog"
    file = announce.channel_files("perplexity", [url])[url]
    runner = FakeRunner()
    runner.on("HEAD:state/announce/index.json", output=_channel_index("a", url, file))
    runner.on("origin/pricelog/older-no:state/announce/index.json", failure=pr.PrError("missing"))
    runner.on(
        "origin/pricelog/newer-yes:state/announce/index.json",
        output=_channel_index("b", url, file),
    )
    candidates = [(552, "pricelog/older-no"), (553, "pricelog/newer-yes")]
    dispositions = {552: False, 553: True}
    assert (
        merge_verified._settled_no_heads(runner, tmp_path, candidates, dispositions) == frozenset()
    )


def test_settled_no_heads_leaves_a_no_pr_carrying_no_differing_channel(tmp_path):
    # a price-only no PR carries no announce channel, so no ruling settled it:
    # re-queueing it would churn the queue and bypass the human it waits on
    url = "https://example.com/changelog"
    file = announce.channel_files("perplexity", [url])[url]
    runner = FakeRunner()
    runner.on(
        "HEAD:state/announce/index.json",
        output=_channel_index("a", url, file, "2026-10-15"),
    )
    runner.on(
        "origin/pricelog/older-no:state/announce/index.json",
        output=_channel_index("a", url, file),
    )
    runner.on(
        "origin/pricelog/newer-yes:state/announce/index.json",
        output=_channel_index("b", url, file),
    )
    # the branch's own commit range changed no announce file
    runner.on("git diff --name-only HEAD...origin/pricelog/older-no", output="")
    candidates = [(552, "pricelog/older-no"), (553, "pricelog/newer-yes")]
    dispositions = {552: False, 553: True}
    assert (
        merge_verified._settled_no_heads(runner, tmp_path, candidates, dispositions) == frozenset()
    )


def test_settled_no_heads_requeues_a_no_pr_whose_channel_the_base_superseded(tmp_path):
    # a sibling merged a newer snapshot of the same channel while this no PR
    # stayed open: the branch's copy lands nothing, so its announce ruling is
    # moot and the PR goes back for a fresh judgement
    url = "https://example.com/changelog"
    file = announce.channel_files("perplexity", [url])[url]
    runner = FakeRunner()
    runner.on(
        "HEAD:state/announce/index.json",
        output=_channel_index("b", url, file, "2026-10-20"),
    )
    runner.on(
        "origin/pricelog/older-no:state/announce/index.json",
        output=_channel_index("a", url, file, "2026-10-15"),
    )
    runner.on("git diff --name-only HEAD...origin/pricelog/older-no", output=f"{file}\n")
    candidates = [(552, "pricelog/older-no")]
    dispositions = {552: False}
    assert merge_verified._settled_no_heads(
        runner, tmp_path, candidates, dispositions
    ) == frozenset({552})


def test_settled_no_heads_requeues_a_carrier_the_base_already_holds(tmp_path):
    # the same run's yes sibling merged this very snapshot: the no branch's
    # index entry now equals the base's, but the branch did carry the change
    url = "https://example.com/changelog"
    file = announce.channel_files("perplexity", [url])[url]
    runner = FakeRunner()
    runner.on(
        "HEAD:state/announce/index.json",
        output=_channel_index("b", url, file, "2026-10-20"),
    )
    runner.on(
        "origin/pricelog/older-no:state/announce/index.json",
        output=_channel_index("b", url, file, "2026-10-20"),
    )
    runner.on("git diff --name-only HEAD...origin/pricelog/older-no", output=f"{file}\n")
    candidates = [(552, "pricelog/older-no")]
    dispositions = {552: False}
    assert merge_verified._settled_no_heads(
        runner, tmp_path, candidates, dispositions
    ) == frozenset({552})


def test_settled_no_heads_leaves_a_same_snapshot_no_pr_that_never_carried_it(tmp_path):
    # the branch's index equals the base's and its commit range changed no
    # announce file: nothing was ever carried, so nothing was settled
    url = "https://example.com/changelog"
    file = announce.channel_files("perplexity", [url])[url]
    runner = FakeRunner()
    runner.on(
        "HEAD:state/announce/index.json",
        output=_channel_index("b", url, file, "2026-10-20"),
    )
    runner.on(
        "origin/pricelog/older-no:state/announce/index.json",
        output=_channel_index("b", url, file, "2026-10-20"),
    )
    runner.on("git diff --name-only HEAD...origin/pricelog/older-no", output="")
    candidates = [(552, "pricelog/older-no")]
    dispositions = {552: False}
    assert (
        merge_verified._settled_no_heads(runner, tmp_path, candidates, dispositions) == frozenset()
    )


def test_settled_no_heads_settles_a_same_instant_differing_snapshot(tmp_path):
    # the merge keeps the base on an identical fetched instant (automerge's
    # tie rule), so the branch's copy lands nothing and the no is settled
    url = "https://example.com/changelog"
    file = announce.channel_files("perplexity", [url])[url]
    runner = FakeRunner()
    runner.on(
        "HEAD:state/announce/index.json",
        output=_channel_index("b", url, file, "2026-10-20"),
    )
    runner.on(
        "origin/pricelog/older-no:state/announce/index.json",
        output=_channel_index("a", url, file, "2026-10-20"),
    )
    runner.on("git diff --name-only HEAD...origin/pricelog/older-no", output=f"{file}\n")
    candidates = [(552, "pricelog/older-no")]
    dispositions = {552: False}
    assert merge_verified._settled_no_heads(
        runner, tmp_path, candidates, dispositions
    ) == frozenset({552})


def test_settled_no_heads_leaves_a_no_pr_whose_diff_cannot_be_read(tmp_path):
    # a branch ref the checkout never fetched leaves the carriage unknown, so
    # the PR is never settled (the unreadable-index twin sits above)
    url = "https://example.com/changelog"
    file = announce.channel_files("perplexity", [url])[url]
    runner = FakeRunner()
    runner.on(
        "HEAD:state/announce/index.json",
        output=_channel_index("b", url, file, "2026-10-20"),
    )
    runner.on(
        "origin/pricelog/older-no:state/announce/index.json",
        output=_channel_index("b", url, file, "2026-10-20"),
    )
    runner.on(
        "git diff --name-only HEAD...origin/pricelog/older-no",
        failure=pr.PrError("fatal: ambiguous argument"),
    )
    candidates = [(552, "pricelog/older-no")]
    dispositions = {552: False}
    assert (
        merge_verified._settled_no_heads(runner, tmp_path, candidates, dispositions) == frozenset()
    )


def test_settled_no_heads_leaves_a_no_pr_when_the_newest_carrier_is_unjudged(tmp_path):
    runner, candidates, dispositions, _channel = _held_fixture((552, "pricelog/older-no", False))
    assert (
        merge_verified._settled_no_heads(runner, tmp_path, candidates, dispositions) == frozenset()
    )


def test_settled_no_heads_requires_every_carried_channel_settled(tmp_path):
    # the no PR carries two channels; only one has a newer yes carrier, so
    # the other channel's ruling is still owed
    x_url, y_url = "https://example.com/x", "https://example.com/y"
    files = announce.channel_files("perplexity", [x_url, y_url])
    runner = FakeRunner()
    runner.on(
        "HEAD:state/announce/index.json",
        output=json.dumps(
            {
                "perplexity": {
                    x_url: {"file": files[x_url], "sha256": "a" * 64, "fetched": "2026-10-15"},
                    y_url: {"file": files[y_url], "sha256": "a" * 64, "fetched": "2026-10-15"},
                }
            }
        ),
    )
    runner.on(
        "origin/pricelog/older-no:state/announce/index.json",
        output=json.dumps(
            {
                "perplexity": {
                    x_url: {"file": files[x_url], "sha256": "b" * 64, "fetched": "2026-10-16"},
                    y_url: {"file": files[y_url], "sha256": "b" * 64, "fetched": "2026-10-16"},
                }
            }
        ),
    )
    runner.on(
        "origin/pricelog/newer-yes:state/announce/index.json",
        output=json.dumps(
            {
                "perplexity": {
                    x_url: {"file": files[x_url], "sha256": "b" * 64, "fetched": "2026-10-16"},
                    y_url: {"file": files[y_url], "sha256": "a" * 64, "fetched": "2026-10-15"},
                }
            }
        ),
    )
    runner.on(
        "git diff --name-only HEAD...origin/pricelog/older-no",
        output=f"{files[x_url]}\n{files[y_url]}\n",
    )
    candidates = [(552, "pricelog/older-no"), (553, "pricelog/newer-yes")]
    dispositions = {552: False, 553: True}
    assert (
        merge_verified._settled_no_heads(runner, tmp_path, candidates, dispositions) == frozenset()
    )


def test_held_channels_ignores_a_stale_branch_snapshot(tmp_path):
    # the merge never lets a stale copy win: a no branch whose snapshot is
    # older than the base carries nothing to hold
    url = "https://example.com/changelog"
    file = announce.channel_files("perplexity", [url])[url]
    runner = FakeRunner()
    runner.on(
        "HEAD:state/announce/index.json",
        output=_channel_index("a", url, file, "2026-10-17"),
    )
    runner.on(
        "origin/pricelog/older-no:state/announce/index.json",
        output=_channel_index("b", url, file, "2026-10-15"),
    )
    candidates = [(552, "pricelog/older-no")]
    dispositions = {552: False}
    assert merge_verified._held_channels(runner, tmp_path, candidates, dispositions) == frozenset()


def test_held_channels_ranks_carriers_by_their_marker_time(tmp_path):
    # an older yes on a higher-numbered PR must not outrank a newer no on a
    # lower-numbered one: the stranded-yes + requeue sequence
    runner, candidates, dispositions, channel = _held_fixture((552, "pricelog/older-no", False))
    dispositions[553] = True
    marker_times = {552: "2026-10-21T11:00:00Z", 553: "2026-10-21T10:00:00Z"}
    assert merge_verified._held_channels(
        runner, tmp_path, candidates, dispositions, marker_times
    ) == frozenset({channel})
    assert (
        merge_verified._settled_no_heads(runner, tmp_path, candidates, dispositions, marker_times)
        == frozenset()
    )


# the self-healing review queue: a PR the pass never judged (its pass died,
# the endpoint was down, the run was killed) carries no marker, so the next
# pass picks it up instead of leaving it open forever (2026-09-27..10-14:
# 80 unjudged PRs stranded behind a dead endpoint, every model behind them
# frozen by the pending skip)


def test_awaiting_review_lists_unmarked_pricelog_prs_oldest_first():
    open_prs = [
        (488, "pricelog/openrouter-2026-10-14-190015-190db2ec"),
        (394, "pricelog/openrouter-2026-09-25-150013-d2c45efc"),
        (460, "pricelog/anthropic-2026-10-07-180015-7c3e50e6"),
        (461, "pricelog/openrouter-2026-10-07-190049-ef298e9e"),
        (300, "pricelog/seed"),
        (301, "feature/foo"),
    ]
    # 460 judged needs-human (a marker, so it waits for a human, never the
    # pass); 461 judged yes; the seed and the human branch never queue
    dispositions = {488: None, 394: None, 460: False, 461: True, 300: None, 301: None}
    assert merge_verified.awaiting_review(open_prs, dispositions, limit=10) == [
        (394, "pricelog/openrouter-2026-09-25-150013-d2c45efc"),
        (488, "pricelog/openrouter-2026-10-14-190015-190db2ec"),
    ]


def test_awaiting_review_caps_the_queue_at_the_oldest():
    open_prs = [(number, f"pricelog/openrouter-{number}") for number in (405, 401, 403, 402, 404)]
    dispositions = {number: None for number, _head in open_prs}
    assert merge_verified.awaiting_review(open_prs, dispositions, limit=3) == [
        (401, "pricelog/openrouter-401"),
        (402, "pricelog/openrouter-402"),
        (403, "pricelog/openrouter-403"),
    ]


def test_main_awaiting_review_does_not_requeue_a_bound_yes(monkeypatch, capsys):
    # a yes stamped with the branch's current head is a finished review: the
    # merge step owns it, so the pass must not judge it again
    head = "b" * 40
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps(
            [{"number": 660, "headRefName": "pricelog/bound-12345678", "headRefOid": head}]
        ),
    )
    runner.on("api user", output="cldbot\n")
    runner.on("ls-remote", output=head + "\trefs/heads/x\n")
    runner.on("git fetch", output="")
    runner.on("git show", output="{}\n")
    runner.on("git diff", output="")
    runner.on(
        "issues/660/comments",
        output=_comments(("cldbot", f"verified\n\nautomerge: yes {head}", "2026-10-24T10:00:00Z")),
    )
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    assert merge_verified.main(["--awaiting-review", "10"]) == 0
    assert capsys.readouterr().out == ""


def test_main_awaiting_review_requeues_a_stale_verdict(monkeypatch, capsys):
    # the branch moved after the verdict, so the yes no longer applies and the
    # pass must judge the new head
    reviewed_head = "a" * 40
    current_head = "b" * 40
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps(
            [{"number": 660, "headRefName": "pricelog/stale-12345678", "headRefOid": current_head}]
        ),
    )
    runner.on("api user", output="cldbot\n")
    runner.on("ls-remote", output=current_head + "\trefs/heads/x\n")
    runner.on("git fetch", output="")
    runner.on("git show", output="{}\n")
    runner.on("git diff", output="")
    runner.on(
        "issues/660/comments",
        output=_comments(
            ("cldbot", f"verified\n\nautomerge: yes {reviewed_head}", "2026-10-24T10:00:00Z")
        ),
    )
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    assert merge_verified.main(["--awaiting-review", "10"]) == 0
    assert capsys.readouterr().out == "660 pricelog/stale-12345678\n"


def _comments(*entries: tuple[str, ...]) -> str:
    """The `gh api --paginate --slurp` payload: one page of (login, body[, created[, updated]]).

    GitHub never moves `created_at` on an edit, so an entry's two times differ
    exactly when the pass edited its verdict.
    """
    comments = []
    for login, body, *times in entries:
        created = times[0] if times else "2026-10-14T19:05:00Z"
        updated = times[1] if len(times) > 1 else created
        comments.append(
            {
                "user": {"login": login},
                "body": body,
                "created_at": created,
                "updated_at": updated,
            }
        )
    return json.dumps([comments])


def test_listing_ranks_a_marker_by_its_edit_time(tmp_path):
    # GitHub never moves created_at on an edit, and the pass EDITS its verdict
    # comment on a re-queued PR: the marker's recency is its edit time, so a
    # fresh verdict on an old comment outranks a later-posted stale one
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps([{"number": 552, "headRefName": "pricelog/openrouter-552"}]),
    )
    runner.on("api user", output="cldbot\n")
    runner.on("ls-remote", output="a" * 40 + "\trefs/heads/x\n")
    runner.on(
        "issues/552/comments",
        output=_comments(
            ("cldbot", "automerge: yes", "2026-10-20T10:00:00Z", "2026-10-21T09:00:00Z"),
            ("cldbot", "automerge: no", "2026-10-20T11:00:00Z", "2026-10-20T11:00:00Z"),
        ),
    )
    candidates, dispositions, marker_times, _binding, _gone = merge_verified._listing(
        runner, tmp_path, io.StringIO()
    )
    assert candidates == [(552, "pricelog/openrouter-552")]
    assert dispositions == {552: True}
    assert marker_times == {552: "2026-10-21T09:00:00Z"}


def test_pr_comments_reads_every_page(tmp_path):
    # `--paginate --slurp` returns one array per page; the verdict can sit on
    # any page, and dropping it leaves the PR unjudged forever
    runner = FakeRunner()
    runner.on(
        "issues/331/comments",
        output=json.dumps(
            [
                [
                    {
                        "user": {"login": "cldbot"},
                        "body": "**claude pass review** (partial)",
                        "created_at": "2026-10-20T10:00:00Z",
                        "updated_at": "2026-10-20T10:00:00Z",
                    }
                ],
                [
                    {
                        "user": {"login": "cldbot"},
                        "body": "verified\n\nautomerge: yes",
                        "created_at": "2026-10-20T11:00:00Z",
                        "updated_at": "2026-10-20T11:00:00Z",
                    }
                ],
            ]
        ),
    )
    triples = merge_verified._pr_comments(runner, tmp_path, 331)
    assert [(author, at) for author, _body, at in triples] == [
        ("cldbot", "2026-10-20T10:00:00Z"),
        ("cldbot", "2026-10-20T11:00:00Z"),
    ]
    assert merge_verified.parse_disposition_at(triples, "cldbot") == (
        True,
        None,
        "2026-10-20T11:00:00Z",
    )
    assert any(
        "--paginate" in " ".join(cmd) and "--slurp" in " ".join(cmd) for cmd, _cwd in runner.calls
    )


def test_pr_comments_refuses_a_non_list_page(tmp_path):
    # `--slurp` always wraps pages in arrays; anything else is a shape change
    # that must stop by name rather than read the PR as unjudged
    runner = FakeRunner()
    runner.on("issues/331/comments", output=json.dumps([{"user": {"login": "cldbot"}}]))
    with pytest.raises(pr.PrError) as excinfo:
        merge_verified._pr_comments(runner, tmp_path, 331)
    assert str(excinfo.value) == "gh api issues/331/comments returned a non-list page value"


def test_main_awaiting_review_prints_the_queue(monkeypatch, capsys):
    head = "a" * 40
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps(
            [
                {"number": 488, "headRefName": "pricelog/openrouter-488", "headRefOid": head},
                {"number": 460, "headRefName": "pricelog/anthropic-460", "headRefOid": head},
                {"number": 414, "headRefName": "pricelog/anthropic-414", "headRefOid": head},
                {"number": 400, "headRefName": "pricelog/openrouter-400", "headRefOid": head},
                {"number": 399, "headRefName": "feature/human", "headRefOid": head},
            ]
        ),
    )
    runner.on("api user", output="cldbot\n")
    runner.on("issues/488/comments", output=_comments())
    runner.on(
        "issues/460/comments", output=_comments(("cldbot", f"needs human\n\nautomerge: no {head}"))
    )
    # a bot comment with no marker line is an unfinished review: it queues
    runner.on(
        "issues/414/comments", output=_comments(("cldbot", "**claude pass review** (partial)"))
    )
    # a human's marker is not the pass's disposition: it queues
    runner.on("issues/400/comments", output=_comments(("uwuclxdy", f"automerge: yes {head}")))
    runner.on("ls-remote", output=head + "\trefs/heads/x\n")
    runner.on("git fetch", output="")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    monkeypatch.setattr(merge_verified, "_settled_no_heads", lambda *a, **k: frozenset())
    monkeypatch.setattr(
        automerge,
        "merge_branches",
        lambda *a, **k: pytest.fail("listing the queue must never merge"),
    )
    assert merge_verified.main(["--awaiting-review", "10"]) == 0
    assert capsys.readouterr().out == (
        "400 pricelog/openrouter-400\n414 pricelog/anthropic-414\n488 pricelog/openrouter-488\n"
    )


def test_main_awaiting_review_requeues_a_settled_no_pr(monkeypatch, capsys):
    # a no PR whose channel a newer yes pass settled prints in the queue
    head = "a" * 40
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps(
            [
                {"number": 488, "headRefName": "pricelog/openrouter-488", "headRefOid": head},
                {"number": 460, "headRefName": "pricelog/anthropic-460", "headRefOid": head},
            ]
        ),
    )
    runner.on("api user", output="cldbot\n")
    runner.on("issues/488/comments", output=_comments())
    runner.on(
        "issues/460/comments", output=_comments(("cldbot", f"needs human\n\nautomerge: no {head}"))
    )
    runner.on("ls-remote", output=head + "\trefs/heads/x\n")
    runner.on("git fetch", output="")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    monkeypatch.setattr(merge_verified, "_settled_no_heads", lambda *a, **k: frozenset({460}))
    assert merge_verified.main(["--awaiting-review", "10"]) == 0
    assert capsys.readouterr().out == ("460 pricelog/anthropic-460\n488 pricelog/openrouter-488\n")


def _edit_time_queue(edited_at: str) -> FakeRunner:
    """552 no + 553 yes on one channel, 552's verdict comment edited at `edited_at`."""
    head = "a" * 40
    url = "https://example.com/changelog"
    file = announce.channel_files("perplexity", [url])[url]
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps(
            [
                {"number": 552, "headRefName": "pricelog/older-no", "headRefOid": head},
                {"number": 553, "headRefName": "pricelog/newer-yes", "headRefOid": head},
            ]
        ),
    )
    runner.on("api user", output="cldbot\n")
    runner.on(
        "issues/552/comments",
        output=_comments(
            ("cldbot", f"needs human\n\nautomerge: no {head}", "2026-10-20T10:00:00Z", edited_at)
        ),
    )
    runner.on(
        "issues/553/comments",
        output=_comments(
            (
                "cldbot",
                f"verified\n\nautomerge: yes {head}",
                "2026-10-21T10:00:00Z",
                "2026-10-21T10:00:00Z",
            )
        ),
    )
    runner.on("ls-remote", output=head + "\trefs/heads/x\n")
    runner.on("git fetch", output="")
    runner.on("HEAD:state/announce/index.json", output=json.dumps({"perplexity": {}}))
    runner.on(
        "origin/pricelog/older-no:state/announce/index.json",
        output=_channel_index("b", url, file),
    )
    runner.on(
        "origin/pricelog/newer-yes:state/announce/index.json",
        output=_channel_index("b", url, file),
    )
    runner.on("git diff --name-only HEAD...origin/pricelog/older-no", output=f"{file}\n")
    runner.on("git diff --name-only HEAD...origin/pricelog/newer-yes", output=f"{file}\n")
    return runner


def test_main_holds_a_no_pr_whose_verdict_was_edited_after_the_yes(monkeypatch, capsys):
    # 553's yes was posted later but 552's verdict was EDITED after it: the
    # newest ruling on the channel is 552's no, so 552 stays held
    runner = _edit_time_queue("2026-10-21T12:00:00Z")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    assert merge_verified.main(["--awaiting-review", "10"]) == 0
    assert capsys.readouterr().out == ""


def test_main_requeues_a_no_pr_whose_later_yes_settled_it(monkeypatch, capsys):
    # control for the edit-time ranking: with 552 never edited, 553's later
    # yes is the newest ruling and 552 re-enters the queue
    runner = _edit_time_queue("2026-10-20T10:00:00Z")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    assert merge_verified.main(["--awaiting-review", "10"]) == 0
    assert capsys.readouterr().out == "552 pricelog/older-no\n"


def test_main_a_stale_yes_settles_no_sibling(monkeypatch, capsys):
    # the settling yes judged an old head, so it rules nothing for the
    # current one: the no PR stays out of the settle requeue (its own
    # verdict is a bound no) and the stale yes queues instead
    head = "a" * 40
    moved_head = "b" * 40
    url = "https://example.com/changelog"
    file = announce.channel_files("perplexity", [url])[url]
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps(
            [
                {"number": 552, "headRefName": "pricelog/older-no", "headRefOid": head},
                {"number": 553, "headRefName": "pricelog/newer-yes", "headRefOid": moved_head},
            ]
        ),
    )
    runner.on("api user", output="cldbot\n")
    runner.on(
        "issues/552/comments",
        output=_comments(
            ("cldbot", f"needs human\n\nautomerge: no {head}", "2026-10-20T10:00:00Z")
        ),
    )
    runner.on(
        "issues/553/comments",
        output=_comments(("cldbot", f"verified\n\nautomerge: yes {head}", "2026-10-21T10:00:00Z")),
    )
    runner.on("ls-remote", output=moved_head + "\trefs/heads/x\n")
    runner.on("git fetch", output="")
    runner.on("HEAD:state/announce/index.json", output=json.dumps({"perplexity": {}}))
    runner.on(
        "origin/pricelog/older-no:state/announce/index.json",
        output=_channel_index("b", url, file),
    )
    runner.on(
        "origin/pricelog/newer-yes:state/announce/index.json",
        output=_channel_index("b", url, file),
    )
    runner.on("git diff --name-only HEAD...origin/pricelog/older-no", output=f"{file}\n")
    runner.on("git diff --name-only HEAD...origin/pricelog/newer-yes", output=f"{file}\n")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    assert merge_verified.main(["--awaiting-review", "10"]) == 0
    assert capsys.readouterr().out == "553 pricelog/newer-yes\n"


def _held_merge_fixture(no_verdict_at: str) -> tuple[FakeRunner, tuple[str, str]]:
    """A yes PR and a no PR on one channel, in merge mode; the no's verdict at `no_verdict_at`."""
    head = "a" * 40
    url = "https://example.com/changelog"
    file = announce.channel_files("perplexity", [url])[url]
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps(
            [
                {"number": 552, "headRefName": "pricelog/older-no", "headRefOid": head},
                {"number": 553, "headRefName": "pricelog/newer-yes", "headRefOid": head},
            ]
        ),
    )
    runner.on("api user", output="cldbot\n")
    runner.on(
        "issues/552/comments",
        output=_comments(
            (
                "cldbot",
                f"needs human\n\nautomerge: no {head}",
                "2026-10-20T10:00:00Z",
                no_verdict_at,
            )
        ),
    )
    runner.on(
        "issues/553/comments",
        output=_comments(
            (
                "cldbot",
                f"verified\n\nautomerge: yes {head}",
                "2026-10-21T10:00:00Z",
                "2026-10-21T10:00:00Z",
            )
        ),
    )
    runner.on("ls-remote", output=head + "\trefs/heads/x\n")
    runner.on("repo view", output="mommy\n")
    runner.on("HEAD:state/announce/index.json", output=json.dumps({"perplexity": {}}))
    runner.on(
        "origin/pricelog/older-no:state/announce/index.json",
        output=_channel_index("b", url, file),
    )
    runner.on(
        "origin/pricelog/newer-yes:state/announce/index.json",
        output=_channel_index("b", url, file),
    )
    runner.on("workflow run publish.yml", output="")
    return runner, ("perplexity", url)


def _merge_held_with(monkeypatch, runner: FakeRunner) -> frozenset[tuple[str, str]]:
    held: list[frozenset[tuple[str, str]]] = []

    def _fake_merge(branches, repo_root, runner_arg, base, push, held_channels=None):
        held.append(frozenset(held_channels or ()))
        return ("f" * 40, [])

    monkeypatch.setattr(automerge, "merge_branches", _fake_merge)
    assert merge_verified.main([]) == 0
    return held[0]


def test_main_holds_a_channel_whose_no_verdict_is_the_newest(monkeypatch):
    # the no was re-judged after the yes landed: the newest ruling is no, so
    # the merge keeps the base copy of the channel
    runner, channel = _held_merge_fixture("2026-10-21T12:00:00Z")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    assert _merge_held_with(monkeypatch, runner) == frozenset({channel})


def test_main_releases_a_channel_whose_yes_verdict_is_the_newest(monkeypatch):
    # control for the merge-mode ranking: with the yes posted after the no,
    # the channel's ruling is made and the merge lands it
    runner, _channel = _held_merge_fixture("2026-10-20T12:00:00Z")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    assert _merge_held_with(monkeypatch, runner) == frozenset()


def test_main_awaiting_review_survives_a_failed_ref_fetch(monkeypatch, capsys):
    # the queue fetch is best-effort: a failure warns on stderr and the
    # unjudged list still prints on stdout, exit 0
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps([{"number": 488, "headRefName": "pricelog/openrouter-488"}]),
    )
    runner.on("api user", output="cldbot\n")
    runner.on("issues/488/comments", output=_comments())
    runner.on("ls-remote", output="a" * 40 + "\trefs/heads/x\n")
    runner.on("git fetch", failure=pr.PrError("network"))
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    monkeypatch.setattr(merge_verified, "_settled_no_heads", lambda *a, **k: frozenset())
    assert merge_verified.main(["--awaiting-review", "10"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "488 pricelog/openrouter-488\n"
    assert captured.err == (
        "::warning::the pricelog ref fetch failed: network;"
        " the queue used the refs the checkout fetched\n"
    )


def test_main_awaiting_review_skips_the_fetch_when_every_pr_is_judged(monkeypatch, capsys):
    # no no-marked candidate means nothing to settle: no ref fetch, empty list
    head = "a" * 40
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps([{"number": 553, "headRefName": "pricelog/yes-553", "headRefOid": head}]),
    )
    runner.on("api user", output="cldbot\n")
    runner.on(
        "issues/553/comments", output=_comments(("cldbot", f"verified\n\nautomerge: yes {head}"))
    )
    runner.on("ls-remote", output=head + "\trefs/heads/x\n")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    assert merge_verified.main(["--awaiting-review", "10"]) == 0
    assert capsys.readouterr().out == ""
    assert not any("fetch" in " ".join(cmd) for cmd, _cwd in runner.calls)


def test_announce_index_wraps_a_malformed_url(tmp_path):
    # a hand-edited index url that urlsplit cannot parse is a named stop, and
    # the name carries the rejected url: the source alone leaves the owner
    # guessing which of a channel set broke the merge
    runner = FakeRunner()
    runner.on(
        "HEAD:state/announce/index.json",
        output=json.dumps(
            {
                "perplexity": {
                    "https://[foo": {"file": "x", "sha256": "a" * 64, "fetched": "2026-10-16"}
                }
            }
        ),
    )
    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge._announce_index(runner, tmp_path, "HEAD", "base")
    assert str(excinfo.value) == (
        "base: state/announce/index.json source 'perplexity': announce channel url"
        " 'https://[foo' is unparseable: Invalid IPv6 URL"
    )


def test_main_awaiting_review_prints_nothing_for_an_empty_queue(monkeypatch, capsys):
    runner = FakeRunner()
    runner.on("pr list", output="[]")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    assert merge_verified.main(["--awaiting-review", "10"]) == 0
    assert capsys.readouterr().out == ""


def test_main_awaiting_review_keeps_stdout_machine_only_on_a_gone_ref(monkeypatch, capsys):
    # a dangling ref must skip to stderr, never into the machine list the
    # prompt pastes: a garbage queue line would flip the pass's -s guard and
    # run a pass on nothing
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps([{"number": 279, "headRefName": "pricelog/gone-12345678"}]),
    )
    runner.on("pricelog/gone-12345678", output="")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    assert merge_verified.main(["--awaiting-review", "10"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "skipping pricelog/gone-12345678" in captured.err


@pytest.mark.parametrize(
    "argv", [["--awaiting-review"], ["--awaiting-review", "0"], ["--awaiting-review", "ten"]]
)
def test_main_awaiting_review_rejects_a_bad_limit(argv, monkeypatch):
    # a bad limit must return 2 before any command runs: a regression that
    # accepted it would shell out to the real gh pr list from the test's cwd
    runner = FakeRunner()
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    assert merge_verified.main(argv) == 2
    assert runner.calls == []


# a GITHUB_TOKEN push starts no workflow run, so the published index rebuilt
# only on a human push: 2026-09-24 10:59 -> 09-29 00:19 carried ~30 bot
# merges and zero publish runs. the merge step dispatches publish itself
# once its push landed (a dispatch event starts a run even from the bot)


def _yes_marked_pr(runner: FakeRunner) -> None:
    head = "a" * 40
    runner.on(
        "pr list",
        output=json.dumps(
            [{"number": 197, "headRefName": "pricelog/stale-99999999", "headRefOid": head}]
        ),
    )
    runner.on("api user", output="cldbot\n")
    runner.on("issues/197/comments", output=_comments(("cldbot", f"automerge: yes {head}")))
    runner.on("repo view", output="mommy\n")
    runner.on("pricelog/stale-99999999", output=head + "\n")


def _dispatches(runner: FakeRunner) -> list[list[str]]:
    return [cmd for cmd, _cwd in runner.calls if cmd[:2] == ["gh", "workflow"]]


def test_main_dispatches_publish_after_a_pushed_merge(monkeypatch):
    runner = FakeRunner()
    _yes_marked_pr(runner)
    runner.on("workflow run publish.yml", output="")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    monkeypatch.setattr(automerge, "merge_branches", lambda *a, **k: ("f" * 40, []))
    assert merge_verified.main([]) == 0
    assert _dispatches(runner) == [["gh", "workflow", "run", "publish.yml", "--ref", "mommy"]]


def test_main_never_dispatches_publish_when_nothing_merged(monkeypatch):
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps([{"number": 197, "headRefName": "pricelog/stale-99999999"}]),
    )
    runner.on("api user", output="cldbot\n")
    runner.on("issues/197/comments", output=_comments(("cldbot", "needs human\n\nautomerge: no")))
    runner.on("pricelog/stale-99999999", output="a" * 40 + "\n")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    assert merge_verified.main([]) == 0
    assert _dispatches(runner) == []


def test_main_never_dispatches_publish_when_the_merge_refuses(monkeypatch):
    # an AutoMergeError (a refused merge, e.g. the claim gate) must return 1
    # and never dispatch: the pre-merge tip must not publish
    runner = FakeRunner()
    _yes_marked_pr(runner)
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)

    def _refuse(*a, **k):
        raise automerge.AutoMergeError("refused")

    monkeypatch.setattr(automerge, "merge_branches", _refuse)
    assert merge_verified.main([]) == 1
    assert _dispatches(runner) == []


def test_main_dispatches_publish_after_merge_branches_returns(monkeypatch):
    # the publish must follow the pushed merge, never precede it or follow a
    # refused one: record the two in call order
    runner = FakeRunner()
    _yes_marked_pr(runner)
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    events: list[str] = []

    def _fake_merge(branches, repo_root, runner_arg, base, push, held_channels=None):
        events.append("merge_branches")
        return ("f" * 40, [])

    def _fake_dispatch(runner_arg, repo_root, base):
        events.append("dispatch")

    monkeypatch.setattr(automerge, "merge_branches", _fake_merge)
    monkeypatch.setattr(merge_verified, "_dispatch_publish", _fake_dispatch)
    assert merge_verified.main([]) == 0
    assert events == ["merge_branches", "dispatch"]


def test_main_keeps_the_merge_when_the_publish_dispatch_fails(monkeypatch, capsys):
    # the push already landed: a failed dispatch only delays the site to the
    # next pushing merge, so it warns in the run and never reads as a failed
    # merge (that would open a false `merge step failed` ping)
    runner = FakeRunner()
    _yes_marked_pr(runner)
    runner.on(
        "workflow run publish.yml",
        failure=pr.PrError("HTTP 403: Resource not accessible by integration"),
    )
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    monkeypatch.setattr(automerge, "merge_branches", lambda *a, **k: ("f" * 40, []))
    assert merge_verified.main([]) == 0
    assert "::warning::" in capsys.readouterr().out


def test_dispatch_publish_warning_names_the_cause(capsys, tmp_path):
    # a permanent refusal reads like a transient 5xx without the cause; the
    # warning must carry it so the owner can tell which one it is
    runner = FakeRunner()
    runner.on(
        "workflow run publish.yml",
        failure=pr.PrError("HTTP 403: Resource not accessible by integration"),
    )
    merge_verified._dispatch_publish(runner, tmp_path, "mommy")
    assert capsys.readouterr().out == (
        "::warning::the publish dispatch failed: HTTP 403: Resource not accessible by"
        " integration; the published index waits for the next pushing merge or a"
        " manual publish.yml dispatch\n"
    )


def test_dispatch_publish_warning_escapes_a_multiline_cause(capsys, tmp_path):
    # workflow commands are line-based: a raw newline in the stderr tail ends
    # the annotation at its first line, so the data escapes %, CR and LF
    runner = FakeRunner()
    runner.on(
        "workflow run publish.yml",
        failure=pr.PrError("HTTP 502: Bad Gateway\r\nretry 100% later\nbye"),
    )
    merge_verified._dispatch_publish(runner, tmp_path, "mommy")
    assert capsys.readouterr().out == (
        "::warning::the publish dispatch failed: HTTP 502: Bad Gateway%0D%0Aretry 100%25"
        " later%0Abye; the published index waits for the next pushing merge or a"
        " manual publish.yml dispatch\n"
    )

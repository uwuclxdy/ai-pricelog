"""merge_verified tests: the pure halves of the disposition-driven merge."""

from __future__ import annotations

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
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps([{"number": 197, "headRefName": "pricelog/stale-99999999"}]),
    )
    runner.on("api user", output="cldbot\n")
    runner.on(
        "pr view 197",
        output=json.dumps(
            {
                "comments": [
                    {
                        "author": {"login": "cldbot"},
                        "body": "automerge: yes",
                        "createdAt": "2026-09-18T11:00:00Z",
                    }
                ]
            }
        ),
    )
    runner.on("repo view", output="mommy\n")
    runner.on("pricelog/stale-99999999", output="a" * 40 + "\n")
    runner.on("workflow run publish.yml", output="")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    calls: list[tuple[list[str], str, bool]] = []

    def _fake_merge(branches, repo_root, runner_arg, base, push, held_channels=None):
        calls.append((branches, base, push))
        return ("f" * 40, [])

    monkeypatch.setattr(automerge, "merge_branches", _fake_merge)
    assert merge_verified.main([]) == 0
    assert calls == [(["pricelog/stale-99999999"], "mommy", True)]


def test_main_skips_an_open_pr_whose_ref_is_deleted(monkeypatch, capsys):
    # a sibling run merged a PR and deleted its branch while github has not
    # closed it yet: the open list still names it, but there is nothing to
    # merge. the run must skip it, never red on the dangling ref (observed
    # 2026-09-20: the 19:00 run red'd on an 18:55 PR mid-close)
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps(
            [
                {"number": 278, "headRefName": "pricelog/gone-12345678"},
                {"number": 279, "headRefName": "pricelog/live-87654321"},
            ]
        ),
    )
    runner.on("api user", output="cldbot\n")
    runner.on(
        "pr view 278",
        output=json.dumps(
            {
                "comments": [
                    {
                        "author": {"login": "cldbot"},
                        "body": "automerge: yes",
                        "createdAt": "2026-09-20T19:05:00Z",
                    }
                ]
            }
        ),
    )
    runner.on(
        "pr view 279",
        output=json.dumps(
            {
                "comments": [
                    {
                        "author": {"login": "cldbot"},
                        "body": "automerge: yes",
                        "createdAt": "2026-09-20T19:05:00Z",
                    }
                ]
            }
        ),
    )
    runner.on("repo view", output="mommy\n")
    runner.on("pricelog/gone-12345678", output="")
    runner.on("pricelog/live-87654321", output="a" * 40 + "\trefs/heads/pricelog/live-87654321\n")
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
        "pr view 279",
        output=json.dumps(
            {
                "comments": [
                    {
                        "author": {"login": "cldbot"},
                        "body": "automerge: yes",
                        "createdAt": "2026-09-20T19:05:00Z",
                    }
                ]
            }
        ),
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


def test_held_channels_flags_a_no_pr_channel_that_differs_from_the_base(tmp_path):
    # a needs-human PR carries the run's fresh snapshot for the channel the
    # pass flagged; its sha differs from the base, so the channel is held
    url = "https://example.com/changelog"
    file = announce.channel_files("perplexity", [url])[url]
    base_index = json.dumps(
        {"perplexity": {url: {"file": file, "sha256": "a" * 64, "fetched": "2026-10-15"}}}
    )
    no_index = json.dumps(
        {"perplexity": {url: {"file": file, "sha256": "b" * 64, "fetched": "2026-10-16"}}}
    )
    runner = FakeRunner()
    runner.on("HEAD:state/announce/index.json", output=base_index)
    runner.on("origin/pricelog/no-12345678:state/announce/index.json", output=no_index)
    candidates = [(552, "pricelog/no-12345678"), (553, "pricelog/yes-87654321")]
    dispositions = {552: False, 553: True}
    assert merge_verified._held_channels(runner, tmp_path, candidates, dispositions) == frozenset(
        {("perplexity", url)}
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


def _comments(*entries: tuple[str, str]) -> str:
    return json.dumps(
        {
            "comments": [
                {"author": {"login": login}, "body": body, "createdAt": "2026-10-14T19:05:00Z"}
                for login, body in entries
            ]
        }
    )


def test_main_awaiting_review_prints_the_queue(monkeypatch, capsys):
    runner = FakeRunner()
    runner.on(
        "pr list",
        output=json.dumps(
            [
                {"number": 488, "headRefName": "pricelog/openrouter-488"},
                {"number": 460, "headRefName": "pricelog/anthropic-460"},
                {"number": 414, "headRefName": "pricelog/anthropic-414"},
                {"number": 400, "headRefName": "pricelog/openrouter-400"},
                {"number": 399, "headRefName": "feature/human"},
            ]
        ),
    )
    runner.on("api user", output="cldbot\n")
    runner.on("pr view 488", output=_comments())
    runner.on("pr view 460", output=_comments(("cldbot", "needs human\n\nautomerge: no")))
    # a bot comment with no marker line is an unfinished review: it queues
    runner.on("pr view 414", output=_comments(("cldbot", "**claude pass review** (partial)")))
    # a human's marker is not the pass's disposition: it queues
    runner.on("pr view 400", output=_comments(("uwuclxdy", "automerge: yes")))
    runner.on("ls-remote", output="a" * 40 + "\trefs/heads/x\n")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    monkeypatch.setattr(
        automerge,
        "merge_branches",
        lambda *a, **k: pytest.fail("listing the queue must never merge"),
    )
    assert merge_verified.main(["--awaiting-review", "10"]) == 0
    assert capsys.readouterr().out == (
        "400 pricelog/openrouter-400\n414 pricelog/anthropic-414\n488 pricelog/openrouter-488\n"
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
    runner.on(
        "pr list",
        output=json.dumps([{"number": 197, "headRefName": "pricelog/stale-99999999"}]),
    )
    runner.on("api user", output="cldbot\n")
    runner.on("pr view 197", output=_comments(("cldbot", "automerge: yes")))
    runner.on("repo view", output="mommy\n")
    runner.on("pricelog/stale-99999999", output="a" * 40 + "\n")


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
    runner.on("pr view 197", output=_comments(("cldbot", "needs human\n\nautomerge: no")))
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

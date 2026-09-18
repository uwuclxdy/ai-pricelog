"""merge_verified tests: the pure halves of the disposition-driven merge."""

from __future__ import annotations

import json

from ai_pricelog import automerge, merge_verified, pr
from conftest import FakeRunner


def test_parse_disposition_yes():
    comments = [
        ("uwuclxdybot", "**claude pass review — verified**\n\nall rows re-read.\n\nautomerge: yes")
    ]
    assert merge_verified.parse_disposition(comments, "uwuclxdybot") is True


def test_parse_disposition_no():
    comments = [("@uwuclxdy", "bot wall; nothing to decide\n\nautomerge: no")]
    assert merge_verified.parse_disposition(comments, "@uwuclxdy") is False


def test_parse_disposition_absent_marker_is_none():
    comments = [("uwuclxdybot", "**claude pass review — findings**\nno marker here")]
    assert merge_verified.parse_disposition(comments, "uwuclxdybot") is None


def test_parse_disposition_last_bot_comment_wins():
    comments = [
        ("uwuclxdybot", "automerge: yes"),
        ("human", "automerge: no"),
        ("uwuclxdybot", "automerge: no"),
    ]
    assert merge_verified.parse_disposition(comments, "uwuclxdybot") is False
    assert merge_verified.parse_disposition(list(reversed(comments)), "uwuclxdybot") is True


def test_parse_disposition_ignores_non_bot_authors():
    comments = [("human", "automerge: yes"), ("other", "automerge: no")]
    assert merge_verified.parse_disposition(comments, "uwuclxdybot") is None


def test_parse_disposition_requires_a_marker_line():
    # a mid-line mention is prose, not the machine line the merge step reads
    body = "the automerge: yes marker is what the merge step reads"
    assert merge_verified.parse_disposition([("uwuclxdybot", body)], "uwuclxdybot") is None


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
    runner.on("api user", output="uwuclxdybot\n")
    runner.on(
        "pr view 197",
        output=json.dumps(
            {
                "comments": [
                    {
                        "author": {"login": "uwuclxdybot"},
                        "body": "automerge: yes",
                        "createdAt": "2026-09-18T11:00:00Z",
                    }
                ]
            }
        ),
    )
    runner.on("repo view", output="mommy\n")
    monkeypatch.setattr(pr.PrRunner, "run", runner.run)
    calls: list[tuple[list[str], str, bool]] = []

    def _fake_merge(branches, repo_root, runner_arg, base, push):
        calls.append((branches, base, push))
        return ("f" * 40, [])

    monkeypatch.setattr(automerge, "merge_branches", _fake_merge)
    assert merge_verified.main([]) == 0
    assert calls == [(["pricelog/stale-99999999"], "mommy", True)]

"""merge_verified tests: the pure halves of the disposition-driven merge."""

from __future__ import annotations

from ai_pricelog import merge_verified, pr


def test_parse_pr_urls_reads_the_real_log_line():
    line = (
        "INFO:ai_pricelog.pipeline:opened pr for deepseek:"
        " https://github.com/uwuclxdy/ai-pricelog/pull/191"
    )
    assert merge_verified.parse_pr_urls(line) == [191]


def test_parse_pr_urls_tolerates_noise_lines():
    text = "\n".join(
        [
            "INFO:ai_pricelog.pipeline:watchdog run complete",
            "WARNING:ai_pricelog.pipeline:detect skip for databricks: unmapped name",
            "announce change: deepseek https://api-docs.deepseek.com/updates/ abcdef12 -> fedcba21",
            "Traceback (most recent call last):",
        ]
    )
    assert merge_verified.parse_pr_urls(text) == []


def test_parse_pr_urls_keeps_order_across_prs():
    text = "\n".join(
        [
            "INFO:ai_pricelog.pipeline:opened pr for deepseek:"
            " https://github.com/uwuclxdy/ai-pricelog/pull/191",
            "INFO:ai_pricelog.pipeline:opened pr for zai:"
            " https://github.com/uwuclxdy/ai-pricelog/pull/190",
            "INFO:ai_pricelog.pipeline:opened pr for openrouter:"
            " https://github.com/uwuclxdy/ai-pricelog/pull/192",
        ]
    )
    assert merge_verified.parse_pr_urls(text) == [191, 190, 192]


def test_parse_pr_urls_ignores_non_pull_urls():
    text = (
        "INFO:ai_pricelog.pipeline:opened pr for deepseek:"
        " https://github.com/uwuclxdy/ai-pricelog/actions/runs/34592012203"
    )
    assert merge_verified.parse_pr_urls(text) == []


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
        # an earlier run's PR, marked yes by that run's pass: not this run's
        (197, "pricelog/stale-99999999"),
    ]
    dispositions = {191: True, 192: True, 193: True, 195: None, 196: False, 197: True}
    assert merge_verified.eligible_branches(open_prs, [191, 192, 193, 195, 196], dispositions) == [
        "pricelog/deepseek-abc12345"
    ]


def test_eligible_branches_orders_by_pr_number():
    open_prs = [(192, "pricelog/b-later"), (191, "pricelog/a-earlier")]
    assert merge_verified.eligible_branches(open_prs, [191, 192], {191: True, 192: True}) == [
        "pricelog/a-earlier",
        "pricelog/b-later",
    ]


def test_main_usage_error():
    assert merge_verified.main([]) == 2


def test_main_no_prs_exits_zero_before_any_gh_call(monkeypatch, tmp_path, capsys):
    log = tmp_path / "run.log"
    log.write_text("INFO:ai_pricelog.pipeline:watchdog run complete\n", encoding="utf-8")

    def _no_network(self, cmd, cwd):
        raise AssertionError(f"network call {cmd} before the empty-run check")

    monkeypatch.setattr(pr.PrRunner, "run", _no_network)
    assert merge_verified.main([str(log)]) == 0
    assert capsys.readouterr().out == "no opened PRs in the run log; nothing to merge\n"

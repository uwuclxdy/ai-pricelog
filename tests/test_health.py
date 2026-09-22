"""provider-health checker tests: log classification and the ping gate."""

from __future__ import annotations

from ai_pricelog import health


def test_parse_log_hard_failures():
    lines = [
        "ERROR:ai_pricelog.pipeline:detector for anthropic failed",
        "Traceback (most recent call last):",
        "ai_pricelog.web.FetchError: no model pricing table on https://x",
        "ERROR:ai_pricelog.pipeline:detector for ai21 failed",
        "ERROR:ai_pricelog.pipeline:scraper ai21 failed for jamba-mini",
        "ERROR:ai_pricelog.pipeline:refresh scrape failed for glm-5.2 (databricks)",
        "ERROR:ai_pricelog.pipeline:openrouter fetch failed",
    ]
    issues = health.parse_log(lines)
    assert set(issues) == {"anthropic", "ai21", "databricks", "openrouter"}
    assert len(issues["anthropic"]["hard"]) == 1
    assert issues["anthropic"]["soft"] == []
    assert len(issues["ai21"]["hard"]) == 2
    assert issues["openrouter"]["hard"]


def test_parse_log_soft_skips():
    lines = [
        "WARNING:ai_pricelog.detectors.databricks_page:detect skip for databricks:"
        " unmapped model name 'GLM-6' on https://x",
        "WARNING:ai_pricelog.openrouter:parse skip for openrouter: data[0] is not an object",
        "WARNING:ai_pricelog.pipeline:entry x failed validation for zai: bad row",
        "WARNING:ai_pricelog.pipeline:refresh for k3 skipped in moonshot: bad row",
    ]
    issues = health.parse_log(lines)
    assert issues["databricks"]["soft"] and issues["databricks"]["hard"] == []
    assert issues["openrouter"]["soft"] and issues["openrouter"]["hard"] == []
    assert issues["zai"]["soft"]
    assert issues["moonshot"]["soft"]


def test_parse_log_ignores_unmatched_lines():
    assert health.parse_log(["INFO:ai_pricelog.pipeline:opened pr for deepseek: url"]) == {}


def test_warning_none_when_clean():
    assert health.warning({}) is None


def test_warning_lists_classes():
    # a provider with both classes lists under hard only: the soft side is
    # the report for providers that stay alive
    now = {
        "anthropic": {"hard": ["a"], "soft": []},
        "databricks": {"hard": [], "soft": ["b"]},
        "zai": {"hard": ["c"], "soft": ["d"]},
    }
    assert health.warning(now) == ("::warning::hard failures: anthropic, zai; skips: databricks")


def test_warning_hard_only_without_soft():
    now = {"anthropic": {"hard": ["a"], "soft": []}}
    assert "skips:" not in health.warning(now)


def test_providers_to_ping_two_consecutive_hard():
    now = {"anthropic": {"hard": ["a"], "soft": []}, "databricks": {"hard": [], "soft": ["b"]}}
    prev = {"anthropic": {"hard": ["c"], "soft": []}, "databricks": {"hard": [], "soft": ["d"]}}
    assert health.providers_to_ping(now, prev) == {"anthropic"}


def test_providers_to_ping_soft_only_never_pings():
    now = {"databricks": {"hard": [], "soft": ["b"]}}
    prev = {"databricks": {"hard": [], "soft": ["d"]}}
    assert health.providers_to_ping(now, prev) == set()


def test_providers_to_ping_missing_in_prev():
    now = {"anthropic": {"hard": ["a"], "soft": []}}
    assert health.providers_to_ping(now, {}) == set()


def test_main_prints_warning_without_gh_env(monkeypatch, tmp_path, capsys):
    log_file = tmp_path / "run.log"
    log_file.write_text("ERROR:ai_pricelog.pipeline:detector for anthropic failed\n")
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    assert health.main([str(log_file)]) == 0
    assert "hard failures: anthropic" in capsys.readouterr().out


def test_main_usage_error():
    assert health.main([]) == 2


def test_close_recovered_closes_only_passed_providers(monkeypatch):
    calls: list[list[str]] = []
    rows = (
        '[{"number": 1, "title": "provider broken: ai21"},'
        ' {"number": 2, "title": "provider broken: digitalocean"},'
        ' {"number": 3, "title": "review pass dead"}]'
    )
    monkeypatch.setattr(health, "_gh", lambda args: calls.append(args) or rows)
    now = {"digitalocean": {"hard": ["a"], "soft": []}}
    assert health.close_recovered(now) == ["provider broken: ai21"]
    assert calls == [
        ["issue", "list", "--state", "open", "--json", "number,title"],
        [
            "issue",
            "close",
            "1",
            "--comment",
            "recovered: `ai21` detects and scrapes clean again",
        ],
    ]


def test_close_recovered_skips_broken_issue_list_failure(monkeypatch):
    monkeypatch.setattr(health, "_gh", lambda args: "not json")
    assert health.close_recovered({}) == []


def test_sync_pass_dead_issue_opens_once(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        health,
        "_gh",
        lambda args: (
            calls.append(args)
            or (
                '[{"number": 7, "title": "review pass dead"}]'
                if args[0] == "issue" and args[1] == "list"
                else ""
            )
        ),
    )
    run_url = "https://github.com/uwuclxdy/ai-pricelog/actions/runs/42"
    assert health.sync_pass_dead_issue("dead", run_url) is None
    assert [c for c in calls if c[:2] != ["issue", "list"]] == []
    # now with no open issue: it creates one
    calls.clear()
    monkeypatch.setattr(health, "_gh", lambda args: calls.append(args) or "[]")
    assert health.sync_pass_dead_issue("dead", run_url) == "opened"
    created = next(c for c in calls if c[1] == "create")
    assert created[3] == "review pass dead"
    assert "ANTHROPIC_BASE_URL" in created[5] and run_url in created[5]


def test_sync_pass_dead_issue_closes_on_alive(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        health,
        "_gh",
        lambda args: (
            calls.append(args)
            or ('[{"number": 7, "title": "review pass dead"}]' if args[1] == "list" else "")
        ),
    )
    assert health.sync_pass_dead_issue("alive", "https://x/actions/runs/42") == "closed"
    assert calls[-1] == [
        "issue",
        "close",
        "7",
        "--comment",
        "the pass completed clean on a data-changing run; closing",
    ]


def test_sync_pass_dead_issue_none_untouched(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(health, "_gh", lambda args: calls.append(args) or "[]")
    assert health.sync_pass_dead_issue(None, "https://x/actions/runs/42") is None
    assert calls == []


def test_main_pass_dead_flag_opens_ping_issue(monkeypatch, tmp_path):
    # drives main() end to end: the --pass-dead flag must reach the issue
    # sync as "dead" (the one-line wiring a direct sync call cannot pin)
    calls: list[list[str]] = []
    log_path = tmp_path / "run.log"
    log_path.write_text("", encoding="utf-8")

    def gh(args: list[str]) -> str:
        calls.append(args)
        return '{"workflow_runs": []}' if args[0] == "api" else "[]"

    monkeypatch.setattr(health, "_gh", gh)
    monkeypatch.setenv("GITHUB_REPOSITORY", "uwuclxdy/ai-pricelog")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    assert health.main([str(log_path), "--pass-dead"]) == 0
    created = [c for c in calls if c[:2] == ["issue", "create"]]
    assert len(created) == 1
    assert created[0][3] == "review pass dead"


def test_sync_pass_dead_issue_list_failure_never_creates(monkeypatch):
    # a broken listing must read as "cannot dedupe", never as "no issue
    # open": creating on a broken list would duplicate the ping every run
    calls: list[list[str]] = []
    monkeypatch.setattr(health, "_gh", lambda args: calls.append(args) or "not json")
    assert health.sync_pass_dead_issue("dead", "https://x/actions/runs/42") is None
    assert [c for c in calls if c[:2] == ["issue", "create"]] == []


def test_sync_merge_dead_issue_opens_once(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        health,
        "_gh",
        lambda args: (
            calls.append(args)
            or (
                '[{"number": 9, "title": "merge step failed"}]'
                if args[0] == "issue" and args[1] == "list"
                else ""
            )
        ),
    )
    run_url = "https://github.com/uwuclxdy/ai-pricelog/actions/runs/43"
    assert health.sync_merge_dead_issue("dead", run_url) is None
    assert [c for c in calls if c[:2] != ["issue", "list"]] == []
    calls.clear()
    monkeypatch.setattr(health, "_gh", lambda args: calls.append(args) or "[]")
    assert health.sync_merge_dead_issue("dead", run_url) == "opened"
    created = next(c for c in calls if c[1] == "create")
    assert created[3] == "merge step failed"
    assert "names the branch and the fix" in created[5] and run_url in created[5]


def test_sync_merge_dead_issue_closes_on_alive(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        health,
        "_gh",
        lambda args: (
            calls.append(args)
            or ('[{"number": 9, "title": "merge step failed"}]' if args[1] == "list" else "")
        ),
    )
    assert health.sync_merge_dead_issue("alive", "https://x/actions/runs/43") == "closed"
    assert calls[-1] == [
        "issue",
        "close",
        "9",
        "--comment",
        "the merge step completed clean on a data-changing run; closing",
    ]


def test_sync_merge_dead_issue_none_untouched(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(health, "_gh", lambda args: calls.append(args) or "[]")
    assert health.sync_merge_dead_issue(None, "https://x/actions/runs/43") is None
    assert calls == []


def test_main_merge_dead_flag_opens_ping_issue(monkeypatch, tmp_path):
    # drives main() end to end: both flag families ride one invocation (the
    # health step passes the pass and the merge state together)
    calls: list[list[str]] = []
    log_path = tmp_path / "run.log"
    log_path.write_text("", encoding="utf-8")

    def gh(args: list[str]) -> str:
        calls.append(args)
        return '{"workflow_runs": []}' if args[0] == "api" else "[]"

    monkeypatch.setattr(health, "_gh", gh)
    monkeypatch.setenv("GITHUB_REPOSITORY", "uwuclxdy/ai-pricelog")
    monkeypatch.setenv("GITHUB_RUN_ID", "43")
    assert health.main([str(log_path), "--pass-alive", "--merge-dead"]) == 0
    created = [c for c in calls if c[:2] == ["issue", "create"]]
    assert len(created) == 1
    assert created[0][3] == "merge step failed"


def test_main_rejects_bad_flags(tmp_path):
    log_path = tmp_path / "run.log"
    log_path.write_text("", encoding="utf-8")
    assert health.main([str(log_path), "--nope"]) == 2
    assert health.main([str(log_path), "--pass-dead", "--pass-alive"]) == 2
    assert health.main([str(log_path), "--merge-dead", "--merge-dead"]) == 2

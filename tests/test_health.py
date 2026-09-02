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
        "WARNING:ai_pricelog.pipeline:entry x failed validation for zai: bad row",
        "WARNING:ai_pricelog.pipeline:refresh for k3 skipped in moonshot: bad row",
    ]
    issues = health.parse_log(lines)
    assert issues["databricks"]["soft"] and issues["databricks"]["hard"] == []
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
    assert health.warning(now) == (
        "::warning::hard failures: anthropic, zai; detect skips: databricks"
    )


def test_warning_hard_only_without_soft():
    now = {"anthropic": {"hard": ["a"], "soft": []}}
    assert "detect skips" not in health.warning(now)


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

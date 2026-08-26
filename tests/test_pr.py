import hashlib
import json
from pathlib import Path

import pytest

from ai_pricelog import pr
from conftest import FakeRunner


def _sha8(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def spec(**overrides) -> pr.PrSpec:
    values = dict(
        source="deepseek",
        model_id="deepseek-chat",
        provider="DeepSeek",
        source_url="https://api-docs.deepseek.com/quick_start/pricing",
        rows=(
            {
                "source": "deepseek",
                "model_id": "deepseek-chat",
                "observed_at": "2026-08-26",
                "input_mtok": 0.27,
                "output_mtok": 1.1,
            },
        ),
    )
    values.update(overrides)
    return pr.PrSpec(**values)


def test_branch_name_slug_and_sha8():
    assert pr.branch_name("deepseek/deepseek-chat") == (
        f"pricelog/deepseek-deepseek-chat-{_sha8('deepseek/deepseek-chat')}"
    )
    assert pr.branch_name("a") == f"pricelog/a-{_sha8('a')}"
    # the slug carries no slash, so one id can no longer be a path prefix of
    # another on the remote
    assert "/" not in pr.branch_name("a/b")[len("pricelog/") :]
    # refname-hostile characters are still sanitized
    assert pr.branch_name("dots-studio/dots-3-note-preview:free") == (
        f"pricelog/dots-studio-dots-3-note-preview-free-"
        f"{_sha8('dots-studio/dots-3-note-preview:free')}"
    )


def test_branch_name_digest_disambiguates_slug_collisions():
    # different ids that slug to the same string get different branches
    assert pr.branch_name("a/b") != pr.branch_name("a-b")


def test_spec_branch():
    assert spec().branch == pr.branch_name("deepseek-chat")
    assert spec(seed=True).branch == "pricelog/seed"


def test_spec_titles():
    assert spec().title == "Add deepseek-chat pricing for DeepSeek"
    assert spec(update=True).title == "Update deepseek-chat pricing for DeepSeek"
    assert spec(seed=True).title == "Seed price history"


def test_spec_body_disclosure_is_first_and_linked_to_the_run():
    s = spec(run_url="https://github.com/uwuclxdy/ai-pricelog/actions/runs/123")
    body = s.body
    assert body.startswith(
        "- **opened automatically by the [GitHub Action]"
        "(https://github.com/uwuclxdy/ai-pricelog/actions/runs/123).**"
    )


def test_spec_body_disclaimer_falls_back_to_actions_tab():
    assert "[GitHub Action](https://github.com/uwuclxdy/ai-pricelog/actions)." in spec().body


def test_spec_body_flat_row_table():
    body = spec().body
    assert "## new rows" in body
    assert "| deepseek | `deepseek-chat` | 2026-08-26 | 0.27 | — | 1.1 | — |" in body
    assert "source: https://api-docs.deepseek.com/quick_start/pricing" in body


def test_spec_body_peak_row():
    row = {
        "source": "deepseek",
        "model_id": "deepseek-v4-flash",
        "observed_at": "2026-08-26",
        "input_mtok": 0.22,
        "output_mtok": 0.66,
        "peak_input_mtok": 0.44,
        "peak_output_mtok": 1.32,
        "peak_windows": [["01:00:00Z", "04:00:00Z"]],
    }
    body = spec(model_id="deepseek-v4-flash", rows=(row,)).body
    assert "| 0.44/1.32 01:00:00Z - 04:00:00Z |" in body


def test_spec_body_review_checklist():
    body = spec().body
    assert "## review checklist" in body
    assert "- [ ] prices verified against the source page" in body
    assert "- [ ] provider name correct" in body
    assert "- [ ] peak/off-peak rates match the page" in body


def test_spec_body_seed_snapshot_line():
    rows = (
        {
            "source": "deepseek",
            "model_id": "a",
            "observed_at": "2026-08-26",
            "input_mtok": 0.1,
            "output_mtok": 0.2,
        },
        {
            "source": "zai",
            "model_id": "b",
            "observed_at": "2026-08-26",
            "input_mtok": 0.3,
            "output_mtok": 0.4,
        },
    )
    body = spec(seed=True, source_url="", rows=rows).body
    assert "first price-history snapshot: 2 rows across 2 sources." in body
    assert "source: " not in body


def test_run_url_from_env(monkeypatch):
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "uwuclxdy/ai-pricelog")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    assert pr.run_url_from_env() == "https://github.com/uwuclxdy/ai-pricelog/actions/runs/123"


def test_run_url_from_env_missing_env_is_none(monkeypatch):
    for var in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"):
        monkeypatch.delenv(var, raising=False)
    assert pr.run_url_from_env() is None


def test_default_branch_reads_the_api():
    fake = FakeRunner().on("gh repo view", output="main\n")
    assert pr.default_branch(fake, Path(".")) == "main"
    (cmd, _cwd) = fake.calls[0]
    assert "defaultBranchRef" in cmd
    assert ".defaultBranchRef.name" in cmd


def test_open_pull_requests_parses_fields():
    fake = FakeRunner().on(
        "gh pr list",
        output=(
            '[{"title": "Add X pricing", "body": "records x rows", '
            '"headRefName": "pricelog/x-12345678"}]\n'
        ),
    )
    assert pr.open_pull_requests(fake, Path(".")) == [
        pr.OpenPr("Add X pricing", "records x rows", "pricelog/x-12345678")
    ]


def test_open_pull_requests_uses_limit_and_json_fields():
    fake = FakeRunner().on("gh pr list", output="[]\n")
    assert pr.open_pull_requests(fake, Path(".")) == []
    (cmd, _cwd) = fake.calls[0]
    assert cmd[0:3] == ["gh", "pr", "list"]
    assert "--state" in cmd and "open" in cmd
    assert "--limit" in cmd and "100" in cmd
    assert "--json" in cmd and "title,body,headRefName" in cmd
    assert "--repo" not in cmd


def test_pending_pr_title_match_is_case_insensitive():
    open_prs = [pr.OpenPr("Add DEEPSEEK-CHAT pricing for DeepSeek", "", "pricelog/x-12345678")]
    assert pr.pending_pr("deepseek-chat", open_prs) is True


def test_pending_pr_body_match():
    open_prs = [pr.OpenPr("t", "records deepseek-chat rows", "")]
    assert pr.pending_pr("deepseek-chat", open_prs) is True


def test_pending_pr_empty_list_is_false():
    assert pr.pending_pr("deepseek-chat", []) is False


def test_seed_pending_matches_head_ref():
    open_prs = [pr.OpenPr("Seed price history", "", "pricelog/seed")]
    assert pr.seed_pending(open_prs) is True
    assert pr.seed_pending([pr.OpenPr("Add x pricing", "", "pricelog/x-12345678")]) is False
    assert pr.seed_pending([]) is False


def test_open_pull_requests_rejects_invalid_json():
    fake = FakeRunner().on("gh pr list", output="{oops\n")
    with pytest.raises(pr.PrError, match="invalid json"):
        pr.open_pull_requests(fake, Path("."))


def test_fetch_pending_rows_no_remote_returns_empty():
    fake = FakeRunner().on("git fetch", failure=pr.PrError("no such remote: origin"))
    assert pr.fetch_pending_rows(fake, Path("."), "data/history.ndjson", []) == []


def test_fetch_pending_rows_reads_branch_histories():
    lines = (
        '{"source": "deepseek", "model_id": "x", "observed_at": "t", "url": "u"}\n'
        '{"source": "deepseek", "model_id": "y", "observed_at": "t", "url": "u"}\n'
    )
    fake = (
        FakeRunner()
        .on("git fetch")
        .on("git for-each-ref", output="refs/remotes/pending/x-12345678\n")
        .on("git show", output=lines)
    )
    open_prs = [pr.OpenPr("Add x pricing", "", "pricelog/x-12345678")]
    assert pr.fetch_pending_rows(fake, Path("."), "data/history.ndjson", open_prs) == [
        json.loads(line) for line in lines.splitlines()
    ]


def test_fetch_pending_rows_skips_branch_without_history():
    fake = (
        FakeRunner()
        .on("git fetch")
        .on("git for-each-ref", output="refs/remotes/pending/bad\n")
        .on("git show", failure=pr.PrError("path does not exist in the tree"))
    )
    open_prs = [pr.OpenPr("Add bad pricing", "", "pricelog/bad")]
    assert pr.fetch_pending_rows(fake, Path("."), "data/history.ndjson", open_prs) == []


def test_fetch_pending_rows_skips_branches_without_open_pr():
    # a closed pr keeps its branch on origin; its head ref is no longer in
    # the open-pr list, so its rows must not ride any future pr branch
    open_lines = '{"source": "deepseek", "model_id": "x", "observed_at": "t", "url": "u"}\n'
    closed_lines = '{"source": "deepseek", "model_id": "stale", "observed_at": "t", "url": "u"}\n'
    fake = (
        FakeRunner()
        .on("git fetch")
        .on(
            "git for-each-ref",
            output="refs/remotes/pending/open-12345678\nrefs/remotes/pending/closed-12345678\n",
        )
        .on("git show refs/remotes/pending/open", output=open_lines)
        .on("git show refs/remotes/pending/closed", output=closed_lines)
    )
    open_prs = [pr.OpenPr("Add x pricing", "", "pricelog/open-12345678")]
    assert pr.fetch_pending_rows(fake, Path("."), "data/history.ndjson", open_prs) == [
        json.loads(open_lines)
    ]


def test_fetch_pending_rows_fetch_is_forced_and_pruned():
    fake = FakeRunner().on("git fetch").on("git for-each-ref", output="")
    pr.fetch_pending_rows(fake, Path("."), "data/history.ndjson", [])
    (cmd, _cwd) = fake.calls[0]
    assert cmd == [
        "git",
        "fetch",
        "origin",
        "+refs/heads/pricelog/*:refs/remotes/pending/*",
        "--prune",
    ]


def test_open_pr_uses_spec_title_and_body():
    fake = FakeRunner().on(
        "gh pr create", output="https://github.com/uwuclxdy/ai-pricelog/pull/3\n"
    )
    s = spec()
    url = pr.open_pr("main", s.branch, s, fake, Path("."))
    assert url == "https://github.com/uwuclxdy/ai-pricelog/pull/3"
    (cmd, _cwd) = fake.calls[0]
    assert cmd[0:3] == ["gh", "pr", "create"]
    assert "--draft" in cmd
    assert cmd[cmd.index("--base") + 1] == "main"
    assert cmd[cmd.index("--head") + 1] == pr.branch_name("deepseek-chat")
    assert cmd[cmd.index("--title") + 1] == s.title
    assert cmd[cmd.index("--body") + 1] == s.body

import pytest

from ai_pricelog import pr
from conftest import FakeRunner


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


def test_branch_name_sanitizes():
    assert pr.branch_name("deepseek/deepseek-chat") == "pricelog/deepseek/deepseek-chat"
    assert pr.branch_name("dots-studio/dots-3-note-preview:free") == (
        "pricelog/dots-studio/dots-3-note-preview-free"
    )
    assert pr.branch_name("a/b_c-d.e") == "pricelog/a/b_c-d.e"


def test_spec_branch():
    assert spec().branch == "pricelog/deepseek-chat"
    assert spec(seed=True).branch == "pricelog/seed"


def test_spec_titles():
    assert spec().title == "Add deepseek-chat pricing for DeepSeek"
    assert spec(update=True).title == "Update deepseek-chat pricing for DeepSeek"
    assert spec(seed=True).title == "Seed price history"


def test_spec_body_disclosure_is_first_and_linked_to_the_run():
    s = spec(run_url="https://github.com/uwuclxdy/ai-pricelog/actions/runs/123")
    body = s.body
    assert body.startswith(
        "- **opened automatically by the [GitHub Action](https://github.com/uwuclxdy/"
        "ai-pricelog/actions/runs/123) from https://github.com/uwuclxdy/ai-pricelog.**"
    )


def test_spec_body_disclaimer_falls_back_to_actions_tab():
    assert "[GitHub Action](https://github.com/uwuclxdy/ai-pricelog/actions) from" in spec().body


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
    assert pr.default_branch(fake) == "main"
    (cmd, _cwd) = fake.calls[0]
    assert "defaultBranchRef" in cmd
    assert ".defaultBranchRef.name" in cmd


def test_pending_pr_title_match_is_case_insensitive():
    fake = FakeRunner().on(
        "gh pr list",
        output='[{"title": "Add DEEPSEEK-CHAT pricing for DeepSeek", "body": ""}]\n',
    )
    assert pr.pending_pr("deepseek-chat", fake) is True
    (cmd, _cwd) = fake.calls[0]
    assert cmd[0:3] == ["gh", "pr", "list"]
    assert "--state" in cmd and "open" in cmd
    assert "--json" in cmd and "title,body" in cmd
    assert "--repo" not in cmd


def test_pending_pr_body_match():
    fake = FakeRunner().on(
        "gh pr list", output='[{"title": "t", "body": "records deepseek-chat rows"}]\n'
    )
    assert pr.pending_pr("deepseek-chat", fake) is True


def test_pending_pr_empty_list_is_false():
    fake = FakeRunner().on("gh pr list", output="[]\n")
    assert pr.pending_pr("deepseek-chat", fake) is False


def test_pending_pr_rejects_invalid_json():
    fake = FakeRunner().on("gh pr list", output="{oops\n")
    with pytest.raises(pr.PrError, match="invalid json"):
        pr.pending_pr("deepseek-chat", fake)


def test_open_pr_uses_spec_title_and_body():
    fake = FakeRunner().on(
        "gh pr create", output="https://github.com/uwuclxdy/ai-pricelog/pull/3\n"
    )
    s = spec()
    url = pr.open_pr("main", s.branch, s, fake)
    assert url == "https://github.com/uwuclxdy/ai-pricelog/pull/3"
    (cmd, _cwd) = fake.calls[0]
    assert cmd[0:3] == ["gh", "pr", "create"]
    assert "--draft" in cmd
    assert cmd[cmd.index("--base") + 1] == "main"
    assert cmd[cmd.index("--head") + 1] == "pricelog/deepseek-chat"
    assert cmd[cmd.index("--title") + 1] == s.title
    assert cmd[cmd.index("--body") + 1] == s.body

import pytest

from ai_pricelog import pr
from ai_pricelog.config import Config
from conftest import FakeRunner


def spec(**overrides) -> pr.PrSpec:
    values = dict(
        key="deepseek",
        model_id="deepseek-v4-pro",
        entry_id="deepseek-v4-pro",
        vendor_yml="deepseek.yml",
        vendor_name="Deepseek",
        vendor_entry="  - id: deepseek-v4-pro\n",
        vendor_input_mtok=0.22,
        vendor_output_mtok=0.66,
        vendor_peak_input_mtok=None,
        vendor_peak_output_mtok=None,
        vendor_peak_windows=(),
        skipped_latest=(),
        source_url="https://api-docs.deepseek.com/quick_start/pricing",
        openrouter_entry="  - id: deepseek/deepseek-v4-pro\n",
        openrouter_slug="deepseek/deepseek-v4-pro",
        openrouter_input_mtok=0.22,
        openrouter_output_mtok=0.66,
        openrouter_cache_read_mtok=0.003625,
        openrouter_note="",
    )
    values.update(overrides)
    return pr.PrSpec(**values)


def test_parse_github_url_good():
    assert pr.parse_github_url("https://github.com/octo/genai-prices") == ("octo", "genai-prices")


@pytest.mark.parametrize(
    "repo",
    [
        "https://gitlab.com/octo/genai-prices",
        "https://github.com/octo",
        "https://github.com/octo/genai-prices/issues/1",
        "https://github.com/octo/genai-prices/",
        "https://github.com//genai-prices",
        "not-a-url",
    ],
)
def test_parse_github_url_bad(repo):
    with pytest.raises(pr.PrError):
        pr.parse_github_url(repo)


def test_branch_name_sanitizes():
    assert pr.branch_name("deepseek/deepseek-chat") == "autopr/deepseek/deepseek-chat"
    assert pr.branch_name("My Model!v2") == "autopr/My-Model-v2"
    assert pr.branch_name("a/b_c-d.e") == "autopr/a/b_c-d.e"


def test_spec_branch():
    assert spec(key="deepseek", model_id="deepseek-chat").branch == "autopr/deepseek/deepseek-chat"


def test_spec_title_with_openrouter():
    assert spec().title == "Add deepseek-v4-pro pricing for Deepseek and OpenRouter"


def test_spec_title_vendor_only():
    assert (
        spec(openrouter_entry=None, openrouter_note="absent").title
        == "Add deepseek-v4-pro pricing for Deepseek"
    )


def test_pending_pr_url():
    fake = FakeRunner().on(
        "gh pr list", output="https://github.com/pydantic/genai-prices/pull/42\n"
    )
    assert pr.pending_pr("grok-4.6", fake) == "https://github.com/pydantic/genai-prices/pull/42"
    (cmd, _cwd) = fake.calls[0]
    assert cmd[0:3] == ["gh", "pr", "list"]
    assert "--repo" in cmd and "pydantic/genai-prices" in cmd
    assert "--state" in cmd and "open" in cmd
    assert "--search" in cmd and cmd[cmd.index("--search") + 1] == "grok-4.6 in:title,body"
    assert "--json" in cmd and "url" in cmd
    assert "--jq" in cmd and ".[0].url" in cmd


def test_pending_pr_empty_is_none():
    fake = FakeRunner().on("gh pr list", output="\n")
    assert pr.pending_pr("grok-4.6", fake) is None


def test_spec_body_flat_vendor_table():
    body = spec().body
    assert "Add `deepseek-v4-pro` pricing for Deepseek." in body
    assert "## Deepseek" in body
    assert "| model | input (/1M) | output (/1M) |" in body
    assert "| `deepseek-v4-pro` | 0.22 | 0.66 |" in body
    assert "source: https://api-docs.deepseek.com/quick_start/pricing" in body


def test_spec_body_split_pricing_table():
    body = spec(
        vendor_input_mtok=0.22,
        vendor_output_mtok=0.66,
        vendor_peak_input_mtok=0.44,
        vendor_peak_output_mtok=1.32,
        vendor_peak_windows=(("01:00:00Z", "04:00:00Z"), ("06:00:00Z", "10:00:00Z")),
    ).body
    assert "| `deepseek-v4-pro` off-peak | 0.22 | 0.66 |" in body
    assert (
        "| `deepseek-v4-pro` peak 01:00:00Z - 04:00:00Z and 06:00:00Z - 10:00:00Z | 0.44 | 1.32 |"
        in body
    )


def test_spec_body_openrouter_table():
    body = spec().body
    assert "## OpenRouter" in body
    assert "| model | input (/1M) | cache read (/1M) | output (/1M) |" in body
    assert "| `deepseek/deepseek-v4-pro` | 0.22 | 0.003625 | 0.66 |" in body
    assert "source: https://openrouter.ai/api/v1/models" in body


def test_spec_body_free_openrouter_row():
    body = spec(
        openrouter_input_mtok=None, openrouter_output_mtok=None, openrouter_cache_read_mtok=None
    ).body
    assert "| `deepseek/deepseek-v4-pro` | free | — | — |" in body


def test_spec_body_openrouter_deferral():
    body = spec(openrouter_entry=None, openrouter_note="`deepseek/deepseek-v4-pro` is absent").body
    assert "## OpenRouter" in body
    assert "`deepseek/deepseek-v4-pro` is absent" in body
    assert "| model | input (/1M) | cache read (/1M) | output (/1M) |" not in body


def test_spec_body_cache_read_note():
    assert (
        "- no cache-read pricing on the vendor page: the vendor entry carries no `cache_read_mtok`"
        in spec().body
    )


def test_spec_body_closed_draft_note():
    assert (
        "- closing this draft settles the model in the watchdog's state; it will "
        "not re-candidate on its own" in spec().body
    )


def test_spec_body_skipped_latest_note():
    body = spec(skipped_latest=("deepseek-v4-pro-latest",)).body
    assert (
        "- `-latest` alias clauses skipped: `deepseek-v4-pro-latest` "
        "(family/version aliases, not separately priced models)" in body
    )
    assert "`-latest` alias clauses skipped" not in spec().body


def test_spec_body_disclaimer():
    body = spec(run_url="https://github.com/uwuclxdy/ai-pricelog/actions/runs/123").body
    assert (
        "- **opened automatically by the [GitHub Action](https://github.com/uwuclxdy/"
        "ai-pricelog/actions/runs/123) from https://github.com/uwuclxdy/"
        "ai-pricelog.** i read replies and will review the prices before "
        "marking it ready." in body
    )


def test_spec_body_disclaimer_falls_back_to_actions_tab():
    body = spec().body
    assert "[GitHub Action](https://github.com/uwuclxdy/ai-pricelog/actions) from" in body


def test_spec_body_review_checklist():
    body = spec().body
    assert "## review checklist" in body
    assert "- [ ] rates verified against the pricing page" in body
    assert "- [ ] provider name checked" in body


def test_run_url_from_env(monkeypatch):
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "uwuclxdy/ai-pricelog")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    assert pr.run_url_from_env() == "https://github.com/uwuclxdy/ai-pricelog/actions/runs/123"


def test_run_url_from_env_missing_env_is_none(monkeypatch):
    for var in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"):
        monkeypatch.delenv(var, raising=False)
    assert pr.run_url_from_env() is None


def test_existing_pr_parses_url():
    fake = FakeRunner().on("gh pr list", output="https://github.com/octo/genai-prices/pull/42\n")
    assert pr.existing_pr("octo", "genai-prices", "autopr/deepseek/x", fake) == (
        "https://github.com/octo/genai-prices/pull/42"
    )
    (cmd, _cwd) = fake.calls[0]
    assert "--head" in cmd and "autopr/deepseek/x" in cmd


def test_existing_pr_empty_is_none():
    fake = FakeRunner().on("gh pr list", output="\n")
    assert pr.existing_pr("octo", "genai-prices", "autopr/deepseek/x", fake) is None


def test_push_or_fork_forks_on_403(tmp_path):
    fake = (
        FakeRunner()
        .on("gh auth", output="")
        .on("git push origin", failure=pr.PrError("push failed", stderr="remote: 403 Forbidden"))
        .on("gh api user", output="octocat\n")
        .on(
            "gh api repos/octocat/genai-prices --jq",
            output="https://github.com/octocat/genai-prices\n",
        )
        .on("git remote add", output="")
        .on("git push fork", output="")
    )
    owner = pr.push_or_fork(
        "https://github.com/octo/genai-prices", "autopr/deepseek/x", tmp_path, fake
    )
    assert owner == "octocat"
    cmds = [" ".join(cmd) for cmd, _cwd in fake.calls]
    fork_cmd = "git remote add fork https://github.com/octocat/genai-prices"
    assert any(fork_cmd in c for c in cmds)
    assert any("git push fork autopr/deepseek/x" in c for c in cmds)


def test_push_or_fork_creates_the_fork_when_absent(tmp_path):
    fake = (
        FakeRunner()
        .on("gh auth", output="")
        .on("git push origin", failure=pr.PrError("push failed", stderr="remote: denied!"))
        .on("gh api user", output="octocat\n")
        .on("gh api repos/octocat/genai-prices --jq", failure=pr.PrError("not found"))
        .on(
            "gh api repos/octo/genai-prices/forks",
            output="https://github.com/octocat/genai-prices\n",
        )
        .on("git remote add", output="")
        .on("git push fork", output="")
    )
    owner = pr.push_or_fork(
        "https://github.com/octo/genai-prices", "autopr/deepseek/x", tmp_path, fake
    )
    assert owner == "octocat"
    cmds = [" ".join(cmd) for cmd, _cwd in fake.calls]
    assert any("gh api repos/octo/genai-prices/forks -X POST" in c for c in cmds)


def test_push_or_fork_denied_word_takes_fork_path(tmp_path):
    fake = (
        FakeRunner()
        .on("gh auth", output="")
        .on("git push origin", failure=pr.PrError("push failed", stderr="remote: denied!"))
        .on("gh api user", output="octocat\n")
        .on(
            "gh api repos/octocat/genai-prices --jq",
            output="https://github.com/octocat/genai-prices\n",
        )
        .on("git remote add", output="")
        .on("git push fork", output="")
    )
    owner = pr.push_or_fork(
        "https://github.com/octo/genai-prices", "autopr/deepseek/x", tmp_path, fake
    )
    assert owner == "octocat"


def test_push_or_fork_direct_push(tmp_path):
    fake = FakeRunner().on("gh auth", output="").on("git push origin", output="")
    owner = pr.push_or_fork(
        "https://github.com/octo/genai-prices", "autopr/deepseek/x", tmp_path, fake
    )
    assert owner == "octo"
    cmds = [" ".join(cmd) for cmd, _cwd in fake.calls]
    assert not any("gh repo fork" in c for c in cmds)


def test_push_or_fork_other_error_raises(tmp_path):
    fake = (
        FakeRunner()
        .on("gh auth", output="")
        .on("git push origin", failure=pr.PrError("push failed", stderr="fatal: network down"))
    )
    with pytest.raises(pr.PrError, match="push failed") as exc_info:
        pr.push_or_fork("https://github.com/octo/genai-prices", "autopr/deepseek/x", tmp_path, fake)
    assert "network down" in exc_info.value.stderr


def test_open_draft_pr_returns_existing_without_preparing(tmp_path, monkeypatch):
    fake = FakeRunner().on("gh pr list", output="https://github.com/octo/genai-prices/pull/7\n")
    cfg = Config(repo="https://github.com/octo/genai-prices", providers=(), cap=1)
    prepared = []
    monkeypatch.setattr("ai_pricelog.build.prepare", lambda *args: prepared.append(args))
    url = pr.open_draft_pr(cfg, "main", tmp_path / "slot", spec(), fake)
    assert url == "https://github.com/octo/genai-prices/pull/7"
    assert prepared == []
    assert not any(cmd[0] == "git" for cmd, _cwd in fake.calls)


def test_open_draft_pr_prepares_pushes_and_opens(tmp_path, monkeypatch):
    fake = (
        FakeRunner()
        .on("gh pr list", output="\n")
        .on("gh auth", output="")
        .on("gh pr create", output="https://github.com/octo/genai-prices/pull/9\n")
    )
    cfg = Config(repo="https://github.com/octo/genai-prices", providers=(), cap=1)
    prepared = []
    monkeypatch.setattr("ai_pricelog.build.prepare", lambda *args: prepared.append(args))
    monkeypatch.setattr(pr, "push_or_fork", lambda repo_url, branch, slot, runner: "octo")
    slot = tmp_path / "slot"
    url = pr.open_draft_pr(cfg, "main", slot, spec(), fake)
    assert url == "https://github.com/octo/genai-prices/pull/9"
    assert prepared == [(slot, "main", spec(), fake)]
    (cmd, _cwd) = fake.calls[-1]
    assert cmd[:3] == ["gh", "pr", "create"]
    assert "--draft" in cmd
    assert "--repo" in cmd and "octo/genai-prices" in cmd
    assert "--head" in cmd and "octo:autopr/deepseek/deepseek-v4-pro" in cmd
    assert "--title" in cmd and "Add deepseek-v4-pro pricing for Deepseek and OpenRouter" in cmd
    body = cmd[cmd.index("--body") + 1]
    assert "| `deepseek-v4-pro` | 0.22 | 0.66 |" in body


def test_open_pr_uses_spec_title_and_body():
    spec_ = spec()
    fake = FakeRunner().on("gh pr create", output="https://github.com/octo/genai-prices/pull/3\n")
    url = pr.open_pr("octo", "genai-prices", "main", spec_.branch, "octo", spec_, fake)
    assert url == "https://github.com/octo/genai-prices/pull/3"
    (cmd, _cwd) = fake.calls[0]
    assert cmd[cmd.index("--title") + 1] == spec_.title
    assert cmd[cmd.index("--body") + 1] == spec_.body


def update(**overrides) -> pr.UpdateSpec:
    values = dict(
        model_id="deepseek-chat",
        case="rate_change",
        prices_section="    prices:\n      - prices: {}\n",
        deviation="the target's never-overwrite rule is followed",
        old_input_mtok=0.2,
        old_output_mtok=0.4,
        old_peak_input_mtok=None,
        old_peak_output_mtok=None,
        old_peak_windows=(),
        input_mtok=0.27,
        output_mtok=1.1,
        peak_input_mtok=None,
        peak_output_mtok=None,
        peak_windows=(),
        start_date="2026-08-24",
        or_prices_section=None,
        or_note="`deepseek/deepseek-chat` is not listed on the api",
    )
    values.update(overrides)
    return pr.UpdateSpec(**values)


def test_update_spec_branch_and_title():
    s = spec(entry_id="deepseek-chat", update=update())
    assert s.branch == "autopr/update/deepseek/deepseek-chat"
    assert s.title == "Update deepseek-chat pricing for Deepseek"


def test_update_spec_title_with_openrouter_mirror():
    s = spec(entry_id="deepseek-chat", update=update(or_prices_section="    prices:\n"))
    assert s.title == "Update deepseek-chat pricing for Deepseek and OpenRouter"


def test_update_body_names_the_caveats():
    s = spec(entry_id="deepseek-chat", update=update())
    body = s.body
    assert "Update `deepseek-chat` pricing for Deepseek." in body
    assert "| `deepseek-chat` old | 0.2 | 0.4 |" in body
    assert "| `deepseek-chat` new | 0.27 | 1.1 |" in body
    assert "start_date is set to 2026-08-24" in body
    assert "actual effective date is unknown" in body
    assert "the target's never-overwrite rule is followed." in body
    assert "`deepseek/deepseek-chat` is not listed on the api" in body
    assert "re-candidates the update" in body


def test_update_body_review_checklist():
    body = spec(entry_id="deepseek-chat", update=update()).body
    assert "- [ ] rates verified against the pricing page" in body
    assert "- [ ] start_date corrected to the provider's effective date" in body
    assert "- [ ] changelog cited beside start_date" in body
    assert "correct it and cite the changelog" not in body


def test_update_body_split_conversion_table():
    s = spec(
        entry_id="deepseek-chat",
        update=update(
            case="conversion",
            peak_input_mtok=0.4,
            peak_output_mtok=0.8,
            peak_windows=(("01:00:00Z", "04:00:00Z"),),
        ),
    )
    body = s.body
    assert "| `deepseek-chat` old off-peak | 0.2 | 0.4 |" in body
    assert "| `deepseek-chat` new off-peak | 0.27 | 1.1 |" in body
    assert "| `deepseek-chat` new peak 01:00:00Z - 04:00:00Z | 0.4 | 0.8 |" in body


def test_or_only_spec_branch_title_body():
    s = spec(
        model_id="deepseek-chat",
        entry_id="deepseek/deepseek-chat",
        vendor_yml="openrouter.yml",
        vendor_name="OpenRouter",
        vendor_entry=None,
        openrouter_slug="deepseek/deepseek-chat",
    )
    assert s.branch == "autopr/or/deepseek/deepseek-chat"
    assert s.title == "Add deepseek/deepseek-chat pricing for OpenRouter"
    body = s.body
    assert "Add `deepseek/deepseek-chat` to openrouter.yml." in body
    assert "only fills the openrouter entry" in body
    assert "## notes" in body
    assert "| `deepseek/deepseek-chat` | 0.22 | 0.003625 | 0.66 |" in body
    assert "- [ ] rates verified against the OpenRouter API" in body


def test_or_only_update_body_review_checklist():
    s = spec(
        entry_id="deepseek/deepseek-chat",
        update=update(or_only=True, old_cache_read_mtok=0.02, cache_read_mtok=0.04),
    )
    body = s.body
    assert "- [ ] rates verified against the OpenRouter API" in body
    assert "- [ ] start_date corrected to the mirror's actual effective date" in body
    assert "correct it before marking ready" not in body


def test_update_body_old_peak_row_surfaces_window_change():
    s = spec(
        entry_id="deepseek-chat",
        update=update(
            case="replace",
            old_peak_input_mtok=0.4,
            old_peak_output_mtok=0.8,
            old_peak_windows=(("00:30:00Z", "16:30:00Z"),),
            peak_input_mtok=0.4,
            peak_output_mtok=0.8,
            peak_windows=(("01:00:00Z", "04:00:00Z"),),
        ),
    )
    body = s.body
    assert "| `deepseek-chat` old peak 00:30:00Z - 16:30:00Z | 0.4 | 0.8 |" in body
    assert "| `deepseek-chat` new peak 01:00:00Z - 04:00:00Z | 0.4 | 0.8 |" in body

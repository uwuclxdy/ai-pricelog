import json
from pathlib import Path

import pytest

from conftest import FakeRunner, git, git_init_repo
from litellm_autopr import pr
from litellm_autopr.config import Config

PRICES = Path("model_prices_and_context_window.json")


class GitRealGhScripted:
    """real git subprocesses, scripted gh calls."""

    def __init__(self, scripted: FakeRunner) -> None:
        self.scripted = scripted
        self.real = pr.PrRunner()

    def run(self, cmd: list[str], cwd: Path) -> str:
        if cmd[0] == "gh":
            return self.scripted.run(cmd, cwd)
        return self.real.run(cmd, cwd)


@pytest.fixture
def seeded_repo(tmp_path):
    def make(entries: dict):
        src = tmp_path / "src"
        git_init_repo(src)
        (src / PRICES).write_text(json.dumps(entries, indent=2) + "\n")
        git(src, "add", str(PRICES))
        git(src, "commit", "-m", "seed")
        return src

    return make


def test_parse_github_url_good():
    assert pr.parse_github_url("https://github.com/octo/litellm") == ("octo", "litellm")


@pytest.mark.parametrize(
    "repo",
    [
        "https://gitlab.com/octo/litellm",
        "https://github.com/octo",
        "https://github.com/octo/litellm/issues/1",
        "https://github.com/octo/litellm/",
        "https://github.com//litellm",
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


def test_prepare_branch_writes_entry_and_commits(tmp_path, seeded_repo):
    src = seeded_repo({"deepseek/deepseek-chat": {"input_cost_per_token": 0.1}})
    scripted = FakeRunner().on("gh api user", output="octocat\n")
    runner = GitRealGhScripted(scripted)
    entry = {"input_cost_per_token": 0.2}
    slot = pr.prepare_branch(
        tmp_path / "work",
        str(src),
        "main",
        "autopr/deepseek/new-model",
        "deepseek/new-model",
        entry,
        PRICES,
        runner,
    )
    assert slot is not None
    data = json.loads((slot / PRICES).read_text())
    assert list(data) == ["deepseek/deepseek-chat", "deepseek/new-model"]
    assert data["deepseek/new-model"] == entry
    assert (slot / PRICES).read_text().endswith("\n")
    assert git(slot, "branch", "--show-current").strip() == "autopr/deepseek/new-model"
    assert git(slot, "log", "--format=%s", "-1").strip() == "add deepseek/new-model pricing"
    assert git(slot, "config", "user.name").strip() == "octocat"
    assert git(slot, "config", "user.email").strip() == "octocat@users.noreply.github.com"


def test_prepare_branch_noop_when_entry_identical(tmp_path, seeded_repo):
    entry = {"input_cost_per_token": 0.1}
    src = seeded_repo({"deepseek/deepseek-chat": entry})
    scripted = FakeRunner()
    runner = GitRealGhScripted(scripted)
    slot = pr.prepare_branch(
        tmp_path / "work",
        str(src),
        "main",
        "autopr/deepseek/deepseek-chat",
        "deepseek/deepseek-chat",
        entry,
        PRICES,
        runner,
    )
    assert slot is None
    assert scripted.calls == []
    cloned = tmp_path / "work" / "autopr" / "deepseek" / "deepseek-chat"
    assert git(cloned, "log", "--format=%s", "-1").strip() == "seed"


def test_existing_pr_parses_url():
    fake = FakeRunner().on("gh pr list", output="https://github.com/octo/litellm/pull/42\n")
    assert pr.existing_pr("octo", "litellm", "autopr/deepseek/x", fake) == (
        "https://github.com/octo/litellm/pull/42"
    )
    (cmd, _cwd) = fake.calls[0]
    assert "--head" in cmd and "autopr/deepseek/x" in cmd


def test_existing_pr_empty_is_none():
    fake = FakeRunner().on("gh pr list", output="\n")
    assert pr.existing_pr("octo", "litellm", "autopr/deepseek/x", fake) is None


def test_push_or_fork_forks_on_403(tmp_path):
    fake = (
        FakeRunner()
        .on("gh auth", output="")
        .on("git push origin", failure=pr.PrError("push failed", stderr="remote: 403 Forbidden"))
        .on("gh repo fork", output="https://github.com/octocat/litellm-fork\n")
        .on("git remote add", output="")
        .on("git push fork", output="")
    )
    owner = pr.push_or_fork("https://github.com/octo/litellm", "autopr/deepseek/x", tmp_path, fake)
    assert owner == "octocat"
    cmds = [" ".join(cmd) for cmd, _cwd in fake.calls]
    assert any("git remote add fork https://github.com/octocat/litellm-fork" in c for c in cmds)
    assert any("git push fork autopr/deepseek/x" in c for c in cmds)


def test_push_or_fork_denied_word_takes_fork_path(tmp_path):
    fake = (
        FakeRunner()
        .on("gh auth", output="")
        .on("git push origin", failure=pr.PrError("push failed", stderr="remote: denied!"))
        .on("gh repo fork", output="https://github.com/octocat/litellm-fork\n")
        .on("git remote add", output="")
        .on("git push fork", output="")
    )
    owner = pr.push_or_fork("https://github.com/octo/litellm", "autopr/deepseek/x", tmp_path, fake)
    assert owner == "octocat"


def test_push_or_fork_direct_push(tmp_path):
    fake = FakeRunner().on("gh auth", output="").on("git push origin", output="")
    owner = pr.push_or_fork("https://github.com/octo/litellm", "autopr/deepseek/x", tmp_path, fake)
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
        pr.push_or_fork("https://github.com/octo/litellm", "autopr/deepseek/x", tmp_path, fake)
    assert "network down" in exc_info.value.stderr


def test_open_draft_pr_returns_existing_without_touching_workdir(tmp_path):
    fake = (
        FakeRunner()
        .on("gh api", output="main\n")
        .on("gh pr list", output="https://github.com/octo/litellm/pull/7\n")
    )
    cfg = Config(repo="https://github.com/octo/litellm", providers=(), cap=1)
    workdir = tmp_path / "work"
    url = pr.open_draft_pr(cfg, "deepseek/deepseek-chat", {}, "https://src.example", workdir, fake)
    assert url == "https://github.com/octo/litellm/pull/7"
    assert not workdir.exists()
    assert not any(cmd[0] == "git" for cmd, _cwd in fake.calls)


def test_open_draft_pr_returns_empty_when_entry_already_merged(tmp_path, seeded_repo, monkeypatch):
    # prepare_branch no-ops (entry identical upstream) -> "" and no pr create
    entry = {"input_cost_per_token": 0.1}
    src = seeded_repo({"deepseek/deepseek-chat": entry})
    monkeypatch.setattr(pr, "parse_github_url", lambda repo: ("octo", "litellm"))
    fake = FakeRunner().on("gh api", output="main\n").on("gh pr list", output="\n")
    runner = GitRealGhScripted(fake)
    cfg = Config(repo=str(src), providers=(), cap=1)
    url = pr.open_draft_pr(
        cfg, "deepseek/deepseek-chat", entry, "https://src.example", tmp_path / "work", runner
    )
    assert url == ""
    assert not any(cmd[:3] == ["gh", "pr", "create"] for cmd, _cwd in fake.calls)
    assert not any(cmd[:2] == ["git", "push"] for cmd, _cwd in fake.calls)

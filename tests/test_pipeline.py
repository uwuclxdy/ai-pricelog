import json
import logging
import sys
import types
from pathlib import Path

import pytest

from conftest import git, git_init_repo, register_fake_module
from litellm_autopr import config, litellm, pipeline, pr
from litellm_autopr.pricing import Pricing
from litellm_autopr.state import load as load_state


def pricing() -> Pricing:
    return Pricing(2.7e-07, 1.1e-06, "chat", 65536)


class PipelineRunner:
    """gh calls scripted, git subprocesses real (all local, offline)."""

    def __init__(self, existing_prs: dict[str, str] | None = None) -> None:
        self.real = pr.PrRunner()
        self.calls: list[tuple[list[str], Path]] = []
        self.pr_urls: list[str] = []
        self.existing_prs = existing_prs or {}

    def run(self, cmd: list[str], cwd: Path) -> str:
        self.calls.append((cmd, cwd))
        if cmd[0] == "gh":
            if cmd[1] == "api":
                return "octocat\n" if cmd[2] == "user" else "main\n"
            if cmd[1] == "pr" and cmd[2] == "list":
                head = cmd[cmd.index("--head") + 1]
                url = self.existing_prs.get(head)
                return f"{url}\n" if url else "\n"
            if cmd[1] == "pr" and cmd[2] == "create":
                url = f"https://github.com/octo/litellm/pull/{len(self.pr_urls) + 1}"
                self.pr_urls.append(url)
                return url + "\n"
            if cmd[1] == "auth":
                return ""
            if cmd[1] == "repo":
                return ""
        if cmd[:3] == ["git", "config", "user.email"] and len(cmd) == 3:
            return ""
        return self.real.run(cmd, cwd)


def make_provider_cfg(key: str) -> config.ProviderCfg:
    return config.ProviderCfg(
        key=key,
        provider=key,
        namespace=key,
        detector="fake_det",
        detector_url="https://example.com/models",
        scraper="fake_scr",
        scraper_url="https://example.com/pricing",
    )


def make_cfg(repo: Path, cap: int, keys: tuple[str, ...]) -> config.Config:
    providers = tuple(make_provider_cfg(k) for k in keys)
    return config.Config(repo=str(repo), providers=providers, cap=cap)


@pytest.fixture
def fake_modules(monkeypatch):
    detect_controls: dict[str, object] = {}
    scrape_controls: dict[str, dict[str, object]] = {}

    def detect(cfg):
        if cfg.key not in detect_controls:
            raise AssertionError(f"unscripted detect for {cfg.key}")
        result = detect_controls[cfg.key]
        if isinstance(result, Exception):
            raise result
        return list(result)

    def scrape(cfg, model_id):
        entries = scrape_controls.get(cfg.key, {})
        if model_id not in entries:
            raise AssertionError(f"unscripted scrape for {cfg.key}/{model_id}")
        result = entries[model_id]
        if isinstance(result, Exception):
            raise result
        return result

    for kind in ("detectors", "scrapers"):
        register_fake_module(monkeypatch, kind, "placeholder")
    det = types.ModuleType("litellm_autopr.detectors.fake_det")
    det.detect = detect
    scr = types.ModuleType("litellm_autopr.scrapers.fake_scr")
    scr.scrape = scrape
    monkeypatch.setitem(sys.modules, "litellm_autopr.detectors.fake_det", det)
    monkeypatch.setitem(sys.modules, "litellm_autopr.scrapers.fake_scr", scr)
    return detect_controls, scrape_controls


@pytest.fixture
def upstream(tmp_path):
    def make(entries: dict | None = None) -> Path:
        src = tmp_path / "upstream-src"
        git_init_repo(src)
        (src / pr.PRICES_FILE).write_text(json.dumps(entries or {}, indent=2) + "\n")
        git(src, "add", str(pr.PRICES_FILE))
        git(src, "commit", "-m", "seed")
        bare = tmp_path / "upstream.git"
        git(src, "clone", "--bare", str(src), str(bare))
        return bare

    return make


@pytest.fixture
def repo_root(tmp_path) -> Path:
    root = tmp_path / "autopr-root"
    git_init_repo(root)
    (root / "state.json").write_text(json.dumps({"providers": {}}) + "\n")
    git(root, "add", "state.json")
    git(root, "commit", "-m", "init state")
    return root


@pytest.fixture
def live() -> litellm.LitellmFile:
    return litellm.LitellmFile(
        entries={}, providers=frozenset({"deepseek"}), modes=frozenset({"chat"})
    )


@pytest.fixture
def wire(monkeypatch, live):
    monkeypatch.setattr(pr, "parse_github_url", lambda repo: ("octo", "litellm"))
    monkeypatch.setattr(litellm, "fetch_live", lambda: live)


def test_fresh_candidate_opens_pr_and_settles(tmp_path, fake_modules, upstream, repo_root, wire):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg(upstream({}), 3, ("deepseek",))
    workdir = tmp_path / "work"
    runner = PipelineRunner()

    report = pipeline.run(cfg, workdir, repo_root, runner)

    provider_report = report.providers["deepseek"]
    assert provider_report.detected == ["deepseek-chat"]
    assert provider_report.candidates == ["deepseek-chat"]
    assert [model_id for model_id, _url in provider_report.prs] == ["deepseek-chat"]
    assert provider_report.prs[0][1] == "https://github.com/octo/litellm/pull/1"
    assert provider_report.skipped_no_pricing == []
    assert provider_report.skipped_cap == []
    assert provider_report.error is None

    saved = load_state(repo_root / "state.json")
    assert saved.providers["deepseek"].last_seen == ["deepseek-chat"]
    assert saved.providers["deepseek"].handled == ["deepseek-chat"]

    subjects = git(repo_root, "log", "--format=%s").splitlines()
    assert subjects[0] == "chore: advance watchdog state"

    slot_file = workdir / "autopr" / "deepseek" / "deepseek-chat" / pr.PRICES_FILE
    entry = json.loads(slot_file.read_text())["deepseek/deepseek-chat"]
    assert entry["input_cost_per_token"] == 2.7e-07
    assert entry["litellm_provider"] == "deepseek"
    assert entry["mode"] == "chat"
    assert entry["max_tokens"] == 65536

    create_calls = [cmd for cmd, _cwd in runner.calls if cmd[:3] == ["gh", "pr", "create"]]
    assert len(create_calls) == 1
    cmd = create_calls[0]
    assert "--draft" in cmd
    assert "--repo" in cmd and "octo/litellm" in cmd
    assert "--head" in cmd and "octo:autopr/deepseek/deepseek-chat" in cmd
    assert "--title" in cmd and "add deepseek/deepseek-chat pricing" in cmd
    body = cmd[cmd.index("--body") + 1]
    assert body == "add `deepseek/deepseek-chat` pricing\n\nsource: `https://example.com/pricing`"

    second = pipeline.run(cfg, workdir, repo_root, runner)
    assert second.providers["deepseek"].candidates == []
    assert len(runner.pr_urls) == 1
    assert len(git(repo_root, "log", "--format=%s").splitlines()) == 2


def test_missing_pricing_stays_unsettled_and_retries(
    tmp_path, fake_modules, upstream, repo_root, wire
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-x"]
    scrape["deepseek"] = {"deepseek-x": None}
    cfg = make_cfg(upstream({}), 3, ("deepseek",))
    workdir = tmp_path / "work"
    runner = PipelineRunner()

    report = pipeline.run(cfg, workdir, repo_root, runner)
    provider_report = report.providers["deepseek"]
    assert provider_report.skipped_no_pricing == ["deepseek-x"]
    assert provider_report.prs == []
    saved = load_state(repo_root / "state.json")
    assert saved.providers["deepseek"].last_seen == []
    assert saved.providers["deepseek"].handled == []

    second = pipeline.run(cfg, workdir, repo_root, runner)
    assert second.providers["deepseek"].candidates == ["deepseek-x"]
    assert second.providers["deepseek"].skipped_no_pricing == ["deepseek-x"]


def test_cap_skips_without_settling(tmp_path, fake_modules, upstream, repo_root, wire):
    detect, scrape = fake_modules
    detect["deepseek"] = ["a", "b"]
    scrape["deepseek"] = {"a": pricing(), "b": pricing()}
    cfg = make_cfg(upstream({}), 1, ("deepseek",))
    workdir = tmp_path / "work"
    runner = PipelineRunner()

    report = pipeline.run(cfg, workdir, repo_root, runner)
    provider_report = report.providers["deepseek"]
    assert [model_id for model_id, _url in provider_report.prs] == ["a"]
    assert provider_report.skipped_cap == ["b"]
    saved = load_state(repo_root / "state.json")
    assert saved.providers["deepseek"].last_seen == ["a"]
    assert saved.providers["deepseek"].handled == ["a"]


def test_detector_error_does_not_block_next_provider(
    tmp_path, fake_modules, upstream, repo_root, wire
):
    detect, scrape = fake_modules
    detect["deepseek"] = RuntimeError("detector boom")
    detect["zai"] = ["zai-x"]
    scrape["zai"] = {"zai-x": None}
    cfg = make_cfg(upstream({}), 3, ("deepseek", "zai"))
    workdir = tmp_path / "work"
    runner = PipelineRunner()

    report = pipeline.run(cfg, workdir, repo_root, runner)
    assert report.providers["deepseek"].error is not None
    assert "detector boom" in report.providers["deepseek"].error
    zai_report = report.providers["zai"]
    assert zai_report.detected == ["zai-x"]
    assert zai_report.skipped_no_pricing == ["zai-x"]
    assert zai_report.error is None


def test_entry_already_in_repo_settles_without_pr(
    tmp_path, fake_modules, upstream, repo_root, wire
):
    detect, _scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    cfg = make_cfg(
        upstream({"deepseek/deepseek-chat": {"input_cost_per_token": 0.1}}),
        3,
        ("deepseek",),
    )
    workdir = tmp_path / "work"
    runner = PipelineRunner()

    report = pipeline.run(cfg, workdir, repo_root, runner)
    provider_report = report.providers["deepseek"]
    assert provider_report.prs == []
    assert provider_report.skipped_no_pricing == []
    assert runner.pr_urls == []
    saved = load_state(repo_root / "state.json")
    assert saved.providers["deepseek"].last_seen == ["deepseek-chat"]
    assert saved.providers["deepseek"].handled == []


def test_scrape_error_aborts_provider_and_retries(
    tmp_path, fake_modules, upstream, repo_root, wire
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["a", "b"]
    scrape["deepseek"] = {"a": RuntimeError("page broke"), "b": pricing()}
    cfg = make_cfg(upstream({}), 3, ("deepseek",))
    workdir = tmp_path / "work"
    runner = PipelineRunner()

    report = pipeline.run(cfg, workdir, repo_root, runner)
    provider_report = report.providers["deepseek"]
    assert provider_report.error is not None
    assert "page broke" in provider_report.error
    assert provider_report.prs == []
    saved = load_state(repo_root / "state.json")
    assert saved.providers["deepseek"].last_seen == []
    assert saved.providers["deepseek"].handled == []

    scrape["deepseek"] = {"a": pricing(), "b": pricing()}
    second = pipeline.run(cfg, workdir, repo_root, runner)
    assert [model_id for model_id, _url in second.providers["deepseek"].prs] == ["a", "b"]


def test_validation_failure_skips_candidate_and_continues(
    tmp_path, fake_modules, upstream, repo_root, wire
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["a", "b"]
    scrape["deepseek"] = {"a": Pricing(2.7e-07, 1.1e-06, "completion", 65536), "b": pricing()}
    cfg = make_cfg(upstream({}), 3, ("deepseek",))
    workdir = tmp_path / "work"
    runner = PipelineRunner()

    report = pipeline.run(cfg, workdir, repo_root, runner)

    provider_report = report.providers["deepseek"]
    assert provider_report.error is not None
    assert "mode" in provider_report.error
    assert [model_id for model_id, _url in provider_report.prs] == ["b"]
    saved = load_state(repo_root / "state.json")
    assert saved.providers["deepseek"].last_seen == ["b"]
    assert saved.providers["deepseek"].handled == ["b"]

    second = pipeline.run(cfg, workdir, repo_root, runner)
    assert second.providers["deepseek"].candidates == ["a"]


def test_pr_noop_settles_without_pr_and_cap(
    monkeypatch, tmp_path, fake_modules, upstream, repo_root, wire
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["a", "b"]
    scrape["deepseek"] = {"a": pricing(), "b": pricing()}
    cfg = make_cfg(upstream({}), 1, ("deepseek",))
    workdir = tmp_path / "work"
    runner = PipelineRunner()

    def fake_open(cfg, entry_key, entry, source_url, workdir, runner):
        if entry_key == "deepseek/a":
            return ""
        return "https://github.com/octo/litellm/pull/1"

    monkeypatch.setattr(pr, "open_draft_pr", fake_open)

    report = pipeline.run(cfg, workdir, repo_root, runner)

    provider_report = report.providers["deepseek"]
    assert [model_id for model_id, _url in provider_report.prs] == ["b"]
    assert provider_report.skipped_cap == []
    saved = load_state(repo_root / "state.json")
    assert saved.providers["deepseek"].last_seen == ["a", "b"]
    assert saved.providers["deepseek"].handled == ["b"]

    second = pipeline.run(cfg, workdir, repo_root, runner)
    assert second.providers["deepseek"].candidates == []


def test_existing_open_pr_settles_without_new_pr(tmp_path, fake_modules, upstream, repo_root, wire):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg(upstream({}), 3, ("deepseek",))
    workdir = tmp_path / "work"
    runner = PipelineRunner()

    report = pipeline.run(cfg, workdir, repo_root, runner)
    assert [model_id for model_id, _url in report.providers["deepseek"].prs] == ["deepseek-chat"]

    # simulate a crash between pr open and state write: the id stays unsettled
    (repo_root / "state.json").write_text(json.dumps({"providers": {}}) + "\n")
    url = runner.pr_urls[0]
    second_runner = PipelineRunner(existing_prs={"autopr/deepseek/deepseek-chat": url})

    second = pipeline.run(cfg, workdir, repo_root, second_runner)

    provider_report = second.providers["deepseek"]
    assert provider_report.prs == [("deepseek-chat", url)]
    assert second_runner.pr_urls == []
    create_calls = [cmd for cmd, _cwd in second_runner.calls if cmd[:3] == ["gh", "pr", "create"]]
    assert create_calls == []
    saved = load_state(repo_root / "state.json")
    assert saved.providers["deepseek"].last_seen == ["deepseek-chat"]
    assert saved.providers["deepseek"].handled == ["deepseek-chat"]


def test_noop_state_commit_logs_info_not_error(caplog, tmp_path, fake_modules, upstream, wire):
    # a gitignored, never-tracked state.json: git add refuses it, the commit is
    # a no-op and must log at INFO instead of raising
    root = tmp_path / "autopr-root"
    git_init_repo(root)
    (root / ".gitignore").write_text("state.json\n")
    (root / "state.json").write_text(json.dumps({"providers": {}}) + "\n")
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg(upstream({}), 3, ("deepseek",))
    workdir = tmp_path / "work"
    runner = PipelineRunner()

    with caplog.at_level(logging.INFO, logger="litellm_autopr.pipeline"):
        report = pipeline.run(cfg, workdir, root, runner)

    provider_report = report.providers["deepseek"]
    assert provider_report.error is None
    assert len(provider_report.prs) == 1
    assert "state commit skipped" in caplog.text
    skip_records = [r for r in caplog.records if "state commit skipped" in r.getMessage()]
    assert skip_records and all(r.levelno == logging.INFO for r in skip_records)


def test_dedup_keys_settle_without_scrape(
    tmp_path, upstream, repo_root, fake_modules, live, monkeypatch
):
    # a provider whose key spelling differs from its detected id (mistral slugs)
    # settles through the scraper's dedup_keys hook without scraping or opening
    from litellm_autopr import pipeline

    repo = upstream({"mistral/mistral-medium-2604": {"input_cost_per_token": 1e-6}})
    detect, scrape = fake_modules
    detect["mistral"] = ["mistral-medium-3-5-26-04"]
    scrape["mistral"] = {}
    scr = sys.modules["litellm_autopr.scrapers.fake_scr"]
    scr.dedup_keys = lambda namespace, model_id: [f"{namespace}/mistral-medium-2604"]
    monkeypatch.setattr(litellm, "fetch_live", lambda: live)
    cfg = make_cfg(repo, 3, ("mistral",))
    runner = PipelineRunner()

    report = pipeline.run(cfg, tmp_path / "work", repo_root, runner)

    provider_report = report.providers["mistral"]
    assert provider_report.prs == []
    assert provider_report.error is None
    assert provider_report.skipped_no_pricing == []
    saved = load_state(repo_root / "state.json")
    assert saved.providers["mistral"].last_seen == ["mistral-medium-3-5-26-04"]
    assert saved.providers["mistral"].handled == []
    create_calls = [c for c in runner.calls if c[0][1] == "pr" and c[0][2] == "create"]
    assert create_calls == []


def test_state_push_uses_github_ref_name(
    tmp_path, fake_modules, upstream, repo_root, wire, monkeypatch
):
    from litellm_autopr import pipeline

    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg(upstream({}), 3, ("deepseek",))
    monkeypatch.setenv("GITHUB_REF_NAME", "mommy")
    runner = PipelineRunner()

    report = pipeline.run(cfg, tmp_path / "work", repo_root, runner)
    assert report.providers["deepseek"].prs
    push_cmds = [c for c in runner.calls if c[0][0] == "git" and c[0][1] == "push"]
    assert push_cmds and push_cmds[-1][0] == ["git", "push", "origin", "HEAD:refs/heads/mommy"]


def test_state_push_uses_current_branch_without_env(
    tmp_path, fake_modules, upstream, repo_root, wire, monkeypatch
):
    from litellm_autopr import pipeline

    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg(upstream({}), 3, ("deepseek",))
    runner = PipelineRunner()

    report = pipeline.run(cfg, tmp_path / "work", repo_root, runner)
    assert report.providers["deepseek"].prs
    push_cmds = [c for c in runner.calls if c[0][0] == "git" and c[0][1] == "push"]
    assert push_cmds and push_cmds[-1][0] == ["git", "push", "origin", "HEAD:refs/heads/main"]


def test_state_commit_sets_identity_when_missing(tmp_path, fake_modules, upstream, repo_root, wire):
    from litellm_autopr import pipeline

    git(repo_root, "config", "--unset", "user.name")
    git(repo_root, "config", "--unset", "user.email")
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg(upstream({}), 3, ("deepseek",))
    runner = PipelineRunner()

    report = pipeline.run(cfg, tmp_path / "work", repo_root, runner)
    assert report.providers["deepseek"].prs
    assert (
        git(repo_root, "log", "--format=%an <%ae>", "-1").strip()
        == "octocat <octocat@users.noreply.github.com>"
    )

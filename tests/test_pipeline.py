import json
import sys
from pathlib import Path

import pytest

from ai_pricelog import config, openrouter, pipeline, pr, store
from ai_pricelog.pricing import Pricing
from conftest import git, git_init_repo, register_fake_module

TODAY = "2026-08-26"


def pricing(input_cost: float = 2.7e-07, output_cost: float = 1.1e-06) -> Pricing:
    return Pricing(input_cost, output_cost, "chat", 65536)


def make_provider_cfg(key: str, provider: str | None = None) -> config.ProviderCfg:
    return config.ProviderCfg(
        key=key,
        provider=provider or key.title(),
        detector="fake_det",
        detector_url="https://example.com/models",
        scraper="fake_scr",
        scraper_url="https://example.com/pricing",
    )


def make_cfg(cap: int, *keys: str) -> config.Config:
    return config.Config(providers=tuple(make_provider_cfg(k) for k in keys), cap=cap)


class PipelineRunner:
    """gh calls scripted, git subprocesses real (all local, offline)."""

    def __init__(self, open_prs: list[dict] | None = None, base: str = "main") -> None:
        self.real = pr.PrRunner()
        self.calls: list[tuple[list[str], Path]] = []
        self.pr_urls: list[str] = []
        self.created: list[tuple[str, str]] = []
        self.open_prs = open_prs or []
        self.base = base

    def run(self, cmd: list[str], cwd: Path) -> str:
        self.calls.append((cmd, cwd))
        if cmd[0] == "gh":
            if cmd[1] == "auth":
                return ""
            if cmd[1] == "api" and cmd[2] == "user":
                return "octocat\n"
            if cmd[1] == "repo" and cmd[2] == "view":
                return self.base + "\n"
            if cmd[1] == "pr" and cmd[2] == "list":
                return json.dumps(self.open_prs) + "\n"
            if cmd[1] == "pr" and cmd[2] == "create":
                url = f"https://github.com/uwuclxdy/ai-pricelog/pull/{len(self.pr_urls) + 1}"
                self.pr_urls.append(url)
                self.created.append((cmd[cmd.index("--title") + 1], cmd[cmd.index("--body") + 1]))
                return url + "\n"
        if cmd[:3] == ["git", "config", "user.email"] and len(cmd) == 3:
            return ""
        return self.real.run(cmd, cwd)


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

    det = register_fake_module(monkeypatch, "detectors", "fake_det")
    det.detect = detect
    scr = register_fake_module(monkeypatch, "scrapers", "fake_scr")
    scr.scrape = scrape
    return detect_controls, scrape_controls


@pytest.fixture(autouse=True)
def or_models(monkeypatch):
    models: list[openrouter.OpenrouterModel] = []
    monkeypatch.setattr(openrouter, "fetch_models", lambda: list(models))
    return models


@pytest.fixture
def repo_root(tmp_path) -> Path:
    root = tmp_path / "repo"
    git_init_repo(root)
    (root / "data").mkdir()
    (root / "data" / "history.ndjson").write_text("")
    (root / "data" / "index.json").write_text(json.dumps({"sources": {}}) + "\n")
    (root / "state.json").write_text(json.dumps({"providers": {}}) + "\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "init")
    bare = tmp_path / "origin.git"
    git(root, "clone", "--bare", str(root), str(bare))
    git(root, "remote", "add", "origin", str(bare))
    return root


def seed_store(repo_root: Path, rows: list[dict], state: dict | None = None) -> None:
    """Commit a prior store snapshot on the default branch (the merged-PR end state)."""
    store.save(rows, repo_root / "data" / "history.ndjson")
    store.write_index(rows, repo_root / "data" / "index.json")
    if state is not None:
        (repo_root / "state.json").write_text(json.dumps(state) + "\n")
    git(repo_root, "add", ".")
    git(repo_root, "commit", "-m", "seed store")


def assert_default_branch_clean(repo_root: Path, tip: str = "init") -> None:
    assert git(repo_root, "status", "--porcelain") == ""
    assert git(repo_root, "branch", "--show-current").strip() == "main"
    assert git(repo_root, "log", "--format=%s", "-1").strip() == tip
    for rel in ("data/history.ndjson", "data/index.json", "state.json"):
        assert (repo_root / rel).read_text() == git(repo_root, "show", f"HEAD:{rel}")


def test_first_seen_row_opens_pr_and_leaves_default_branch_clean(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg(3, "deepseek")
    # a non-empty store at load: the run takes the per-change path, not the seed
    legacy = store.build_row(
        "deepseek",
        "deepseek-legacy",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
    )
    seed_store(repo_root, [legacy])
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    provider_report = report.providers["deepseek"]
    assert provider_report.detected == ["deepseek-chat"]
    assert provider_report.candidates == ["deepseek-chat"]
    assert [model_id for model_id, _url in provider_report.prs] == ["deepseek-chat"]
    assert provider_report.rows == ["deepseek-chat"]
    assert provider_report.skipped_pending == []
    assert provider_report.skipped_no_pricing == []
    assert provider_report.skipped_cap == []
    assert provider_report.errors == []

    # the row and the seen-state ride the pr branch only; the branch carries
    # the full store (the loaded legacy row plus the new one)
    branch_history = git(repo_root, "show", "pricelog/deepseek-chat:data/history.ndjson")
    rows = [json.loads(line) for line in branch_history.splitlines()]
    assert len(rows) == 2
    row = rows[1]
    assert row["source"] == "deepseek"
    assert row["model_id"] == "deepseek-chat"
    assert row["observed_at"] == TODAY
    assert row["input_mtok"] == 0.27
    assert row["output_mtok"] == 1.1
    assert row["url"] == "https://example.com/pricing"
    branch_state = json.loads(git(repo_root, "show", "pricelog/deepseek-chat:state.json"))
    assert branch_state["providers"]["deepseek"]["last_seen"] == ["deepseek-chat"]

    # the open pr names the id, so the next run skips it as pending: the store
    # on the default branch is still empty (no row, no seen-state)
    assert_default_branch_clean(repo_root, tip="seed store")
    runner.open_prs = [{"title": runner.created[0][0], "body": ""}]
    second = pipeline.run(cfg, repo_root, runner, today="2026-08-27")
    assert second.providers["deepseek"].skipped_pending == ["deepseek-chat"]
    assert second.providers["deepseek"].candidates == []
    assert len(runner.pr_urls) == 1


def test_pending_pr_skip_fires_before_scrape(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {}  # any scrape call would raise AssertionError
    cfg = make_cfg(3, "deepseek")
    runner = PipelineRunner(
        open_prs=[{"title": "Add DEEPSEEK-CHAT pricing for DeepSeek", "body": ""}]
    )

    report = pipeline.run(cfg, repo_root, runner)

    provider_report = report.providers["deepseek"]
    assert provider_report.skipped_pending == ["deepseek-chat"]
    assert provider_report.candidates == []
    assert provider_report.errors == []
    assert runner.pr_urls == []
    assert_default_branch_clean(repo_root)


def test_missing_pricing_skips_and_retries(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-x"]
    scrape["deepseek"] = {"deepseek-x": None}
    cfg = make_cfg(3, "deepseek")
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner)
    provider_report = report.providers["deepseek"]
    assert provider_report.skipped_no_pricing == ["deepseek-x"]
    assert provider_report.prs == []
    assert runner.pr_urls == []
    assert_default_branch_clean(repo_root)

    second = pipeline.run(cfg, repo_root, runner)
    assert second.providers["deepseek"].candidates == ["deepseek-x"]
    assert second.providers["deepseek"].skipped_no_pricing == ["deepseek-x"]


def test_cap_skips_extra_candidates(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["a", "b"]
    scrape["deepseek"] = {"a": pricing(), "b": pricing()}
    cfg = make_cfg(1, "deepseek")
    legacy = store.build_row(
        "deepseek",
        "deepseek-legacy",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
    )
    seed_store(repo_root, [legacy])
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner)
    provider_report = report.providers["deepseek"]
    assert [model_id for model_id, _url in provider_report.prs] == ["a"]
    assert provider_report.skipped_cap == ["b"]
    assert len(runner.pr_urls) == 1
    assert_default_branch_clean(repo_root, tip="seed store")


def test_seed_pr_carries_all_rows_without_cap(tmp_path, fake_modules, repo_root, or_models):
    detect, scrape = fake_modules
    detect["deepseek"] = ["a", "b"]
    detect["zai"] = ["c"]
    scrape["deepseek"] = {"a": pricing(), "b": pricing()}
    scrape["zai"] = {"c": pricing()}
    or_models.append(
        openrouter.OpenrouterModel(
            id="deepseek/deepseek-chat",
            name="DeepSeek Chat",
            input_mtok=0.27,
            output_mtok=1.1,
            cache_read_mtok=None,
            pricing={"prompt": "2.7e-7", "completion": "1.1e-6"},
        )
    )
    cfg = make_cfg(1, "deepseek", "zai")
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    assert len(runner.pr_urls) == 1
    (title, body) = runner.created[0]
    assert title == "Seed price history"
    assert "first price-history snapshot: 4 rows across 3 sources." in body
    assert report.providers["deepseek"].prs == [
        ("a", runner.pr_urls[0]),
        ("b", runner.pr_urls[0]),
    ]
    assert report.providers["zai"].prs == [("c", runner.pr_urls[0])]
    assert report.providers["openrouter"].prs == [("deepseek/deepseek-chat", runner.pr_urls[0])]
    assert report.providers["deepseek"].skipped_cap == []
    assert report.providers["zai"].skipped_cap == []

    branch_history = git(repo_root, "show", "pricelog/seed:data/history.ndjson")
    rows = [json.loads(line) for line in branch_history.splitlines()]
    assert [row["model_id"] for row in rows] == ["a", "b", "c", "deepseek/deepseek-chat"]
    branch_state = json.loads(git(repo_root, "show", "pricelog/seed:state.json"))
    assert branch_state["providers"]["deepseek"]["last_seen"] == ["a", "b"]
    assert branch_state["providers"]["zai"]["last_seen"] == ["c"]
    assert "openrouter" not in branch_state["providers"]
    assert_default_branch_clean(repo_root)


def test_refresh_drift_appends_and_opens_update_pr(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}  # 0.27/1.1 vs stored 0.2/0.4
    cfg = make_cfg(3, "deepseek")
    prior = store.build_row(
        "deepseek",
        "deepseek-chat",
        Pricing(0.2e-6, 0.4e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
    )
    seed_store(repo_root, [prior], {"providers": {"deepseek": {"last_seen": ["deepseek-chat"]}}})
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    provider_report = report.providers["deepseek"]
    assert provider_report.candidates == []
    assert [model_id for model_id, _url in provider_report.prs] == ["deepseek-chat"]
    assert provider_report.rows == ["deepseek-chat"]
    assert runner.created[0][0] == "Update deepseek-chat pricing for Deepseek"

    branch_history = git(repo_root, "show", "pricelog/deepseek-chat:data/history.ndjson")
    rows = [json.loads(line) for line in branch_history.splitlines()]
    assert len(rows) == 2
    assert rows[1]["model_id"] == "deepseek-chat"
    assert rows[1]["observed_at"] == TODAY
    assert rows[1]["input_mtok"] == 0.27
    assert rows[1]["output_mtok"] == 1.1


def test_refresh_unchanged_appends_nothing(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": Pricing(0.2e-6, 0.4e-6, "chat")}
    cfg = make_cfg(3, "deepseek")
    prior = store.build_row(
        "deepseek",
        "deepseek-chat",
        Pricing(0.2e-6, 0.4e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
    )
    seed_store(repo_root, [prior], {"providers": {"deepseek": {"last_seen": ["deepseek-chat"]}}})
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    provider_report = report.providers["deepseek"]
    assert provider_report.prs == []
    assert provider_report.rows == []
    assert provider_report.errors == []
    assert runner.pr_urls == []


def test_refresh_uses_dedup_spelling_for_stored_rows(tmp_path, fake_modules, repo_root):
    # the mistral case: the page spells dated snapshots with dashes, a store
    # seeded from the pre-pivot era tracks the compacted spelling
    detect, scrape = fake_modules
    detect["mistral"] = ["codestral-25-08"]
    scrape["mistral"] = {"codestral-25-08": pricing()}
    scr = sys.modules["ai_pricelog.scrapers.fake_scr"]
    scr.dedup_keys = lambda model_id: [model_id.replace("-25-08", "-2508")]
    cfg = make_cfg(3, "mistral")
    prior = store.build_row(
        "mistral",
        "codestral-2508",
        Pricing(0.2e-6, 0.4e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
    )
    seed_store(
        repo_root,
        [prior],
        {"providers": {"mistral": {"last_seen": ["codestral-25-08", "codestral-2508"]}}},
    )

    report = pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY)

    provider_report = report.providers["mistral"]
    assert provider_report.candidates == []
    assert [model_id for model_id, _url in provider_report.prs] == ["codestral-2508"]
    branch_history = git(repo_root, "show", "pricelog/codestral-2508:data/history.ndjson")
    rows = [json.loads(line) for line in branch_history.splitlines()]
    assert rows[1]["model_id"] == "codestral-2508"
    branch_state = json.loads(git(repo_root, "show", "pricelog/codestral-2508:state.json"))
    assert branch_state["providers"]["mistral"]["last_seen"] == [
        "codestral-25-08",
        "codestral-2508",
    ]


def test_openrouter_rows_append_and_open_pr(tmp_path, fake_modules, repo_root, or_models):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": None}
    or_models.append(
        openrouter.OpenrouterModel(
            id="deepseek/deepseek-chat",
            name="DeepSeek Chat",
            input_mtok=0.27,
            output_mtok=1.1,
            cache_read_mtok=None,
            pricing={"prompt": "2.7e-7", "completion": "1.1e-6"},
        )
    )
    cfg = make_cfg(3, "deepseek")
    # a non-empty store at load: the openrouter row takes the per-change path
    legacy = store.build_row(
        "deepseek",
        "deepseek-legacy",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
    )
    seed_store(repo_root, [legacy])
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    or_report = report.providers["openrouter"]
    assert or_report.detected == ["deepseek/deepseek-chat"]
    assert or_report.candidates == ["deepseek/deepseek-chat"]
    assert [model_id for model_id, _url in or_report.prs] == ["deepseek/deepseek-chat"]
    assert runner.created[0][0] == "Add deepseek/deepseek-chat pricing for OpenRouter"

    branch_history = git(repo_root, "show", "pricelog/deepseek/deepseek-chat:data/history.ndjson")
    rows = [json.loads(line) for line in branch_history.splitlines()]
    # the branch carries the full store: the loaded rows plus the new one
    assert len(rows) == 2
    assert rows[1]["source"] == "openrouter"
    assert rows[1]["model_id"] == "deepseek/deepseek-chat"
    assert rows[1]["input_mtok"] == 0.27
    # openrouter keeps no seen-state: the branch state.json equals the head one
    assert git(repo_root, "show", "pricelog/deepseek/deepseek-chat:state.json") == git(
        repo_root, "show", "HEAD:state.json"
    )
    assert_default_branch_clean(repo_root, tip="seed store")


def test_openrouter_unchanged_appends_nothing(tmp_path, fake_modules, repo_root, or_models):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": None}
    model = openrouter.OpenrouterModel(
        id="deepseek/deepseek-chat",
        name="DeepSeek Chat",
        input_mtok=0.27,
        output_mtok=1.1,
        cache_read_mtok=None,
        pricing={"prompt": "2.7e-7", "completion": "1.1e-6"},
    )
    or_models.append(model)
    prior = openrouter.build_row(model, "2026-08-19")
    assert prior is not None
    seed_store(repo_root, [prior])
    cfg = make_cfg(3, "deepseek")
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    assert report.providers["openrouter"].prs == []
    assert runner.pr_urls == []


def test_detector_error_does_not_block_next_provider(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = RuntimeError("detector boom")
    detect["zai"] = ["zai-x"]
    scrape["zai"] = {"zai-x": pricing()}
    cfg = make_cfg(3, "deepseek", "zai")
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner)

    assert "detector boom" in report.providers["deepseek"].errors[0]
    assert report.providers["deepseek"].detected == []
    zai_report = report.providers["zai"]
    assert zai_report.detected == ["zai-x"]
    assert [model_id for model_id, _url in zai_report.prs] == ["zai-x"]
    assert zai_report.errors == []


def test_scrape_error_records_and_continues(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["a", "b"]
    scrape["deepseek"] = {"a": RuntimeError("page broke"), "b": pricing()}
    cfg = make_cfg(3, "deepseek")

    report = pipeline.run(cfg, repo_root, PipelineRunner())

    provider_report = report.providers["deepseek"]
    assert "page broke" in provider_report.errors[0]
    assert [model_id for model_id, _url in provider_report.prs] == ["b"]
    # a is not settled: the next run re-candidates it
    assert json.loads((repo_root / "state.json").read_text()) == {"providers": {}}


def test_validation_failure_skips_candidate_and_continues(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["a", "b"]
    scrape["deepseek"] = {"a": Pricing(-1.0, 1.1e-06, "chat", 65536), "b": pricing()}
    cfg = make_cfg(3, "deepseek")

    report = pipeline.run(cfg, repo_root, PipelineRunner())

    provider_report = report.providers["deepseek"]
    assert any("input_mtok" in error for error in provider_report.errors)
    assert [model_id for model_id, _url in provider_report.prs] == ["b"]


def test_run_url_threads_into_pr_body(tmp_path, fake_modules, repo_root, monkeypatch):
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "uwuclxdy/ai-pricelog")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg(3, "deepseek")
    runner = PipelineRunner()

    pipeline.run(cfg, repo_root, runner)

    (_title, body) = runner.created[0]
    assert "[GitHub Action](https://github.com/uwuclxdy/ai-pricelog/actions/runs/123)" in body


def test_branch_commit_sets_identity_when_missing(tmp_path, fake_modules, repo_root):
    git(repo_root, "config", "--unset", "user.name")
    git(repo_root, "config", "--unset", "user.email")
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg(3, "deepseek")

    pipeline.run(cfg, repo_root, PipelineRunner())

    assert (
        git(repo_root, "log", "--format=%an <%ae>", "-1", "pricelog/seed").strip()
        == "octocat <octocat@users.noreply.github.com>"
    )

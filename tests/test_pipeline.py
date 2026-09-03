from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

from ai_pricelog import absence, announce, config, health, openrouter, pipeline, pr, store
from ai_pricelog.pricing import Pricing
from conftest import git, git_init_repo, register_fake_module

TODAY = "2026-08-26"
VERSION = 4


def pricing(input_cost: float = 2.7e-07, output_cost: float = 1.1e-06) -> Pricing:
    return Pricing(input_cost, output_cost, "chat", 65536)


def make_provider_cfg(
    key: str,
    provider: str | None = None,
    announce_urls: tuple[str, ...] = (),
    currency_rate: float | None = None,
) -> config.ProviderCfg:
    return config.ProviderCfg(
        key=key,
        provider=provider or key.title(),
        detector="fake_det",
        detector_url="https://example.com/models",
        scraper="fake_scr",
        scraper_url="https://example.com/pricing",
        announce_urls=announce_urls,
        currency_rate=currency_rate,
    )


def make_cfg(*keys: str) -> config.Config:
    return config.Config(providers=tuple(make_provider_cfg(k) for k in keys))


def batch_branch(source: str, today: str = TODAY, stamp: str = "000000") -> str:
    return pr.branch_name(f"{source}@{today}-{stamp}")


class PipelineRunner:
    """gh calls scripted, git subprocesses real (all local, offline)."""

    def __init__(
        self,
        open_prs: list[dict] | None = None,
        base: str = "main",
        failures: dict[str, Exception] | None = None,
    ) -> None:
        self.real = pr.PrRunner()
        self.calls: list[tuple[list[str], Path]] = []
        self.pr_urls: list[str] = []
        self.created: list[tuple[str, str, str]] = []
        self.open_prs = open_prs or []
        self.failures = failures or {}
        self.base = base

    def run(self, cmd: list[str], cwd: Path) -> str:
        self.calls.append((cmd, cwd))
        key = " ".join(cmd)
        for pattern, failure in self.failures.items():
            if pattern in key:
                raise failure
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
                self.created.append(
                    (
                        cmd[cmd.index("--title") + 1],
                        cmd[cmd.index("--body") + 1],
                        cmd[cmd.index("--head") + 1],
                    )
                )
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
    # the validator derives its key sets from the committed schema file
    schema_src = Path(__file__).resolve().parents[1] / "data" / "schema" / "row.v4.json"
    (root / "data" / "schema").mkdir(parents=True)
    (root / "data" / "schema" / "row.v4.json").write_text(schema_src.read_text(encoding="utf-8"))
    # the pipeline reads the committed catalog, so the test repo needs one
    (root / "data" / "catalog").mkdir(parents=True)
    (root / "data" / "catalog" / "models.json").write_text(
        json.dumps({"version": 4, "models": {}}) + "\n"
    )
    (root / "data" / "catalog" / "aliases.json").write_text(
        json.dumps({"version": 4, "aliases": {}}) + "\n"
    )
    (root / "README.md").write_text("\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "init")
    bare = tmp_path / "origin.git"
    git(root, "clone", "--bare", str(root), str(bare))
    git(root, "remote", "add", "origin", str(bare))
    return root


def seed_store(repo_root: Path, rows: list[dict]) -> None:
    """Commit a prior store snapshot on the default branch (the merged-PR end state)."""
    shard_dir = repo_root / "data" / "history"
    by_source: dict[str, list[dict]] = {}
    for row in rows:
        by_source.setdefault(row["source"], []).append(row)
    for source, source_rows in by_source.items():
        store.save_shard(source_rows, shard_dir, source)
    git(repo_root, "add", ".")
    git(repo_root, "commit", "-m", "seed store")


def assert_default_branch_clean(repo_root: Path, tip: str = "init") -> None:
    # the run marker is an untracked runtime artifact, not default-branch state
    (repo_root / pipeline.MARKER_FILE).unlink(missing_ok=True)
    assert git(repo_root, "status", "--porcelain") == ""
    assert git(repo_root, "branch", "--show-current").strip() == "main"
    assert git(repo_root, "log", "--format=%s", "-1").strip() == tip


def branch_rows(repo_root: Path, branch: str, source: str) -> list[dict]:
    text = git(repo_root, "show", f"{branch}:data/history/{source}.ndjson")
    return [json.loads(line) for line in text.splitlines()]


def branch_all_rows(repo_root: Path, branch: str) -> list[dict]:
    paths = git(repo_root, "ls-tree", "-r", "--name-only", branch).splitlines()
    rows: list[dict] = []
    for path in paths:
        if path.startswith("data/history/") and path.endswith(".ndjson"):
            text = git(repo_root, "show", f"{branch}:{path}")
            rows.extend(json.loads(line) for line in text.splitlines())
    return rows


def test_first_seen_row_opens_pr_and_leaves_default_branch_clean(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")
    # a non-empty store at load: the run takes the per-change path, not the seed
    legacy = store.build_row(
        "deepseek",
        "deepseek-legacy",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [legacy])
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    provider_report = report.providers["deepseek"]
    assert provider_report.detected == ["deepseek-chat"]
    assert provider_report.candidates == ["deepseek-chat"]
    assert [model_id for model_id, _url in provider_report.prs] == ["deepseek-chat"]
    assert provider_report.rows == ["deepseek-chat"]
    assert provider_report.skipped_pending == []
    assert provider_report.skipped_no_pricing == []
    assert provider_report.errors == []

    # the row rides the pr branch only; the branch carries its source's shard
    rows = branch_rows(repo_root, batch_branch("deepseek"), "deepseek")
    assert len(rows) == 2
    row = next(r for r in rows if r["model_id"] == "deepseek-chat")
    assert row["source"] == "deepseek"
    assert row["observed_at"] == TODAY
    assert row["rates"]["input"] == 0.27
    assert row["rates"]["output"] == 1.1
    assert row["provenance"]["url"] == "https://example.com/pricing"

    # the open pr names the id in its body, so the next run skips it as
    # pending: the store on the default branch is still empty (no row)
    assert_default_branch_clean(repo_root, tip="seed store")
    runner.open_prs = [
        {
            "title": runner.created[0][0],
            "body": runner.created[0][1],
            "headRefName": runner.created[0][2],
        }
    ]
    second = pipeline.run(cfg, repo_root, runner, today="2026-08-27")
    assert second.providers["deepseek"].skipped_pending == ["deepseek-chat"]
    assert second.providers["deepseek"].candidates == []
    assert len(runner.pr_urls) == 1


def test_pending_pr_skip_fires_before_scrape(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {}  # any scrape call would raise AssertionError
    cfg = make_cfg("deepseek")
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
    cfg = make_cfg("deepseek")
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


def test_candidates_batch_into_one_pr_per_source(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["model-a", "model-b"]
    scrape["deepseek"] = {"model-a": pricing(), "model-b": pricing()}
    cfg = make_cfg("deepseek")
    legacy = store.build_row(
        "deepseek",
        "deepseek-legacy",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [legacy])
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")
    provider_report = report.providers["deepseek"]
    assert [model_id for model_id, _url in provider_report.prs] == ["model-a", "model-b"]
    assert len(runner.pr_urls) == 1
    assert runner.created[0][0] == "Update Deepseek price history (2 rows)"
    assert runner.created[0][2] == batch_branch("deepseek")

    # both rows ride the one source branch (shard order sorts by model id)
    rows = branch_rows(repo_root, batch_branch("deepseek"), "deepseek")
    assert sorted(row["model_id"] for row in rows) == [
        "deepseek-legacy",
        "model-a",
        "model-b",
    ]
    assert_default_branch_clean(repo_root, tip="seed store")

    # next run: model-a and model-b are settled by the open pr; a new
    # candidate gets a new batch pr for the same source on a distinct branch
    # (no force-push over the still-open pr's branch)
    detect["deepseek"] = ["model-a", "model-b", "model-c"]
    scrape["deepseek"]["model-c"] = pricing()
    runner.open_prs = [
        {
            "title": runner.created[0][0],
            "body": runner.created[0][1],
            "headRefName": runner.created[0][2],
        }
    ]
    second = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000001")
    assert [model_id for model_id, _url in second.providers["deepseek"].prs] == ["model-c"]
    assert runner.created[1][2] == batch_branch("deepseek", stamp="000001")
    assert runner.created[1][2] != runner.created[0][2]
    rows = branch_rows(repo_root, batch_branch("deepseek", stamp="000001"), "deepseek")
    assert sorted(row["model_id"] for row in rows) == [
        "deepseek-legacy",
        "model-a",
        "model-b",
        "model-c",
    ]
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
    cfg = make_cfg("deepseek", "zai")
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    assert len(runner.pr_urls) == 1
    (title, body, _head) = runner.created[0]
    assert title == "Seed price history"
    assert "first price-history snapshot: 4 rows across 3 sources." in body
    assert report.providers["deepseek"].prs == [
        ("a", runner.pr_urls[0]),
        ("b", runner.pr_urls[0]),
    ]
    assert report.providers["zai"].prs == [("c", runner.pr_urls[0])]
    assert report.providers["openrouter"].prs == [("deepseek/deepseek-chat", runner.pr_urls[0])]

    rows = branch_all_rows(repo_root, "pricelog/seed")
    assert sorted(row["model_id"] for row in rows) == ["a", "b", "c", "deepseek/deepseek-chat"]
    assert_default_branch_clean(repo_root)


def test_write_shards_writes_only_the_spec_source(tmp_path):
    shard_dir = tmp_path / "history"
    spec = pr.PrSpec(
        source="deepseek",
        provider="DeepSeek",
        source_url="",
        rows=(),
        batch_key="deepseek@2026-08-26-000000",
    )
    full_rows = [
        {"schema": 4, "source": "deepseek", "model_id": "a", "observed_at": "t"},
        {"schema": 4, "source": "zai", "model_id": "b", "observed_at": "t"},
    ]
    pipeline._write_shards(shard_dir, spec, full_rows)
    assert (shard_dir / "deepseek.ndjson").exists()
    assert not (shard_dir / "zai.ndjson").exists()


def test_seed_pr_open_failure_records_errors_per_model(tmp_path, fake_modules, repo_root):
    # the seed pr fails to open: the run records one error per model instead
    # of crashing, and nothing lands
    detect, scrape = fake_modules
    detect["deepseek"] = ["model-a", "model-b"]
    scrape["deepseek"] = {"model-a": pricing(), "model-b": pricing()}
    cfg = make_cfg("deepseek")
    runner = PipelineRunner(failures={"gh pr create": pr.PrError("create boom")})

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    assert report.providers["deepseek"].errors == [
        "seed pr failed for model-a",
        "seed pr failed for model-b",
    ]
    assert runner.pr_urls == []
    assert not (repo_root / pipeline.MARKER_FILE).exists()
    assert_default_branch_clean(repo_root)


def test_refresh_drift_appends_and_opens_update_pr(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}  # 0.27/1.1 vs stored 0.2/0.4
    cfg = make_cfg("deepseek")
    prior = store.build_row(
        "deepseek",
        "deepseek-chat",
        Pricing(0.2e-6, 0.4e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [prior])
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    provider_report = report.providers["deepseek"]
    assert provider_report.candidates == []
    assert [model_id for model_id, _url in provider_report.prs] == ["deepseek-chat"]
    assert provider_report.rows == ["deepseek-chat"]
    assert runner.created[0][0] == "Update Deepseek price history (1 row)"

    rows = branch_rows(repo_root, batch_branch("deepseek"), "deepseek")
    assert len(rows) == 2
    assert rows[1]["model_id"] == "deepseek-chat"
    assert rows[1]["observed_at"] == TODAY
    assert rows[1]["rates"]["input"] == 0.27
    assert rows[1]["rates"]["output"] == 1.1


def test_refresh_unchanged_appends_nothing(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": Pricing(0.2e-6, 0.4e-6, "chat")}
    cfg = make_cfg("deepseek")
    prior = store.build_row(
        "deepseek",
        "deepseek-chat",
        Pricing(0.2e-6, 0.4e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [prior])
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
    cfg = make_cfg("mistral")
    prior = store.build_row(
        "mistral",
        "codestral-2508",
        Pricing(0.2e-6, 0.4e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [prior])

    report = pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")

    provider_report = report.providers["mistral"]
    assert provider_report.candidates == []
    assert [model_id for model_id, _url in provider_report.prs] == ["codestral-2508"]
    rows = branch_rows(repo_root, batch_branch("mistral"), "mistral")
    assert rows[1]["model_id"] == "codestral-2508"


def test_dedup_spelling_row_settles_detected_id(tmp_path, fake_modules, repo_root):
    # the candidate gate is dedup-aware: a page id whose deduped spelling
    # already has a row must not seed a duplicate track under the page
    # spelling
    detect, scrape = fake_modules
    detect["mistral"] = ["codestral-25-08"]
    scrape["mistral"] = {"codestral-25-08": Pricing(0.2e-6, 0.4e-6, "chat")}
    scr = sys.modules["ai_pricelog.scrapers.fake_scr"]
    scr.dedup_keys = lambda model_id: [model_id.replace("-25-08", "-2508")]
    cfg = make_cfg("mistral")
    prior = store.build_row(
        "mistral",
        "codestral-2508",
        Pricing(0.2e-6, 0.4e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [prior])
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    provider_report = report.providers["mistral"]
    assert provider_report.candidates == []
    assert provider_report.prs == []
    assert provider_report.skipped_no_pricing == []


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
    cfg = make_cfg("deepseek")
    # a non-empty store at load: the openrouter row takes the per-change path
    legacy = store.build_row(
        "deepseek",
        "deepseek-legacy",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [legacy])
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    or_report = report.providers["openrouter"]
    assert or_report.detected == ["deepseek/deepseek-chat"]
    assert or_report.candidates == ["deepseek/deepseek-chat"]
    assert [model_id for model_id, _url in or_report.prs] == ["deepseek/deepseek-chat"]
    assert runner.created[0][0] == "Update OpenRouter price history (1 row)"

    rows = branch_rows(repo_root, batch_branch("openrouter"), "openrouter")
    # the per-source branch carries only its own shard
    assert len(rows) == 1
    assert rows[0]["source"] == "openrouter"
    assert rows[0]["model_id"] == "deepseek/deepseek-chat"
    assert rows[0]["rates"]["input"] == 0.27
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
    prior = openrouter.build_row(model, "2026-08-19", VERSION)
    assert prior is not None
    seed_store(repo_root, [prior])
    cfg = make_cfg("deepseek")
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    assert report.providers["openrouter"].prs == []
    assert runner.pr_urls == []


def test_openrouter_negative_pricing_builds_row_without_prices(
    tmp_path, fake_modules, repo_root, or_models
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": None}
    or_models.append(
        openrouter.OpenrouterModel(
            id="openrouter/auto",
            name="Auto Router",
            input_mtok=None,
            output_mtok=None,
            cache_read_mtok=None,
            pricing={"prompt": "-1", "completion": "-1"},
        )
    )
    cfg = make_cfg("deepseek")
    legacy = store.build_row(
        "deepseek",
        "deepseek-legacy",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [legacy])
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    or_report = report.providers["openrouter"]
    assert or_report.candidates == ["openrouter/auto"]
    assert or_report.errors == []
    rows = branch_rows(repo_root, batch_branch("openrouter"), "openrouter")
    assert len(rows) == 1
    row = rows[0]
    assert row["model_id"] == "openrouter/auto"
    assert "rates" not in row
    assert_default_branch_clean(repo_root, tip="seed store")


def test_detector_error_does_not_block_next_provider(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = RuntimeError("detector boom")
    detect["zai"] = ["zai-x"]
    scrape["zai"] = {"zai-x": pricing()}
    cfg = make_cfg("deepseek", "zai")
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner)

    assert "detector boom" in report.providers["deepseek"].errors[0]
    assert report.providers["deepseek"].detected == []
    zai_report = report.providers["zai"]
    assert zai_report.detected == ["zai-x"]
    assert [model_id for model_id, _url in zai_report.prs] == ["zai-x"]
    assert zai_report.errors == []


def _logged_lines(caplog) -> list[str]:
    return [f"{record.levelname}:{record.name}:{record.getMessage()}" for record in caplog.records]


def test_detector_failure_line_is_health_parseable(tmp_path, fake_modules, repo_root, caplog):
    # the pipeline's failure log and the health checker's patterns are two
    # sides of one wire: a failing detector must parse as a hard failure
    detect, _ = fake_modules
    detect["deepseek"] = RuntimeError("detector boom")
    cfg = make_cfg("deepseek")
    with caplog.at_level(logging.ERROR):
        pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")
    assert health.parse_log(_logged_lines(caplog))["deepseek"]["hard"]


def test_refresh_scrape_failure_line_is_health_parseable(tmp_path, fake_modules, repo_root, caplog):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": RuntimeError("scrape boom")}
    prior = store.build_row(
        "deepseek",
        "deepseek-chat",
        Pricing(0.2e-6, 0.4e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [prior])
    cfg = make_cfg("deepseek")
    with caplog.at_level(logging.ERROR):
        pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")
    assert health.parse_log(_logged_lines(caplog))["deepseek"]["hard"]


def test_validation_failure_line_is_health_parseable(tmp_path, fake_modules, repo_root, caplog):
    # a rejected candidate row parses as a soft (provider-alive) issue
    detect, scrape = fake_modules
    detect["deepseek"] = ["a"]
    scrape["deepseek"] = {"a": Pricing(-1.0, 1.1e-06, "chat", 65536)}
    cfg = make_cfg("deepseek")
    with caplog.at_level(logging.WARNING):
        pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")
    issues = health.parse_log(_logged_lines(caplog))
    assert issues["deepseek"]["soft"] and issues["deepseek"]["hard"] == []


def test_scrape_error_records_and_continues(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["a", "b"]
    scrape["deepseek"] = {"a": RuntimeError("page broke"), "b": pricing()}
    cfg = make_cfg("deepseek")
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner)

    provider_report = report.providers["deepseek"]
    assert "page broke" in provider_report.errors[0]
    assert [model_id for model_id, _url in provider_report.prs] == ["b"]
    # a is not settled: the next run re-candidates it
    second = pipeline.run(cfg, repo_root, runner, today="2026-08-27")
    assert "a" in second.providers["deepseek"].candidates


def test_validation_failure_skips_candidate_and_continues(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["a", "b"]
    scrape["deepseek"] = {"a": Pricing(-1.0, 1.1e-06, "chat", 65536), "b": pricing()}
    cfg = make_cfg("deepseek")

    report = pipeline.run(cfg, repo_root, PipelineRunner())

    provider_report = report.providers["deepseek"]
    assert any("rates.input" in error for error in provider_report.errors)
    assert [model_id for model_id, _url in provider_report.prs] == ["b"]


def test_run_url_threads_into_pr_body(tmp_path, fake_modules, repo_root, monkeypatch):
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "uwuclxdy/ai-pricelog")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")
    runner = PipelineRunner()

    pipeline.run(cfg, repo_root, runner)

    (_title, body, _head) = runner.created[0]
    assert "[GitHub Action](https://github.com/uwuclxdy/ai-pricelog/actions/runs/123)" in body


def test_branch_commit_sets_identity_when_missing(tmp_path, fake_modules, repo_root):
    git(repo_root, "config", "--unset", "user.name")
    git(repo_root, "config", "--unset", "user.email")
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")

    pipeline.run(cfg, repo_root, PipelineRunner())

    assert (
        git(repo_root, "log", "--format=%an <%ae>", "-1", "pricelog/seed").strip()
        == "octocat <octocat@users.noreply.github.com>"
    )


def test_push_uses_force_with_lease(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")
    legacy = store.build_row(
        "deepseek",
        "deepseek-legacy",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [legacy])
    runner = PipelineRunner()

    pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    pushes = [cmd for cmd, _cwd in runner.calls if cmd[0:2] == ["git", "push"]]
    assert pushes == [["git", "push", "--force-with-lease", "origin", batch_branch("deepseek")]]


def test_push_failure_does_not_delete_remote_branch(tmp_path, fake_modules, repo_root):
    # a rejected force-with-lease push may mean a peer run pushed the same
    # branch first; deleting it would drop the peer's pr branch
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")
    legacy = store.build_row(
        "deepseek",
        "deepseek-legacy",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [legacy])
    runner = PipelineRunner(failures={"git push --force-with-lease": pr.PrError("push rejected")})

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert runner.pr_urls == []
    assert "pr open failed for 1 rows" in report.providers["deepseek"].errors[0]
    branch = batch_branch("deepseek")
    pushes = [cmd for cmd, _cwd in runner.calls if cmd[0:2] == ["git", "push"]]
    assert ["git", "push", "--force-with-lease", "origin", branch] in pushes
    assert ["git", "push", "origin", "--delete", branch] not in pushes
    assert branch not in git(repo_root, "ls-remote", "origin")
    assert_default_branch_clean(repo_root, tip="seed store")


def test_pr_create_failure_deletes_the_remote_branch(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")
    legacy = store.build_row(
        "deepseek",
        "deepseek-legacy",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [legacy])
    runner = PipelineRunner(failures={"gh pr create": pr.PrError("pr create failed")})

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert runner.pr_urls == []
    assert "pr open failed for 1 rows" in report.providers["deepseek"].errors[0]
    branch = batch_branch("deepseek")
    pushes = [cmd for cmd, _cwd in runner.calls if cmd[0:2] == ["git", "push"]]
    assert ["git", "push", "--force-with-lease", "origin", branch] in pushes
    assert ["git", "push", "origin", "--delete", branch] in pushes
    # the orphaned branch is gone, so the next run re-creates it cleanly
    assert branch not in git(repo_root, "ls-remote", "origin")
    assert_default_branch_clean(repo_root, tip="seed store")


def test_seed_rerun_skipped_while_seed_pr_open(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")
    runner = PipelineRunner(
        open_prs=[{"title": "Seed price history", "body": "", "headRefName": "pricelog/seed"}]
    )

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    assert report.providers == {}
    assert runner.pr_urls == []
    assert_default_branch_clean(repo_root)


def test_pending_branch_rows_union_prevents_duplicate_rows(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat", "deepseek-new"]
    scrape["deepseek"] = {"deepseek-chat": pricing(), "deepseek-new": pricing(3.0e-7, 1.2e-6)}
    cfg = make_cfg("deepseek")
    legacy = store.build_row(
        "deepseek",
        "deepseek-legacy",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    prior = store.build_row(
        "deepseek",
        "deepseek-chat",
        Pricing(0.2e-6, 0.4e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [legacy, prior])

    # a sibling run already opened the drift update pr for deepseek-chat; the
    # pending branch carries the source's full shard snapshot
    pending = store.build_row(
        "deepseek",
        "deepseek-chat",
        pricing(),
        "2026-08-25",
        "https://example.com/pricing",
        VERSION,
    )
    pending_branch = pr.branch_name("deepseek-chat")
    git(repo_root, "switch", "-C", pending_branch)
    store.save_shard([legacy, prior, pending], repo_root / "data" / "history", "deepseek")
    git(repo_root, "add", ".")
    git(repo_root, "commit", "-m", "sibling drift update")
    git(repo_root, "push", "origin", pending_branch)
    git(repo_root, "switch", "main")
    runner = PipelineRunner(
        open_prs=[
            {
                "title": "Update deepseek-chat pricing for Deepseek",
                "body": "",
                "headRefName": pending_branch,
            }
        ]
    )

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    # deepseek-chat is pending behind an open pr: the union diff stops a
    # duplicate row, and only the genuinely new model gets a pr
    assert [model_id for model_id, _url in report.providers["deepseek"].prs] == ["deepseek-new"]
    assert report.providers["deepseek"].skipped_pending == ["deepseek-chat"]
    rows = branch_rows(repo_root, batch_branch("deepseek"), "deepseek")
    assert sorted(row["model_id"] for row in rows) == [
        "deepseek-chat",
        "deepseek-chat",
        "deepseek-legacy",
        "deepseek-new",
    ]
    keys = [(row["source"], row["model_id"], row["observed_at"]) for row in rows]
    assert len(keys) == len(set(keys))
    assert_default_branch_clean(repo_root, tip="seed store")


def test_pending_branch_carried_removal_lands_once(tmp_path, fake_modules, repo_root):
    # a pending branch's full-store snapshot repeats a landed removal row; the
    # union must not append the copy, or every open pr duplicates every
    # landed removal
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-new"]
    scrape["deepseek"] = {"deepseek-new": pricing(3.0e-7, 1.2e-6)}
    cfg = make_cfg("deepseek")
    removal = store.build_removal_row("deepseek", "deepseek-gone", "2026-08-19", VERSION)
    prior = store.build_row(
        "deepseek",
        "deepseek-chat",
        Pricing(0.2e-6, 0.4e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [removal, prior])

    # the sibling pr branch carries the source's full shard snapshot plus its own row
    pending = store.build_row(
        "deepseek",
        "deepseek-chat",
        pricing(),
        "2026-08-25",
        "https://example.com/pricing",
        VERSION,
    )
    pending_branch = pr.branch_name("deepseek-chat")
    git(repo_root, "switch", "-C", pending_branch)
    store.save_shard([removal, prior, pending], repo_root / "data" / "history", "deepseek")
    git(repo_root, "add", ".")
    git(repo_root, "commit", "-m", "sibling drift update")
    git(repo_root, "push", "origin", pending_branch)
    git(repo_root, "switch", "main")
    runner = PipelineRunner(
        open_prs=[
            {
                "title": "Update deepseek-chat pricing for Deepseek",
                "body": "",
                "headRefName": pending_branch,
            }
        ]
    )

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert [model_id for model_id, _url in report.providers["deepseek"].prs] == ["deepseek-new"]
    rows = branch_rows(repo_root, batch_branch("deepseek"), "deepseek")
    assert sorted(row["model_id"] for row in rows) == [
        "deepseek-chat",
        "deepseek-chat",
        "deepseek-gone",
        "deepseek-new",
    ]
    keys = [(row["source"], row["model_id"], row["observed_at"]) for row in rows]
    assert len(keys) == len(set(keys))
    assert_default_branch_clean(repo_root, tip="seed store")


def test_closed_pr_branch_contributes_no_rows(tmp_path, fake_modules, repo_root):
    # a closed pr keeps its branch on origin; without an open pr naming its
    # head ref the rows must not ride any new branch, and the model
    # re-candidates against the landed store with a fresh drift pr
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat", "deepseek-new"]
    scrape["deepseek"] = {"deepseek-chat": pricing(), "deepseek-new": pricing(3.0e-7, 1.2e-6)}
    cfg = make_cfg("deepseek")
    legacy = store.build_row(
        "deepseek",
        "deepseek-legacy",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    prior = store.build_row(
        "deepseek",
        "deepseek-chat",
        Pricing(0.2e-6, 0.4e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [legacy, prior])
    stale = store.build_row(
        "deepseek",
        "deepseek-chat",
        pricing(),
        "2026-08-25",
        "https://example.com/pricing",
        VERSION,
    )
    stale_branch = pr.branch_name("deepseek-chat")
    git(repo_root, "switch", "-C", stale_branch)
    store.save_shard([legacy, prior, stale], repo_root / "data" / "history", "deepseek")
    git(repo_root, "add", ".")
    git(repo_root, "commit", "-m", "rejected drift update")
    git(repo_root, "push", "origin", stale_branch)
    git(repo_root, "switch", "main")

    report = pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")

    # the rejected row dropped out of the union: deepseek-chat drifts against
    # the landed store and both models ride the one batch pr
    assert [model_id for model_id, _url in report.providers["deepseek"].prs] == [
        "deepseek-new",
        "deepseek-chat",
    ]
    assert report.providers["deepseek"].skipped_pending == []
    rows = branch_rows(repo_root, batch_branch("deepseek"), "deepseek")
    assert sorted(row["model_id"] for row in rows) == [
        "deepseek-chat",
        "deepseek-chat",
        "deepseek-legacy",
        "deepseek-new",
    ]
    # the rejected 2026-08-25 row appears on no branch
    assert all(row["observed_at"] != "2026-08-25" for row in rows)
    assert_default_branch_clean(repo_root, tip="seed store")


def test_open_pr_list_fetched_once_per_run(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-a", "deepseek-b"]
    scrape["deepseek"] = {"deepseek-a": pricing(), "deepseek-b": pricing()}
    cfg = make_cfg("deepseek")
    legacy = store.build_row(
        "deepseek",
        "deepseek-legacy",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [legacy])
    runner = PipelineRunner(
        open_prs=[
            {
                "title": "Add DEEPSEEK-A pricing for Deepseek",
                "body": "",
                "headRefName": "pricelog/deepseek-a-12345678",
            }
        ]
    )

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    list_calls = [cmd for cmd, _cwd in runner.calls if cmd[0:3] == ["gh", "pr", "list"]]
    assert len(list_calls) == 1
    assert "--limit" in list_calls[0] and "100" in list_calls[0]
    assert report.providers["deepseek"].skipped_pending == ["deepseek-a"]
    assert [model_id for model_id, _url in report.providers["deepseek"].prs] == ["deepseek-b"]
    assert_default_branch_clean(repo_root, tip="seed store")


def announce_change(provider: str = "deepseek", url: str = "https://example.com/updates"):
    return announce.ChannelChange(provider, url, "a" * 64, "b" * 64, "old prose", "new prose")


def announce_snapshot():
    url = "https://example.com/updates"
    return {
        "deepseek": {
            url: {
                "file": announce.channel_files("deepseek", (url,))[url],
                "text": "new prose",
                "sha256": announce._sha256("new prose"),
                "fetched": TODAY,
            }
        }
    }


def test_announce_change_rides_the_pr_branch_and_body(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")
    legacy = store.build_row(
        "deepseek",
        "deepseek-legacy",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [legacy])
    change = announce_change()
    snapshot = announce_snapshot()
    monkeypatch.setattr(
        pipeline.announce,
        "fetch_channels",
        lambda *a: announce.FetchResult((change,), snapshot, ()),
    )
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert report.announce == [change]
    assert report.announce_errors == []
    (_title, body, _head) = runner.created[0]
    assert "## announcement channels" in body
    assert "| deepseek | https://example.com/updates | `aaaaaaaa` -> `bbbbbbbb` |" in body
    index = json.loads(
        git(repo_root, "show", f"{batch_branch('deepseek')}:state/announce/index.json")
    )
    channel = index["deepseek"]["https://example.com/updates"]
    assert channel["sha256"] == announce._sha256("new prose")
    assert channel["file"] == "state/announce/deepseek/updates.md"
    prose = git(repo_root, "show", f"{batch_branch('deepseek')}:{channel['file']}")
    assert announce.unwrap(prose) == "new prose"
    # the snapshot settled on the branch only; the default branch keeps none
    assert not (repo_root / "state" / "announce" / "index.json").exists()
    assert_default_branch_clean(repo_root, tip="seed store")


def test_announce_change_without_pr_stays_stale(tmp_path, fake_modules, repo_root, monkeypatch):
    # no rows changed: the run opens no pr, so nothing commits the snapshot
    detect, scrape = fake_modules
    detect["deepseek"] = []
    scrape["deepseek"] = {}
    cfg = make_cfg("deepseek")
    change = announce_change()
    monkeypatch.setattr(
        pipeline.announce,
        "fetch_channels",
        lambda *a: announce.FetchResult((change,), announce_snapshot(), ()),
    )
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    assert report.announce == [change]
    assert runner.pr_urls == []
    assert not (repo_root / "state" / "announce" / "index.json").exists()
    assert_default_branch_clean(repo_root)

    # nothing settled the change, so it re-surfaces next run (skip-and-retry)
    second = pipeline.run(cfg, repo_root, runner, today="2026-08-27")
    assert second.announce == [change]
    assert runner.pr_urls == []


def test_announce_fetch_error_does_not_block_rows(tmp_path, fake_modules, repo_root, monkeypatch):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")
    legacy = store.build_row(
        "deepseek",
        "deepseek-legacy",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [legacy])
    monkeypatch.setattr(
        pipeline.announce,
        "fetch_channels",
        lambda *a: announce.FetchResult((), {}, ("deepseek https://x: FetchError: boom",)),
    )
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert report.announce_errors == ["deepseek https://x: FetchError: boom"]
    assert report.announce == []
    assert report.providers["deepseek"].errors == []
    assert len(runner.pr_urls) == 1
    (_title, body, _head) = runner.created[0]
    assert "## announcement channels" not in body


def test_landed_rows_hint_mapping_candidates(tmp_path, fake_modules, repo_root):
    # a landed id whose stripped spelling matches a stored twin under another
    # source rides the pr body as a mapping candidate for the human review
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")
    seed_store(
        repo_root,
        [
            {
                "schema": 4,
                "source": "openrouter",
                "model_id": "deepseek/deepseek-chat",
                "observed_at": "2026-08-25",
                "rates": {"input": 1.0},
            }
        ],
    )
    runner = PipelineRunner()

    pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    (_title, body, _head) = runner.created[0]
    assert body.count("## mapping candidates") == 1
    assert "- `deepseek-chat` (deepseek) -> canonical `deepseek/deepseek-chat`" in body


def test_announce_fetch_flows_through_the_pipeline(tmp_path, fake_modules, repo_root, monkeypatch):
    # the real fetch_channels over a patched network: the configured url is
    # fetched, and the first-fetch baseline rides the branch for later diffs
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    pcfg = make_provider_cfg("deepseek", announce_urls=("https://example.com/updates",))
    cfg = config.Config(providers=(pcfg,))
    legacy = store.build_row(
        "deepseek",
        "deepseek-legacy",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [legacy])
    fetched: list[str] = []
    monkeypatch.setattr(
        announce.web,
        "fetch_text",
        lambda url: fetched.append(url) or "<html><body>one</body></html>",
    )
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert fetched == ["https://example.com/updates"]
    assert report.announce == []
    index = json.loads(
        git(repo_root, "show", f"{batch_branch('deepseek')}:state/announce/index.json")
    )
    channel = index["deepseek"]["https://example.com/updates"]
    prose = git(repo_root, "show", f"{batch_branch('deepseek')}:{channel['file']}")
    assert announce.unwrap(prose) == "one"


def seed_absence(repo_root: Path, state: dict) -> None:
    """Commit per-source absence files on the default branch (a merged-PR end state)."""
    if state:
        absence.save_absence(state, repo_root)
        git(repo_root, "add", ".")
        git(repo_root, "commit", "-m", "land absence state")


def branch_absence(repo_root: Path, branch: str) -> dict:
    """The merged absence state on a branch, across its state/absence files."""
    state: dict = {}
    paths = git(repo_root, "ls-tree", "-r", "--name-only", branch, "state/absence/").splitlines()
    for path in paths:
        if path.endswith(".json"):
            state[Path(path).stem] = json.loads(git(repo_root, "show", f"{branch}:{path}"))
    return state


def deepseek_prior() -> dict:
    return store.build_row(
        "deepseek",
        "deepseek-chat",
        Pricing(0.2e-6, 0.4e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )


def test_absent_once_counts_without_removal(tmp_path, fake_modules, repo_root):
    # one landed absent observation: the counter rides the source's own pr at
    # 1, and no removal row exists anywhere yet
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-new"]
    detect["zai"] = ["zai-chat"]
    scrape["deepseek"] = {"deepseek-new": pricing(3.0e-7, 1.2e-6)}
    scrape["zai"] = {"zai-chat": pricing()}
    cfg = make_cfg("deepseek", "zai")
    seed_store(repo_root, [deepseek_prior()])
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert [model_id for model_id, _url in report.providers["deepseek"].prs] == ["deepseek-new"]
    assert [model_id for model_id, _url in report.providers["zai"].prs] == ["zai-chat"]
    deepseek_branch = batch_branch("deepseek")
    state = branch_absence(repo_root, deepseek_branch)
    assert state == {"deepseek": {"deepseek-chat": {"absent_runs": 1, "since": TODAY}}}
    rows = branch_rows(repo_root, deepseek_branch, "deepseek")
    assert [row["model_id"] for row in rows] == ["deepseek-chat", "deepseek-new"]
    assert all(row.get("removed") is not True for row in rows)
    # the sibling branch never touches another source's absence file
    assert branch_absence(repo_root, batch_branch("zai")) == {}
    assert (repo_root / pipeline.MARKER_FILE).exists()
    assert_default_branch_clean(repo_root, tip="seed store")


def test_absent_on_two_landed_runs_appends_removal_row(tmp_path, fake_modules, repo_root):
    # the second landed absent observation appends the removal row, opens its
    # pr, and deletes the counter entry. the first observation lands on the
    # source's own price-row branch
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-new"]
    scrape["deepseek"] = {"deepseek-new": pricing(3.0e-7, 1.2e-6)}
    cfg = make_cfg("deepseek")
    seed_store(repo_root, [deepseek_prior()])
    runner = PipelineRunner()

    pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    # the human merges the first pr: the counter at 1 lands with it
    git(repo_root, "merge", "--no-ff", batch_branch("deepseek"), "-m", "merge deepseek pr")
    runner.open_prs = []

    second = pipeline.run(cfg, repo_root, runner, today="2026-08-27", now="000000")

    deepseek_report = second.providers["deepseek"]
    assert [model_id for model_id, _url in deepseek_report.prs] == ["deepseek-chat"]
    assert runner.created[1][0] == "Mark deepseek-chat delisted from Deepseek"
    removal_branch = batch_branch("deepseek", today="2026-08-27")
    rows = branch_rows(repo_root, removal_branch, "deepseek")
    assert [row["model_id"] for row in rows] == ["deepseek-chat", "deepseek-chat", "deepseek-new"]
    removal = rows[1]
    assert removal["removed"] is True
    assert removal["observed_at"] == "2026-08-27"
    # the removal carries the last priced row's comparable fields as the
    # final snapshot; provenance (url) stays off
    assert list(removal) == [
        "schema",
        "source",
        "model_id",
        "observed_at",
        "removed",
        "rates",
    ]
    assert removal["rates"] == {"input": 0.2, "output": 0.4}
    # the counter stays at 2 on the branch; the landed-removal cleanup drops
    # it once the row reaches the store
    assert branch_absence(repo_root, removal_branch) == {
        "deepseek": {"deepseek-chat": {"absent_runs": 2, "since": TODAY}}
    }
    assert (repo_root / pipeline.MARKER_FILE).exists()
    assert_default_branch_clean(repo_root, tip="merge deepseek pr")


def test_pending_removal_keeps_the_counter_until_the_row_lands(tmp_path, fake_modules, repo_root):
    # a sibling pr carries the removal row; it is pending, not landed, so the
    # cleanup must not drop the counter: a rejected pr leaves the committed
    # baseline intact for the next run to re-derive
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-new"]
    scrape["deepseek"] = {"deepseek-new": pricing(3.0e-7, 1.2e-6)}
    cfg = make_cfg("deepseek")
    prior = deepseek_prior()
    seed_store(repo_root, [prior])
    seed_absence(repo_root, {"deepseek": {"deepseek-chat": {"absent_runs": 2, "since": TODAY}}})

    removal = store.build_removal_row("deepseek", "deepseek-chat", "2026-08-26", VERSION)
    pending_branch = pr.branch_name("deepseek-chat")
    git(repo_root, "switch", "-C", pending_branch)
    store.save_shard([prior, removal], repo_root / "data" / "history", "deepseek")
    git(repo_root, "add", ".")
    git(repo_root, "commit", "-m", "sibling removal pr")
    git(repo_root, "push", "origin", pending_branch)
    git(repo_root, "switch", "main")
    runner = PipelineRunner(
        open_prs=[
            {
                "title": "Mark deepseek-chat delisted from Deepseek",
                "body": "",
                "headRefName": pending_branch,
            }
        ]
    )

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert [model_id for model_id, _url in report.providers["deepseek"].prs] == ["deepseek-new"]
    # the counter survives on the branch: the removal is pending, not landed
    assert branch_absence(repo_root, batch_branch("deepseek")) == {
        "deepseek": {"deepseek-chat": {"absent_runs": 2, "since": TODAY}}
    }
    assert_default_branch_clean(repo_root, tip="land absence state")


def test_flaky_absent_run_without_pr_leaves_no_trace(tmp_path, fake_modules, repo_root):
    # a run with no pr opens nothing: the counter at 1 never lands, so the
    # next run re-derives from the committed (empty) state
    detect, scrape = fake_modules
    detect["deepseek"] = []
    scrape["deepseek"] = {}
    cfg = make_cfg("deepseek")
    seed_store(repo_root, [deepseek_prior()])
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    assert runner.pr_urls == []
    assert report.providers["deepseek"].prs == []
    assert_default_branch_clean(repo_root, tip="seed store")

    second = pipeline.run(cfg, repo_root, runner, today="2026-08-27")
    assert second.providers["deepseek"].prs == []
    assert_default_branch_clean(repo_root, tip="seed store")


def test_absence_keys_on_priced_set_when_detect_priced_exists(tmp_path, fake_modules, repo_root):
    # the mistral case: a carded-but-unpriced model counts absent, while a
    # priced model whose store row uses the raw slug stays present. the counter
    # rides mistral's own branch
    detect, scrape = fake_modules
    detect["mistral"] = ["devstral-2-25-12", "ministral-3-14b-25-12", "mistral-new"]
    det = sys.modules["ai_pricelog.detectors.fake_det"]
    det.detect_priced = lambda cfg: ["ministral-3-14b-25-12", "mistral-new"]
    scrape["mistral"] = {
        "devstral-2-25-12": None,
        "ministral-3-14b-25-12": pricing(),
        "mistral-new": pricing(3.0e-7, 1.2e-6),
    }
    detect["zai"] = ["zai-chat"]
    scrape["zai"] = {"zai-chat": pricing()}
    cfg = make_cfg("mistral", "zai")
    seed_store(
        repo_root,
        [
            store.build_row(
                "mistral",
                "ministral-3-14b-25-12",
                pricing(),
                "2026-02-06",
                "https://example.com/pricing",
                VERSION,
            ),
            store.build_row(
                "mistral",
                "devstral-2-25-12",
                pricing(),
                "2025-12-09",
                "https://example.com/pricing",
                VERSION,
            ),
        ],
    )

    report = pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")

    assert [model_id for model_id, _url in report.providers["zai"].prs] == ["zai-chat"]
    mistral_branch = batch_branch("mistral")
    assert branch_absence(repo_root, mistral_branch) == {
        "mistral": {"devstral-2-25-12": {"absent_runs": 1, "since": TODAY}}
    }
    assert branch_absence(repo_root, batch_branch("zai")) == {}


def test_absence_skips_when_priced_detection_fails(tmp_path, fake_modules, repo_root):
    # a priced-detection failure leaves the counters alone: no false absence
    # from a transient page break
    detect, scrape = fake_modules
    detect["mistral"] = ["ministral-3-14b-25-12"]
    det = sys.modules["ai_pricelog.detectors.fake_det"]

    def priced_or_boom(cfg):
        if cfg.key == "mistral":
            raise RuntimeError("boom")
        return det.detect(cfg)

    det.detect_priced = priced_or_boom
    scrape["mistral"] = {"ministral-3-14b-25-12": pricing()}
    detect["zai"] = ["zai-chat"]
    scrape["zai"] = {"zai-chat": pricing()}
    cfg = make_cfg("mistral", "zai")
    seed_store(
        repo_root,
        [
            store.build_row(
                "mistral",
                "ministral-3-14b-25-12",
                pricing(),
                "2026-02-06",
                "https://example.com/pricing",
                VERSION,
            ),
        ],
    )

    report = pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")

    assert [model_id for model_id, _url in report.providers["zai"].prs] == ["zai-chat"]
    # no counter landed on the branch: the pr carries no absence state at all
    tree = git(repo_root, "ls-tree", "-r", "--name-only", batch_branch("zai"))
    assert not any(path.startswith("state/absence/") for path in tree.splitlines())
    assert report.providers["mistral"].errors


def test_removals_batch_without_cap(tmp_path, fake_modules, repo_root):
    # two removals from one source ride one pr; the counter entries stay at 2
    # on the branch and the landed-removal cleanup drops them after the merge
    detect, scrape = fake_modules
    detect["deepseek"] = []
    scrape["deepseek"] = {}
    cfg = make_cfg("deepseek")
    prior_a = store.build_row(
        "deepseek", "a", pricing(), "2026-08-19", "https://example.com/pricing", VERSION
    )
    prior_b = store.build_row(
        "deepseek", "b", pricing(), "2026-08-19", "https://example.com/pricing", VERSION
    )
    seed_store(repo_root, [prior_a, prior_b])
    seed_absence(
        repo_root,
        {
            "deepseek": {
                "a": {"absent_runs": 1, "since": "2026-08-19"},
                "b": {"absent_runs": 1, "since": "2026-08-19"},
            }
        },
    )
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert [model_id for model_id, _url in report.providers["deepseek"].prs] == ["a", "b"]
    assert runner.created[0][0] == "Mark 2 models delisted from Deepseek"
    branch = batch_branch("deepseek")
    rows = branch_rows(repo_root, branch, "deepseek")
    assert [row["model_id"] for row in rows] == ["a", "a", "b", "b"]
    assert [row["model_id"] for row in rows if row.get("removed") is True] == ["a", "b"]
    assert branch_absence(repo_root, branch) == {
        "deepseek": {
            "a": {"absent_runs": 2, "since": "2026-08-19"},
            "b": {"absent_runs": 2, "since": "2026-08-19"},
        }
    }
    assert_default_branch_clean(repo_root, tip="land absence state")


def test_failed_batch_pr_keeps_counter_on_own_branch(tmp_path, fake_modules, repo_root):
    # a failed pr open commits nothing; the raised counter rides the source's
    # own successful branch at 2, so the next run re-derives the rows
    detect, scrape = fake_modules
    detect["deepseek"] = []
    detect["zai"] = ["zai-chat"]
    scrape["deepseek"] = {}
    scrape["zai"] = {"zai-chat": pricing()}
    cfg = make_cfg("deepseek", "zai")
    prior_a = store.build_row(
        "deepseek", "a", pricing(), "2026-08-19", "https://example.com/pricing", VERSION
    )
    seed_store(repo_root, [prior_a])
    seed_absence(
        repo_root,
        {"deepseek": {"a": {"absent_runs": 1, "since": "2026-08-19"}}},
    )
    runner = PipelineRunner(failures={"gh pr create": pr.PrError("create boom")})

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    # every batch pr failed to open; nothing lands and the committed state is
    # untouched, so the next run re-derives from the baseline
    assert [model_id for model_id, _url in report.providers["zai"].prs] == []
    assert report.providers["deepseek"].errors
    assert report.providers["zai"].errors
    assert runner.pr_urls == []
    assert not (repo_root / pipeline.MARKER_FILE).exists()
    assert_default_branch_clean(repo_root, tip="land absence state")

    # deepseek opens, zai fails: the raised counter rides deepseek's branch at 2
    runner.failures = {"gh pr create --draft --base main --head pricelog/zai": pr.PrError("boom")}
    second = pipeline.run(cfg, repo_root, runner, today="2026-08-27", now="000000")
    assert [model_id for model_id, _url in second.providers["deepseek"].prs] == ["a"]
    assert [model_id for model_id, _url in second.providers["zai"].prs] == []
    deepseek_branch = runner.created[0][2]
    assert deepseek_branch == batch_branch("deepseek", today="2026-08-27")
    assert branch_absence(repo_root, deepseek_branch) == {
        "deepseek": {"a": {"absent_runs": 2, "since": "2026-08-19"}}
    }
    assert_default_branch_clean(repo_root, tip="land absence state")


def test_reappearance_appends_fresh_row_and_clears_counter(tmp_path, fake_modules, repo_root):
    # a removed model reappears with unchanged prices: the run appends a fresh
    # price row anyway (clearing removed_at in the index) and deletes the entry
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")
    prior = store.build_row(
        "deepseek",
        "deepseek-chat",
        pricing(),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    removal = store.build_removal_row("deepseek", "deepseek-chat", "2026-08-20", VERSION)
    seed_store(repo_root, [prior, removal])
    seed_absence(
        repo_root,
        {"deepseek": {"deepseek-chat": {"absent_runs": 1, "since": "2026-08-20"}}},
    )
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    provider_report = report.providers["deepseek"]
    assert [model_id for model_id, _url in provider_report.prs] == ["deepseek-chat"]
    assert runner.created[0][0] == "Update Deepseek price history (1 row)"
    branch = batch_branch("deepseek")
    rows = branch_rows(repo_root, branch, "deepseek")
    assert [row["model_id"] for row in rows] == ["deepseek-chat", "deepseek-chat", "deepseek-chat"]
    assert rows[-1]["observed_at"] == TODAY
    assert "removed" not in rows[-1]
    assert branch_absence(repo_root, branch) == {}
    assert_default_branch_clean(repo_root, tip="land absence state")


def test_openrouter_absence_appends_removal_row(tmp_path, fake_modules, repo_root, or_models):
    # the patched fetch lists no models: stored openrouter ids count absent
    detect, scrape = fake_modules
    detect["deepseek"] = []
    scrape["deepseek"] = {}
    cfg = make_cfg("deepseek")
    model = openrouter.OpenrouterModel(
        id="deepseek/deepseek-chat",
        name="DeepSeek Chat",
        input_mtok=0.27,
        output_mtok=1.1,
        cache_read_mtok=None,
        pricing={"prompt": "2.7e-7", "completion": "1.1e-6"},
    )
    prior = openrouter.build_row(model, "2026-08-19", VERSION)
    assert prior is not None
    seed_store(repo_root, [prior])
    seed_absence(
        repo_root,
        {"openrouter": {"deepseek/deepseek-chat": {"absent_runs": 1, "since": "2026-08-20"}}},
    )
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    or_report = report.providers["openrouter"]
    assert [model_id for model_id, _url in or_report.prs] == ["deepseek/deepseek-chat"]
    assert runner.created[0][0] == "Mark deepseek/deepseek-chat delisted from OpenRouter"
    branch = batch_branch("openrouter")
    rows = branch_rows(repo_root, branch, "openrouter")
    assert len(rows) == 2
    assert rows[-1]["removed"] is True
    assert rows[-1]["source"] == "openrouter"
    assert branch_absence(repo_root, branch) == {
        "openrouter": {"deepseek/deepseek-chat": {"absent_runs": 2, "since": "2026-08-20"}}
    }
    assert_default_branch_clean(repo_root, tip="land absence state")


def test_openrouter_validation_failure_still_counts_present(
    tmp_path, fake_modules, repo_root, or_models, monkeypatch
):
    # a row that builds but fails validation must not fake a delisting: the
    # model counts present because build_row produced a rowable id
    detect, scrape = fake_modules
    detect["deepseek"] = []
    scrape["deepseek"] = {}
    cfg = make_cfg("deepseek")
    model = openrouter.OpenrouterModel(
        id="deepseek/deepseek-chat",
        name="DeepSeek Chat",
        input_mtok=0.27,
        output_mtok=1.1,
        cache_read_mtok=None,
        pricing={"prompt": "2.7e-7", "completion": "1.1e-6"},
    )
    prior = openrouter.build_row(model, "2026-08-19", VERSION)
    assert prior is not None
    seed_store(repo_root, [prior])
    seed_absence(
        repo_root,
        {"openrouter": {"deepseek/deepseek-chat": {"absent_runs": 1, "since": "2026-08-20"}}},
    )
    real_validate = pipeline.validate.validate_row

    def failing_validate(row, keys):
        if row.get("model_id") == "deepseek/deepseek-chat" and "removed" not in row:
            raise pipeline.validate.ValidationError(
                "row field 'rates.input' has bad value; fix: float"
            )
        real_validate(row, keys)

    monkeypatch.setattr(pipeline.validate, "validate_row", failing_validate)
    monkeypatch.setattr(pipeline.openrouter, "fetch_models", lambda: [model])
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    assert report.providers["openrouter"].errors
    assert [model_id for model_id, _url in report.providers["openrouter"].prs] == []
    assert runner.pr_urls == []
    assert not (repo_root / pipeline.MARKER_FILE).exists()


def test_dedup_twin_counts_present(tmp_path, fake_modules, repo_root):
    # a page id that dedups to the stored spelling counts as present: the
    # stored model is not absent while its page twin is listed
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat-v2"]
    scrape["deepseek"] = {"deepseek-chat-v2": pricing()}
    cfg = make_cfg("deepseek")
    scr = sys.modules["ai_pricelog.scrapers.fake_scr"]
    scr.dedup_keys = lambda model_id: ["deepseek-chat"] if model_id == "deepseek-chat-v2" else []
    stored = store.build_row(
        "deepseek",
        "deepseek-chat",
        pricing(),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [stored])
    seed_absence(
        repo_root,
        {"deepseek": {"deepseek-chat": {"absent_runs": 1, "since": "2026-08-20"}}},
    )
    runner = PipelineRunner()

    pipeline.run(cfg, repo_root, runner, today=TODAY)

    assert runner.pr_urls == []
    assert not (repo_root / pipeline.MARKER_FILE).exists()


def test_absence_after_landed_removal_appends_nothing(tmp_path, fake_modules, repo_root):
    # the newest row is already a removal: a second absent cycle must never
    # append another removal row (one per source/model ever)
    detect, scrape = fake_modules
    detect["deepseek"] = []
    scrape["deepseek"] = {}
    cfg = make_cfg("deepseek")
    prior = store.build_row(
        "deepseek",
        "deepseek-chat",
        pricing(),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    removal = store.build_removal_row("deepseek", "deepseek-chat", "2026-08-20", VERSION)
    seed_store(repo_root, [prior, removal])
    seed_absence(
        repo_root,
        {"deepseek": {"deepseek-chat": {"absent_runs": 1, "since": "2026-08-21"}}},
    )
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    assert runner.pr_urls == []
    assert report.providers["deepseek"].prs == []
    assert_default_branch_clean(repo_root, tip="land absence state")


def test_landed_removal_cleanup_drops_the_entry_at_two(tmp_path, fake_modules, repo_root):
    # a merged removal branch lands the counter at 2; the next run's cleanup
    # drops it (the row is the record), visible on that source's next pr branch
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-new"]
    scrape["deepseek"] = {"deepseek-new": pricing(3.0e-7, 1.2e-6)}
    cfg = make_cfg("deepseek")
    prior = store.build_row(
        "deepseek",
        "deepseek-chat",
        pricing(),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    removal = store.build_removal_row("deepseek", "deepseek-chat", "2026-08-20", VERSION)
    seed_store(repo_root, [prior, removal])
    seed_absence(
        repo_root,
        {"deepseek": {"deepseek-chat": {"absent_runs": 2, "since": "2026-08-19"}}},
    )
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert [model_id for model_id, _url in report.providers["deepseek"].prs] == ["deepseek-new"]
    assert branch_absence(repo_root, batch_branch("deepseek")) == {}
    assert_default_branch_clean(repo_root, tip="land absence state")


def test_absent_removed_model_does_not_churn_state(tmp_path, fake_modules, repo_root):
    # a landed removal ends absence tracking: later quiet runs recreate no
    # counter, so the state stays equal and the CI marker stays untouched
    detect, scrape = fake_modules
    detect["deepseek"] = []
    scrape["deepseek"] = {}
    cfg = make_cfg("deepseek")
    prior = store.build_row(
        "deepseek",
        "deepseek-chat",
        pricing(),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    removal = store.build_removal_row("deepseek", "deepseek-chat", "2026-08-20", VERSION)
    seed_store(repo_root, [prior, removal])
    seed_absence(repo_root, {})
    runner = PipelineRunner()

    pipeline.run(cfg, repo_root, runner, today=TODAY)

    assert runner.pr_urls == []
    assert not (repo_root / pipeline.MARKER_FILE).exists()


def test_run_changed_marker_follows_row_prs(tmp_path, fake_modules, repo_root):
    # a run that opens a row pr touches the marker; a quiet run clears it
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")
    legacy = store.build_row(
        "deepseek",
        "deepseek-legacy",
        pricing(),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [legacy])
    runner = PipelineRunner()

    assert not (repo_root / pipeline.MARKER_FILE).exists()
    pipeline.run(cfg, repo_root, runner, today=TODAY)
    assert (repo_root / pipeline.MARKER_FILE).exists()

    runner.open_prs = [
        {
            "title": runner.created[0][0],
            "body": runner.created[0][1],
            "headRefName": runner.created[0][2],
        }
    ]
    detect["deepseek"] = ["deepseek-chat", "deepseek-legacy"]
    scrape["deepseek"] = {"deepseek-chat": pricing(), "deepseek-legacy": pricing()}
    pipeline.run(cfg, repo_root, runner, today="2026-08-27")
    assert not (repo_root / pipeline.MARKER_FILE).exists()


def test_run_changed_marker_stays_off_on_state_only_change(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # a state-only change with no pr opens nothing reviewable: no marker
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-legacy"]
    scrape["deepseek"] = {"deepseek-legacy": pricing()}
    cfg = make_cfg("deepseek")
    legacy = store.build_row(
        "deepseek",
        "deepseek-legacy",
        pricing(),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [legacy])
    change = announce_change()
    monkeypatch.setattr(
        pipeline.announce,
        "fetch_channels",
        lambda *a: announce.FetchResult((change,), announce_snapshot(), ()),
    )
    runner = PipelineRunner()

    pipeline.run(cfg, repo_root, runner, today=TODAY)

    assert runner.pr_urls == []  # unchanged prices open no pr
    assert not (repo_root / pipeline.MARKER_FILE).exists()


def commit_fx(repo_root: Path, rates: dict[str, dict[str, float]]) -> None:
    (repo_root / "data" / "catalog").mkdir(parents=True, exist_ok=True)
    (repo_root / "data" / "catalog" / "fx-rates.json").write_text(
        json.dumps(rates) + "\n", encoding="utf-8"
    )
    git(repo_root, "add", ".")
    git(repo_root, "commit", "-m", "seed fx")


def test_eur_quote_row_converts_and_opens_pr(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["scaleway"] = ["m"]
    scrape["scaleway"] = {
        "m": Pricing(1e-6, 2e-6, "chat", 65536, currency="EUR"),
    }
    commit_fx(repo_root, {"EUR": {"2026-08-26": 1.1643}})
    cfg = make_cfg("scaleway")
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    assert [model_id for model_id, _url in report.providers["scaleway"].prs] == ["m"]
    rows = branch_rows(repo_root, "pricelog/seed", "scaleway")
    assert len(rows) == 1
    row = rows[0]
    assert row["rates"]["input"] == 1.1643
    assert row["rates"]["output"] == 2.3286
    assert row["currency"] == "EUR"
    assert row["provenance"]["fx_rate"] == 1.1643
    assert row["provenance"]["fx_rate_date"] == TODAY
    assert "quoted `1 EUR per 1M tokens`, rate `1.1643`" in runner.created[0][1]
    assert_default_branch_clean(repo_root, tip="seed fx")


def test_eur_refresh_converts_against_the_dated_rate(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["scaleway"] = ["m"]
    scrape["scaleway"] = {
        "m": Pricing(1e-6, 2e-6, "chat", 65536, currency="EUR"),
    }
    commit_fx(repo_root, {"EUR": {"2026-08-19": 1.05, "2026-08-26": 1.1643}})
    prior = {
        "schema": 4,
        "source": "scaleway",
        "model_id": "m",
        "observed_at": "2026-08-19",
        "currency": "EUR",
        "rates": {"input": 1.05, "output": 2.1},
        "provenance": {
            "url": "https://example.com/pricing",
            "fx_rate": 1.05,
            "fx_rate_date": "2026-08-19",
        },
    }
    seed_store(repo_root, [prior])
    cfg = make_cfg("scaleway")
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert [model_id for model_id, _url in report.providers["scaleway"].prs] == ["m"]
    rows = branch_rows(repo_root, batch_branch("scaleway"), "scaleway")
    assert len(rows) == 2
    row = rows[1]
    assert row["rates"]["input"] == 1.1643
    assert row["currency"] == "EUR"
    assert row["provenance"]["fx_rate"] == 1.1643
    assert row["provenance"]["fx_rate_date"] == TODAY
    assert_default_branch_clean(repo_root, tip="seed store")


def test_dbu_provider_uses_the_configured_rate(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["databricks"] = ["m"]
    scrape["databricks"] = {"m": Pricing(7e-8, 1.4e-7, "chat", 65536, currency="DBU")}
    cfg = config.Config(providers=(make_provider_cfg("databricks", currency_rate=0.55),))
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    assert [model_id for model_id, _url in report.providers["databricks"].prs] == ["m"]
    rows = branch_rows(repo_root, "pricelog/seed", "databricks")
    assert len(rows) == 1
    row = rows[0]
    assert row["rates"]["input"] == 0.0385
    assert row["rates"]["output"] == 0.077
    assert row["currency"] == "DBU"
    assert row["provenance"]["fx_rate"] == 0.55
    assert row["provenance"]["fx_rate_date"] == TODAY
    assert_default_branch_clean(repo_root)


def test_missing_fx_rate_fails_the_run_loudly(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["scaleway"] = ["m"]
    scrape["scaleway"] = {"m": Pricing(1e-6, 2e-6, "chat", 65536, currency="EUR")}
    cfg = make_cfg("scaleway")

    with pytest.raises(store.FxError, match="EUR"):
        pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY)

    # nothing was committed or branched, and the marker stays off
    assert_default_branch_clean(repo_root)

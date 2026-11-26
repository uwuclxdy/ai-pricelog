from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

import test_dashscope_page as dashscope_fixtures
import test_moonshot_page as moonshot_fixtures
from ai_pricelog import absence, announce, config, health, openrouter, pipeline, pr, store, web
from ai_pricelog.detectors import dashscope_page as dashscope_detector
from ai_pricelog.detectors import moonshot_page as moonshot_detector
from ai_pricelog.pricing import Pricing
from ai_pricelog.scrapers import dashscope_page as dashscope_scraper
from ai_pricelog.scrapers import moonshot_page as moonshot_scraper
from conftest import git, git_init_repo, register_fake_module

TODAY = "2026-08-26"
VERSION = 4
# captured before the autouse or_models fixture patches the module attribute
REAL_FETCH_MODELS = openrouter.fetch_models


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


fake_det_log = logging.getLogger("ai_pricelog.detectors.fake_det")


class UnscriptedCalls:
    """A fake's unscripted-call assertion, recorded for a teardown check.

    A pipeline run catches the fake's assertion and carries on with an `errors`
    line, so a test that never reads `errors` would stay green; the autouse
    fixture fails each recorded call at teardown unless the test expected it.
    """

    def __init__(self) -> None:
        self.recorded: list[tuple[str, str]] = []
        self.expected: list[tuple[str, str]] = []

    def fail(self, kind: str, where: str) -> None:
        self.recorded.append((kind, where))
        raise AssertionError(f"unscripted {kind} for {where}")

    def expect(self, kind: str, where: str) -> None:
        """Opt out for the one call a test drives on purpose."""
        self.expected.append((kind, where))

    def unexpected(self) -> list[str]:
        remaining = list(self.expected)
        missed: list[str] = []
        for call in self.recorded:
            if call in remaining:
                remaining.remove(call)
            else:
                missed.append(f"{call[0]} for {call[1]}")
        return missed


@pytest.fixture(autouse=True)
def unscripted_calls():
    calls = UnscriptedCalls()
    yield calls
    missed = calls.unexpected()
    assert missed == [], (
        "unscripted fake call(s): "
        + "; ".join(missed)
        + ". Script the value, or declare the call with unscripted_calls.expect(kind, where)"
    )


@pytest.fixture
def fake_modules(monkeypatch, unscripted_calls):
    detect_controls: dict[str, object] = {}
    scrape_controls: dict[str, dict[str, object]] = {}

    def detect(cfg):
        if cfg.key not in detect_controls:
            unscripted_calls.fail("detect", cfg.key)
        result = detect_controls[cfg.key]
        if isinstance(result, Exception):
            raise result
        # an (ids, skips) tuple logs `skips` detect-skip warnings, the
        # detectors' additive-drift line the absence suppression watches
        if isinstance(result, tuple):
            ids, skips = result
            for _ in range(skips):
                fake_det_log.warning(
                    "detect skip for %s: unmapped model name 'Drifted' on https://example.com/models",
                    cfg.key,
                )
            return list(ids)
        return list(result)

    def scrape(cfg, model_id):
        entries = scrape_controls.get(cfg.key, {})
        if model_id not in entries:
            unscripted_calls.fail("scrape", f"{cfg.key}/{model_id}")
        result = entries[model_id]
        if isinstance(result, Exception):
            raise result
        return result

    det = register_fake_module(monkeypatch, "detectors", "fake_det")
    det.detect = detect
    scr = register_fake_module(monkeypatch, "scrapers", "fake_scr")
    scr.scrape = scrape
    return detect_controls, scrape_controls


def test_unscripted_calls_reports_a_call_no_expectation_covers():
    calls = UnscriptedCalls()
    with pytest.raises(AssertionError, match="unscripted scrape for deepseek/a"):
        calls.fail("scrape", "deepseek/a")

    assert calls.unexpected() == ["scrape for deepseek/a"]


def test_unscripted_calls_expectation_covers_one_call():
    # one expectation covers one call: a second unscripted call of the same
    # shape is still reported, so an opt-out mutes nothing beyond itself
    calls = UnscriptedCalls()
    calls.expect("scrape", "deepseek/a")
    with pytest.raises(AssertionError):
        calls.fail("scrape", "deepseek/a")
    assert calls.unexpected() == []

    with pytest.raises(AssertionError):
        calls.fail("scrape", "deepseek/a")
    assert calls.unexpected() == ["scrape for deepseek/a"]


def test_the_unscripted_calls_fixture_fails_at_teardown():
    # calling the fixture's own body is what pins the fixture to the check: a
    # recorded call the test did not declare must fail it, so disabling that
    # assert reds here, and both names and their order ride the message
    teardown = unscripted_calls.__wrapped__()
    calls = next(teardown)
    with pytest.raises(AssertionError, match="unscripted scrape for deepseek/b"):
        calls.fail("scrape", "deepseek/b")
    with pytest.raises(AssertionError, match="unscripted detect for zai"):
        calls.fail("detect", "zai")

    with pytest.raises(AssertionError) as teardown_failure:
        next(teardown)

    assert str(teardown_failure.value).startswith(
        "unscripted fake call(s): scrape for deepseek/b; detect for zai."
    )


@pytest.fixture(autouse=True)
def or_models(monkeypatch):
    models: list[openrouter.OpenrouterModel] = []

    def fake_fetch(*, errors=None, listed=None):
        if listed is not None:
            listed.update(model.id for model in models)
        return list(models)

    monkeypatch.setattr(openrouter, "fetch_models", fake_fetch)
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


def branch_state_paths(repo_root: Path, branch: str, state_dir: str) -> list[str]:
    """Every path a branch commits under one state directory."""
    return git(repo_root, "ls-tree", "-r", "--name-only", branch, state_dir).splitlines()


def test_branch_state_paths_reads_the_committed_tree(tmp_path):
    # only what the branch commits counts: a state file left in the working
    # tree must not read as branch state (the caller's clean-tree check owns it)
    root = tmp_path / "repo"
    git_init_repo(root)
    (root / "state" / "absence").mkdir(parents=True)
    (root / "state" / "absence" / "zai.json").write_text("{}\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "land absence state")

    assert branch_state_paths(root, "main", "state/absence") == ["state/absence/zai.json"]
    assert branch_state_paths(root, "main", "state/announce") == []

    git(root, "checkout", "-b", "side")
    (root / "state" / "absence" / "zai-2.json").write_text("{}\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "land side absence state")

    assert branch_state_paths(root, "side", "state/absence") == [
        "state/absence/zai-2.json",
        "state/absence/zai.json",
    ]
    assert branch_state_paths(root, "main", "state/absence") == ["state/absence/zai.json"]

    (root / "state" / "announce").mkdir()
    (root / "state" / "announce" / "index.json").write_text("{}\n")

    assert branch_state_paths(root, "main", "state/announce") == []
    assert branch_state_paths(root, "side", "state/announce") == []


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

    # the open pr's branch carries the id's row, so the next run holds it as
    # pending: the store on the default branch is still empty (no row)
    assert_default_branch_clean(repo_root, tip="seed store")
    runner.open_prs = [
        {
            "title": runner.created[0][0],
            "body": runner.created[0][1],
            "headRefName": runner.created[0][2],
        }
    ]
    # the page moved since the branch's row: only the hold keeps the refresh
    # from planning a competing row
    scrape["deepseek"]["deepseek-chat"] = pricing(3.3e-7, 1.3e-6)
    second = pipeline.run(cfg, repo_root, runner, today="2026-08-27")
    assert second.providers["deepseek"].skipped_pending == ["deepseek-chat"]
    assert second.providers["deepseek"].candidates == []
    assert len(runner.pr_urls) == 1


def push_pending_branch(repo_root: Path, branch: str, source: str, rows: list[dict]) -> None:
    """Push an open sibling PR's branch carrying `rows` as its `source` shard."""
    git(repo_root, "switch", "-C", branch)
    store.save_shard(rows, repo_root / "data" / "history", source)
    git(repo_root, "add", ".")
    git(repo_root, "commit", "-m", f"sibling {source} update")
    git(repo_root, "push", "origin", branch)
    git(repo_root, "switch", "main")


def or_model(model_id: str, input_mtok: float, output_mtok: float) -> openrouter.OpenrouterModel:
    return openrouter.OpenrouterModel(
        id=model_id,
        name=model_id,
        input_mtok=input_mtok,
        output_mtok=output_mtok,
        cache_read_mtok=None,
        pricing={"prompt": str(input_mtok / 1e6), "completion": str(output_mtok / 1e6)},
    )


def deepseek_legacy() -> dict:
    return store.build_row(
        "deepseek",
        "deepseek-legacy",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )


def deepseek_chat_pending() -> dict:
    return store.build_row(
        "deepseek",
        "deepseek-chat",
        pricing(),
        "2026-08-25",
        "https://example.com/pricing",
        VERSION,
    )


def test_pending_pr_held_id_is_scraped_for_the_verdict_but_writes_no_row(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # the open pr owns deepseek-chat's row: the scrape may plan no competing
    # row, but its outcome still feeds the provider's health verdict
    detect, scrape = fake_modules
    calls = counted_scrapes(monkeypatch)
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing(3.0e-7, 1.2e-6)}
    cfg = make_cfg("deepseek")
    legacy = deepseek_legacy()
    seed_store(repo_root, [legacy])
    pending_branch = pr.branch_name("deepseek@2026-08-25-000000")
    push_pending_branch(repo_root, pending_branch, "deepseek", [legacy, deepseek_chat_pending()])
    runner = PipelineRunner(
        open_prs=[
            {"title": "Update Deepseek price history", "body": "", "headRefName": pending_branch}
        ]
    )

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    provider_report = report.providers["deepseek"]
    assert calls == [("deepseek", "deepseek-chat")]
    assert provider_report.tried == ["deepseek-chat"]
    assert provider_report.skipped_no_pricing == []
    assert provider_report.skipped_pending == ["deepseek-chat"]
    assert provider_report.candidates == []
    assert provider_report.errors == []
    assert runner.pr_urls == []
    assert branch_state_paths(repo_root, "main", absence.ABSENCE_DIR) == []
    assert_default_branch_clean(repo_root, tip="seed store")


def test_a_pending_skip_line_cannot_be_forged(tmp_path, fake_modules, repo_root, caplog):
    # the pending-skip line is a health-parsed soft signal and interpolates a
    # page-sourced id too: a newline in it must not forge a hard line
    detect, scrape = fake_modules
    page_id = "a\nERROR:ai_pricelog.pipeline:detector for openai failed"
    detect["deepseek"] = [page_id]
    scrape["deepseek"] = {page_id: pricing()}
    cfg = make_cfg("deepseek")
    legacy = deepseek_legacy()
    seed_store(repo_root, [legacy])
    pending = store.build_row(
        "deepseek", page_id, pricing(), "2026-08-25", "https://example.com/pricing", VERSION
    )
    branch = pr.branch_name("deepseek@2026-08-25-000000")
    push_pending_branch(repo_root, branch, "deepseek", [legacy, pending])
    runner = PipelineRunner(open_prs=[{"title": "Update", "body": "", "headRefName": branch}])
    with caplog.at_level(logging.INFO):
        report = pipeline.run(cfg, repo_root, runner, today=TODAY)
    assert report.providers["deepseek"].skipped_pending == [page_id]
    assert report.providers["deepseek"].errors == []
    lines = _logged_lines(caplog)
    assert not any("\n" in line for line in lines)
    assert "openai" not in health.parse_log(lines)


def test_pending_scan_holds_the_full_id_on_the_branch_source_only(
    tmp_path, fake_modules, repo_root, or_models
):
    # an open openrouter pr carrying `x/foo-bar` holds exactly (openrouter,
    # x/foo-bar). its body names the id, so a substring scan over pr text also
    # held openrouter `x/foo`, zai `foo`, and froze zai `foo-b`'s absence counter
    detect, scrape = fake_modules
    detect["zai"] = ["foo"]  # zai `foo-b` is gone from the page
    scrape["zai"] = {"foo": pricing(3.0e-7, 1.2e-6)}
    cfg = make_cfg("zai")
    zai_rows = [
        store.build_row(
            "zai",
            model_id,
            Pricing(0.2e-6, 0.4e-6, "chat"),
            "2026-08-19",
            "https://example.com/pricing",
            VERSION,
        )
        for model_id in ("foo", "foo-b")
    ]
    or_ids = ("x/foo", "x/foo-bar", "x/foo-bar-baz")
    or_landed = [openrouter.build_row(or_model(i, 0.1, 0.2), "2026-08-19", VERSION) for i in or_ids]
    assert all(row is not None for row in or_landed)
    seed_store(repo_root, [*zai_rows, *or_landed])
    or_pending = openrouter.build_row(or_model("x/foo-bar", 0.15, 0.3), "2026-08-25", VERSION)
    assert or_pending is not None
    pending_branch = pr.branch_name("openrouter@2026-08-25-000000")
    push_pending_branch(repo_root, pending_branch, "openrouter", [*or_landed, or_pending])
    or_models.extend(or_model(i, 0.27, 1.1) for i in or_ids)
    runner = PipelineRunner(
        open_prs=[
            {
                "title": "Update OpenRouter price history (1 row)",
                "body": "| openrouter | `x/foo-bar` | 2026-08-25 | 0.15 | — | — | 0.3 |\n",
                "headRefName": pending_branch,
            }
        ]
    )

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    or_report = report.providers["openrouter"]
    assert or_report.candidates == ["x/foo", "x/foo-bar-baz"]
    assert or_report.skipped_pending == ["x/foo-bar"]
    zai_report = report.providers["zai"]
    assert zai_report.skipped_pending == []
    assert [model_id for model_id, _url in zai_report.prs] == ["foo"]
    assert branch_absence(repo_root, batch_branch("zai")) == {
        "zai": {"foo-b": {"absent_runs": 1, "since": TODAY}}
    }
    assert_default_branch_clean(repo_root, tip="seed store")


def test_pending_scan_ignores_pr_text_without_a_branch_row(tmp_path, fake_modules, repo_root):
    # an open pr whose title and body name deepseek-chat while its branch
    # carries no deepseek-chat row holds nothing: the branch is what lands
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")
    legacy = deepseek_legacy()
    seed_store(repo_root, [legacy])
    other = store.build_row(
        "deepseek",
        "deepseek-other",
        pricing(),
        "2026-08-25",
        "https://example.com/pricing",
        VERSION,
    )
    pending_branch = pr.branch_name("deepseek@2026-08-25-000000")
    push_pending_branch(repo_root, pending_branch, "deepseek", [legacy, other])
    runner = PipelineRunner(
        open_prs=[
            {
                "title": "Add deepseek-chat pricing for Deepseek",
                "body": "| deepseek | `deepseek-chat` | 2026-08-25 |",
                "headRefName": pending_branch,
            }
        ]
    )

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert report.providers["deepseek"].skipped_pending == []
    assert [model_id for model_id, _url in report.providers["deepseek"].prs] == ["deepseek-chat"]
    assert_default_branch_clean(repo_root, tip="seed store")


def test_unfetchable_pending_branches_open_no_pr(tmp_path, fake_modules, repo_root):
    # the held set comes from the open branches; a run that cannot fetch them
    # cannot tell which models are held, so it opens nothing and the next run
    # retries (cloudy's pick, 2026-10-18)
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")
    legacy = deepseek_legacy()
    seed_store(repo_root, [legacy])
    pending_branch = pr.branch_name("deepseek@2026-08-25-000000")
    push_pending_branch(repo_root, pending_branch, "deepseek", [legacy, deepseek_chat_pending()])
    runner = PipelineRunner(
        open_prs=[
            {"title": "Update Deepseek price history", "body": "", "headRefName": pending_branch}
        ],
        failures={
            "+refs/heads/pricelog/*:refs/remotes/pending/*": pr.PrError("fetch failed: network")
        },
    )

    pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert runner.pr_urls == []
    pushed = git(repo_root, "ls-remote", "--heads", "origin", "pricelog/*").splitlines()
    assert [line.split("\t")[1] for line in pushed] == [f"refs/heads/{pending_branch}"]
    assert_default_branch_clean(repo_root, tip="seed store")


def test_same_day_update_row_on_an_open_branch_holds_its_model(tmp_path, fake_modules, repo_root):
    # a same-day row landed, then a later same-day update rides an open pr: the
    # update shares the landed row's (source, model_id, observed_at) key, so a
    # key-based "not landed" test misses it and every run reopens the drift
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing(3.0e-7, 1.2e-6)}
    cfg = make_cfg("deepseek")
    landed = store.build_row(
        "deepseek", "deepseek-chat", pricing(), TODAY, "https://example.com/pricing", VERSION
    )
    seed_store(repo_root, [landed])
    update = store.build_row(
        "deepseek",
        "deepseek-chat",
        pricing(3.0e-7, 1.2e-6),
        TODAY,
        "https://example.com/pricing",
        VERSION,
    )
    pending_branch = pr.branch_name(f"deepseek@{TODAY}-010000")
    push_pending_branch(repo_root, pending_branch, "deepseek", [landed, update])
    runner = PipelineRunner(open_prs=[{"title": "t", "body": "", "headRefName": pending_branch}])

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="020000")

    assert report.providers["deepseek"].skipped_pending == ["deepseek-chat"]
    assert runner.pr_urls == []


def test_held_rows_key_on_their_own_source(tmp_path, fake_modules, repo_root, or_models):
    # an open openrouter branch carries rows for ids `foo`, `bar` and `baz`,
    # spelled exactly as zai's own stored and new ids: none of them holds zai.
    # its `baz` row breaks the row contract, so it reaches the first-seen check
    # only through the held set, never through the union
    detect, scrape = fake_modules
    detect["zai"] = ["foo", "baz"]  # zai `bar` is gone from the page
    scrape["zai"] = {"foo": pricing(3.0e-7, 1.2e-6), "baz": pricing()}
    cfg = make_cfg("zai")
    zai_rows = [
        store.build_row(
            "zai",
            model_id,
            Pricing(0.2e-6, 0.4e-6, "chat"),
            "2026-08-19",
            "https://example.com/pricing",
            VERSION,
        )
        for model_id in ("foo", "bar")
    ]
    seed_store(repo_root, zai_rows)
    or_rows = [
        openrouter.build_row(or_model(model_id, 0.15, 0.3), "2026-08-25", VERSION)
        for model_id in ("foo", "bar", "baz")
    ]
    assert all(row is not None for row in or_rows)
    or_rows[2]["surprise"] = "a hand edit the row contract refuses"
    pending_branch = pr.branch_name("openrouter@2026-08-25-000000")
    push_pending_branch(repo_root, pending_branch, "openrouter", or_rows)
    runner = PipelineRunner(open_prs=[{"title": "t", "body": "", "headRefName": pending_branch}])

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    zai_report = report.providers["zai"]
    assert zai_report.skipped_pending == []
    assert sorted(model_id for model_id, _url in zai_report.prs) == ["baz", "foo"]
    assert branch_absence(repo_root, batch_branch("zai")) == {
        "zai": {"bar": {"absent_runs": 1, "since": TODAY}}
    }


@pytest.mark.parametrize(
    "failure",
    [
        "for-each-ref refs/remotes/pending",
        "show refs/remotes/pending/",
    ],
    ids=["ref-listing", "shard-read"],
)
def test_unreadable_pending_branch_rows_open_no_pr(tmp_path, fake_modules, repo_root, failure):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")
    legacy = deepseek_legacy()
    seed_store(repo_root, [legacy])
    pending_branch = pr.branch_name("deepseek@2026-08-25-000000")
    push_pending_branch(repo_root, pending_branch, "deepseek", [legacy, deepseek_chat_pending()])
    runner = PipelineRunner(
        open_prs=[{"title": "t", "body": "", "headRefName": pending_branch}],
        failures={failure: pr.PrError("read failed")},
    )

    pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert runner.pr_urls == []


def test_unparseable_pending_shard_opens_no_pr(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")
    seed_store(repo_root, [deepseek_legacy()])
    pending_branch = pr.branch_name("deepseek@2026-08-25-000000")
    git(repo_root, "switch", "-C", pending_branch)
    (repo_root / "data" / "history" / "deepseek.ndjson").write_text("{not json\n")
    git(repo_root, "add", ".")
    git(repo_root, "commit", "-m", "torn shard")
    git(repo_root, "push", "origin", pending_branch)
    git(repo_root, "switch", "main")
    runner = PipelineRunner(open_prs=[{"title": "t", "body": "", "headRefName": pending_branch}])

    pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert runner.pr_urls == []


@pytest.mark.parametrize(
    "head_ref", ["pricelog/seed", "pricelog/deepseek-gone-12345678"], ids=["seed", "missing-ref"]
)
def test_open_pricelog_pr_without_readable_rows_opens_no_pr(
    tmp_path, fake_modules, repo_root, head_ref
):
    # the seed pr's rows hold models too, and an open pricelog pr whose branch
    # never arrives cannot say what it holds: either way the run holds
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")
    seed_store(repo_root, [deepseek_legacy()])
    failures = (
        {"+refs/heads/pricelog/*:refs/remotes/pending/*": pr.PrError("fetch failed")}
        if head_ref == "pricelog/seed"
        else {}
    )
    runner = PipelineRunner(
        open_prs=[{"title": "t", "body": "", "headRefName": head_ref}], failures=failures
    )

    pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert runner.pr_urls == []


def _health_main_on(
    tmp_path, caplog, monkeypatch, issues: list[str], previous: list[str] | None = None
) -> list[list[str]]:
    """Run the health step over this test's captured run log; return its gh calls.

    `previous` is the prior run's log, the two-consecutive gate's other side.
    """
    log_path = tmp_path / "health-run.log"
    log_path.write_text("\n".join(_logged_lines(caplog)) + "\n", encoding="utf-8")
    calls: list[list[str]] = []

    def gh(args: list[str]) -> str:
        calls.append(args)
        if args[:2] == ["issue", "list"]:
            return json.dumps(
                [{"number": n, "title": f"provider broken: {key}"} for n, key in enumerate(issues)]
            )
        return ""

    monkeypatch.setattr(health, "_gh", gh)
    monkeypatch.setattr(
        health,
        "previous_run",
        lambda repo, run_id: None if previous is None else ("47", previous),
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", "uwuclxdy/ai-pricelog")
    monkeypatch.setenv("GITHUB_RUN_ID", "48")
    assert health.main([str(log_path)]) == 0
    return calls


def test_health_closes_only_issues_of_providers_the_run_checked(
    tmp_path, fake_modules, repo_root, caplog, monkeypatch
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    seed_store(repo_root, [deepseek_legacy()])
    caplog.set_level(logging.INFO)
    pipeline.run(make_cfg("deepseek"), repo_root, PipelineRunner(), today=TODAY, now="000000")

    calls = _health_main_on(tmp_path, caplog, monkeypatch, ["deepseek", "zai", "openrouter"])

    closed = [call[2] for call in calls if call[:2] == ["issue", "close"]]
    # deepseek and the openrouter pass ran clean; zai is not in this run's config
    assert closed == ["0", "2"]


def test_run_crashing_before_its_checked_line_closes_no_issue(
    tmp_path, fake_modules, repo_root, caplog, monkeypatch
):
    # a crash anywhere before the provider loop and the openrouter pass finish
    # leaves no checked line, so no provider's issue reads as recovered
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    seed_store(repo_root, [deepseek_legacy()])

    def crash(*args, **kwargs):
        raise RuntimeError("openrouter pass crashed")

    monkeypatch.setattr(pipeline, "_openrouter_rows", crash)
    caplog.set_level(logging.INFO)
    with pytest.raises(RuntimeError, match="openrouter pass crashed"):
        pipeline.run(make_cfg("deepseek"), repo_root, PipelineRunner(), today=TODAY, now="000000")

    calls = _health_main_on(tmp_path, caplog, monkeypatch, ["deepseek"])

    assert not [call for call in calls if call[:2] == ["issue", "close"]]


def test_seed_hold_warns_and_closes_no_provider_issue(
    tmp_path, fake_modules, repo_root, caplog, monkeypatch, capsys
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {}
    runner = PipelineRunner(
        open_prs=[{"title": "Seed price history", "body": "", "headRefName": "pricelog/seed"}]
    )
    caplog.set_level(logging.INFO)
    pipeline.run(make_cfg("deepseek"), repo_root, runner)
    capsys.readouterr()

    calls = _health_main_on(tmp_path, caplog, monkeypatch, ["deepseek"])

    assert not [call for call in calls if call[:2] == ["issue", "close"]]
    assert any(line.startswith("::warning::") for line in capsys.readouterr().out.splitlines())


def test_provider_pricing_none_of_its_ids_opens_its_issue_on_the_second_run(
    tmp_path, fake_modules, repo_root, caplog, monkeypatch
):
    # a page whose tables the scraper no longer matches returns no pricing for
    # every id, the stored refresh and the new candidate alike: nothing raised,
    # yet the provider recorded no price
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-legacy", "deepseek-new"]
    scrape["deepseek"] = {"deepseek-legacy": None, "deepseek-new": None}
    seed_store(repo_root, [deepseek_legacy()])
    caplog.set_level(logging.INFO)
    pipeline.run(make_cfg("deepseek"), repo_root, PipelineRunner(), today=TODAY, now="000000")
    first = _logged_lines(caplog)
    caplog.clear()
    pipeline.run(make_cfg("deepseek"), repo_root, PipelineRunner(), today=TODAY, now="000001")

    calls = _health_main_on(tmp_path, caplog, monkeypatch, [], previous=first)

    issues = health.parse_log(first)
    assert set(issues) == {"deepseek"}
    assert issues["deepseek"]["hard"] == [_priced_none_line("deepseek", 2)]
    created = [call[3] for call in calls if call[:2] == ["issue", "create"]]
    assert created == ["provider broken: deepseek"]


def _priced_none_line(key: str, tried: int) -> str:
    ids = "id" if tried == 1 else "ids"
    return (
        f"ERROR:ai_pricelog.pipeline:{health.PRICED_NONE} {key}:"
        f" {tried} {ids}, each returned no pricing"
    )


def test_priced_none_line_counts_a_repeated_detected_id_once(
    tmp_path, fake_modules, repo_root, caplog
):
    # a detector listing one id twice refreshes it twice, so two attempts are
    # skipped while the line names the id once
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-legacy", "deepseek-legacy"]
    scrape["deepseek"] = {"deepseek-legacy": None}
    seed_store(repo_root, [deepseek_legacy()])

    with caplog.at_level(logging.INFO):
        pipeline.run(make_cfg("deepseek"), repo_root, PipelineRunner(), today=TODAY)

    issues = health.parse_log(_logged_lines(caplog))
    assert set(issues) == {"deepseek"}
    assert issues["deepseek"]["hard"] == [_priced_none_line("deepseek", 1)]


def test_priced_only_ids_count_as_tried_ids(tmp_path, fake_modules, repo_root, monkeypatch, caplog):
    # the pricing page keeps a dated snapshot the candidate page omits: it is
    # the only id the run tries, and its scrape returns no pricing
    calls = priced_only_source(fake_modules, monkeypatch, ["qwen-max-0501"])
    detect, scrape = fake_modules
    detect["dashscope"] = []
    scrape["dashscope"] = {"qwen-max-0501": None}
    seed_store(repo_root, [stored_row("qwen-max-0501")])

    with caplog.at_level(logging.INFO):
        pipeline.run(make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY)

    assert calls == [("dashscope", "qwen-max-0501")]
    issues = health.parse_log(_logged_lines(caplog))
    assert set(issues) == {"dashscope"}
    assert issues["dashscope"]["hard"] == [_priced_none_line("dashscope", 1)]


def test_priced_none_rule_spares_a_provider_that_priced_or_raised(
    tmp_path, fake_modules, repo_root, caplog
):
    # deepseek prices none of its ids (the rule's control); zai prices one id
    # and skips the other; moonshot's only failure is the scrape that raised,
    # which its own line already classes hard
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-legacy"]
    scrape["deepseek"] = {"deepseek-legacy": None}
    detect["zai"] = ["a", "b"]
    scrape["zai"] = {"a": pricing(), "b": None}
    detect["moonshot"] = ["a", "b"]
    scrape["moonshot"] = {"a": web.FetchError("no pricing table on https://x"), "b": None}
    seed_store(
        repo_root,
        [
            deepseek_legacy(),
            *(
                stored_row(model_id, source=source)
                for source in ("zai", "moonshot")
                for model_id in ("a", "b")
            ),
        ],
    )

    with caplog.at_level(logging.INFO):
        report = pipeline.run(
            make_cfg("deepseek", "zai", "moonshot"), repo_root, PipelineRunner(), today=TODAY
        )

    assert report.providers["zai"].skipped_no_pricing == ["b"]
    assert report.providers["moonshot"].skipped_no_pricing == ["b"]
    issues = health.parse_log(_logged_lines(caplog))
    assert set(issues) == {"deepseek", "moonshot"}
    assert issues["deepseek"]["hard"] == [_priced_none_line("deepseek", 1)]
    assert issues["moonshot"]["hard"] == [
        "ERROR:ai_pricelog.pipeline:refresh scrape failed for 'a' (moonshot)"
    ]


def test_priced_none_rule_spares_a_provider_that_tried_no_id(
    tmp_path, fake_modules, repo_root, caplog
):
    # deepseek prices none of its ids (the rule's control); zai's page lists
    # nothing, so its stored id goes the absence path and no scrape runs; the
    # openrouter api lists no model
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-legacy"]
    scrape["deepseek"] = {"deepseek-legacy": None}
    detect["zai"] = []
    scrape["zai"] = {}
    seed_store(repo_root, [deepseek_legacy(), stored_row("a", source="zai")])

    with caplog.at_level(logging.INFO):
        pipeline.run(make_cfg("deepseek", "zai"), repo_root, PipelineRunner(), today=TODAY)

    issues = health.parse_log(_logged_lines(caplog))
    assert set(issues) == {"deepseek"}
    assert issues["deepseek"]["hard"] == [_priced_none_line("deepseek", 1)]


def test_priced_none_issue_closes_once_the_provider_prices_again(
    tmp_path, fake_modules, repo_root, caplog, monkeypatch
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-legacy"]
    scrape["deepseek"] = {"deepseek-legacy": None}
    seed_store(repo_root, [deepseek_legacy()])
    caplog.set_level(logging.INFO)
    pipeline.run(make_cfg("deepseek"), repo_root, PipelineRunner(), today=TODAY)

    still_broken = _health_main_on(tmp_path, caplog, monkeypatch, ["deepseek"])

    assert not [call for call in still_broken if call[:2] == ["issue", "close"]]

    caplog.clear()
    scrape["deepseek"] = {"deepseek-legacy": Pricing(0.1e-6, 0.2e-6, "chat")}
    pipeline.run(make_cfg("deepseek"), repo_root, PipelineRunner(), today=TODAY)

    recovered = _health_main_on(tmp_path, caplog, monkeypatch, ["deepseek"])

    assert [call[2] for call in recovered if call[:2] == ["issue", "close"]] == ["0"]


def test_priced_none_rule_reads_a_held_ids_scrape_for_the_verdict(
    tmp_path, fake_modules, repo_root, caplog, monkeypatch
):
    # m3 comes back unpriced while m31's row rides an open pr: the held scrape
    # is the evidence the provider is alive, so the blind sibling alone does not
    # fire the rule, and two held runs in a row open no issue
    detect, scrape = fake_modules
    detect["zai"] = ["m3", "m31"]
    scrape["zai"] = {"m3": None, "m31": pricing()}
    seed_store(repo_root, [stored_row("m3", source="zai")])
    caplog.set_level(logging.INFO)
    runner = PipelineRunner()

    pipeline.run(make_cfg("zai"), repo_root, runner, today=TODAY, now="000000")
    previous = _logged_lines(caplog)
    assert len(runner.pr_urls) == 1
    assert not health.parse_log(previous).get("zai", {}).get("hard")

    runner.open_prs = [
        {
            "title": runner.created[0][0],
            "body": runner.created[0][1],
            "headRefName": runner.created[0][2],
        }
    ]
    for now in ("000001", "000002"):
        caplog.clear()
        report = pipeline.run(make_cfg("zai"), repo_root, runner, today=TODAY, now=now)
        lines = _logged_lines(caplog)
        assert report.providers["zai"].tried == ["m3", "m31"]
        assert report.providers["zai"].skipped_pending == ["m31"]
        assert not any(health.PRICED_NONE in line for line in lines)
        assert not health.parse_log(lines).get("zai", {}).get("hard")
        calls = _health_main_on(tmp_path, caplog, monkeypatch, [], previous=previous)
        assert not [call for call in calls if call[:2] == ["issue", "create"]]
        previous = lines

    # near miss: the held id is blind too, so every tried id came back unpriced
    caplog.clear()
    scrape["zai"] = {"m3": None, "m31": None}
    pipeline.run(make_cfg("zai"), repo_root, runner, today=TODAY, now="000003")

    issues = health.parse_log(_logged_lines(caplog))
    assert issues["zai"]["hard"] == [_priced_none_line("zai", 2)]


def test_held_only_run_keeps_a_blind_provider_open_until_a_held_id_prices(
    tmp_path, fake_modules, repo_root, caplog, monkeypatch
):
    # every stored id is held and the page lists no new candidate: the held
    # scrape decides recovery, so an unpriced held id keeps the issue open and
    # a priced one closes it
    detect, scrape = fake_modules
    detect["zai"] = ["m31"]
    scrape["zai"] = {"m31": None}
    held = stored_row("m31", source="zai")
    newer = store.build_row(
        "zai", "m31", pricing(3.0e-7, 1.2e-6), "2026-08-25", "https://example.com/pricing", VERSION
    )
    seed_store(repo_root, [held])
    branch = pr.branch_name("zai@2026-08-25-000000")
    push_pending_branch(repo_root, branch, "zai", [held, newer])
    runner = PipelineRunner(open_prs=[{"title": "t", "body": "", "headRefName": branch}])
    caplog.set_level(logging.INFO)

    report = pipeline.run(make_cfg("zai"), repo_root, runner, today=TODAY, now="000000")

    assert report.providers["zai"].candidates == []
    assert report.providers["zai"].tried == ["m31"]
    issues = health.parse_log(_logged_lines(caplog))
    assert issues["zai"]["hard"] == [_priced_none_line("zai", 1)]
    still_broken = _health_main_on(tmp_path, caplog, monkeypatch, ["zai"])

    assert not [call for call in still_broken if call[:2] == ["issue", "close"]]

    caplog.clear()
    scrape["zai"] = {"m31": pricing()}
    pipeline.run(make_cfg("zai"), repo_root, runner, today=TODAY, now="000001")

    recovered = _health_main_on(tmp_path, caplog, monkeypatch, ["zai"])

    assert [call[2] for call in recovered if call[:2] == ["issue", "close"]] == ["0"]


def test_priced_none_rule_reads_a_held_candidates_scrape_for_the_verdict(
    tmp_path, fake_modules, repo_root, caplog
):
    # fresh's first row rides an open pr but fails the row contract, so it drops
    # out of the union while the pr still holds its key: the held page id is
    # scraped for the verdict, so m3's blind scrape alone fires no rule
    detect, scrape = fake_modules
    detect["zai"] = ["m3", "fresh"]
    scrape["zai"] = {"m3": None, "fresh": pricing()}
    m3 = stored_row("m3", source="zai")
    seed_store(repo_root, [m3])
    refused = store.build_row(
        "zai", "fresh", pricing(), "2026-08-25", "https://example.com/pricing", VERSION
    )
    refused["surprise"] = "a hand edit the row contract refuses"
    pending_branch = pr.branch_name("zai@2026-08-25-000000")
    push_pending_branch(repo_root, pending_branch, "zai", [m3, refused])
    runner = PipelineRunner(open_prs=[{"title": "t", "body": "", "headRefName": pending_branch}])
    caplog.set_level(logging.INFO)

    report = pipeline.run(make_cfg("zai"), repo_root, runner, today=TODAY, now="000000")

    provider_report = report.providers["zai"]
    assert provider_report.detected == ["m3", "fresh"]
    assert provider_report.candidates == []
    assert provider_report.tried == ["fresh", "m3"]
    assert provider_report.skipped_pending == ["fresh"]
    assert provider_report.errors == []
    # the held scrape plans no row: no pr opens, so no branch carries a row,
    # a catalog seed or an absence file
    assert runner.pr_urls == []
    assert_default_branch_clean(repo_root, tip="seed store")
    assert len(branch_rows(repo_root, pending_branch, "zai")) == 2
    lines = _logged_lines(caplog)
    assert not any(health.PRICED_NONE in line for line in lines)
    assert not health.parse_log(lines).get("zai", {}).get("hard")

    # near miss: the held candidate is blind too, so every tried id came back unpriced
    caplog.clear()
    scrape["zai"] = {"m3": None, "fresh": None}
    pipeline.run(make_cfg("zai"), repo_root, runner, today=TODAY, now="000001")

    issues = health.parse_log(_logged_lines(caplog))
    assert issues["zai"]["hard"] == [_priced_none_line("zai", 2)]


def test_held_candidate_scrape_failure_logs_the_unheld_candidates_hard_line(
    tmp_path, fake_modules, repo_root, caplog
):
    # a held candidate's raise is the evidence an unheld candidate's raise is,
    # not a silent skip: it lands in errors and logs the same parseable line
    detect, scrape = fake_modules
    detect["zai"] = ["fresh"]
    scrape["zai"] = {"fresh": web.FetchError("fresh boom")}
    m3 = stored_row("m3", source="zai")
    seed_store(repo_root, [m3])
    runner = PipelineRunner()
    caplog.set_level(logging.INFO)
    line = "ERROR:ai_pricelog.pipeline:scraper zai failed for 'fresh'"

    first = pipeline.run(make_cfg("zai"), repo_root, runner, today=TODAY, now="000000")

    assert first.providers["zai"].errors == ["FetchError: fresh boom"]
    assert _logged_lines(caplog).count(line) == 1

    caplog.clear()
    refused = store.build_row(
        "zai", "fresh", pricing(), "2026-08-25", "https://example.com/pricing", VERSION
    )
    refused["surprise"] = "a hand edit the row contract refuses"
    pending_branch = pr.branch_name("zai@2026-08-25-000000")
    push_pending_branch(repo_root, pending_branch, "zai", [m3, refused])
    runner.open_prs = [{"title": "t", "body": "", "headRefName": pending_branch}]

    second = pipeline.run(make_cfg("zai"), repo_root, runner, today=TODAY, now="000001")

    provider_report = second.providers["zai"]
    assert provider_report.candidates == []
    assert provider_report.tried == ["fresh"]
    assert provider_report.skipped_pending == ["fresh"]
    assert provider_report.errors == ["FetchError: fresh boom"]
    assert _logged_lines(caplog).count(line) == 1


def test_openrouter_pass_follows_the_priced_none_rule(
    tmp_path, fake_modules, repo_root, caplog, or_models
):
    # every entry the api lists is an alias, so the pass builds no priced row
    or_models.append(
        openrouter.OpenrouterModel(
            id="openai/gpt-x-latest",
            name="gpt-x-latest",
            input_mtok=None,
            output_mtok=None,
            cache_read_mtok=None,
            alias_target="openai/gpt-x",
        )
    )
    seed_store(repo_root, [deepseek_legacy()])
    caplog.set_level(logging.INFO)
    report = pipeline.run(make_cfg(), repo_root, PipelineRunner(), today=TODAY, now="000000")

    assert report.providers["openrouter"].skipped_no_pricing == ["openai/gpt-x-latest"]
    issues = health.parse_log(_logged_lines(caplog))
    assert set(issues) == {"openrouter"}
    assert issues["openrouter"]["hard"] == [_priced_none_line("openrouter", 1)]

    # near miss: one priced entry beside the alias
    caplog.clear()
    or_models.append(or_model("openai/gpt-x", 1.0, 2.0))
    pipeline.run(make_cfg(), repo_root, PipelineRunner(), today=TODAY, now="000001")

    assert health.parse_log(_logged_lines(caplog)) == {}


def test_held_dedup_spelling_holds_the_page_id(tmp_path, fake_modules, repo_root, monkeypatch):
    # the page renamed `foo` to `foo-v2`; an open branch carries a `foo` row
    # the row contract refuses, so only the held set can settle the page id,
    # through the same spelling list the store lookup uses
    detect, scrape = fake_modules
    scraper_module = sys.modules["ai_pricelog.scrapers.fake_scr"]
    monkeypatch.setattr(
        scraper_module,
        "dedup_keys",
        lambda model_id: ["foo"] if model_id == "foo-v2" else [],
        raising=False,
    )
    legacy = store.build_row(
        "zai", "zai-legacy", pricing(), "2026-08-19", "https://example.com/pricing", VERSION
    )
    seed_store(repo_root, [legacy])
    detect["zai"] = ["foo-v2", "zai-legacy"]
    scrape["zai"] = {"zai-legacy": pricing(), "foo-v2": pricing()}
    refused = store.build_row(
        "zai", "foo", pricing(), "2026-08-25", "https://example.com/pricing", VERSION
    )
    refused["surprise"] = "a hand edit the row contract refuses"
    pending_branch = pr.branch_name("zai@2026-08-25-000000")
    push_pending_branch(repo_root, pending_branch, "zai", [legacy, refused])
    runner = PipelineRunner(open_prs=[{"title": "t", "body": "", "headRefName": pending_branch}])

    report = pipeline.run(make_cfg("zai"), repo_root, runner, today=TODAY, now="000000")

    provider_report = report.providers["zai"]
    assert provider_report.skipped_pending == ["foo-v2"]
    assert provider_report.candidates == []
    assert provider_report.tried == ["foo-v2", "zai-legacy"]
    assert provider_report.errors == []
    assert runner.pr_urls == []


def test_non_shard_file_under_history_on_a_branch_is_not_a_read_failure(
    tmp_path, fake_modules, repo_root
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    legacy = deepseek_legacy()
    seed_store(repo_root, [legacy])
    pending_branch = pr.branch_name("deepseek@2026-08-25-000000")
    git(repo_root, "switch", "-C", pending_branch)
    (repo_root / "data" / "history" / "README.md").write_text("shards live here\n")
    git(repo_root, "add", ".")
    git(repo_root, "commit", "-m", "a note beside the shards")
    git(repo_root, "push", "origin", pending_branch)
    git(repo_root, "switch", "main")
    runner = PipelineRunner(open_prs=[{"title": "t", "body": "", "headRefName": pending_branch}])

    report = pipeline.run(make_cfg("deepseek"), repo_root, runner, today=TODAY, now="000000")

    assert [model_id for model_id, _url in report.providers["deepseek"].prs] == ["deepseek-chat"]


def test_held_run_warns_and_closes_no_provider_issue(
    tmp_path, fake_modules, repo_root, caplog, monkeypatch, capsys
):
    # a held run ran no provider, so its log says nothing about provider
    # health: the health step flags the hold and leaves every issue as it is
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")
    legacy = deepseek_legacy()
    seed_store(repo_root, [legacy])
    pending_branch = pr.branch_name("deepseek@2026-08-25-000000")
    push_pending_branch(repo_root, pending_branch, "deepseek", [legacy, deepseek_chat_pending()])
    runner = PipelineRunner(
        open_prs=[{"title": "t", "body": "", "headRefName": pending_branch}],
        failures={"+refs/heads/pricelog/*:refs/remotes/pending/*": pr.PrError("fetch failed")},
    )
    caplog.set_level(logging.INFO)
    pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")
    log_path = tmp_path / "run.log"
    log_path.write_text("\n".join(_logged_lines(caplog)) + "\n", encoding="utf-8")
    gh_calls: list[list[str]] = []

    def gh(args: list[str]) -> str:
        gh_calls.append(args)
        if args[:2] == ["issue", "list"]:
            return json.dumps([{"number": 7, "title": "provider broken: deepseek"}])
        return ""

    monkeypatch.setattr(health, "_gh", gh)
    monkeypatch.setattr(health, "previous_run", lambda repo, run_id: None)
    monkeypatch.setenv("GITHUB_REPOSITORY", "uwuclxdy/ai-pricelog")
    monkeypatch.setenv("GITHUB_RUN_ID", "46")
    capsys.readouterr()

    assert health.main([str(log_path)]) == 0

    assert not [call for call in gh_calls if call[:2] == ["issue", "close"]]
    out = capsys.readouterr().out
    assert any(line.startswith("::warning::") for line in out.splitlines())


def test_unreadable_pending_branch_ls_tree_opens_no_pr(tmp_path, fake_modules, repo_root):
    # a read failure past the fetch (the open branch's ls-tree) is the same
    # class: the held set is unknowable, so nothing opens and the next run
    # retries
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")
    legacy = deepseek_legacy()
    seed_store(repo_root, [legacy])
    pending_branch = pr.branch_name("deepseek@2026-08-25-000000")
    push_pending_branch(repo_root, pending_branch, "deepseek", [legacy, deepseek_chat_pending()])
    runner = PipelineRunner(
        open_prs=[
            {"title": "Update Deepseek price history", "body": "", "headRefName": pending_branch}
        ],
        failures={"git ls-tree": pr.PrError("ls-tree failed")},
    )

    pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert runner.pr_urls == []
    assert_default_branch_clean(repo_root, tip="seed store")


def test_pending_scan_contract_failing_row_still_holds_its_key(tmp_path, fake_modules, repo_root):
    # a hand-edited branch row that fails validate_row still holds its model:
    # the PR is open and carries it, so the run must not re-candidate it and
    # open a duplicate
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat", "deepseek-new"]
    scrape["deepseek"] = {"deepseek-new": pricing(3.0e-7, 1.2e-6), "deepseek-chat": pricing()}
    cfg = make_cfg("deepseek")
    legacy = deepseek_legacy()
    seed_store(repo_root, [legacy])
    failing = deepseek_chat_pending()
    failing["surprise"] = "hand edit"
    pending_branch = pr.branch_name("deepseek@2026-08-25-000000")
    push_pending_branch(repo_root, pending_branch, "deepseek", [legacy, failing])
    runner = PipelineRunner(
        open_prs=[
            {"title": "Update Deepseek price history", "body": "", "headRefName": pending_branch}
        ]
    )

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    provider_report = report.providers["deepseek"]
    assert provider_report.skipped_pending == ["deepseek-chat"]
    assert provider_report.tried == ["deepseek-new", "deepseek-chat"]
    assert provider_report.errors == []
    assert [model_id for model_id, _url in provider_report.prs] == ["deepseek-new"]
    assert_default_branch_clean(repo_root, tip="seed store")


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
    # their pages moved since the branch's rows: only the hold keeps the
    # refresh from planning competing rows
    scrape["deepseek"]["model-a"] = pricing(3.3e-7, 1.3e-6)
    scrape["deepseek"]["model-b"] = pricing(3.6e-7, 1.4e-6)
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
    # the open pr's model-a and model-b rows stay on its own branch
    rows = branch_rows(repo_root, batch_branch("deepseek", stamp="000001"), "deepseek")
    assert sorted(row["model_id"] for row in rows) == ["deepseek-legacy", "model-c"]
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


def test_seed_pr_leaves_open_sibling_rows_on_the_sibling(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-new"]
    scrape["deepseek"] = {"deepseek-new": pricing()}
    cfg = make_cfg("deepseek")
    sibling_row = store.build_row(
        "deepseek",
        "deepseek-old",
        pricing(),
        "2026-08-25",
        "https://example.com/pricing",
        VERSION,
    )
    sibling_branch = pr.branch_name("deepseek-old")
    git(repo_root, "switch", "-C", sibling_branch)
    store.save_shard([sibling_row], repo_root / "data" / "history", "deepseek")
    git(repo_root, "add", ".")
    git(repo_root, "commit", "-m", "sibling row")
    git(repo_root, "push", "origin", sibling_branch)
    git(repo_root, "switch", "main")
    runner = PipelineRunner(
        open_prs=[
            {
                "title": "Update deepseek-old pricing for Deepseek",
                "body": "",
                "headRefName": sibling_branch,
            }
        ]
    )

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    assert report.providers["deepseek"].prs == [("deepseek-new", runner.pr_urls[0])]
    rows = branch_all_rows(repo_root, "pricelog/seed")
    assert [(row["model_id"], row["observed_at"]) for row in rows] == [("deepseek-new", TODAY)]
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


def test_refresh_same_day_repeat_appends_no_duplicate_line(tmp_path, fake_modules, repo_root):
    # a same-day A -> B -> A flip-flop rebuilds A while B is the last row;
    # A's exact line already sits in the shard, so the append lands nothing
    # the merge can take (the 2026-10-21 nemotron phantom)
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": Pricing(0.2e-6, 0.4e-6, "chat")}
    cfg = make_cfg("deepseek")
    first = store.build_row(
        "deepseek",
        "deepseek-chat",
        Pricing(0.2e-6, 0.4e-6, "chat"),
        TODAY,
        "https://example.com/pricing",
        VERSION,
    )
    second = store.build_row(
        "deepseek",
        "deepseek-chat",
        Pricing(0.3e-6, 0.6e-6, "chat"),
        TODAY,
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [first, second])
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    provider_report = report.providers["deepseek"]
    assert provider_report.prs == []
    assert provider_report.rows == []
    assert provider_report.errors == []
    assert runner.pr_urls == []


def test_openrouter_same_day_repeat_appends_no_duplicate_line(
    tmp_path, fake_modules, or_models, repo_root
):
    # the observed site: the api serves A while B is the last landed row and
    # A's exact line is already in the shard
    detect, scrape = fake_modules
    detect["deepseek"] = []
    scrape["deepseek"] = {}
    first = openrouter.build_row(or_model("x/foo", 0.1, 0.2), TODAY, VERSION)
    second = openrouter.build_row(or_model("x/foo", 0.15, 0.3), TODAY, VERSION)
    assert first is not None and second is not None
    seed_store(repo_root, [first, second])
    or_models.append(or_model("x/foo", 0.1, 0.2))
    runner = PipelineRunner()

    report = pipeline.run(make_cfg("deepseek"), repo_root, runner, today=TODAY)

    or_report = report.providers["openrouter"]
    assert or_report.candidates == []
    assert or_report.prs == []
    assert or_report.errors == []
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


def test_openrouter_pending_branch_row_settles_drift_the_pr_text_never_names(
    tmp_path, fake_modules, repo_root, or_models
):
    # the sibling pr's title and body never name the model, so only its
    # branch's row, read into the run's rows, already records the listed price:
    # the drift check plans nothing
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": None}
    old = openrouter.OpenrouterModel(
        id="deepseek/deepseek-chat",
        name="DeepSeek Chat",
        input_mtok=0.2,
        output_mtok=1.0,
        cache_read_mtok=None,
        pricing={"prompt": "2e-7", "completion": "1e-6"},
    )
    current = openrouter.OpenrouterModel(
        id="deepseek/deepseek-chat",
        name="DeepSeek Chat",
        input_mtok=0.27,
        output_mtok=1.1,
        cache_read_mtok=None,
        pricing={"prompt": "2.7e-7", "completion": "1.1e-6"},
    )
    or_models.append(current)
    prior = openrouter.build_row(old, "2026-08-19", VERSION)
    pending = openrouter.build_row(current, "2026-08-25", VERSION)
    assert prior is not None and pending is not None
    seed_store(repo_root, [prior])
    pending_branch = pr.branch_name("sibling")
    git(repo_root, "switch", "-C", pending_branch)
    store.save_shard([prior, pending], repo_root / "data" / "history", "openrouter")
    git(repo_root, "add", ".")
    git(repo_root, "commit", "-m", "sibling drift update")
    git(repo_root, "push", "origin", pending_branch)
    git(repo_root, "switch", "main")
    cfg = make_cfg("deepseek")
    runner = PipelineRunner(
        open_prs=[
            {"title": "Update OpenRouter price history", "body": "", "headRefName": pending_branch}
        ]
    )

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert report.providers["openrouter"].prs == []
    assert runner.pr_urls == []
    assert_default_branch_clean(repo_root, tip="seed store")


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


def test_openrouter_build_failure_skips_model_and_continues(
    tmp_path, fake_modules, repo_root, or_models
):
    # an api shape drift that breaks build_row (overrides stops being a list)
    # skips the model with a report line; the rest of the run is unaffected
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": None}
    or_models.append(
        openrouter.OpenrouterModel(
            id="bad/shape",
            name="Bad Shape",
            input_mtok=None,
            output_mtok=None,
            cache_read_mtok=None,
            pricing={"prompt": "1e-7", "completion": "1e-6", "overrides": "not-a-list"},
        )
    )
    or_models.append(
        openrouter.OpenrouterModel(
            id="bad/length",
            name="Bad Length",
            input_mtok=None,
            output_mtok=None,
            cache_read_mtok=None,
            pricing={"prompt": "1e-7", "completion": "1e-6"},
            context_length="large",
        )
    )
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
    assert or_report.detected == ["bad/shape", "bad/length", "deepseek/deepseek-chat"]
    assert or_report.candidates == ["deepseek/deepseek-chat"]
    assert [model_id for model_id, _url in or_report.prs] == ["deepseek/deepseek-chat"]
    assert len(or_report.errors) == 2
    assert or_report.errors[0].startswith("ValueError: model 'bad/shape'")
    assert or_report.errors[1].startswith("TypeError: ")


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


def test_row_build_failure_line_is_health_parseable(
    tmp_path, fake_modules, repo_root, caplog, or_models
):
    # a model whose row fails to build parses as a soft (provider-alive) issue
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": None}
    or_models.append(
        openrouter.OpenrouterModel(
            id="bad/shape",
            name="Bad Shape",
            input_mtok=None,
            output_mtok=None,
            cache_read_mtok=None,
            pricing={"prompt": "1e-7", "completion": "1e-6", "overrides": "not-a-list"},
        )
    )
    cfg = make_cfg("deepseek")
    with caplog.at_level(logging.WARNING):
        pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")
    issues = health.parse_log(_logged_lines(caplog))
    assert issues["openrouter"]["soft"] and issues["openrouter"]["hard"] == []


def test_openrouter_parse_failure_skips_entry_and_continues(
    tmp_path, monkeypatch, fake_modules, repo_root
):
    # a malformed api entry (non-object pricing) skips with a report line and
    # the well-formed models' rows still land
    monkeypatch.setattr(openrouter, "fetch_models", REAL_FETCH_MODELS)
    payload = json.dumps(
        {
            "data": [
                {"id": "bad/pricing", "name": "B", "pricing": ["not-an-object"]},
                {
                    "id": "deepseek/deepseek-chat",
                    "name": "DeepSeek Chat",
                    "pricing": {"prompt": "2.7e-7", "completion": "1.1e-6"},
                    "architecture": {"output_modalities": ["text"]},
                },
            ]
        }
    )
    monkeypatch.setattr(openrouter, "fetch_text", lambda url: payload)
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": None}
    legacy = store.build_row(
        "deepseek",
        "deepseek-legacy",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [legacy])
    cfg = make_cfg("deepseek")

    report = pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")

    or_report = report.providers["openrouter"]
    assert or_report.detected == ["deepseek/deepseek-chat"]
    assert or_report.candidates == ["deepseek/deepseek-chat"]
    assert [model_id for model_id, _url in or_report.prs] == ["deepseek/deepseek-chat"]
    assert or_report.errors == ["pricing of 'bad/pricing' must be an object"]
    rows = branch_rows(repo_root, batch_branch("openrouter"), "openrouter")
    assert [row["model_id"] for row in rows] == ["deepseek/deepseek-chat"]
    assert_default_branch_clean(repo_root, tip="seed store")


def test_parse_skip_line_is_health_parseable(
    tmp_path, monkeypatch, fake_modules, repo_root, caplog
):
    # a malformed api entry parses as a soft (provider-alive) issue
    monkeypatch.setattr(openrouter, "fetch_models", REAL_FETCH_MODELS)
    payload = json.dumps(
        {
            "data": [
                {"id": "bad/pricing", "name": "B", "pricing": ["not-an-object"]},
                {
                    "id": "deepseek/deepseek-chat",
                    "name": "DeepSeek Chat",
                    "pricing": {"prompt": "2.7e-7", "completion": "1.1e-6"},
                    "architecture": {"output_modalities": ["text"]},
                },
            ]
        }
    )
    monkeypatch.setattr(openrouter, "fetch_text", lambda url: payload)
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": None}
    cfg = make_cfg("deepseek")
    with caplog.at_level(logging.WARNING):
        pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")
    issues = health.parse_log(_logged_lines(caplog))
    assert issues["openrouter"]["soft"] and issues["openrouter"]["hard"] == []


def test_openrouter_malformed_stored_entry_does_not_fake_delisting(
    tmp_path, monkeypatch, fake_modules, repo_root
):
    # the api still lists the model, so a malformed entry must not advance the
    # absence clock: present keys on listing, never on row success
    monkeypatch.setattr(openrouter, "fetch_models", REAL_FETCH_MODELS)
    payload = json.dumps(
        {
            "data": [
                {"id": "deepseek/deepseek-chat", "name": "DeepSeek Chat", "pricing": ["bad"]},
                {
                    "id": "good/model",
                    "name": "Good",
                    "pricing": {"prompt": "1e-7", "completion": "1e-6"},
                    "architecture": {"output_modalities": ["text"]},
                },
            ]
        }
    )
    monkeypatch.setattr(openrouter, "fetch_text", lambda url: payload)
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": None}
    stored = store.build_row(
        "openrouter",
        "deepseek/deepseek-chat",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://openrouter.ai/api/v1/models",
        VERSION,
    )
    seed_store(repo_root, [stored])
    seed_absence(
        repo_root,
        {"openrouter": {"deepseek/deepseek-chat": {"absent_runs": 1, "since": "2026-08-20"}}},
    )
    cfg = make_cfg("deepseek")
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    or_report = report.providers["openrouter"]
    assert or_report.detected == ["good/model"]
    assert or_report.errors == ["pricing of 'deepseek/deepseek-chat' must be an object"]
    assert [model_id for model_id, _url in or_report.prs] == ["good/model"]
    assert all("delisted" not in title for title, _body, _head in runner.created)
    # the seeded counter clears: the file leaves the branch
    assert branch_absence(repo_root, batch_branch("openrouter")) == {}
    assert_default_branch_clean(repo_root, tip="land absence state")


def test_openrouter_empty_listing_fails_the_fetch_and_holds_absence(
    tmp_path, monkeypatch, repo_root, caplog
):
    # {"data": []} names no model id: the fetch fails loudly (the hard line)
    # and the run writes nothing, so the seeded counter never moves
    monkeypatch.setattr(openrouter, "fetch_models", REAL_FETCH_MODELS)
    monkeypatch.setattr(openrouter, "fetch_text", lambda url: '{"data": []}')
    stored = store.build_row(
        "openrouter",
        "deepseek/deepseek-chat",
        Pricing(0.1e-6, 0.2e-6, "chat"),
        "2026-08-19",
        "https://openrouter.ai/api/v1/models",
        VERSION,
    )
    seed_store(repo_root, [stored])
    seeded = {"openrouter": {"deepseek/deepseek-chat": {"absent_runs": 1, "since": "2026-08-20"}}}
    seed_absence(repo_root, seeded)
    runner = PipelineRunner()

    with caplog.at_level(logging.ERROR):
        report = pipeline.run(make_cfg(), repo_root, runner, today=TODAY, now="000000")

    # a pr branch would carry the moved absence counter and the removal row, so
    # no pricelog ref is the lock on the seeded counter's bytes
    assert git(repo_root, "for-each-ref", "--format=%(refname)", "refs/heads/pricelog/") == ""
    or_report = report.providers["openrouter"]
    assert or_report.errors == [
        "ValueError: url 'https://openrouter.ai/api/v1/models?output_modalities=all':"
        " listing names no model"
    ]
    assert or_report.detected == []
    assert runner.created == []
    assert runner.pr_urls == []
    assert health.parse_log(_logged_lines(caplog))["openrouter"]["hard"] == [
        "ERROR:ai_pricelog.pipeline:openrouter fetch failed"
    ]
    assert_default_branch_clean(repo_root, tip="land absence state")


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


def test_an_expected_unscripted_scrape_records_its_error_line(
    tmp_path, fake_modules, repo_root, unscripted_calls
):
    # the fake's own assertion is the failure this test drives: the run reports
    # each unscripted id as its own error line, the scripted id still opens its
    # row, and both names derive from the fake's input, not a hardcoded where
    detect, scrape = fake_modules
    detect["deepseek"] = ["a", "b", "c"]
    scrape["deepseek"] = {"a": pricing()}
    unscripted_calls.expect("scrape", "deepseek/b")
    unscripted_calls.expect("scrape", "deepseek/c")

    report = pipeline.run(
        make_cfg("deepseek"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert report.providers["deepseek"].errors == [
        "AssertionError: unscripted scrape for deepseek/b",
        "AssertionError: unscripted scrape for deepseek/c",
    ]
    assert [model_id for model_id, _url in report.providers["deepseek"].prs] == ["a"]
    assert unscripted_calls.recorded == [("scrape", "deepseek/b"), ("scrape", "deepseek/c")]


def test_an_expected_unscripted_detect_records_its_error_line(
    tmp_path, fake_modules, repo_root, unscripted_calls
):
    # two providers have no scripted detection, so each fake assertion is its
    # provider's only error line and the recorded providers derive from the
    # config, not a hardcoded where
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-x"]
    scrape["deepseek"] = {"deepseek-x": pricing()}
    unscripted_calls.expect("detect", "zai")
    unscripted_calls.expect("detect", "moonshot")

    report = pipeline.run(
        make_cfg("deepseek", "zai", "moonshot"),
        repo_root,
        PipelineRunner(),
        today=TODAY,
        now="000000",
    )

    assert report.providers["zai"].errors == ["AssertionError: unscripted detect for zai"]
    assert report.providers["moonshot"].errors == ["AssertionError: unscripted detect for moonshot"]
    assert [model_id for model_id, _url in report.providers["deepseek"].prs] == ["deepseek-x"]
    assert unscripted_calls.recorded == [("detect", "zai"), ("detect", "moonshot")]


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


def test_pending_branch_rows_stay_off_the_new_branch(tmp_path, fake_modules, repo_root):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat", "deepseek-new"]
    # the page moved since the branch's row: only the hold keeps the refresh
    # from planning a competing row
    scrape["deepseek"] = {
        "deepseek-chat": pricing(3.3e-7, 1.3e-6),
        "deepseek-new": pricing(3.0e-7, 1.2e-6),
    }
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

    # deepseek-chat is pending behind an open pr that names it, so only the
    # genuinely new model gets a pr
    assert [model_id for model_id, _url in report.providers["deepseek"].prs] == ["deepseek-new"]
    assert report.providers["deepseek"].skipped_pending == ["deepseek-chat"]
    # the branch holds the landed rows plus its own; the sibling's pending row
    # stays on the sibling, so it lands only through its own pr
    rows = branch_rows(repo_root, batch_branch("deepseek"), "deepseek")
    assert sorted((row["model_id"], row["observed_at"]) for row in rows) == [
        ("deepseek-chat", "2026-08-19"),
        ("deepseek-legacy", "2026-08-19"),
        ("deepseek-new", TODAY),
    ]
    assert_default_branch_clean(repo_root, tip="seed store")


def test_pending_branch_snapshot_leaves_landed_removal_once(tmp_path, fake_modules, repo_root):
    # a pending branch's full-store snapshot repeats a landed removal row; the
    # new branch writes the landed copy alone
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
    assert sorted((row["model_id"], row["observed_at"]) for row in rows) == [
        ("deepseek-chat", "2026-08-19"),
        ("deepseek-gone", "2026-08-19"),
        ("deepseek-new", TODAY),
    ]
    assert_default_branch_clean(repo_root, tip="seed store")


def test_pending_branch_row_settles_drift_the_pr_text_never_names(
    tmp_path, fake_modules, repo_root
):
    # the sibling pr's title and body never name deepseek-chat, so only its
    # branch's row, read into the run's rows, already records this run's price:
    # the drift check plans nothing
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
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
    pending = store.build_row(
        "deepseek",
        "deepseek-chat",
        pricing(),
        "2026-08-25",
        "https://example.com/pricing",
        VERSION,
    )
    pending_branch = pr.branch_name("sibling")
    git(repo_root, "switch", "-C", pending_branch)
    store.save_shard([prior, pending], repo_root / "data" / "history", "deepseek")
    git(repo_root, "add", ".")
    git(repo_root, "commit", "-m", "sibling drift update")
    git(repo_root, "push", "origin", pending_branch)
    git(repo_root, "switch", "main")
    runner = PipelineRunner(
        open_prs=[
            {"title": "Update Deepseek price history", "body": "", "headRefName": pending_branch}
        ]
    )

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert report.providers["deepseek"].prs == []
    # the branch row's price matches the run's scrape, whatever the pr text says
    assert report.providers["deepseek"].skipped_pending == ["deepseek-chat"]
    assert runner.pr_urls == []
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
    pending = store.build_row(
        "deepseek",
        "deepseek-a",
        pricing(),
        "2026-08-25",
        "https://example.com/pricing",
        VERSION,
    )
    pending_branch = pr.branch_name("deepseek@2026-08-25-000000")
    push_pending_branch(repo_root, pending_branch, "deepseek", [legacy, pending])
    runner = PipelineRunner(
        open_prs=[
            {
                "title": "Update Deepseek price history (1 row)",
                "body": "",
                "headRefName": pending_branch,
            }
        ]
    )

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    list_calls = [cmd for cmd, _cwd in runner.calls if cmd[0:3] == ["gh", "pr", "list"]]
    assert len(list_calls) == 1
    assert "--limit" in list_calls[0] and "1000" in list_calls[0]
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
    assert branch_state_paths(repo_root, "main", announce.ANNOUNCE_DIR) == []
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
    assert branch_state_paths(repo_root, "main", announce.ANNOUNCE_DIR) == []
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


def test_run_stamps_announce_fetched_with_a_utc_instant(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # the announce snapshot stamps `fetched` with the run's UTC fetch instant
    # (YYYY-MM-DDTHH:MM:SSZ, one clock read per run), so two same-day changes
    # order by time instead of tieing. the date-only observed_at stays separate.
    detect, scrape = fake_modules
    detect["deepseek"] = []
    scrape["deepseek"] = {}
    cfg = make_cfg("deepseek")
    captured: dict[str, str] = {}

    def capture_fetch(cfg, snapshot, now):
        captured["now"] = now
        return announce.FetchResult((), {}, ())

    monkeypatch.setattr(pipeline.announce, "fetch_channels", capture_fetch)
    runner = PipelineRunner()

    pipeline.run(cfg, repo_root, runner, today=TODAY)

    stamp = datetime.strptime(captured["now"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert 0 <= (datetime.now(UTC) - stamp).total_seconds() < 5


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
    assert_default_branch_clean(repo_root, tip="seed store")


def test_seed_body_names_absence_only_when_its_branch_changes_a_file(
    tmp_path, fake_modules, repo_root
):
    # a seed run with committed provider-only absence counters: the provider is
    # dropped for having no stored ids, so the body must not name `## absence
    # state` and the branch must leave the committed absence file untouched
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-new"]
    scrape["deepseek"] = {"deepseek-new": pricing()}
    cfg = make_cfg("deepseek")
    absence.save_absence(
        {"deepseek": {"deepseek-chat": {"absent_runs": 1, "since": "2026-08-25"}}},
        repo_root,
    )
    git(repo_root, "add", ".")
    git(repo_root, "commit", "-m", "absence counters")
    runner = PipelineRunner()

    pipeline.run(cfg, repo_root, runner, today=TODAY)

    (title, body, _head) = runner.created[0]
    assert "## absence state" not in body
    assert branch_absence(repo_root, "pricelog/seed") == {
        "deepseek": {"deepseek-chat": {"absent_runs": 1, "since": "2026-08-25"}}
    }
    assert_default_branch_clean(repo_root, tip="absence counters")


def test_seed_body_names_absence_when_its_branch_deletes_openrouter_counter(
    tmp_path, fake_modules, repo_root, or_models
):
    # a seed run whose openrouter counter clears: the branch deletes the
    # openrouter absence file, so the body must still name `## absence state`
    detect, scrape = fake_modules
    detect["deepseek"] = []
    scrape["deepseek"] = {}
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
    seed_absence(
        repo_root,
        {"openrouter": {"deepseek/deepseek-chat": {"absent_runs": 1, "since": "2026-08-20"}}},
    )
    runner = PipelineRunner()

    pipeline.run(cfg, repo_root, runner, today=TODAY)

    (title, body, _head) = runner.created[0]
    assert "## absence state" in body
    assert branch_absence(repo_root, "pricelog/seed") == {}
    assert_default_branch_clean(repo_root, tip="land absence state")


def test_absence_section_only_on_the_pr_whose_source_counters_changed(
    tmp_path, fake_modules, repo_root
):
    # deepseek's counter moves and zai's does not: only the deepseek body may
    # point the reviewer at a state/absence diff, since the zai branch has none
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-new"]
    detect["zai"] = ["zai-chat"]
    scrape["deepseek"] = {"deepseek-new": pricing(3.0e-7, 1.2e-6)}
    scrape["zai"] = {"zai-chat": pricing()}
    cfg = make_cfg("deepseek", "zai")
    seed_store(repo_root, [deepseek_prior()])
    runner = PipelineRunner()

    pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    bodies = {head: body for _title, body, head in runner.created}
    assert set(bodies) == {batch_branch("deepseek"), batch_branch("zai")}
    assert "## absence state" in bodies[batch_branch("deepseek")]
    assert "## absence state" not in bodies[batch_branch("zai")]
    assert branch_absence(repo_root, batch_branch("zai")) == {}


def test_absence_section_names_a_cleared_counter(tmp_path, fake_modules, repo_root):
    # a counter that clears deletes the source's absence file on the branch;
    # that deletion is a state/absence diff the body must still point at
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing(3.0e-7, 1.2e-6)}
    cfg = make_cfg("deepseek")
    seed_store(repo_root, [deepseek_prior()])
    seed_absence(
        repo_root, {"deepseek": {"deepseek-chat": {"absent_runs": 1, "since": "2026-08-25"}}}
    )
    runner = PipelineRunner()

    pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    bodies = {head: body for _title, body, head in runner.created}
    assert (
        "## absence state\n\n`state/absence/<source>.json` changed on this branch; diff it"
        " against the base to see which counters this run raised or cleared (a deleted file:"
        " every counter cleared).\n"
    ) in bodies[batch_branch("deepseek")]
    assert branch_absence(repo_root, batch_branch("deepseek")) == {}


def test_detect_skips_freeze_absence_counters(tmp_path, fake_modules, repo_root):
    # a detect that skipped rows has an incomplete id set: a renamed or merged
    # display row skips as unmapped drift, and the stored ids it used to cover
    # must not read as delisted. the counters neither bump (no removal at the
    # threshold) nor clear (a present id keeps its entry), so the branch
    # carries the landed absence state unchanged
    detect, scrape = fake_modules
    detect["deepseek"] = (["deepseek-kept", "deepseek-new"], 1)
    scrape["deepseek"] = {
        "deepseek-kept": pricing(),
        "deepseek-new": pricing(3.0e-7, 1.2e-6),
    }
    cfg = make_cfg("deepseek")
    kept = store.build_row(
        "deepseek",
        "deepseek-kept",
        pricing(),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [deepseek_prior(), kept])
    seed_absence(
        repo_root,
        {
            "deepseek": {
                "deepseek-chat": {"absent_runs": 2, "since": TODAY},
                "deepseek-kept": {"absent_runs": 1, "since": TODAY},
            }
        },
    )
    runner = PipelineRunner()

    pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    branch = batch_branch("deepseek")
    rows = branch_rows(repo_root, branch, "deepseek")
    assert [row["model_id"] for row in rows] == [
        "deepseek-chat",
        "deepseek-kept",
        "deepseek-new",
    ]
    assert all(row.get("removed") is not True for row in rows)
    assert branch_absence(repo_root, branch) == {
        "deepseek": {
            "deepseek-chat": {"absent_runs": 2, "since": TODAY},
            "deepseek-kept": {"absent_runs": 1, "since": TODAY},
        }
    }
    # the counters exist but did not move: the branch has no absence diff to name
    assert "## absence state" not in runner.created[0][1]
    assert_default_branch_clean(repo_root, tip="land absence state")


def test_stale_empty_absence_file_is_deleted_on_the_source_branch(
    tmp_path, fake_modules, repo_root
):
    # a hand-edited or badly merged `{}` file holds no counter; the source's
    # next branch deletes it, as save_absence never leaves one behind
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing(3.0e-7, 1.2e-6)}
    cfg = make_cfg("deepseek")
    seed_store(repo_root, [deepseek_prior()])
    stale = repo_root / absence.ABSENCE_DIR / "deepseek.json"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("{}\n")
    git(repo_root, "add", ".")
    git(repo_root, "commit", "-m", "stale absence file")
    runner = PipelineRunner()

    pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    branch = batch_branch("deepseek")
    paths = git(repo_root, "ls-tree", "-r", "--name-only", branch, "state/absence/").splitlines()
    assert paths == []
    assert "## absence state" in runner.created[0][1]


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
    assert_default_branch_clean(repo_root, tip="merge deepseek pr")


def test_absent_on_two_landed_runs_restamps_a_legacy_schedule(tmp_path, fake_modules, repo_root):
    # a last priced row stored before the UTC-only contract names its source's
    # zone; the removal row still lands, its carried schedule stamped UTC
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-new"]
    scrape["deepseek"] = {"deepseek-new": pricing(3.0e-7, 1.2e-6)}
    cfg = make_cfg("deepseek")
    prior = deepseek_prior()
    prior["overrides"] = [
        {
            "when": {"days": ["monday"], "window": [100, 400], "timezone": "Asia/Shanghai"},
            "rates": {"input": 1.0},
        }
    ]
    seed_store(repo_root, [prior])
    runner = PipelineRunner()

    pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")
    git(repo_root, "merge", "--no-ff", batch_branch("deepseek"), "-m", "merge deepseek pr")
    runner.open_prs = []

    second = pipeline.run(cfg, repo_root, runner, today="2026-08-27", now="000000")

    assert [model_id for model_id, _url in second.providers["deepseek"].prs] == ["deepseek-chat"]
    removal_branch = batch_branch("deepseek", today="2026-08-27")
    removal = branch_rows(repo_root, removal_branch, "deepseek")[1]
    assert removal["removed"] is True
    assert removal["overrides"] == [
        {
            "when": {"days": ["monday"], "window": [100, 400], "timezone": "UTC"},
            "rates": {"input": 1.0},
        }
    ]
    assert_default_branch_clean(repo_root, tip="merge deepseek pr")


def test_same_day_duplicate_removal_line_is_not_replanned(tmp_path, fake_modules, repo_root):
    # a delist -> revival -> re-delist whose removal snapshot repeats an
    # earlier same-day removal builds a byte-identical line; the merge would
    # drop it, so the run plans no PR
    detect, scrape = fake_modules
    detect["deepseek"] = []
    scrape["deepseek"] = {}
    cfg = make_cfg("deepseek")
    price = deepseek_prior()
    removal = store.build_removal_row("deepseek", "deepseek-chat", TODAY, VERSION, last_row=price)
    revival = store.build_row(
        "deepseek",
        "deepseek-chat",
        Pricing(0.2e-6, 0.4e-6, "chat"),
        TODAY,
        "https://example.com/pricing",
        VERSION,
    )
    seed_store(repo_root, [price, removal, revival])
    seed_absence(repo_root, {"deepseek": {"deepseek-chat": {"absent_runs": 2, "since": TODAY}}})
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    deepseek_report = report.providers["deepseek"]
    assert deepseek_report.prs == []
    assert deepseek_report.errors == []
    assert runner.pr_urls == []


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


def test_removal_row_failing_validation_skips_and_reports(tmp_path, fake_modules, repo_root):
    # a last stored row the contract refuses (say a hand-edited branch row that
    # landed) makes build_removal_row inherit the bad shape: the removal skips
    # with a provider error instead of the exception killing the run, and the
    # counter stays at 2 for the next run to retry
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-new"]
    scrape["deepseek"] = {"deepseek-new": pricing(3.0e-7, 1.2e-6)}
    cfg = make_cfg("deepseek")
    prior = deepseek_prior()
    prior["rates"] = {"input": 1, "output": 2}  # ints: not the contract's floats
    seed_store(repo_root, [prior])
    seed_absence(repo_root, {"deepseek": {"deepseek-chat": {"absent_runs": 2, "since": TODAY}}})

    report = pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")

    deepseek_report = report.providers["deepseek"]
    assert [model_id for model_id, _url in deepseek_report.prs] == ["deepseek-new"]
    assert any("rates" in error for error in deepseek_report.errors)
    rows = branch_rows(repo_root, batch_branch("deepseek"), "deepseek")
    assert all(row.get("removed") is not True for row in rows)
    assert branch_absence(repo_root, batch_branch("deepseek")) == {
        "deepseek": {"deepseek-chat": {"absent_runs": 2, "since": TODAY}}
    }


def test_pending_only_rows_keep_the_absence_entry(tmp_path, fake_modules, repo_root):
    # an entry can name a model whose rows sit only on a pending branch (say a
    # hand merge that landed the state file without its shard): the
    # landed-removal cleanup reads no row for it and must keep the entry
    # instead of crashing on None
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-new", "deepseek-other"]
    scrape["deepseek"] = {
        "deepseek-new": pricing(3.0e-7, 1.2e-6),
        "deepseek-other": pricing(),
    }
    cfg = make_cfg("deepseek")
    seed_store(
        repo_root,
        [
            store.build_row(
                "deepseek",
                "deepseek-other",
                pricing(),
                "2026-08-19",
                "https://example.com/pricing",
                VERSION,
            )
        ],
    )
    seed_absence(repo_root, {"deepseek": {"deepseek-chat": {"absent_runs": 2, "since": TODAY}}})
    pending_branch = pr.branch_name("deepseek-chat")
    git(repo_root, "switch", "-C", pending_branch)
    shard_dir = repo_root / "data" / "history"
    pending_shard = store.load_shard(shard_dir, "deepseek") + [deepseek_prior()]
    store.save_shard(pending_shard, shard_dir, "deepseek")
    git(repo_root, "add", ".")
    git(repo_root, "commit", "-m", "sibling pr for the model's only row")
    git(repo_root, "push", "origin", pending_branch)
    git(repo_root, "switch", "main")
    runner = PipelineRunner(
        open_prs=[
            {
                "title": "Add deepseek-chat pricing",
                "body": "",
                "headRefName": pending_branch,
            }
        ]
    )

    report = pipeline.run(cfg, repo_root, runner, today=TODAY, now="000000")

    assert [model_id for model_id, _url in report.providers["deepseek"].prs] == ["deepseek-new"]
    assert report.providers["deepseek"].errors == []
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


def counted_scrapes(monkeypatch) -> list[tuple[str, str]]:
    """Every (source, page id) the fake scraper serves, in call order."""
    scr = sys.modules["ai_pricelog.scrapers.fake_scr"]
    served = scr.scrape
    calls: list[tuple[str, str]] = []

    def scrape(cfg, model_id):
        calls.append((cfg.key, model_id))
        return served(cfg, model_id)

    monkeypatch.setattr(scr, "scrape", scrape)
    return calls


def stored_row(model_id: str, price: Pricing | None = None, source: str = "dashscope") -> dict:
    return store.build_row(
        source,
        model_id,
        price or pricing(),
        "2026-08-19",
        "https://example.com/pricing",
        VERSION,
    )


def appended_rows(repo_root: Path, source: str) -> list[tuple[str, dict, object]]:
    return [
        (row["model_id"], row["rates"], row.get("removed"))
        for row in branch_rows(repo_root, batch_branch(source), source)
        if row["observed_at"] == TODAY
    ]


def priced_only_source(fake_modules, monkeypatch, priced: list[str]) -> list[tuple[str, str]]:
    """The dashscope shape: candidates from one page, the priced set from another."""
    detect, scrape = fake_modules
    detect["dashscope"] = ["qwen-max", "qwen-new"]
    sys.modules["ai_pricelog.detectors.fake_det"].detect_priced = lambda cfg: list(priced)
    scrape["dashscope"] = {
        "qwen-max": pricing(),
        "qwen-new": pricing(),
        "qwen-max-0501": pricing(3.0e-7, 1.2e-6),
    }
    return counted_scrapes(monkeypatch)


def test_refresh_rereads_a_stored_priced_id_the_detector_omits(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # the candidate page lists the official version only, while the pricing
    # page keeps the dated snapshot live: its moved price appends a row
    calls = priced_only_source(fake_modules, monkeypatch, ["qwen-max", "qwen-max-0501"])
    seed_store(repo_root, [stored_row("qwen-max"), stored_row("qwen-max-0501")])

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert report.providers["dashscope"].errors == []
    assert ("dashscope", "qwen-max-0501") in calls
    assert appended_rows(repo_root, "dashscope") == [
        ("qwen-max-0501", {"input": 0.3, "output": 1.2}, None),
        ("qwen-new", {"input": 0.27, "output": 1.1}, None),
    ]


def test_refresh_skips_a_stored_id_in_neither_set(tmp_path, fake_modules, repo_root, monkeypatch):
    # neither page lists qwen-old: no scrape, and absence counts it
    calls = priced_only_source(fake_modules, monkeypatch, ["qwen-max"])
    seed_store(repo_root, [stored_row("qwen-max"), stored_row("qwen-old")])

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert report.providers["dashscope"].errors == []
    assert calls == [("dashscope", "qwen-new"), ("dashscope", "qwen-max")]
    assert appended_rows(repo_root, "dashscope") == [
        ("qwen-new", {"input": 0.27, "output": 1.1}, None)
    ]
    assert branch_absence(repo_root, batch_branch("dashscope")) == {
        "dashscope": {"qwen-old": {"absent_runs": 1, "since": TODAY}}
    }


def test_refresh_reads_an_id_in_both_sets_once(tmp_path, fake_modules, repo_root, monkeypatch):
    calls = priced_only_source(fake_modules, monkeypatch, ["qwen-max", "qwen-max"])
    seed_store(repo_root, [stored_row("qwen-max")])

    pipeline.run(make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY)

    assert calls.count(("dashscope", "qwen-max")) == 1


def test_refresh_refuses_a_removed_id_only_the_priced_set_lists(
    tmp_path, fake_modules, repo_root, monkeypatch, caplog
):
    # no reading settles whether the pricing page re-listed a removed id the
    # candidate page omits: a hard failure naming the page ids, never a
    # reappearance row
    calls = priced_only_source(fake_modules, monkeypatch, ["qwen-max", "qwen-max-0501"])
    price = stored_row("qwen-max-0501")
    removal = store.build_removal_row("dashscope", "qwen-max-0501", "2026-08-20", VERSION, price)
    seed_store(repo_root, [stored_row("qwen-max"), price, removal])

    with caplog.at_level(logging.ERROR):
        report = pipeline.run(
            make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
        )

    assert ("dashscope", "qwen-max-0501") not in calls
    [error] = report.providers["dashscope"].errors
    assert error == (
        "FetchError: page ids ['qwen-max-0501'] reach stored 'qwen-max-0501', removed in the store "
        "(the fake_det detector lists [] and prices ['qwen-max-0501']): refresh cannot tell a "
        "reappearance; fix: re-verify on the provider's pages whether the model is sold again, "
        "then make exactly one page id reach 'qwen-max-0501', detected as well as priced, if it "
        "is, or none if it is not"
    )
    assert health.parse_log(_logged_lines(caplog))["dashscope"]["hard"]
    assert appended_rows(repo_root, "dashscope") == [
        ("qwen-new", {"input": 0.27, "output": 1.1}, None)
    ]


def test_refresh_refuses_a_removed_priced_id_by_its_own_detector_and_scraper(
    tmp_path, repo_root, monkeypatch
):
    # a second provider's removed spelling reached by a priced-only page id:
    # the line names that provider's page id, stored spelling and detector,
    # so a literal of the first removed fixture cannot stand in
    qwen_det = register_fake_module(monkeypatch, "detectors", "qwen_det")
    qwen_det.detect = lambda cfg: []
    qwen_det.detect_priced = lambda cfg: ["qwen-turbo-latest"]
    qwen_scr = register_fake_module(monkeypatch, "scrapers", "qwen_scr")

    def scrape(cfg, model_id):
        return {"qwen-turbo-latest": pricing(3.0e-7, 1.2e-6)}[model_id]

    qwen_scr.scrape = scrape
    qwen_scr.dedup_keys = lambda model_id: (
        ["qwen-turbo-0915"] if model_id == "qwen-turbo-latest" else []
    )
    price = stored_row("qwen-turbo-0915", source="qwen")
    removal = store.build_removal_row("qwen", "qwen-turbo-0915", "2026-08-20", VERSION, price)
    seed_store(repo_root, [price, removal])
    cfg = config.Config(
        providers=(
            config.ProviderCfg(
                key="qwen",
                provider="Qwen",
                detector="qwen_det",
                detector_url="https://example.com/qwen-models",
                scraper="qwen_scr",
                scraper_url="https://example.com/qwen-pricing",
            ),
        )
    )

    report = pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")

    [error] = report.providers["qwen"].errors
    assert error == (
        "FetchError: page ids ['qwen-turbo-latest'] reach stored 'qwen-turbo-0915', removed in the "
        "store (the qwen_det detector lists [] and prices ['qwen-turbo-latest']): refresh cannot "
        "tell a reappearance; fix: re-verify on the provider's pages whether the model is sold "
        "again, then make exactly one page id reach 'qwen-turbo-0915', detected as well as priced, "
        "if it is, or none if it is not"
    )


def test_refresh_scrapes_a_held_priced_only_id_without_planning_a_row(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # an open removal pr holds the snapshot's key: refresh reads it for the
    # verdict only, so its moved price appends no competing row and no state
    calls = priced_only_source(fake_modules, monkeypatch, ["qwen-max", "qwen-max-0501"])
    price = stored_row("qwen-max-0501")
    seed_store(repo_root, [stored_row("qwen-max"), price])
    pending_branch = pr.branch_name("dashscope@2026-08-25-000000")
    removal = store.build_removal_row("dashscope", "qwen-max-0501", "2026-08-25", VERSION, price)
    push_pending_branch(
        repo_root, pending_branch, "dashscope", [stored_row("qwen-max"), price, removal]
    )
    runner = PipelineRunner(
        open_prs=[{"title": "Remove dashscope ids", "body": "", "headRefName": pending_branch}]
    )

    report = pipeline.run(make_cfg("dashscope"), repo_root, runner, today=TODAY, now="000000")

    dashscope_report = report.providers["dashscope"]
    assert dashscope_report.errors == []
    assert dashscope_report.skipped_pending == ["qwen-max-0501"]
    assert ("dashscope", "qwen-max-0501") in calls
    assert "qwen-max-0501" in dashscope_report.tried
    # the scrape priced the held id: no priced-none evidence, and no row
    assert "qwen-max-0501" not in dashscope_report.skipped_no_pricing
    assert appended_rows(repo_root, "dashscope") == [
        ("qwen-new", {"input": 0.27, "output": 1.1}, None)
    ]
    tree = git(repo_root, "ls-tree", "-r", "--name-only", batch_branch("dashscope"))
    assert not any(path.startswith("state/absence/") for path in tree.splitlines())


def test_refresh_refuses_a_priced_only_dedup_twin_of_a_detected_id(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # a priced-only page id whose stored key a detected id also reaches would
    # read one stored price from more than one page id
    calls = priced_only_source(fake_modules, monkeypatch, ["qwen-max", "qwen-max-latest"])
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-max"] if model_id == "qwen-max-latest" else []
    )
    seed_store(repo_root, [stored_row("qwen-max")])

    report = pipeline.run(make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY)

    assert ("dashscope", "qwen-max-latest") not in calls
    [error] = report.providers["dashscope"].errors
    assert error == (
        "FetchError: page ids ['qwen-max', 'qwen-max-latest'] reach stored 'qwen-max' (the "
        "fake_det detector lists ['qwen-max'] and prices ['qwen-max', 'qwen-max-latest']): one "
        "stored price, more than one page id; fix: re-verify on the provider's pages which page id "
        "prices the model, make it the only page id reaching 'qwen-max', and confirm the next two "
        "landed runs refresh it with no absence entry and no removal"
    )


def test_refresh_refuses_a_priced_only_dedup_twin_by_its_own_detector_and_scraper(
    tmp_path, repo_root, monkeypatch
):
    # the same collision on a second provider: the page id, stored spelling
    # and detector name all come from the fixture
    qwen_det = register_fake_module(monkeypatch, "detectors", "qwen_det")
    qwen_det.detect = lambda cfg: ["qwen-turbo-0915"]
    qwen_det.detect_priced = lambda cfg: ["qwen-turbo-0915", "qwen-turbo-latest"]
    qwen_scr = register_fake_module(monkeypatch, "scrapers", "qwen_scr")
    calls: list[str] = []

    def scrape(cfg, model_id):
        calls.append(model_id)
        return {"qwen-turbo-0915": pricing(3.0e-7, 1.2e-6)}[model_id]

    qwen_scr.scrape = scrape
    qwen_scr.dedup_keys = lambda model_id: (
        ["qwen-turbo"] if model_id in ("qwen-turbo-0915", "qwen-turbo-latest") else []
    )
    seed_store(repo_root, [stored_row("qwen-turbo", source="qwen")])
    cfg = config.Config(
        providers=(
            config.ProviderCfg(
                key="qwen",
                provider="Qwen",
                detector="qwen_det",
                detector_url="https://example.com/qwen-models",
                scraper="qwen_scr",
                scraper_url="https://example.com/qwen-pricing",
            ),
        )
    )

    report = pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")

    assert calls == ["qwen-turbo-0915"]
    [error] = report.providers["qwen"].errors
    assert error == (
        "FetchError: page ids ['qwen-turbo-0915', 'qwen-turbo-latest'] reach stored 'qwen-turbo' "
        "(the qwen_det detector lists ['qwen-turbo-0915'] and prices ['qwen-turbo-0915', "
        "'qwen-turbo-latest']): one stored price, more than one page id; fix: re-verify on the "
        "provider's pages which page id prices the model, make it the only page id reaching "
        "'qwen-turbo', and confirm the next two landed runs refresh it with no absence entry and "
        "no removal"
    )


def test_refresh_refuses_a_priced_only_twin_that_is_the_stored_spelling(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # a priced-only id that is its own stored spelling still collides with the
    # detected id that dedups onto it: one stored price, two page ids, so the
    # refusal names both
    detect, scrape = fake_modules
    detect["dashscope"] = ["qwen-max-latest"]
    sys.modules["ai_pricelog.detectors.fake_det"].detect_priced = lambda cfg: [
        "qwen-max-latest",
        "qwen-max",
    ]
    scrape["dashscope"] = {"qwen-max-latest": pricing(3.0e-7, 1.2e-6)}
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-max"] if model_id == "qwen-max-latest" else []
    )
    calls = counted_scrapes(monkeypatch)
    seed_store(repo_root, [stored_row("qwen-max")])

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert calls == [("dashscope", "qwen-max-latest")]
    [error] = report.providers["dashscope"].errors
    assert error == (
        "FetchError: page ids ['qwen-max', 'qwen-max-latest'] reach stored 'qwen-max' (the "
        "fake_det detector lists ['qwen-max-latest'] and prices ['qwen-max', 'qwen-max-latest']): "
        "one stored price, more than one page id; fix: re-verify on the provider's pages which "
        "page id prices the model, make it the only page id reaching 'qwen-max', and confirm the "
        "next two landed runs refresh it with no absence entry and no removal"
    )


def test_refresh_refuses_a_priced_only_twin_whose_detected_collider_is_unpriced(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # the detected id is absent from the pricing page and its scrape reads no
    # price, so the priced-only id is the stored key's only priced spelling:
    # one stored price, more than one page id
    detect, scrape = fake_modules
    detect["dashscope"] = ["qwen-max-latest"]
    sys.modules["ai_pricelog.detectors.fake_det"].detect_priced = lambda cfg: ["qwen-max"]
    scrape["dashscope"] = {"qwen-max-latest": None, "qwen-max": pricing(3.0e-7, 1.2e-6)}
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-max"] if model_id == "qwen-max-latest" else []
    )
    calls = counted_scrapes(monkeypatch)
    seed_store(repo_root, [stored_row("qwen-max")])

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert calls == [("dashscope", "qwen-max-latest")]
    assert report.providers["dashscope"].skipped_no_pricing == ["qwen-max"]
    assert report.providers["dashscope"].prs == []
    [error] = report.providers["dashscope"].errors
    assert error == (
        "FetchError: page ids ['qwen-max', 'qwen-max-latest'] reach stored 'qwen-max' (the "
        "fake_det detector lists ['qwen-max-latest'] and prices ['qwen-max']): one stored price, "
        "more than one page id; fix: re-verify on the provider's pages which page id prices the "
        "model, make it the only page id reaching 'qwen-max', and confirm the next two landed runs "
        "refresh it with no absence entry and no removal"
    )


def test_refresh_refuses_a_priced_only_twin_when_one_detected_collider_is_unpriced(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # one of two detected colliders is absent from the pricing page: the other
    # one prices the key, and the priced-only id reaches the same stored key
    detect, scrape = fake_modules
    detect["dashscope"] = ["qwen-max-0501", "qwen-max-0815"]
    sys.modules["ai_pricelog.detectors.fake_det"].detect_priced = lambda cfg: [
        "qwen-max-0501",
        "qwen-twin",
    ]
    scrape["dashscope"] = {
        "qwen-max-0501": pricing(3.0e-7, 1.2e-6),
        "qwen-max-0815": None,
        "qwen-twin": pricing(),
    }
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-max"] if model_id in ("qwen-max-0501", "qwen-max-0815", "qwen-twin") else []
    )
    calls = counted_scrapes(monkeypatch)
    seed_store(repo_root, [stored_row("qwen-max")])

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert calls == [("dashscope", "qwen-max-0501")]
    [error] = report.providers["dashscope"].errors
    assert error == (
        "FetchError: page ids ['qwen-max-0501', 'qwen-max-0815', 'qwen-twin'] reach stored "
        "'qwen-max' (the fake_det detector lists ['qwen-max-0501', 'qwen-max-0815'] and prices "
        "['qwen-max-0501', 'qwen-twin']): one stored price, more than one page id; fix: re-verify "
        "on the provider's pages which page id prices the model, make it the only page id reaching "
        "'qwen-max', and confirm the next two landed runs refresh it with no absence entry and no "
        "removal"
    )
    assert appended_rows(repo_root, "dashscope") == [
        ("qwen-max", {"input": 0.3, "output": 1.2}, None)
    ]


def test_refresh_refuses_a_priced_only_twin_when_no_detected_collider_is_priced(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # no detected collider is on the pricing page, so the priced-only id is the
    # stored key's only priced spelling, and two page ids still reach the key
    detect, scrape = fake_modules
    detect["dashscope"] = ["qwen-max-latest"]
    sys.modules["ai_pricelog.detectors.fake_det"].detect_priced = lambda cfg: ["qwen-max-new"]
    scrape["dashscope"] = {
        "qwen-max-latest": pricing(),
        "qwen-max-new": pricing(3.0e-7, 1.2e-6),
    }
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-max"] if model_id in ("qwen-max-latest", "qwen-max-new") else []
    )
    calls = counted_scrapes(monkeypatch)
    seed_store(repo_root, [stored_row("qwen-max")])

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert calls == [("dashscope", "qwen-max-latest")]
    [error] = report.providers["dashscope"].errors
    assert error == (
        "FetchError: page ids ['qwen-max-latest', 'qwen-max-new'] reach stored 'qwen-max' (the "
        "fake_det detector lists ['qwen-max-latest'] and prices ['qwen-max-new']): one stored "
        "price, more than one page id; fix: re-verify on the provider's pages which page id prices "
        "the model, make it the only page id reaching 'qwen-max', and confirm the next two landed "
        "runs refresh it with no absence entry and no removal"
    )
    assert report.providers["dashscope"].prs == []


def test_refresh_refuses_a_priced_only_twin_beside_two_unpriced_detected_colliders(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # two detected colliders read no price and one priced-only id reaches the
    # key: neither detected id prices it, and the priced-only id is its only
    # priced spelling
    detect, scrape = fake_modules
    detect["dashscope"] = ["qwen-max-0501", "qwen-max-0815"]
    sys.modules["ai_pricelog.detectors.fake_det"].detect_priced = lambda cfg: ["qwen-twin"]
    scrape["dashscope"] = {
        "qwen-max-0501": None,
        "qwen-max-0815": None,
        "qwen-twin": pricing(3.0e-7, 1.2e-6),
    }
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-max"] if model_id in ("qwen-max-0501", "qwen-max-0815", "qwen-twin") else []
    )
    calls = counted_scrapes(monkeypatch)
    seed_store(repo_root, [stored_row("qwen-max")])

    report = pipeline.run(make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY)

    assert calls == [("dashscope", "qwen-max-0501"), ("dashscope", "qwen-max-0815")]
    [error] = report.providers["dashscope"].errors
    assert error == (
        "FetchError: page ids ['qwen-max-0501', 'qwen-max-0815', 'qwen-twin'] reach stored "
        "'qwen-max' (the fake_det detector lists ['qwen-max-0501', 'qwen-max-0815'] and prices "
        "['qwen-twin']): one stored price, more than one page id; fix: re-verify on the provider's "
        "pages which page id prices the model, make it the only page id reaching 'qwen-max', and "
        "confirm the next two landed runs refresh it with no absence entry and no removal"
    )
    assert report.providers["dashscope"].prs == []


def test_refresh_refuses_a_priced_only_twin_of_a_detected_stored_spelling(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # the stored spelling is itself a detected collider and another detected
    # collider prices the key: the priced-only id reaches the same stored key
    detect, scrape = fake_modules
    detect["dashscope"] = ["qwen-max", "qwen-max-latest"]
    sys.modules["ai_pricelog.detectors.fake_det"].detect_priced = lambda cfg: [
        "qwen-max-latest",
        "qwen-twin",
    ]
    scrape["dashscope"] = {"qwen-max": pricing(), "qwen-max-latest": pricing()}
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-max"] if model_id in ("qwen-max-latest", "qwen-twin") else []
    )
    calls = counted_scrapes(monkeypatch)
    seed_store(repo_root, [stored_row("qwen-max")])

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert calls == [("dashscope", "qwen-max"), ("dashscope", "qwen-max-latest")]
    [error] = report.providers["dashscope"].errors
    assert error == (
        "FetchError: page ids ['qwen-max', 'qwen-max-latest', 'qwen-twin'] reach stored 'qwen-max' "
        "(the fake_det detector lists ['qwen-max', 'qwen-max-latest'] and prices "
        "['qwen-max-latest', 'qwen-twin']): one stored price, more than one page id; fix: "
        "re-verify on the provider's pages which page id prices the model, make it the only page "
        "id reaching 'qwen-max', and confirm the next two landed runs refresh it with no absence "
        "entry and no removal"
    )
    assert report.providers["dashscope"].prs == []


def test_refresh_refuses_a_priced_only_twin_of_a_stored_spelling_detected_alone(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # the stored spelling is a detected collider absent from detect_priced, and
    # the priced-only id is listed there: the key's one stored price would be
    # read by both page ids
    detect, scrape = fake_modules
    detect["dashscope"] = ["qwen-max"]
    sys.modules["ai_pricelog.detectors.fake_det"].detect_priced = lambda cfg: ["qwen-max-new"]
    scrape["dashscope"] = {"qwen-max": pricing()}
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-max"] if model_id == "qwen-max-new" else []
    )
    calls = counted_scrapes(monkeypatch)
    seed_store(repo_root, [stored_row("qwen-max")])

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert calls == [("dashscope", "qwen-max")]
    [error] = report.providers["dashscope"].errors
    assert error == (
        "FetchError: page ids ['qwen-max', 'qwen-max-new'] reach stored 'qwen-max' (the fake_det "
        "detector lists ['qwen-max'] and prices ['qwen-max-new']): one stored price, more than one "
        "page id; fix: re-verify on the provider's pages which page id prices the model, make it "
        "the only page id reaching 'qwen-max', and confirm the next two landed runs refresh it "
        "with no absence entry and no removal"
    )
    assert report.providers["dashscope"].prs == []


def test_refresh_refuses_a_priced_only_twin_of_a_detected_stored_spelling_beside_a_collider(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # the stored spelling and a second detected collider both read no price,
    # and the priced-only id is listed in detect_priced: one stored price,
    # more than one page id
    detect, scrape = fake_modules
    detect["dashscope"] = ["qwen-max", "qwen-max-latest"]
    sys.modules["ai_pricelog.detectors.fake_det"].detect_priced = lambda cfg: ["qwen-max-new"]
    scrape["dashscope"] = {
        "qwen-max": None,
        "qwen-max-latest": None,
        "qwen-max-new": pricing(3.0e-7, 1.2e-6),
    }
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-max"] if model_id in ("qwen-max-latest", "qwen-max-new") else []
    )
    calls = counted_scrapes(monkeypatch)
    seed_store(repo_root, [stored_row("qwen-max")])

    report = pipeline.run(make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY)

    assert calls == [("dashscope", "qwen-max"), ("dashscope", "qwen-max-latest")]
    [error] = report.providers["dashscope"].errors
    assert error == (
        "FetchError: page ids ['qwen-max', 'qwen-max-latest', 'qwen-max-new'] reach stored "
        "'qwen-max' (the fake_det detector lists ['qwen-max', 'qwen-max-latest'] and prices "
        "['qwen-max-new']): one stored price, more than one page id; fix: re-verify on the "
        "provider's pages which page id prices the model, make it the only page id reaching "
        "'qwen-max', and confirm the next two landed runs refresh it with no absence entry and no "
        "removal"
    )
    assert report.providers["dashscope"].prs == []


def test_refresh_refuses_a_priced_only_twin_by_its_own_detector(repo_root, monkeypatch):
    # the same collision on a second provider: the page ids, stored spelling
    # and detector name all come from the fixture
    qwen_det = register_fake_module(monkeypatch, "detectors", "qwen_det")
    qwen_det.detect = lambda cfg: ["qwen-turbo"]
    qwen_det.detect_priced = lambda cfg: ["qwen-turbo-latest"]
    qwen_scr = register_fake_module(monkeypatch, "scrapers", "qwen_scr")
    qwen_scr.scrape = lambda cfg, model_id: {"qwen-turbo": pricing()}[model_id]
    qwen_scr.dedup_keys = lambda model_id: ["qwen-turbo"] if model_id == "qwen-turbo-latest" else []
    seed_store(repo_root, [stored_row("qwen-turbo", source="qwen")])
    cfg = config.Config(
        providers=(
            config.ProviderCfg(
                key="qwen",
                provider="Qwen",
                detector="qwen_det",
                detector_url="https://example.com/qwen-models",
                scraper="qwen_scr",
                scraper_url="https://example.com/qwen-pricing",
            ),
        )
    )

    report = pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")

    [error] = report.providers["qwen"].errors
    assert error == (
        "FetchError: page ids ['qwen-turbo', 'qwen-turbo-latest'] reach stored 'qwen-turbo' (the "
        "qwen_det detector lists ['qwen-turbo'] and prices ['qwen-turbo-latest']): one stored "
        "price, more than one page id; fix: re-verify on the provider's pages which page id prices "
        "the model, make it the only page id reaching 'qwen-turbo', and confirm the next two "
        "landed runs refresh it with no absence entry and no removal"
    )
    assert report.providers["qwen"].prs == []


def test_refresh_refuses_two_priced_only_twins_of_one_stored_key(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # two ids the candidate page omits both dedup to one stored key: one
    # stored price would be read by more than one page id, so the key gets one
    # line naming both ids; their scrapes are scripted, so a run that skipped
    # the refusal lands their rows instead of tripping the unscripted-call
    # fixture
    calls = priced_only_source(
        fake_modules, monkeypatch, ["qwen-max", "qwen-twin-a", "qwen-twin-b"]
    )
    _, scrape = fake_modules
    scrape["dashscope"]["qwen-twin-a"] = pricing(3.0e-7, 1.2e-6)
    scrape["dashscope"]["qwen-twin-b"] = pricing(3.3e-7, 1.3e-6)
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-max-0501"] if model_id.startswith("qwen-twin-") else []
    )
    seed_store(repo_root, [stored_row("qwen-max"), stored_row("qwen-max-0501")])

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert ("dashscope", "qwen-twin-a") not in calls
    assert ("dashscope", "qwen-twin-b") not in calls
    assert report.providers["dashscope"].errors == [
        "FetchError: page ids ['qwen-twin-a', 'qwen-twin-b'] reach stored 'qwen-max-0501' (the "
        "fake_det detector lists [] and prices ['qwen-twin-a', 'qwen-twin-b']): one stored price, "
        "more than one page id; fix: re-verify on the provider's pages which page id prices the "
        "model, make it the only page id reaching 'qwen-max-0501', and confirm the next two landed "
        "runs refresh it with no absence entry and no removal"
    ]
    # the refused key is one attempt, however many priced-only ids reach it
    assert report.providers["dashscope"].tried.count("qwen-max-0501") == 1
    assert appended_rows(repo_root, "dashscope") == [
        ("qwen-new", {"input": 0.27, "output": 1.1}, None)
    ]


def test_refresh_refuses_two_priced_only_twins_of_a_second_stored_key(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # the same collision on another stored key: the refusal's id list and
    # stored spelling follow the fixture
    calls = priced_only_source(
        fake_modules, monkeypatch, ["qwen-max", "qwen-plus-twin-a", "qwen-plus-twin-b"]
    )
    _, scrape = fake_modules
    scrape["dashscope"]["qwen-plus-twin-a"] = pricing(3.0e-7, 1.2e-6)
    scrape["dashscope"]["qwen-plus-twin-b"] = pricing(3.3e-7, 1.3e-6)
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-plus"] if model_id.startswith("qwen-plus-twin-") else []
    )
    seed_store(repo_root, [stored_row("qwen-max"), stored_row("qwen-plus")])

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert ("dashscope", "qwen-plus-twin-a") not in calls
    assert ("dashscope", "qwen-plus-twin-b") not in calls
    assert report.providers["dashscope"].errors == [
        "FetchError: page ids ['qwen-plus-twin-a', 'qwen-plus-twin-b'] reach stored 'qwen-plus' "
        "(the fake_det detector lists [] and prices ['qwen-plus-twin-a', 'qwen-plus-twin-b']): one "
        "stored price, more than one page id; fix: re-verify on the provider's pages which page id "
        "prices the model, make it the only page id reaching 'qwen-plus', and confirm the next two "
        "landed runs refresh it with no absence entry and no removal"
    ]


def test_refresh_refuses_two_priced_only_twins_by_their_own_detector_and_scraper(
    tmp_path, repo_root, monkeypatch
):
    # the twin refusal on a second provider: the page ids, stored spelling
    # and detector name all come from the fixture
    qwen_det = register_fake_module(monkeypatch, "detectors", "qwen_det")
    qwen_det.detect = lambda cfg: []
    qwen_det.detect_priced = lambda cfg: ["qwen-turbo-latest", "qwen-turbo-old"]
    qwen_scr = register_fake_module(monkeypatch, "scrapers", "qwen_scr")
    calls: list[str] = []
    qwen_scr.scrape = lambda cfg, model_id: calls.append(model_id)
    qwen_scr.dedup_keys = lambda model_id: (
        ["qwen-turbo"] if model_id.startswith("qwen-turbo-") else []
    )
    seed_store(repo_root, [stored_row("qwen-turbo", source="qwen")])
    cfg = config.Config(
        providers=(
            config.ProviderCfg(
                key="qwen",
                provider="Qwen",
                detector="qwen_det",
                detector_url="https://example.com/qwen-models",
                scraper="qwen_scr",
                scraper_url="https://example.com/qwen-pricing",
            ),
        )
    )

    report = pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")

    assert calls == []
    assert report.providers["qwen"].errors == [
        "FetchError: page ids ['qwen-turbo-latest', 'qwen-turbo-old'] reach stored 'qwen-turbo' "
        "(the qwen_det detector lists [] and prices ['qwen-turbo-latest', 'qwen-turbo-old']): one "
        "stored price, more than one page id; fix: re-verify on the provider's pages which page id "
        "prices the model, make it the only page id reaching 'qwen-turbo', and confirm the next "
        "two landed runs refresh it with no absence entry and no removal"
    ]


def test_refresh_refuses_two_priced_only_ids_one_of_them_the_stored_spelling(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # one priced-only id is the stored spelling and the other dedups to it:
    # both page ids reach one stored key, so its one line names both
    detect, scrape = fake_modules
    detect["dashscope"] = []
    sys.modules["ai_pricelog.detectors.fake_det"].detect_priced = lambda cfg: [
        "qwen-max",
        "qwen-max-latest",
    ]
    scrape["dashscope"] = {"qwen-max": pricing(), "qwen-max-latest": pricing(3.0e-7, 1.2e-6)}
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-max"] if model_id == "qwen-max-latest" else []
    )
    calls = counted_scrapes(monkeypatch)
    seed_store(repo_root, [stored_row("qwen-max")])

    report = pipeline.run(make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY)

    assert calls == []
    assert report.providers["dashscope"].errors == [
        "FetchError: page ids ['qwen-max', 'qwen-max-latest'] reach stored 'qwen-max' (the "
        "fake_det detector lists [] and prices ['qwen-max', 'qwen-max-latest']): one stored price, "
        "more than one page id; fix: re-verify on the provider's pages which page id prices the "
        "model, make it the only page id reaching 'qwen-max', and confirm the next two landed runs "
        "refresh it with no absence entry and no removal"
    ]


def test_refresh_refuses_three_priced_only_ids_of_one_stored_key(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # three priced-only ids reach one stored key: one stored price would be
    # read by more than one page id, so the key gets one line naming all three
    calls = one_key_source(
        fake_modules,
        monkeypatch,
        "qwen-tw",
        [],
        ["qwen-tw-c", "qwen-tw-a", "qwen-tw-b"],
    )
    seed_store(repo_root, [stored_row("qwen-tw")])

    report = pipeline.run(make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY)

    assert calls == []
    assert report.providers["dashscope"].errors == [
        "FetchError: page ids ['qwen-tw-a', 'qwen-tw-b', 'qwen-tw-c'] reach stored 'qwen-tw' (the "
        "fake_det detector lists [] and prices ['qwen-tw-a', 'qwen-tw-b', 'qwen-tw-c']): one "
        "stored price, more than one page id; fix: re-verify on the provider's pages which page id "
        "prices the model, make it the only page id reaching 'qwen-tw', and confirm the next two "
        "landed runs refresh it with no absence entry and no removal"
    ]
    assert report.providers["dashscope"].prs == []


def test_refresh_refuses_a_priced_only_twin_behind_a_planned_detected_row(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # the detected id's refresh plans a row under the stored spelling this
    # run; the priced-only twin of that key is still refused, not skipped as
    # a fresh row
    detect, scrape = fake_modules
    detect["dashscope"] = ["qwen-max-0501"]
    sys.modules["ai_pricelog.detectors.fake_det"].detect_priced = lambda cfg: [
        "qwen-max-0501",
        "qwen-twin",
    ]
    scrape["dashscope"] = {"qwen-max-0501": pricing(3.0e-7, 1.2e-6)}
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-max"] if model_id in ("qwen-max-0501", "qwen-twin") else []
    )
    calls = counted_scrapes(monkeypatch)
    seed_store(repo_root, [stored_row("qwen-max")])

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert ("dashscope", "qwen-twin") not in calls
    [error] = report.providers["dashscope"].errors
    assert error == (
        "FetchError: page ids ['qwen-max-0501', 'qwen-twin'] reach stored 'qwen-max' (the fake_det "
        "detector lists ['qwen-max-0501'] and prices ['qwen-max-0501', 'qwen-twin']): one stored "
        "price, more than one page id; fix: re-verify on the provider's pages which page id prices "
        "the model, make it the only page id reaching 'qwen-max', and confirm the next two landed "
        "runs refresh it with no absence entry and no removal"
    )
    assert appended_rows(repo_root, "dashscope") == [
        ("qwen-max", {"input": 0.3, "output": 1.2}, None)
    ]


def test_refresh_refuses_two_priced_only_twins_of_a_detected_key(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # one stored key reached by a detected id and two priced-only ids: one
    # line names all three, and neither twin reads a row
    detect, scrape = fake_modules
    detect["dashscope"] = ["qwen-max-0501"]
    sys.modules["ai_pricelog.detectors.fake_det"].detect_priced = lambda cfg: [
        "qwen-max-0501",
        "qwen-twin-a",
        "qwen-twin-b",
    ]
    scrape["dashscope"] = {"qwen-max-0501": pricing()}
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-max"] if model_id in ("qwen-max-0501", "qwen-twin-a", "qwen-twin-b") else []
    )
    calls = counted_scrapes(monkeypatch)
    seed_store(repo_root, [stored_row("qwen-max")])

    report = pipeline.run(make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY)

    assert calls == [("dashscope", "qwen-max-0501")]
    assert report.providers["dashscope"].errors == [
        "FetchError: page ids ['qwen-max-0501', 'qwen-twin-a', 'qwen-twin-b'] reach stored "
        "'qwen-max' (the fake_det detector lists ['qwen-max-0501'] and prices ['qwen-max-0501', "
        "'qwen-twin-a', 'qwen-twin-b']): one stored price, more than one page id; fix: re-verify "
        "on the provider's pages which page id prices the model, make it the only page id reaching "
        "'qwen-max', and confirm the next two landed runs refresh it with no absence entry and no "
        "removal"
    ]
    assert report.providers["dashscope"].prs == []


def test_refresh_refuses_a_priced_only_twin_naming_every_detected_collider(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # two detected ids reach one stored key beside a priced-only twin: the
    # detector lists them in page order, the refusal names every detected id
    # that also reaches the key, and the line sorts them
    detect, scrape = fake_modules
    detect["dashscope"] = ["qwen-plus-0815", "qwen-plus-0501"]
    sys.modules["ai_pricelog.detectors.fake_det"].detect_priced = lambda cfg: [
        "qwen-plus-0501",
        "qwen-plus-0815",
        "qwen-plus-twin",
    ]
    scrape["dashscope"] = {
        "qwen-plus-0501": pricing(),
        "qwen-plus-0815": pricing(),
        "qwen-plus-twin": pricing(3.0e-7, 1.2e-6),
    }
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-plus"] if model_id.startswith("qwen-plus-") else []
    )
    calls = counted_scrapes(monkeypatch)
    seed_store(repo_root, [stored_row("qwen-plus")])

    report = pipeline.run(make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY)

    assert calls == [("dashscope", "qwen-plus-0815"), ("dashscope", "qwen-plus-0501")]
    [error] = report.providers["dashscope"].errors
    assert error == (
        "FetchError: page ids ['qwen-plus-0501', 'qwen-plus-0815', 'qwen-plus-twin'] reach stored "
        "'qwen-plus' (the fake_det detector lists ['qwen-plus-0501', 'qwen-plus-0815'] and prices "
        "['qwen-plus-0501', 'qwen-plus-0815', 'qwen-plus-twin']): one stored price, more than one "
        "page id; fix: re-verify on the provider's pages which page id prices the model, make it "
        "the only page id reaching 'qwen-plus', and confirm the next two landed runs refresh it "
        "with no absence entry and no removal"
    )
    assert report.providers["dashscope"].prs == []


def test_refresh_refuses_a_priced_only_twin_of_a_planned_reappearance(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # the detected id's refresh plans the removed key's revival row this run:
    # the detected id confirms the reappearance, so the priced-only twin of
    # that key is refused by name with the detected reading, before the
    # planned-row skip can hide it
    detect, scrape = fake_modules
    detect["dashscope"] = ["qwen-max-0501"]
    sys.modules["ai_pricelog.detectors.fake_det"].detect_priced = lambda cfg: [
        "qwen-max-0501",
        "qwen-twin",
    ]
    scrape["dashscope"] = {"qwen-max-0501": pricing(3.0e-7, 1.2e-6)}
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-max"] if model_id in ("qwen-max-0501", "qwen-twin") else []
    )
    calls = counted_scrapes(monkeypatch)
    price = stored_row("qwen-max")
    removal = store.build_removal_row("dashscope", "qwen-max", "2026-08-20", VERSION, price)
    seed_store(repo_root, [price, removal])

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert ("dashscope", "qwen-twin") not in calls
    [error] = report.providers["dashscope"].errors
    assert error == (
        "FetchError: page ids ['qwen-max-0501', 'qwen-twin'] reach stored 'qwen-max' (the fake_det "
        "detector lists ['qwen-max-0501'] and prices ['qwen-max-0501', 'qwen-twin']): one stored "
        "price, more than one page id; fix: re-verify on the provider's pages which page id prices "
        "the model, make it the only page id reaching 'qwen-max', detected as well as priced since "
        "'qwen-max' is removed in the store, and confirm the next two landed runs refresh it with "
        "no absence entry and no removal"
    )
    assert appended_rows(repo_root, "dashscope") == [
        ("qwen-max", {"input": 0.3, "output": 1.2}, None)
    ]


def one_key_source(
    fake_modules, monkeypatch, stored: str, detected: list[str], priced: list[str]
) -> list[tuple[str, str]]:
    """One stored key every page id but the stored spelling dedups onto.

    A detected id off the pricing page reads no price; every other id prices,
    so a run that skipped a refusal would read a row instead of failing quietly.
    """
    detect, scrape = fake_modules
    detect["dashscope"] = list(detected)
    sys.modules["ai_pricelog.detectors.fake_det"].detect_priced = lambda cfg: list(priced)
    scrape["dashscope"] = {
        page_id: None if page_id not in priced else pricing(3.0e-7, 1.2e-6)
        for page_id in [*detected, *priced]
    }
    colliders = {*detected, *priced} - {stored}
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        [stored] if model_id in colliders else []
    )
    return counted_scrapes(monkeypatch)


def test_refresh_refuses_two_priced_only_ids_of_an_unpriced_detected_key(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # the detected id reads no price and two priced-only ids reach the key:
    # one stored price cannot follow three page ids
    calls = one_key_source(
        fake_modules,
        monkeypatch,
        "qwen-max",
        ["qwen-max-latest"],
        ["qwen-twin", "qwen-max-0501"],
    )
    seed_store(repo_root, [stored_row("qwen-max")])

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert calls == [("dashscope", "qwen-max-latest")]
    assert report.providers["dashscope"].errors == [
        "FetchError: page ids ['qwen-max-0501', 'qwen-max-latest', 'qwen-twin'] reach stored "
        "'qwen-max' (the fake_det detector lists ['qwen-max-latest'] and prices ['qwen-max-0501', "
        "'qwen-twin']): one stored price, more than one page id; fix: re-verify on the provider's "
        "pages which page id prices the model, make it the only page id reaching 'qwen-max', and "
        "confirm the next two landed runs refresh it with no absence entry and no removal"
    ]
    assert report.providers["dashscope"].prs == []


def test_refresh_refuses_a_priced_only_twin_beside_the_stored_spelling(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # the stored spelling is priced-only beside a twin that sorts before it:
    # both page ids reach the key, and the line names them in sorted order
    calls = one_key_source(
        fake_modules,
        monkeypatch,
        "qwen-max",
        ["qwen-max-latest"],
        ["qwen-early", "qwen-max"],
    )
    seed_store(repo_root, [stored_row("qwen-max")])

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert calls == [("dashscope", "qwen-max-latest")]
    assert report.providers["dashscope"].errors == [
        "FetchError: page ids ['qwen-early', 'qwen-max', 'qwen-max-latest'] reach stored "
        "'qwen-max' (the fake_det detector lists ['qwen-max-latest'] and prices ['qwen-early', "
        "'qwen-max']): one stored price, more than one page id; fix: re-verify on the provider's "
        "pages which page id prices the model, make it the only page id reaching 'qwen-max', and "
        "confirm the next two landed runs refresh it with no absence entry and no removal"
    ]


def test_refresh_refuses_two_priced_only_ids_of_a_detected_stored_spelling(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # the stored spelling is the only detected collider and reads no price:
    # two priced-only ids reach the key beside it
    calls = one_key_source(
        fake_modules,
        monkeypatch,
        "qwen-max",
        ["qwen-max"],
        ["qwen-twin", "qwen-max-new"],
    )
    seed_store(repo_root, [stored_row("qwen-max")])

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert calls == [("dashscope", "qwen-max")]
    assert report.providers["dashscope"].errors == [
        "FetchError: page ids ['qwen-max', 'qwen-max-new', 'qwen-twin'] reach stored 'qwen-max' "
        "(the fake_det detector lists ['qwen-max'] and prices ['qwen-max-new', 'qwen-twin']): one "
        "stored price, more than one page id; fix: re-verify on the provider's pages which page id "
        "prices the model, make it the only page id reaching 'qwen-max', and confirm the next two "
        "landed runs refresh it with no absence entry and no removal"
    ]


def test_refresh_refuses_a_priced_only_id_of_a_removed_key_an_unpriced_detected_id_reaches(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # a removed key an unpriced detected id reaches: the detected id reaches
    # the stored key, so the line names the collision
    calls = one_key_source(fake_modules, monkeypatch, "qwen-max", ["qwen-max-0501"], ["qwen-twin"])
    price = stored_row("qwen-max")
    removal = store.build_removal_row("dashscope", "qwen-max", "2026-08-20", VERSION, price)
    seed_store(repo_root, [price, removal])

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert calls == [("dashscope", "qwen-max-0501")]
    assert report.providers["dashscope"].errors == [
        "FetchError: page ids ['qwen-max-0501', 'qwen-twin'] reach stored 'qwen-max' (the fake_det "
        "detector lists ['qwen-max-0501'] and prices ['qwen-twin']): one stored price, more than "
        "one page id; fix: re-verify on the provider's pages which page id prices the model, make "
        "it the only page id reaching 'qwen-max', detected as well as priced since 'qwen-max' is "
        "removed in the store, and confirm the next two landed runs refresh it with no absence "
        "entry and no removal"
    ]
    assert report.providers["dashscope"].prs == []


def test_refresh_refuses_a_priced_only_id_of_a_removed_key_whose_stored_spelling_is_detected(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # a removed key the detector lists under its stored spelling: the stored
    # spelling is a detected collider, so the line names the collision
    calls = one_key_source(fake_modules, monkeypatch, "qwen-max", ["qwen-max"], ["qwen-twin"])
    price = stored_row("qwen-max")
    removal = store.build_removal_row("dashscope", "qwen-max", "2026-08-20", VERSION, price)
    seed_store(repo_root, [price, removal])

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert calls == [("dashscope", "qwen-max")]
    assert report.providers["dashscope"].errors == [
        "FetchError: page ids ['qwen-max', 'qwen-twin'] reach stored 'qwen-max' (the fake_det "
        "detector lists ['qwen-max'] and prices ['qwen-twin']): one stored price, more than one "
        "page id; fix: re-verify on the provider's pages which page id prices the model, make it "
        "the only page id reaching 'qwen-max', detected as well as priced since 'qwen-max' is "
        "removed in the store, and confirm the next two landed runs refresh it with no absence "
        "entry and no removal"
    ]
    assert report.providers["dashscope"].prs == []


def test_refresh_refuses_a_priced_only_twin_of_a_planned_reappearance_on_a_second_provider(
    tmp_path, repo_root, monkeypatch
):
    # the live form on a removed key, on a second provider: the page ids, the
    # stored spelling and the detector name all come from the fixture, so no
    # literal of the first removed fixture stands in
    qwen_det = register_fake_module(monkeypatch, "detectors", "qwen_det")
    qwen_det.detect = lambda cfg: ["qwen-turbo-latest"]
    qwen_det.detect_priced = lambda cfg: ["qwen-turbo-latest", "qwen-turbo-old"]
    qwen_scr = register_fake_module(monkeypatch, "scrapers", "qwen_scr")
    calls: list[str] = []

    def scrape(cfg, model_id):
        calls.append(model_id)
        return {"qwen-turbo-latest": pricing(3.0e-7, 1.2e-6)}[model_id]

    qwen_scr.scrape = scrape
    qwen_scr.dedup_keys = lambda model_id: (
        ["qwen-turbo-0915"] if model_id in ("qwen-turbo-latest", "qwen-turbo-old") else []
    )
    price = stored_row("qwen-turbo-0915", source="qwen")
    removal = store.build_removal_row("qwen", "qwen-turbo-0915", "2026-08-20", VERSION, price)
    seed_store(repo_root, [price, removal])
    cfg = config.Config(
        providers=(
            config.ProviderCfg(
                key="qwen",
                provider="Qwen",
                detector="qwen_det",
                detector_url="https://example.com/qwen-models",
                scraper="qwen_scr",
                scraper_url="https://example.com/qwen-pricing",
            ),
        )
    )

    report = pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")

    assert calls == ["qwen-turbo-latest"]
    [error] = report.providers["qwen"].errors
    assert error == (
        "FetchError: page ids ['qwen-turbo-latest', 'qwen-turbo-old'] reach stored "
        "'qwen-turbo-0915' (the qwen_det detector lists ['qwen-turbo-latest'] and prices "
        "['qwen-turbo-latest', 'qwen-turbo-old']): one stored price, more than one page id; fix: "
        "re-verify on the provider's pages which page id prices the model, make it the only page "
        "id reaching 'qwen-turbo-0915', detected as well as priced since 'qwen-turbo-0915' is "
        "removed in the store, and confirm the next two landed runs refresh it with no absence "
        "entry and no removal"
    )
    assert appended_rows(repo_root, "qwen") == [
        ("qwen-turbo-0915", {"input": 0.3, "output": 1.2}, None)
    ]


def removed_twin_source(fake_modules, monkeypatch, repo_root) -> list[tuple[str, str]]:
    """One removed stored key two priced-only ids dedup onto.

    Both candidate-page ids stay priced, so no stored key but the removed one
    can count absent.
    """
    _, scrape = fake_modules
    priced = ["qwen-max", "qwen-new", "qwen-twin-b", "qwen-twin-a"]
    calls = priced_only_source(fake_modules, monkeypatch, priced)
    scrape["dashscope"]["qwen-twin-a"] = pricing(3.0e-7, 1.2e-6)
    scrape["dashscope"]["qwen-twin-b"] = pricing(3.3e-7, 1.3e-6)
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-max-0501"] if model_id.startswith("qwen-twin-") else []
    )
    price = stored_row("qwen-max-0501")
    removal = store.build_removal_row("dashscope", "qwen-max-0501", "2026-08-20", VERSION, price)
    seed_store(repo_root, [stored_row("qwen-max"), price, removal])
    return calls


def test_refresh_refuses_two_priced_only_twins_of_a_removed_key_in_one_line(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # a removed key two priced-only ids reach gets one line naming both, and
    # neither id reads a row
    calls = removed_twin_source(fake_modules, monkeypatch, repo_root)

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert ("dashscope", "qwen-twin-a") not in calls
    assert ("dashscope", "qwen-twin-b") not in calls
    assert report.providers["dashscope"].errors == [
        "FetchError: page ids ['qwen-twin-a', 'qwen-twin-b'] reach stored 'qwen-max-0501', removed "
        "in the store (the fake_det detector lists [] and prices ['qwen-twin-a', 'qwen-twin-b']): "
        "refresh cannot tell a reappearance; fix: re-verify on the provider's pages whether the "
        "model is sold again, then make exactly one page id reach 'qwen-max-0501', detected as "
        "well as priced, if it is, or none if it is not"
    ]
    assert appended_rows(repo_root, "dashscope") == [
        ("qwen-new", {"input": 0.27, "output": 1.1}, None)
    ]


def test_refresh_lands_the_revival_of_a_removed_key_once_its_page_id_is_detected_and_priced(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # the removed line's end state: the one page id reaching the key is
    # detected and priced, so the run plans its revival row and refuses nothing
    detect, _ = fake_modules
    priced_only_source(fake_modules, monkeypatch, ["qwen-max", "qwen-max-0501"])
    detect["dashscope"] = ["qwen-max", "qwen-new", "qwen-max-0501"]
    price = stored_row("qwen-max-0501")
    removal = store.build_removal_row("dashscope", "qwen-max-0501", "2026-08-20", VERSION, price)
    seed_store(repo_root, [stored_row("qwen-max"), price, removal])

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert report.providers["dashscope"].errors == []
    assert appended_rows(repo_root, "dashscope") == [
        ("qwen-max-0501", {"input": 0.3, "output": 1.2}, None),
        ("qwen-new", {"input": 0.27, "output": 1.1}, None),
    ]


def test_refresh_refuses_two_priced_only_ids_by_their_own_detector(repo_root, monkeypatch):
    # two priced-only ids beside an unpriced detected id, on a second provider:
    # the page ids, stored spelling and detector name all come from the fixture
    qwen_det = register_fake_module(monkeypatch, "detectors", "qwen_det")
    qwen_det.detect = lambda cfg: ["qwen-turbo-latest"]
    qwen_det.detect_priced = lambda cfg: ["qwen-turbo-old", "qwen-turbo-new"]
    qwen_scr = register_fake_module(monkeypatch, "scrapers", "qwen_scr")
    qwen_scr.scrape = lambda cfg, model_id: {"qwen-turbo-latest": None}[model_id]
    qwen_scr.dedup_keys = lambda model_id: (
        ["qwen-turbo"] if model_id.startswith("qwen-turbo-") else []
    )
    seed_store(repo_root, [stored_row("qwen-turbo", source="qwen")])
    cfg = config.Config(
        providers=(
            config.ProviderCfg(
                key="qwen",
                provider="Qwen",
                detector="qwen_det",
                detector_url="https://example.com/qwen-models",
                scraper="qwen_scr",
                scraper_url="https://example.com/qwen-pricing",
            ),
        )
    )

    report = pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")

    assert report.providers["qwen"].errors == [
        "FetchError: page ids ['qwen-turbo-latest', 'qwen-turbo-new', 'qwen-turbo-old'] reach "
        "stored 'qwen-turbo' (the qwen_det detector lists ['qwen-turbo-latest'] and prices "
        "['qwen-turbo-new', 'qwen-turbo-old']): one stored price, more than one page id; fix: "
        "re-verify on the provider's pages which page id prices the model, make it the only page "
        "id reaching 'qwen-turbo', and confirm the next two landed runs refresh it with no absence "
        "entry and no removal"
    ]


def test_refresh_does_not_refuse_a_held_priced_only_twin(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # the stored key rides an open pr: a held key is read for the health
    # verdict and never refused, even when two priced-only ids reach it
    calls = priced_only_source(
        fake_modules, monkeypatch, ["qwen-max", "qwen-twin-a", "qwen-twin-b"]
    )
    _, scrape = fake_modules
    scrape["dashscope"]["qwen-twin-a"] = pricing()
    scrape["dashscope"]["qwen-twin-b"] = pricing()
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-max-0501"] if model_id.startswith("qwen-twin-") else []
    )
    price = stored_row("qwen-max-0501")
    seed_store(repo_root, [stored_row("qwen-max"), price])
    pending_branch = pr.branch_name("dashscope@2026-08-25-000000")
    removal = store.build_removal_row("dashscope", "qwen-max-0501", "2026-08-25", VERSION, price)
    push_pending_branch(repo_root, pending_branch, "dashscope", [price, removal])
    runner = PipelineRunner(
        open_prs=[{"title": "Remove dashscope ids", "body": "", "headRefName": pending_branch}]
    )

    report = pipeline.run(make_cfg("dashscope"), repo_root, runner, today=TODAY, now="000000")

    assert report.providers["dashscope"].errors == []
    assert ("dashscope", "qwen-twin-a") in calls
    assert ("dashscope", "qwen-twin-b") in calls
    assert appended_rows(repo_root, "dashscope") == [
        ("qwen-new", {"input": 0.27, "output": 1.1}, None)
    ]


def test_refresh_keeps_two_detected_ids_sharing_a_stored_key_unrefused(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # two detected page ids dedup to one stored key: both read, neither is
    # the priced-only collision the refusal exists for
    detect, scrape = fake_modules
    detect["dashscope"] = ["qwen-max-0501", "qwen-max-0815"]
    sys.modules["ai_pricelog.detectors.fake_det"].detect_priced = lambda cfg: [
        "qwen-max-0501",
        "qwen-max-0815",
    ]
    scrape["dashscope"] = {"qwen-max-0501": pricing(), "qwen-max-0815": pricing()}
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-max"] if model_id != "qwen-max" else []
    )
    calls = counted_scrapes(monkeypatch)
    seed_store(repo_root, [stored_row("qwen-max")])

    report = pipeline.run(make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY)

    assert report.providers["dashscope"].errors == []
    assert calls == [("dashscope", "qwen-max-0501"), ("dashscope", "qwen-max-0815")]
    assert report.providers["dashscope"].prs == []


def test_refresh_reads_a_repeated_priced_only_id_once(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # the priced set repeats a stored id the candidate page omits: one scrape
    # and one row, because a repeat is not a second page id reaching the key;
    # the fresh id beside it has no stored spelling and lands nothing
    calls = priced_only_source(
        fake_modules, monkeypatch, ["qwen-max-0501", "qwen-max-0501", "qwen-fresh"]
    )
    seed_store(repo_root, [stored_row("qwen-max"), stored_row("qwen-max-0501")])

    report = pipeline.run(
        make_cfg("dashscope"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert report.providers["dashscope"].errors == []
    assert calls.count(("dashscope", "qwen-max-0501")) == 1
    assert appended_rows(repo_root, "dashscope") == [
        ("qwen-max-0501", {"input": 0.3, "output": 1.2}, None),
        ("qwen-new", {"input": 0.27, "output": 1.1}, None),
    ]


def test_refresh_reads_a_repeated_held_priced_only_id_once(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # an open pr holds a stored key whose priced set repeats one id: the
    # repeat is one page id, so refresh scrapes it and reports the hold once
    calls = priced_only_source(
        fake_modules, monkeypatch, ["qwen-max", "qwen-twin-a", "qwen-twin-a"]
    )
    _, scrape = fake_modules
    scrape["dashscope"]["qwen-twin-a"] = pricing()
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["qwen-max-0501"] if model_id.startswith("qwen-twin-") else []
    )
    price = stored_row("qwen-max-0501")
    seed_store(repo_root, [stored_row("qwen-max"), price])
    pending_branch = pr.branch_name("dashscope@2026-08-25-000000")
    removal = store.build_removal_row("dashscope", "qwen-max-0501", "2026-08-25", VERSION, price)
    push_pending_branch(repo_root, pending_branch, "dashscope", [price, removal])
    runner = PipelineRunner(
        open_prs=[{"title": "Remove dashscope ids", "body": "", "headRefName": pending_branch}]
    )

    report = pipeline.run(make_cfg("dashscope"), repo_root, runner, today=TODAY, now="000000")

    dashscope_report = report.providers["dashscope"]
    assert dashscope_report.errors == []
    assert calls.count(("dashscope", "qwen-twin-a")) == 1
    assert dashscope_report.skipped_pending == ["qwen-max-0501"]
    assert dashscope_report.tried.count("qwen-max-0501") == 1
    assert appended_rows(repo_root, "dashscope") == [
        ("qwen-new", {"input": 0.27, "output": 1.1}, None)
    ]


def test_refresh_without_detect_priced_reads_the_detected_ids(
    tmp_path, fake_modules, repo_root, monkeypatch
):
    # refresh walks the detected list as listed: a repeated page id and a
    # dedup twin each scrape, and an undetected stored id goes absent
    detect, scrape = fake_modules
    detect["deepseek"] = ["a", "a-alias", "a", "b"]
    scrape["deepseek"] = {"a": pricing(), "a-alias": pricing(), "b": pricing(3.0e-7, 1.2e-6)}
    sys.modules["ai_pricelog.scrapers.fake_scr"].dedup_keys = lambda model_id: (
        ["a"] if model_id == "a-alias" else []
    )
    calls = counted_scrapes(monkeypatch)
    seed_store(
        repo_root,
        [stored_row(model_id, source="deepseek") for model_id in ("a", "b", "gone")],
    )

    report = pipeline.run(
        make_cfg("deepseek"), repo_root, PipelineRunner(), today=TODAY, now="000000"
    )

    assert report.providers["deepseek"].errors == []
    assert calls == [
        ("deepseek", "a"),
        ("deepseek", "a-alias"),
        ("deepseek", "a"),
        ("deepseek", "b"),
    ]
    assert appended_rows(repo_root, "deepseek") == [("b", {"input": 0.3, "output": 1.2}, None)]
    assert branch_absence(repo_root, batch_branch("deepseek")) == {
        "deepseek": {"gone": {"absent_runs": 1, "since": TODAY}}
    }


def test_dashscope_absence_keys_on_the_international_priced_rows(
    repo_root, monkeypatch, unscripted_calls
):
    # the real dashscope pair on the 2026-11-18 captures: the CN page lists
    # official versions only, so absence keyed on it counted every dated and
    # preview spelling absent (PR #839's 14 removals). keyed on the pricing
    # page's priced rows, none of the stored ids counts absent, the landed
    # counters clear, and candidates still come from the CN page only
    today = "2026-11-18"
    pcfg = config.ProviderCfg(
        key="dashscope",
        provider="DashScope",
        detector="dashscope_page",
        detector_url=dashscope_fixtures.CN_URL,
        scraper="dashscope_page",
        scraper_url=dashscope_fixtures.EN_URL,
    )
    pages = {
        dashscope_fixtures.CN_URL: "textgen-cn.html",
        dashscope_fixtures.EN_URL: "model-pricing-intl.html",
    }
    soups = {
        url: web.parse_html((dashscope_fixtures.FIXTURES / name).read_text(encoding="utf-8"))
        for url, name in pages.items()
    }

    serve_urls(
        monkeypatch,
        (dashscope_detector, dashscope_scraper),
        "fetch_soup",
        soups,
        unscripted_calls,
    )
    seed_store(
        repo_root,
        [
            store.build_row(
                "dashscope",
                model_id,
                Pricing(input_rate / 1e6, output_rate / 1e6, "chat"),
                "2026-11-16",
                dashscope_fixtures.EN_URL,
                VERSION,
            )
            for model_id, (input_rate, output_rate) in dashscope_fixtures.LIVE_STORED.items()
        ],
    )
    seed_absence(
        repo_root,
        {
            "dashscope": {
                model_id: {"absent_runs": 1, "since": "2026-11-05"}
                for model_id in dashscope_fixtures.FALSE_REMOVALS
            }
        },
    )
    runner = PipelineRunner()

    report = pipeline.run(
        config.Config(providers=(pcfg,)), repo_root, runner, today=today, now="000000"
    )

    assert report.providers["dashscope"].errors == []
    branch = batch_branch("dashscope", today=today)
    shard = branch_rows(repo_root, branch, "dashscope")
    appended = [row for row in shard if row["observed_at"] == today]
    # the run appends the stored scheduled id's off-peak base with its peak
    # override, and the promo rate in force; no removal, and no candidate row
    # for the pricing page's image model
    assert [
        (row["model_id"], row["rates"], row.get("overrides"), row.get("removed"))
        for row in appended
    ] == [
        (
            "deepseek-v4.1-flash-1017",
            {"input": 0.15, "output": 0.6},
            [
                {
                    "rates": {"input": 0.3, "output": 1.2},
                    "when": {"window": [0, 1400], "timezone": "UTC"},
                }
            ],
            None,
        ),
        ("qwen3.7-plus", {"input": 0.32, "output": 1.28}, None, None),
    ]
    assert branch_absence(repo_root, branch).get("dashscope", {}) == {}
    assert [head for _title, _body, head in runner.created] == [branch]


def moonshot_pages(rendered: str | None = None) -> dict[str, str]:
    """The live moonshot captures by url; `rendered` overrides the chat page.

    measured 2026-11-19: the export and the pricing table's compiled source
    were byte-identical to the 2026-11-18 fixtures, so those stand for the
    live page; models.md is its own 2026-11-19 capture."""
    fixtures = moonshot_fixtures.FIXTURES
    return {
        moonshot_fixtures.MODELS_URL: (fixtures / "models-2026-11-19.md").read_text(
            encoding="utf-8"
        ),
        moonshot_fixtures.INDEX_URL: (fixtures / "llms.txt").read_text(encoding="utf-8"),
        moonshot_fixtures.CHAT_URL: (fixtures / "chat-2026-11-18.md").read_text(encoding="utf-8"),
        moonshot_fixtures.FLIGHT_URL: (
            rendered
            if rendered is not None
            else (fixtures / "chat-rendered-2026-11-18.html").read_text(encoding="utf-8")
        ),
    }


def moonshot_cfg() -> config.ProviderCfg:
    return config.ProviderCfg(
        key="moonshot",
        provider="Moonshot AI",
        detector="moonshot_page",
        detector_url=moonshot_fixtures.MODELS_URL,
        scraper="moonshot_page",
        scraper_url=moonshot_fixtures.INDEX_URL,
    )


@pytest.fixture(autouse=True)
def clear_moonshot_caches():
    # the module-level lru caches outlive a test in a shared worker, so a
    # later test would read the previous one's fixture text
    moonshot_scraper._load_index.cache_clear()
    moonshot_scraper._page_text.cache_clear()
    yield
    moonshot_scraper._load_index.cache_clear()
    moonshot_scraper._page_text.cache_clear()


def serve_urls(
    monkeypatch, modules, attr: str, pages: Mapping[str, object], unscripted_calls
) -> None:
    """Answer `attr` on each module from `pages`; an unscripted url is recorded."""

    def fetch(url: str):
        if url not in pages:
            unscripted_calls.fail("fetch", url)
        return pages[url]

    for module in modules:
        monkeypatch.setattr(module, attr, fetch)


def serve_moonshot(monkeypatch, pages: dict[str, str], unscripted_calls) -> None:
    serve_urls(
        monkeypatch,
        (moonshot_detector, moonshot_scraper),
        "fetch_text",
        pages,
        unscripted_calls,
    )


def test_serve_urls_records_an_unscripted_fetch(monkeypatch, unscripted_calls):
    # serve_urls is the one guard both page-serving fakes share, and the url
    # derives from the caller's input, so a hardcoded where reds here
    serve_urls(monkeypatch, (moonshot_scraper,), "fetch_text", {}, unscripted_calls)
    with pytest.raises(AssertionError, match="unscripted fetch for https://example.com/x"):
        moonshot_scraper.fetch_text("https://example.com/x")
    with pytest.raises(AssertionError, match="unscripted fetch for https://example.com/y"):
        moonshot_scraper.fetch_text("https://example.com/y")

    assert unscripted_calls.recorded == [
        ("fetch", "https://example.com/x"),
        ("fetch", "https://example.com/y"),
    ]
    unscripted_calls.expect("fetch", "https://example.com/x")
    unscripted_calls.expect("fetch", "https://example.com/y")


def test_serve_moonshot_records_an_unscripted_fetch(monkeypatch, unscripted_calls):
    # serve_moonshot is what the moonshot tests call: it must delegate to
    # serve_urls, so an unscripted page is recorded and not raised bare
    serve_moonshot(monkeypatch, {}, unscripted_calls)
    with pytest.raises(AssertionError, match="unscripted fetch for https://example.com/x"):
        moonshot_detector.fetch_text("https://example.com/x")

    assert unscripted_calls.recorded == [("fetch", "https://example.com/x")]
    unscripted_calls.expect("fetch", "https://example.com/x")


def count_moonshot_scrapes(monkeypatch) -> list[str]:
    calls: list[str] = []
    real_scrape = moonshot_scraper.scrape

    def scrape(cfg, model_id):
        calls.append(model_id)
        return real_scrape(cfg, model_id)

    monkeypatch.setattr(moonshot_scraper, "scrape", scrape)
    return calls


def moonshot_stored_row(model_id: str) -> dict:
    """One stored moonshot row, priced as the live page prints it; the rates
    are pinned by value so a later landed row does not rewrite the tests."""
    input_rate, output_rate, cached, write, write_1h = moonshot_fixtures.LIVE_ROWS[model_id]
    return store.build_row(
        "moonshot",
        model_id,
        Pricing(
            input_rate / 1e6,
            output_rate / 1e6,
            "chat",
            0,
            cached / 1e6,
            cache_write_cost_per_token=None if write is None else write / 1e6,
            cache_write_1h_cost_per_token=None if write_1h is None else write_1h / 1e6,
        ),
        "2026-10-31",
        moonshot_fixtures.FLIGHT_URL,
        VERSION,
    )


def seed_moonshot_store(repo_root: Path) -> None:
    """The six stored live ids, plus a moved kimi-k2.6 row so a change lands."""
    rows = [moonshot_stored_row(model_id) for model_id in moonshot_fixtures.LIVE_ROWS]
    rows.append(
        store.build_row(
            "moonshot",
            "kimi-k2.6",
            Pricing(0.99e-6, 4.0e-6, "chat", 0, 0.16e-6),
            "2026-11-18",
            moonshot_fixtures.FLIGHT_URL,
            VERSION,
        )
    )
    seed_store(repo_root, rows)


def test_moonshot_absence_keys_on_the_chat_page_priced_rows(
    repo_root, monkeypatch, unscripted_calls
):
    # the models page hides the three K2 ids in its deprecated table while the
    # chat page still prices them: keyed on the chat page's priced set, the
    # landed counter clears, every id refreshes, the moved K2 price lands, and
    # no removal is planned for a still-priced id
    today = "2026-11-19"
    serve_moonshot(monkeypatch, moonshot_pages(), unscripted_calls)
    calls = count_moonshot_scrapes(monkeypatch)
    seed_moonshot_store(repo_root)
    seed_absence(repo_root, {"moonshot": {"kimi-k2.6": {"absent_runs": 1, "since": "2026-11-05"}}})
    runner = PipelineRunner()

    report = pipeline.run(
        config.Config(providers=(moonshot_cfg(),)), repo_root, runner, today=today, now="000000"
    )

    assert report.providers["moonshot"].errors == []
    assert sorted(calls) == sorted(moonshot_fixtures.LIVE_PRICED_IDS)
    assert set(report.providers["moonshot"].tried) == set(moonshot_fixtures.LIVE_PRICED_IDS)
    assert [model_id for model_id, _url in report.providers["moonshot"].prs] == ["kimi-k2.6"]
    branch = batch_branch("moonshot", today=today)
    assert branch_absence(repo_root, branch) == {}
    appended = [
        (row["model_id"], row["rates"], row.get("removed"))
        for row in branch_rows(repo_root, branch, "moonshot")
        if row["observed_at"] == today
    ]
    assert appended == [("kimi-k2.6", {"input": 0.95, "output": 4.0, "cache_read": 0.16}, None)]


def test_moonshot_absence_counts_an_id_the_chat_page_stops_pricing(
    repo_root, monkeypatch, unscripted_calls
):
    # near miss: kimi-k2.6's row leaves the chat page, so the priced set drops
    # it and the seeded counter reaches 2: the removal row is planned as before
    today = "2026-11-19"
    rendered = moonshot_fixtures.rendered_without_row(
        (moonshot_fixtures.FIXTURES / "chat-rendered-2026-11-18.html").read_text(encoding="utf-8"),
        "kimi-k2.6",
    )
    serve_moonshot(monkeypatch, moonshot_pages(rendered), unscripted_calls)
    calls = count_moonshot_scrapes(monkeypatch)
    seed_moonshot_store(repo_root)
    seed_absence(repo_root, {"moonshot": {"kimi-k2.6": {"absent_runs": 1, "since": "2026-11-05"}}})
    runner = PipelineRunner()

    report = pipeline.run(
        config.Config(providers=(moonshot_cfg(),)), repo_root, runner, today=today, now="000000"
    )

    assert report.providers["moonshot"].errors == []
    assert "kimi-k2.6" not in calls
    branch = batch_branch("moonshot", today=today)
    assert branch_absence(repo_root, branch) == {
        "moonshot": {"kimi-k2.6": {"absent_runs": 2, "since": "2026-11-05"}}
    }
    removed = [
        row["model_id"]
        for row in branch_rows(repo_root, branch, "moonshot")
        if row["observed_at"] == today and row.get("removed") is True
    ]
    assert removed == ["kimi-k2.6"]


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
    # model counts present because the api lists it (the stub fills `listed`)
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

    def fake_fetch(*, errors=None, listed=None):
        if listed is not None:
            listed.add(model.id)
        return [model]

    monkeypatch.setattr(pipeline.openrouter, "fetch_models", fake_fetch)
    runner = PipelineRunner()

    report = pipeline.run(cfg, repo_root, runner, today=TODAY)

    assert report.providers["openrouter"].errors
    assert [model_id for model_id, _url in report.providers["openrouter"].prs] == []
    assert runner.pr_urls == []


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
    # counter, so the state stays equal
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

    # nothing was committed or branched
    assert_default_branch_clean(repo_root)


def test_api_sourced_id_cannot_forge_a_health_line(
    tmp_path, fake_modules, repo_root, caplog, or_models
):
    # an api-sourced id is page text: a newline in it must not become a
    # run-log line the health step reads, or a forged "detector for openai
    # failed" line classes a healthy provider as broken
    detect, _ = fake_modules
    detect["deepseek"] = []
    or_models.append(
        openrouter.OpenrouterModel(
            id="bad\nERROR:ai_pricelog.pipeline:detector for openai failed",
            name="Bad Shape",
            input_mtok=None,
            output_mtok=None,
            cache_read_mtok=None,
            pricing={"prompt": "1e-7", "completion": "1e-6", "overrides": "not-a-list"},
        )
    )
    cfg = make_cfg("deepseek")
    with caplog.at_level(logging.WARNING):
        pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")
    lines = _logged_lines(caplog)
    assert not any("\n" in line for line in lines)
    assert "openai" not in health.parse_log(lines)


def test_page_id_cannot_forge_a_health_line(tmp_path, fake_modules, repo_root, caplog):
    # a detector's page id is page text too: the validation sink must not
    # split it into a forged line
    detect, scrape = fake_modules
    page_id = "a\nERROR:ai_pricelog.pipeline:detector for openai failed"
    detect["deepseek"] = [page_id]
    scrape["deepseek"] = {page_id: Pricing(-1.0, 1.1e-06, "chat", 65536)}
    cfg = make_cfg("deepseek")
    with caplog.at_level(logging.WARNING):
        pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")
    lines = _logged_lines(caplog)
    assert not any("\n" in line for line in lines)
    assert "openai" not in health.parse_log(lines)


def test_a_scraper_error_message_cannot_forge_a_health_line(
    tmp_path, fake_modules, repo_root, caplog
):
    # the run log is read line by line, traceback tail included: a page-sourced
    # id inside a FetchError message must not split into its own line
    detect, scrape = fake_modules
    page_id = "a\nERROR:ai_pricelog.pipeline:detector for openai failed"
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": web.FetchError(f"unreadable rate for {page_id} on u")}
    cfg = make_cfg("deepseek")
    with caplog.at_level(logging.WARNING):
        pipeline.run(cfg, repo_root, PipelineRunner(), today=TODAY, now="000000")
    formatter = logging.Formatter(logging.BASIC_FORMAT)
    lines = "\n".join(formatter.format(record) for record in caplog.records).splitlines()
    assert not any("\n" in line for line in lines)
    assert "openai" not in health.parse_log(lines)


def test_detect_skip_watch_counts_a_real_skip_line(caplog):
    watch = pipeline._DetectSkipWatch("databricks")
    page_log = logging.getLogger("ai_pricelog.detectors.databricks_page")
    with caplog.at_level(logging.WARNING), watch.installed():
        page_log.warning(
            "detect skip for databricks: unmapped model name 'Drifted' on https://example.com"
        )
    assert watch.count == 1


def test_detect_skip_watch_ignores_page_text_naming_a_skip(caplog):
    # page text inside a parse-skip line must not count as a detect skip: a
    # databricks section row spelling that phrase would freeze the source's
    # absence counters for as long as the page carries the text
    watch = pipeline._DetectSkipWatch("databricks")
    page_log = logging.getLogger("ai_pricelog.detectors.databricks_page")
    with caplog.at_level(logging.WARNING), watch.installed():
        page_log.warning(
            "parse skip for databricks: section row %r on %s",
            "detect skip for databricks: x",
            "https://example.com/pricing",
        )
    assert watch.count == 0

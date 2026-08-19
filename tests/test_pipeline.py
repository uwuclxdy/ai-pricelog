import json
import logging
import shutil
import sys
import types
from pathlib import Path

import pytest

from autopr_genai_prices import build, config, openrouter, pipeline, pr
from autopr_genai_prices.pricing import Pricing
from autopr_genai_prices.state import load as load_state
from conftest import git, git_init_repo, register_fake_module

DEEPSEEK_YML = "deepseek.yml"
OPENROUTER_YML = "openrouter.yml"


def pricing() -> Pricing:
    return Pricing(2.7e-07, 1.1e-06, "chat", 65536)


def vendor_yml(name: str, *tracked: str) -> str:
    blocks = "".join(
        f"  - id: {model_id}\n    match:\n      equals: {model_id}\n" for model_id in tracked
    )
    return f"id: {name.lower()}\nname: {name}\nmodels: {'[]' if not blocks else ''}\n{blocks}"


def openrouter_yml(*tracked: str) -> str:
    blocks = "".join(f"  - id: {slug}\n    match:\n      equals: {slug}\n" for slug in tracked)
    return f"id: openrouter\nname: OpenRouter\nmodels: {'[]' if not blocks else ''}\n{blocks}"


class PipelineRunner:
    """gh calls scripted, git subprocesses real (all local, offline)."""

    def __init__(
        self,
        existing_prs: dict[str, str] | None = None,
        pending_prs: dict[str, str] | None = None,
    ) -> None:
        self.real = pr.PrRunner()
        self.calls: list[tuple[list[str], Path]] = []
        self.pr_urls: list[str] = []
        self.existing_prs = existing_prs or {}
        self.pending_prs = pending_prs or {}

    def run(self, cmd: list[str], cwd: Path) -> str:
        self.calls.append((cmd, cwd))
        if cmd[0] == "gh":
            if cmd[1] == "api":
                return "octocat\n" if cmd[2] == "user" else "main\n"
            if cmd[1] == "pr" and cmd[2] == "list":
                if "--head" in cmd:
                    head = cmd[cmd.index("--head") + 1]
                    url = self.existing_prs.get(head)
                    return f"{url}\n" if url else "\n"
                search = cmd[cmd.index("--search") + 1]
                model_id = search.strip('"').split(" in:", 1)[0]
                url = self.pending_prs.get(model_id)
                return f"{url}\n" if url else "\n"
            if cmd[1] == "pr" and cmd[2] == "create":
                url = f"https://github.com/octo/genai-prices/pull/{len(self.pr_urls) + 1}"
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
        yml=f"{key}.yml",
        or_prefix=key,
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
    det = types.ModuleType("autopr_genai_prices.detectors.fake_det")
    det.detect = detect
    scr = types.ModuleType("autopr_genai_prices.scrapers.fake_scr")
    scr.scrape = scrape
    monkeypatch.setitem(sys.modules, "autopr_genai_prices.detectors.fake_det", det)
    monkeypatch.setitem(sys.modules, "autopr_genai_prices.scrapers.fake_scr", scr)
    return detect_controls, scrape_controls


@pytest.fixture
def upstream(tmp_path):
    def make(
        ymls: dict[str, str] | None = None,
        or_tracked: tuple[str, ...] = (),
    ) -> Path:
        src = tmp_path / "upstream-src"
        git_init_repo(src)
        providers = src / "prices" / "providers"
        providers.mkdir(parents=True, exist_ok=True)
        for file_name, text in (
            ymls or {DEEPSEEK_YML: vendor_yml("Deepseek", "deepseek-legacy")}
        ).items():
            (providers / file_name).write_text(text)
        (providers / OPENROUTER_YML).write_text(openrouter_yml(*or_tracked))
        git(src, "add", ".")
        git(src, "commit", "-m", "seed")
        bare = tmp_path / "upstream.git"
        shutil.rmtree(bare, ignore_errors=True)
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
def or_models() -> list[openrouter.OpenrouterModel]:
    return []


@pytest.fixture
def wire(monkeypatch, or_models):
    monkeypatch.setattr(pr, "parse_github_url", lambda repo: ("octo", "genai-prices"))
    monkeypatch.setattr(openrouter, "fetch_models", lambda: list(or_models))


@pytest.fixture
def fake_open_pr(monkeypatch):
    """record specs, script urls: the pipeline's build/pr seam stays offline."""
    specs: list[pr.PrSpec] = []
    failures: dict[str, Exception] = {}

    def fake(cfg, base, slot, spec, runner):
        specs.append(spec)
        failure = failures.get(spec.model_id)
        if failure is not None:
            raise failure
        return f"https://github.com/octo/genai-prices/pull/{len(specs)}"

    monkeypatch.setattr(pr, "open_draft_pr", fake)
    return specs, failures


def test_fresh_candidate_opens_pr_and_settles(
    tmp_path, fake_modules, upstream, repo_root, wire, or_models, fake_open_pr
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    or_models.append(
        openrouter.OpenrouterModel(
            id="deepseek/deepseek-chat",
            name="DeepSeek Chat",
            input_mtok=0.27,
            output_mtok=1.1,
            cache_read_mtok=None,
        )
    )
    cfg = make_cfg(upstream(), 3, ("deepseek",))
    workdir = tmp_path / "work"
    runner = PipelineRunner()

    report = pipeline.run(cfg, workdir, repo_root, runner)

    provider_report = report.providers["deepseek"]
    assert provider_report.detected == ["deepseek-chat"]
    assert provider_report.candidates == ["deepseek-chat"]
    assert [model_id for model_id, _url in provider_report.prs] == ["deepseek-chat"]
    assert provider_report.prs[0][1] == "https://github.com/octo/genai-prices/pull/1"
    assert provider_report.skipped_pending == []
    assert provider_report.skipped_no_pricing == []
    assert provider_report.skipped_cap == []
    assert provider_report.skipped_build == []
    assert provider_report.error is None

    saved = load_state(repo_root / "state.json")
    assert saved.providers["deepseek"].last_seen == ["deepseek-chat"]
    assert saved.providers["deepseek"].handled == ["deepseek-chat"]

    subjects = git(repo_root, "log", "--format=%s").splitlines()
    assert subjects[0] == "chore: advance watchdog state"

    (spec,) = fake_open_pr[0]
    assert spec.vendor_yml == DEEPSEEK_YML
    assert spec.title == "Add deepseek-chat pricing for Deepseek and OpenRouter"
    assert "  - id: deepseek-chat" in spec.vendor_entry
    assert "context_window: 65536" in spec.vendor_entry
    assert "input_mtok: 0.27" in spec.vendor_entry
    assert "output_mtok: 1.1" in spec.vendor_entry
    assert "Ref: https://example.com/pricing" in spec.vendor_entry
    assert spec.openrouter_entry is not None
    assert "  - id: deepseek/deepseek-chat" in spec.openrouter_entry

    second = pipeline.run(cfg, workdir, repo_root, runner)
    assert second.providers["deepseek"].candidates == []
    assert len(fake_open_pr[0]) == 1
    assert len(git(repo_root, "log", "--format=%s").splitlines()) == 2


def test_missing_pricing_stays_unsettled_and_retries(
    tmp_path, fake_modules, upstream, repo_root, wire, fake_open_pr
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-x"]
    scrape["deepseek"] = {"deepseek-x": None}
    cfg = make_cfg(upstream(), 3, ("deepseek",))
    workdir = tmp_path / "work"
    runner = PipelineRunner()

    report = pipeline.run(cfg, workdir, repo_root, runner)
    provider_report = report.providers["deepseek"]
    assert provider_report.skipped_no_pricing == ["deepseek-x"]
    assert provider_report.prs == []
    assert fake_open_pr[0] == []
    saved = load_state(repo_root / "state.json")
    assert saved.providers["deepseek"].last_seen == []
    assert saved.providers["deepseek"].handled == []

    second = pipeline.run(cfg, workdir, repo_root, runner)
    assert second.providers["deepseek"].candidates == ["deepseek-x"]
    assert second.providers["deepseek"].skipped_no_pricing == ["deepseek-x"]


def test_cap_skips_without_settling(
    tmp_path, fake_modules, upstream, repo_root, wire, fake_open_pr
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["a", "b"]
    scrape["deepseek"] = {"a": pricing(), "b": pricing()}
    cfg = make_cfg(upstream(), 1, ("deepseek",))
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
    tmp_path, fake_modules, upstream, repo_root, wire, fake_open_pr
):
    detect, scrape = fake_modules
    detect["deepseek"] = RuntimeError("detector boom")
    detect["zai"] = ["zai-x"]
    scrape["zai"] = {"zai-x": None}
    ymls = {
        DEEPSEEK_YML: vendor_yml("Deepseek", "deepseek-legacy"),
        "zai.yml": vendor_yml("Zai", "zai-legacy"),
    }
    cfg = make_cfg(upstream(ymls=ymls), 3, ("deepseek", "zai"))
    workdir = tmp_path / "work"
    runner = PipelineRunner()

    report = pipeline.run(cfg, workdir, repo_root, runner)
    assert report.providers["deepseek"].error is not None
    assert "detector boom" in report.providers["deepseek"].error
    zai_report = report.providers["zai"]
    assert zai_report.detected == ["zai-x"]
    assert zai_report.skipped_no_pricing == ["zai-x"]
    assert zai_report.error is None


def test_entry_already_tracked_settles_without_pr(
    tmp_path, fake_modules, upstream, repo_root, wire, fake_open_pr
):
    detect, _scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    ymls = {DEEPSEEK_YML: vendor_yml("Deepseek", "deepseek-chat")}
    cfg = make_cfg(upstream(ymls=ymls), 3, ("deepseek",))
    workdir = tmp_path / "work"
    runner = PipelineRunner()

    report = pipeline.run(cfg, workdir, repo_root, runner)
    provider_report = report.providers["deepseek"]
    assert provider_report.prs == []
    assert provider_report.skipped_no_pricing == []
    assert fake_open_pr[0] == []
    saved = load_state(repo_root / "state.json")
    assert saved.providers["deepseek"].last_seen == ["deepseek-chat"]
    assert saved.providers["deepseek"].handled == []


def test_dedup_keys_settle_without_scrape(
    tmp_path, upstream, repo_root, fake_modules, wire, fake_open_pr
):
    # a provider whose key spelling differs from its detected id (mistral
    # slugs) settles through the scraper's dedup_keys hook without scraping
    detect, scrape = fake_modules
    detect["mistral"] = ["codestral-25-08"]
    scrape["mistral"] = {}
    scr = sys.modules["autopr_genai_prices.scrapers.fake_scr"]
    scr.dedup_keys = lambda model_id: ["codestral-2508"]
    ymls = {"mistral.yml": vendor_yml("Mistral", "codestral-2508")}
    cfg = make_cfg(upstream(ymls=ymls), 3, ("mistral",))
    runner = PipelineRunner()

    report = pipeline.run(cfg, tmp_path / "work", repo_root, runner)

    provider_report = report.providers["mistral"]
    assert provider_report.prs == []
    assert provider_report.error is None
    assert provider_report.skipped_no_pricing == []
    assert fake_open_pr[0] == []
    saved = load_state(repo_root / "state.json")
    assert saved.providers["mistral"].last_seen == ["codestral-25-08"]
    assert saved.providers["mistral"].handled == []


def test_scrape_error_aborts_provider_and_retries(
    tmp_path, fake_modules, upstream, repo_root, wire, fake_open_pr
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["a", "b"]
    scrape["deepseek"] = {"a": RuntimeError("page broke"), "b": pricing()}
    cfg = make_cfg(upstream(), 3, ("deepseek",))
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
    tmp_path, fake_modules, upstream, repo_root, wire, fake_open_pr
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["a", "b"]
    scrape["deepseek"] = {"a": Pricing(0.0, 1.1e-06, "chat", 65536), "b": pricing()}
    cfg = make_cfg(upstream(), 3, ("deepseek",))
    workdir = tmp_path / "work"
    runner = PipelineRunner()

    report = pipeline.run(cfg, workdir, repo_root, runner)

    provider_report = report.providers["deepseek"]
    assert provider_report.error is not None
    assert "input_cost_per_token" in provider_report.error
    assert [model_id for model_id, _url in provider_report.prs] == ["b"]
    saved = load_state(repo_root / "state.json")
    assert saved.providers["deepseek"].last_seen == ["b"]
    assert saved.providers["deepseek"].handled == ["b"]

    second = pipeline.run(cfg, workdir, repo_root, runner)
    assert second.providers["deepseek"].candidates == ["a"]


def test_pending_pr_skips_without_state_change(
    tmp_path, fake_modules, upstream, repo_root, wire, fake_open_pr
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": None}
    cfg = make_cfg(upstream(), 3, ("deepseek",))
    workdir = tmp_path / "work"
    url = "https://github.com/pydantic/genai-prices/pull/574"
    runner = PipelineRunner(pending_prs={"deepseek-chat": url})

    report = pipeline.run(cfg, workdir, repo_root, runner)
    provider_report = report.providers["deepseek"]
    assert provider_report.skipped_pending == ["deepseek-chat"]
    assert provider_report.prs == []
    assert provider_report.error is None
    assert fake_open_pr[0] == []
    # the skip itself writes nothing: the lists stay empty, so a closed-unmerged
    # PR re-candidates the model next run
    saved = load_state(repo_root / "state.json")
    assert saved.providers["deepseek"].last_seen == []
    assert saved.providers["deepseek"].handled == []

    # the pending PR closed unmerged: the id re-candidates and ships
    second = pipeline.run(cfg, workdir, repo_root, PipelineRunner())
    assert second.providers["deepseek"].candidates == ["deepseek-chat"]
    assert second.providers["deepseek"].skipped_no_pricing == ["deepseek-chat"]


def test_pending_check_runs_before_scrape(
    tmp_path, fake_modules, upstream, repo_root, wire, fake_open_pr
):
    # the scrape controls are empty: any scrape call raises AssertionError, so
    # a green run proves the pending skip fired before the scraper
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {}
    cfg = make_cfg(upstream(), 3, ("deepseek",))
    runner = PipelineRunner(
        pending_prs={"deepseek-chat": "https://github.com/pydantic/genai-prices/pull/574"}
    )
    report = pipeline.run(cfg, tmp_path / "work", repo_root, runner)
    assert report.providers["deepseek"].skipped_pending == ["deepseek-chat"]
    assert report.providers["deepseek"].error is None


def test_openrouter_deferral_keeps_vendor_pr(
    tmp_path, fake_modules, upstream, repo_root, wire, or_models, fake_open_pr
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg(upstream(), 3, ("deepseek",))
    report = pipeline.run(cfg, tmp_path / "work", repo_root, PipelineRunner())

    provider_report = report.providers["deepseek"]
    assert len(provider_report.prs) == 1
    (spec,) = fake_open_pr[0]
    assert spec.openrouter_entry is None
    assert spec.title == "Add deepseek-chat pricing for Deepseek"
    assert "`deepseek/deepseek-chat` is not listed on the OpenRouter models API" in spec.body
    assert "the openrouter entry is deferred" in spec.body


def test_openrouter_entry_already_tracked_is_skipped(
    tmp_path, fake_modules, upstream, repo_root, wire, or_models, fake_open_pr
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    or_models.append(
        openrouter.OpenrouterModel(
            id="deepseek/deepseek-chat",
            name="DeepSeek Chat",
            input_mtok=0.27,
            output_mtok=1.1,
            cache_read_mtok=None,
        )
    )
    cfg = make_cfg(upstream(or_tracked=("deepseek/deepseek-chat",)), 3, ("deepseek",))
    report = pipeline.run(cfg, tmp_path / "work", repo_root, PipelineRunner())

    assert len(report.providers["deepseek"].prs) == 1
    (spec,) = fake_open_pr[0]
    assert spec.openrouter_entry is None
    assert "already tracked in openrouter.yml" in spec.openrouter_note
    assert "and OpenRouter" not in spec.title


def test_openrouter_fetched_once_per_run(
    tmp_path, fake_modules, upstream, repo_root, or_models, fake_open_pr, monkeypatch
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["a"]
    detect["zai"] = ["b"]
    scrape["deepseek"] = {"a": pricing()}
    scrape["zai"] = {"b": pricing()}
    fetches = {"count": 0}

    def counting():
        fetches["count"] += 1
        return list(or_models)

    monkeypatch.setattr(pr, "parse_github_url", lambda repo: ("octo", "genai-prices"))
    monkeypatch.setattr(openrouter, "fetch_models", counting)
    ymls = {
        DEEPSEEK_YML: vendor_yml("Deepseek", "deepseek-legacy"),
        "zai.yml": vendor_yml("Zai", "zai-legacy"),
    }
    cfg = make_cfg(upstream(ymls=ymls), 3, ("deepseek", "zai"))
    report = pipeline.run(cfg, tmp_path / "work", repo_root, PipelineRunner())

    assert len(report.providers["deepseek"].prs) == 1
    assert len(report.providers["zai"].prs) == 1
    assert fetches["count"] == 1


def test_build_failure_skips_and_settles_next_run(
    tmp_path, fake_modules, upstream, repo_root, wire, fake_open_pr
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["a"]
    scrape["deepseek"] = {"a": pricing()}
    cfg = make_cfg(upstream(), 3, ("deepseek",))
    specs, failures = fake_open_pr
    failures["a"] = build.BuildError("make build failed in the clone: duplicate model id")

    report = pipeline.run(cfg, tmp_path / "work", repo_root, PipelineRunner())
    provider_report = report.providers["deepseek"]
    assert provider_report.skipped_build == ["a"]
    assert provider_report.prs == []
    assert provider_report.error is None
    saved = load_state(repo_root / "state.json")
    assert saved.providers["deepseek"].last_seen == []
    assert saved.providers["deepseek"].handled == []

    # the raced merge landed upstream: the next run's clone tracks the id and
    # settles it without a pr
    failures.pop("a")
    ymls = {DEEPSEEK_YML: vendor_yml("Deepseek", "a")}
    cfg = make_cfg(upstream(ymls=ymls), 3, ("deepseek",))
    second = pipeline.run(cfg, tmp_path / "work", repo_root, PipelineRunner())
    assert second.providers["deepseek"].candidates == ["a"]
    assert second.providers["deepseek"].prs == []
    saved = load_state(repo_root / "state.json")
    assert saved.providers["deepseek"].last_seen == ["a"]
    assert saved.providers["deepseek"].handled == []


def test_existing_open_pr_settles_without_new_pr(
    tmp_path, fake_modules, upstream, repo_root, wire, monkeypatch
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg(upstream(), 3, ("deepseek",))
    workdir = tmp_path / "work"

    real_open_draft_pr = pr.open_draft_pr

    def fake_open(cfg, base, slot, spec, runner):
        return "https://github.com/octo/genai-prices/pull/1"

    monkeypatch.setattr(pr, "open_draft_pr", fake_open)

    report = pipeline.run(cfg, workdir, repo_root, PipelineRunner())
    assert [model_id for model_id, _url in report.providers["deepseek"].prs] == ["deepseek-chat"]

    # simulate a crash between pr open and state write: the id stays unsettled.
    # the second run goes through the real open_draft_pr, whose existing_pr
    # check finds the open PR and skips the build entirely.
    (repo_root / "state.json").write_text(json.dumps({"providers": {}}) + "\n")
    url = report.providers["deepseek"].prs[0][1]
    second_runner = PipelineRunner(existing_prs={"autopr/deepseek/deepseek-chat": url})
    monkeypatch.setattr(pr, "open_draft_pr", real_open_draft_pr)

    second = pipeline.run(cfg, workdir, repo_root, second_runner)

    provider_report = second.providers["deepseek"]
    assert provider_report.prs == [("deepseek-chat", url)]
    assert second_runner.pr_urls == []
    create_calls = [c for c in second_runner.calls if c[0][1] == "pr" and c[0][2] == "create"]
    assert create_calls == []
    saved = load_state(repo_root / "state.json")
    assert saved.providers["deepseek"].last_seen == ["deepseek-chat"]
    assert saved.providers["deepseek"].handled == ["deepseek-chat"]


def test_noop_state_commit_logs_info_not_error(
    caplog, tmp_path, fake_modules, upstream, wire, fake_open_pr
):
    # a gitignored, never-tracked state.json: git add refuses it, the commit is
    # a no-op and must log at INFO instead of raising
    root = tmp_path / "autopr-root"
    git_init_repo(root)
    (root / ".gitignore").write_text("state.json\n")
    (root / "state.json").write_text(json.dumps({"providers": {}}) + "\n")
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg(upstream(), 3, ("deepseek",))
    workdir = tmp_path / "work"
    runner = PipelineRunner()

    with caplog.at_level(logging.INFO, logger="autopr_genai_prices.pipeline"):
        report = pipeline.run(cfg, workdir, root, runner)

    provider_report = report.providers["deepseek"]
    assert provider_report.error is None
    assert len(provider_report.prs) == 1
    assert "state commit skipped" in caplog.text
    skip_records = [r for r in caplog.records if "state commit skipped" in r.getMessage()]
    assert skip_records and all(r.levelno == logging.INFO for r in skip_records)


def test_state_push_uses_github_ref_name(
    tmp_path, fake_modules, upstream, repo_root, wire, fake_open_pr, monkeypatch
):
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg(upstream(), 3, ("deepseek",))
    monkeypatch.setenv("GITHUB_REF_NAME", "mommy")
    runner = PipelineRunner()

    report = pipeline.run(cfg, tmp_path / "work", repo_root, runner)
    assert report.providers["deepseek"].prs
    push_cmds = [c for c in runner.calls if c[0][0] == "git" and c[0][1] == "push"]
    assert push_cmds and push_cmds[-1][0] == ["git", "push", "origin", "HEAD:refs/heads/mommy"]


def test_state_push_uses_current_branch_without_env(
    tmp_path, fake_modules, upstream, repo_root, wire, fake_open_pr, monkeypatch
):
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg(upstream(), 3, ("deepseek",))
    runner = PipelineRunner()

    report = pipeline.run(cfg, tmp_path / "work", repo_root, runner)
    assert report.providers["deepseek"].prs
    push_cmds = [c for c in runner.calls if c[0][0] == "git" and c[0][1] == "push"]
    assert push_cmds and push_cmds[-1][0] == ["git", "push", "origin", "HEAD:refs/heads/main"]


def test_state_commit_sets_identity_when_missing(
    tmp_path, fake_modules, upstream, repo_root, wire, fake_open_pr
):
    git(repo_root, "config", "--unset", "user.name")
    git(repo_root, "config", "--unset", "user.email")
    detect, scrape = fake_modules
    detect["deepseek"] = ["deepseek-chat"]
    scrape["deepseek"] = {"deepseek-chat": pricing()}
    cfg = make_cfg(upstream(), 3, ("deepseek",))
    runner = PipelineRunner()

    report = pipeline.run(cfg, tmp_path / "work", repo_root, runner)
    assert report.providers["deepseek"].prs
    assert (
        git(repo_root, "log", "--format=%an <%ae>", "-1").strip()
        == "octocat <octocat@users.noreply.github.com>"
    )

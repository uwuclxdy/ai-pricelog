from pathlib import Path

import pytest

from autopr_genai_prices import build, pr
from conftest import git, git_init_repo

TEST_CALC_HEAD = "from decimal import Decimal\n\nfrom genai_prices import Usage, calc_price\n"

VENDOR_ENTRY = (
    "  - id: deepseek-v4-pro\n"
    "    name: deepseek-v4-pro\n"
    "    match:\n"
    "      starts_with: deepseek-v4-pro\n"
    '    prices_checked: "2026-08-19"\n'
    '    price_comments: "Ref: https://example.com/pricing"\n'
    "    prices:\n"
    "      input_mtok: 0.27\n"
    "      output_mtok: 1.1\n"
)

OR_ENTRY = (
    "  - id: deepseek/deepseek-v4-pro\n"
    "    name: DeepSeek V4 Pro\n"
    "    match:\n"
    "      equals: deepseek/deepseek-v4-pro\n"
    "    prices:\n"
    "      input_mtok: 0.27\n"
    "      output_mtok: 1.1\n"
)

CALC_OK = (
    '{"ok": true, "provider_id": "deepseek", "model_id": "deepseek-v4-pro", '
    '"input_price": "0.0027", "output_price": "0.0011", "total_price": "0.00281"}'
)

GENERATED_TEST = """def test_deepseek_deepseek_v4_pro_price() -> None:
    from datetime import datetime, timezone

    price = calc_price(
        Usage(input_tokens=1_000, output_tokens=100),
        model_ref='deepseek-v4-pro',
        genai_request_timestamp=datetime(2025, 6, 1, 12, tzinfo=timezone.utc),
    )

    assert price.provider.id == 'deepseek'
    assert price.model.id == 'deepseek-v4-pro'
    assert price.input_price == Decimal('0.0027')
    assert price.output_price == Decimal('0.0011')
    assert price.total_price == Decimal('0.00281')
"""


class BuildRunner:
    """scripted non-git commands, real git subprocesses (local, offline)."""

    def __init__(self) -> None:
        self.real = pr.PrRunner()
        self.calls: list[tuple[list[str], Path]] = []
        self._outputs: dict[str, str] = {}
        self._failures: dict[str, Exception] = {}
        self._effects: dict[str, object] = {}

    def on(self, pattern, output="", failure=None, effect=None):
        if failure is not None:
            self._failures[pattern] = failure
        elif effect is not None:
            self._effects[pattern] = effect
        else:
            self._outputs[pattern] = output
        return self

    def run(self, cmd: list[str], cwd: Path) -> str:
        self.calls.append((cmd, cwd))
        if cmd[0] == "git":
            return self.real.run(cmd, cwd)
        key = " ".join(cmd)
        for pattern, failure in self._failures.items():
            if pattern in key:
                raise failure
        for pattern, effect in self._effects.items():
            if pattern in key:
                result = effect(key)
                if isinstance(result, Exception):
                    raise result
                return result or ""
        for pattern, output in self._outputs.items():
            if pattern in key:
                return output
        raise AssertionError(f"unscripted command: {key}")


def seed_slot(tmp_path: Path) -> Path:
    src = tmp_path / "clone"
    git_init_repo(src)
    providers = src / "prices" / "providers"
    providers.mkdir(parents=True)
    (providers / "deepseek.yml").write_text(
        "id: deepseek\n"
        "name: Deepseek\n"
        "api_pattern: 'https://api\\.deepseek\\.com'\n"
        "models:\n"
        "  - id: deepseek-chat\n"
        "    match:\n"
        "      starts_with: deepseek-chat\n"
    )
    (providers / "openrouter.yml").write_text("id: openrouter\nname: OpenRouter\nmodels: []\n")
    for rel, content in [
        ("prices/new_data/v2/data.json", "{}\n"),
        ("prices/new_data/v2/data_slim.json", "{}\n"),
        ("packages/python/genai_prices/data.py", "# data\n"),
        ("packages/js/src/data.ts", "// data\n"),
        ("tests/test_price_calc.py", TEST_CALC_HEAD),
        ("tests/test_cli.py", "# cli\n"),
        ("tests/dataset/usages.json", "{}\n"),
        ("README.md", "# readme\n"),
    ]:
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(src, "add", ".")
    git(src, "commit", "-m", "seed")
    return src


def spec(**overrides) -> pr.PrSpec:
    values = dict(
        key="deepseek",
        model_id="deepseek-v4-pro",
        entry_id="deepseek-v4-pro",
        vendor_yml="deepseek.yml",
        vendor_name="Deepseek",
        vendor_entry=VENDOR_ENTRY,
        vendor_input_mtok=0.27,
        vendor_output_mtok=1.1,
        vendor_peak_input_mtok=None,
        vendor_peak_output_mtok=None,
        vendor_peak_windows=(),
        skipped_latest=(),
        source_url="https://example.com/pricing",
        openrouter_entry=OR_ENTRY,
        openrouter_slug="deepseek/deepseek-v4-pro",
        openrouter_input_mtok=0.27,
        openrouter_output_mtok=1.1,
        openrouter_cache_read_mtok=None,
        openrouter_note="",
    )
    values.update(overrides)
    return pr.PrSpec(**values)


def quiet_runner() -> BuildRunner:
    return (
        BuildRunner()
        .on("uv sync", output="")
        .on("npm ci", output="")
        .on("make build", output="")
        .on("uv run python", output=CALC_OK)
        .on("uv run pytest", output="")
        .on("make test", output="")
        .on("uvx pre-commit", output="")
    )


def test_prepare_commits_entries_on_branch(tmp_path):
    slot = seed_slot(tmp_path)
    runner = quiet_runner()
    build.prepare(slot, "main", spec(), runner)

    assert git(slot, "branch", "--show-current").strip() == "autopr/deepseek/deepseek-v4-pro"
    assert git(slot, "log", "--format=%s", "-1").strip() == (
        "Add deepseek-v4-pro pricing for Deepseek and OpenRouter"
    )
    vendor = git(slot, "show", "HEAD:prices/providers/deepseek.yml")
    assert "  - id: deepseek-chat" in vendor
    assert "  - id: deepseek-v4-pro" in vendor
    assert vendor.index("deepseek-chat") < vendor.index("deepseek-v4-pro")
    openrouter = git(slot, "show", "HEAD:prices/providers/openrouter.yml")
    assert "  - id: deepseek/deepseek-v4-pro" in openrouter
    assert git(slot, "status", "--porcelain").strip() == ""


def test_stage_paths_cover_the_targets_generated_files():
    assert {
        "prices/providers/openrouter.yml",
        "prices/new_data/v2/data.json",
        "prices/new_data/v2/data_slim.json",
        "prices/providers/.schema.json",
        "prices/new_data/v2/data.schema.json",
        "prices/new_data/v2/data_slim.schema.json",
        "packages/python/genai_prices/data.py",
        "packages/python/genai_prices/data_units.py",
        "packages/js/src/data.ts",
        "packages/js/src/dataUnits.ts",
        "README.md",
        "tests/test_price_calc.py",
        "tests/test_cli.py",
        "tests/dataset/usages.json",
    } == build._STAGE_PATHS


def test_prepare_runs_npm_ci_before_make_build(tmp_path):
    slot = seed_slot(tmp_path)
    runner = quiet_runner()
    build.prepare(slot, "main", spec(), runner)

    cmds = [" ".join(cmd) for cmd, _cwd in runner.calls]
    assert "npm ci" in cmds
    assert cmds.index("npm ci") < cmds.index("make build")
    assert "npm install --no-package-lock" not in cmds


def test_prepare_falls_back_to_npm_install_when_ci_refuses(tmp_path):
    slot = seed_slot(tmp_path)
    runner = (
        quiet_runner()
        .on("npm ci", failure=pr.PrError("frozen lockfile", stderr="lockfile had changes"))
        .on("npm install --no-package-lock", output="")
    )
    build.prepare(slot, "main", spec(), runner)

    cmds = [" ".join(cmd) for cmd, _cwd in runner.calls]
    assert "npm ci" in cmds
    assert "npm install --no-package-lock" in cmds
    assert cmds.index("npm ci") < cmds.index("npm install --no-package-lock")


def test_prepare_sorts_the_vendor_insert_by_entry_id(tmp_path):
    slot = seed_slot(tmp_path)
    build._insert_entries(
        slot,
        spec(
            model_id="zzz-page",
            entry_id="aaa-entry",
            vendor_entry=VENDOR_ENTRY.replace("  - id: deepseek-v4-pro", "  - id: aaa-entry"),
        ),
    )
    vendor = (slot / "prices" / "providers" / "deepseek.yml").read_text()
    assert vendor.index("  - id: aaa-entry") < vendor.index("  - id: deepseek-chat")


def test_generate_test_probes_the_entry_id(tmp_path):
    slot = seed_slot(tmp_path)
    build._insert_entries(
        slot,
        spec(
            model_id="zzz-page",
            entry_id="aaa-entry",
            vendor_entry=VENDOR_ENTRY.replace("  - id: deepseek-v4-pro", "  - id: aaa-entry"),
        ),
    )
    seen: list[str] = []

    def calc_effect(key: str) -> str:
        seen.append(key)
        return CALC_OK

    runner = quiet_runner().on("uv run python", effect=calc_effect)
    build._generate_test(slot, spec(model_id="zzz-page", entry_id="aaa-entry"), runner)

    (key,) = seen
    assert "aaa-entry 12" in key
    assert "zzz-page" not in key


def test_build_error_tail_falls_back_to_stdout():
    exc = pr.PrError("boom", stderr="", stdout="inject-providers failed")
    assert "inject-providers failed" in build._tail(exc)


def test_prepare_removes_the_bun_shim_lock(tmp_path):
    slot = seed_slot(tmp_path)

    def npm_effect(_key: str) -> str:
        # a bun-shimmed npm leaves its own lock behind; it must never reach
        # the commit
        (slot / "bun.lock").write_text("lock\n")
        return ""

    runner = quiet_runner().on("npm ci", effect=npm_effect)
    build.prepare(slot, "main", spec(), runner)

    assert not (slot / "bun.lock").exists()
    assert git(slot, "status", "--porcelain").strip() == ""


def test_make_test_failure_fixes_cli_snapshot_then_reruns(tmp_path):
    slot = seed_slot(tmp_path)
    calls = {"make_test": 0}

    def make_effect(_key: str) -> str:
        calls["make_test"] += 1
        if calls["make_test"] == 1:
            raise pr.PrError("make: boom", stderr="boom")
        return ""

    def fix_effect(_key: str) -> str:
        # the fix pass rewrites the drifted snapshot; real git then sees it dirty
        path = slot / "tests" / "test_cli.py"
        path.write_text(path.read_text() + "# snapshot fixed\n")
        return ""

    runner = (
        quiet_runner()
        .on("make test", effect=make_effect)
        .on("uv run pytest tests/test_cli.py", effect=fix_effect)
    )
    build.prepare(slot, "main", spec(), runner)

    cmds = [" ".join(cmd) for cmd, _cwd in runner.calls]
    first = cmds.index("make test")
    fix = cmds.index("uv run pytest tests/test_cli.py --inline-snapshot=fix")
    rerun = [i for i, c in enumerate(cmds) if c == "make test" and i > first][0]
    assert first < fix < rerun
    committed = git(slot, "show", "HEAD:tests/test_cli.py")
    assert "# snapshot fixed" in committed


def test_offpeak_hour_skips_peak_windows():
    windows = (("01:00:00Z", "04:00:00Z"), ("06:00:00Z", "10:00:00Z"))
    assert build._offpeak_hour(windows) == 0
    assert build._offpeak_hour(()) == 12
    assert build._offpeak_hour((("16:30:00Z", "00:30:00Z"),)) == 1


def test_prepare_resets_a_dirty_tree_left_by_a_failed_candidate(tmp_path):
    slot = seed_slot(tmp_path)
    failing = quiet_runner().on("make build", failure=build.BuildError("make build failed"))
    with pytest.raises(build.BuildError):
        build.prepare(slot, "main", spec(), runner=failing)
    # the failed candidate's own edits stay uncommitted in the shared slot;
    # the next candidate's prepare must start from a clean base, not inherit
    second = quiet_runner()
    build.prepare(slot, "main", spec(), runner=second)
    vendor = git(slot, "show", "HEAD:prices/providers/deepseek.yml")
    assert vendor.count("  - id: deepseek-v4-pro") == 1
    openrouter = git(slot, "show", "HEAD:prices/providers/openrouter.yml")
    assert openrouter.count("  - id: deepseek/deepseek-v4-pro") == 1
    assert not (tmp_path / ".autopr_calc.py").exists()

    cmds = [" ".join(cmd) for cmd, _cwd in second.calls]
    assert any(c.startswith("uv sync --frozen --all-packages --all-extras") for c in cmds)
    assert "make build" in cmds
    assert "make test" in cmds
    # make build is faked here, so only the hand-edited files plus the kept
    # generated test show as changed
    changed = {
        "prices/providers/deepseek.yml",
        "prices/providers/openrouter.yml",
        "tests/test_price_calc.py",
    }
    add = next(cmd for cmd, _cwd in second.calls if cmd[:2] == ["git", "add"])
    assert add[:2] == ["git", "add"] and add[2] == "--"
    assert set(add[3:]) == changed
    precommit = next(cmd for cmd, _cwd in second.calls if cmd[0] == "uvx")
    assert precommit[:4] == ["uvx", "pre-commit", "run", "--files"]
    assert set(precommit[4:]) == changed


def test_generated_test_is_inlined_and_kept(tmp_path):
    slot = seed_slot(tmp_path)
    runner = quiet_runner()
    build.prepare(slot, "main", spec(), runner)

    content = git(slot, "show", "HEAD:tests/test_price_calc.py")
    assert GENERATED_TEST in content
    pytest_calls = [cmd for cmd, _cwd in runner.calls if cmd[0:3] == ["uv", "run", "pytest"]]
    assert len(pytest_calls) == 1
    assert pytest_calls[0][-2:] == ["-k", "test_deepseek_deepseek_v4_pro_price"]


def test_generated_test_red_is_deleted(tmp_path):
    slot = seed_slot(tmp_path)
    runner = quiet_runner().on("uv run pytest", failure=pr.PrError("1 failed"))
    build.prepare(slot, "main", spec(), runner)

    assert git(slot, "show", "HEAD:tests/test_price_calc.py") == TEST_CALC_HEAD
    assert (slot / "tests" / "test_price_calc.py").read_text() == TEST_CALC_HEAD


def test_calc_unresolved_ships_without_test(tmp_path):
    slot = seed_slot(tmp_path)
    runner = quiet_runner().on(
        "uv run python", output='{"ok": false, "error": "LookupError: no model"}'
    )
    build.prepare(slot, "main", spec(), runner)

    assert git(slot, "show", "HEAD:tests/test_price_calc.py") == TEST_CALC_HEAD
    calc_calls = [cmd for cmd, _cwd in runner.calls if cmd[0:3] == ["uv", "run", "python"]]
    assert len(calc_calls) == 2  # bare ref, then the api url retry
    assert calc_calls[1][-2] == "https://api.deepseek.com"
    assert calc_calls[1][-1] == "2025-06-01"


def test_calc_other_error_skips_retry(tmp_path):
    slot = seed_slot(tmp_path)
    runner = quiet_runner().on(
        "uv run python", output='{"ok": false, "error": "ValueError: bad usage"}'
    )
    build.prepare(slot, "main", spec(), runner)

    calc_calls = [cmd for cmd, _cwd in runner.calls if cmd[0:3] == ["uv", "run", "python"]]
    assert len(calc_calls) == 1
    assert git(slot, "show", "HEAD:tests/test_price_calc.py") == TEST_CALC_HEAD


def test_calc_wrong_provider_retries_with_api_url(tmp_path):
    slot = seed_slot(tmp_path)
    calls = {"count": 0}
    wrong = '{"ok": true, "provider_id": "zhipuai", "model_id": "glm-5.2", ' + (
        '"input_price": "0.01", "output_price": "0.02", "total_price": "0.03"}'
    )

    def calc_effect(_key: str) -> str:
        calls["count"] += 1
        return wrong if calls["count"] == 1 else CALC_OK

    runner = quiet_runner().on("uv run python", effect=calc_effect)
    build.prepare(slot, "main", spec(), runner)

    calc_cmds = [cmd for cmd, _cwd in runner.calls if cmd[0:3] == ["uv", "run", "python"]]
    assert len(calc_cmds) == 2
    # tail args: api_url (empty on the bare first attempt) and the pin day
    assert calc_cmds[0][-2] == ""
    assert calc_cmds[1][-2] == "https://api.deepseek.com"
    assert calc_cmds[1][-1] == "2025-06-01"
    content = git(slot, "show", "HEAD:tests/test_price_calc.py")
    assert "provider_api_url='https://api.deepseek.com'," in content


def test_wrong_provider_without_api_pattern_ships_without_test(tmp_path):
    slot = seed_slot(tmp_path)
    vendor_path = slot / "prices" / "providers" / "deepseek.yml"
    vendor_path.write_text(
        "id: deepseek\nname: Deepseek\nmodels:\n  - id: deepseek-chat\n    match:\n"
        "      starts_with: deepseek-chat\n"
    )
    git(slot, "add", "prices/providers/deepseek.yml")
    git(slot, "commit", "-m", "drop api pattern")
    runner = quiet_runner().on(
        "uv run python",
        output='{"ok": true, "provider_id": "zhipuai", "model_id": "glm-5.2", '
        '"input_price": "0.01", "output_price": "0.02", "total_price": "0.03"}',
    )
    build.prepare(slot, "main", spec(), runner)
    calc_calls = [cmd for cmd, _cwd in runner.calls if cmd[0:3] == ["uv", "run", "python"]]
    assert len(calc_calls) == 1
    assert git(slot, "show", "HEAD:tests/test_price_calc.py") == TEST_CALC_HEAD


def test_make_build_failure_raises_and_commits_nothing(tmp_path):
    slot = seed_slot(tmp_path)
    runner = quiet_runner().on("make build", failure=pr.PrError("make: boom", stderr="boom"))
    with pytest.raises(build.BuildError, match="make build failed"):
        build.prepare(slot, "main", spec(), runner)
    assert [line.split() for line in git(slot, "log", "--format=%s").splitlines()] == [["seed"]]


def test_make_test_rewrites_usages_then_reruns_green(tmp_path):
    slot = seed_slot(tmp_path)
    calls = {"count": 0}

    def make_test_effect(_key: str) -> Exception | str:
        calls["count"] += 1
        if calls["count"] == 1:
            (slot / "tests" / "dataset" / "usages.json").write_text('{"rewritten": true}\n')
            return pr.PrError("make test: exit 1", stderr="usages rewritten")
        return ""

    runner = quiet_runner().on("make test", effect=make_test_effect)
    build.prepare(slot, "main", spec(), runner)

    assert calls["count"] == 2
    usages = git(slot, "show", "HEAD:tests/dataset/usages.json")
    assert "rewritten" in usages
    add = next(cmd for cmd, _cwd in runner.calls if cmd[:2] == ["git", "add"])
    assert "tests/dataset/usages.json" in add


def test_make_test_failure_without_usages_change_is_real(tmp_path):
    slot = seed_slot(tmp_path)
    runner = quiet_runner().on("make test", failure=pr.PrError("1 failed", stderr="1 failed"))
    with pytest.raises(build.BuildError, match="make test failed"):
        build.prepare(slot, "main", spec(), runner)
    assert [line.split() for line in git(slot, "log", "--format=%s").splitlines()] == [["seed"]]


def test_make_test_rerun_failure_raises(tmp_path):
    slot = seed_slot(tmp_path)
    calls = {"count": 0}

    def make_test_effect(_key: str) -> Exception:
        calls["count"] += 1
        if calls["count"] == 1:
            (slot / "tests" / "dataset" / "usages.json").write_text('{"rewritten": true}\n')
        return pr.PrError("make test: boom", stderr="boom")

    runner = quiet_runner().on("make test", effect=make_test_effect)
    with pytest.raises(build.BuildError, match="failed on the rerun"):
        build.prepare(slot, "main", spec(), runner)


def test_unexpected_modified_file_fails_naming_it(tmp_path):
    slot = seed_slot(tmp_path)
    runner = quiet_runner().on(
        "make test", effect=lambda _key: (slot / "stray.txt").write_text("x") or ""
    )
    with pytest.raises(build.BuildError, match="stray.txt"):
        build.prepare(slot, "main", spec(), runner)


def test_precommit_fix_reruns_once_then_green(tmp_path):
    slot = seed_slot(tmp_path)
    calls = {"count": 0}

    def precommit_effect(_key: str) -> Exception | str:
        calls["count"] += 1
        if calls["count"] == 1:
            return pr.PrError("fixed files", stderr="fixes applied")
        return ""

    runner = quiet_runner().on("uvx pre-commit", effect=precommit_effect)
    build.prepare(slot, "main", spec(), runner)
    assert calls["count"] == 2


def test_precommit_failure_twice_raises(tmp_path):
    slot = seed_slot(tmp_path)
    runner = quiet_runner().on("uvx pre-commit", failure=pr.PrError("hook boom", stderr="boom"))
    with pytest.raises(build.BuildError, match="pre-commit failed"):
        build.prepare(slot, "main", spec(), runner)


def test_deferred_openrouter_leaves_yml_untouched(tmp_path):
    slot = seed_slot(tmp_path)
    runner = quiet_runner()
    build.prepare(slot, "main", spec(openrouter_entry=None), runner)
    assert git(slot, "show", "HEAD:prices/providers/openrouter.yml") == (
        "id: openrouter\nname: OpenRouter\nmodels: []\n"
    )
    add = next(cmd for cmd, _cwd in runner.calls if cmd[:2] == ["git", "add"])
    assert "prices/providers/openrouter.yml" not in add


def test_second_candidate_starts_from_base(tmp_path):
    slot = seed_slot(tmp_path)
    runner = quiet_runner()
    build.prepare(slot, "main", spec(), runner)
    build.prepare(
        slot,
        "main",
        spec(
            model_id="deepseek-v4-flash",
            vendor_entry="  - id: deepseek-v4-flash\n",
            openrouter_entry=None,
            openrouter_note="absent",
        ),
        runner,
    )
    vendor = git(slot, "show", "HEAD:prices/providers/deepseek.yml")
    assert "deepseek-v4-pro" not in vendor
    assert "deepseek-v4-flash" in vendor
    openrouter = git(slot, "show", "HEAD:prices/providers/openrouter.yml")
    assert "deepseek/deepseek-v4-pro" not in openrouter


def test_commit_bypasses_global_hooks(tmp_path, monkeypatch):
    # reproduce the production failure: the operator's global hooksPath points
    # at a hook that rejects every commit; the clone's commit must bypass it
    slot = seed_slot(tmp_path)
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "commit-msg").write_text("#!/bin/sh\nexit 1\n")
    (hooks / "commit-msg").chmod(0o755)
    global_cfg = tmp_path / "global.gitconfig"
    global_cfg.write_text(f"[core]\n\thooksPath = {hooks}\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_cfg))
    # sanity: a plain commit under the poisoned config does fail
    probe = tmp_path / "probe"
    git_init_repo(probe)
    (probe / "f").write_text("x")
    git(probe, "add", "f")
    with pytest.raises(pr.PrError):
        git(probe, "commit", "-m", "seed")
    runner = quiet_runner()
    build.prepare(slot, "main", spec(), runner)
    assert git(slot, "log", "--format=%s", "-1").strip() == (
        "Add deepseek-v4-pro pricing for Deepseek and OpenRouter"
    )


def update_spec(**overrides) -> pr.UpdateSpec:
    values = dict(
        model_id="deepseek-chat",
        case="rate_change",
        prices_section=(
            "    prices:\n"
            "      - prices:\n"
            "          input_mtok: 0.2\n"
            "          output_mtok: 0.4\n"
            "      - constraint:\n"
            "          # rate change\n"
            "          start_date: 2026-08-24\n"
            "        prices:\n"
            "          input_mtok: 0.27\n"
            "          output_mtok: 1.1\n"
        ),
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
        or_note="not listed on the api",
    )
    values.update(overrides)
    return pr.UpdateSpec(**values)


OLD_TEST = """def test_deepseek_deepseek_chat_price() -> None:
    from datetime import datetime, timezone

    price = calc_price(
        Usage(input_tokens=1_000, output_tokens=100),
        model_ref='deepseek-chat',
        genai_request_timestamp=datetime(2025, 6, 1, 12, tzinfo=timezone.utc),
    )

    assert price.provider.id == 'deepseek'
    assert price.model.id == 'deepseek-chat'
    assert price.input_price == Decimal('0.002')
    assert price.output_price == Decimal('0.004')
    assert price.total_price == Decimal('0.0024')
"""

OLD_CALC = (
    '{"ok": true, "provider_id": "deepseek", "model_id": "deepseek-chat", '
    '"input_price": "0.002", "output_price": "0.004", "total_price": "0.0024"}'
)
NEW_CALC = (
    '{"ok": true, "provider_id": "deepseek", "model_id": "deepseek-chat", '
    '"input_price": "0.0027", "output_price": "0.011", "total_price": "0.00281"}'
)


def seed_slot_priced(tmp_path: Path) -> Path:
    slot = seed_slot(tmp_path)
    providers = slot / "prices" / "providers"
    (providers / "deepseek.yml").write_text(
        "id: deepseek\n"
        "name: Deepseek\n"
        "api_pattern: 'https://api\\.deepseek\\.com'\n"
        "models:\n"
        "  - id: deepseek-chat\n"
        "    match:\n"
        "      starts_with: deepseek-chat\n"
        '    prices_checked: "2026-08-19"\n'
        "    prices:\n"
        "      input_mtok: 0.2\n"
        "      output_mtok: 0.4\n"
    )
    (providers / "openrouter.yml").write_text(
        "id: openrouter\n"
        "name: OpenRouter\n"
        "models:\n"
        "  - id: deepseek/deepseek-chat\n"
        "    match:\n"
        "      equals: deepseek/deepseek-chat\n"
        "    prices:\n"
        "      input_mtok: 0.2\n"
        "      cache_read_mtok: 0.02\n"
        "      output_mtok: 0.4\n"
    )
    tests = slot / "tests" / "test_price_calc.py"
    tests.write_text(TEST_CALC_HEAD + "\n" + OLD_TEST)
    git(slot, "add", "prices/providers/deepseek.yml", "prices/providers/openrouter.yml")
    git(slot, "add", "tests/test_price_calc.py")
    git(slot, "commit", "-m", "priced seed")
    return slot


def test_replace_test_function_swaps_the_whole_function():
    text = TEST_CALC_HEAD + "\n" + OLD_TEST + "\n" + "def test_other() -> None:\n    assert True\n"
    rendered = "def test_deepseek_deepseek_chat_price() -> None:\n    ...\n"
    result = build._replace_test_function(text, "deepseek-chat", rendered)
    assert result is not None
    assert "    from datetime import datetime, timezone" not in result
    assert "test_other" in result
    assert result.endswith("def test_other() -> None:\n    assert True\n")


def test_replace_test_function_handles_double_quoted_model_ref():
    text = (
        TEST_CALC_HEAD
        + "\ndef test_x() -> None:\n"
        + '    price = calc_price(Usage(), model_ref="deepseek-chat", '
        + "genai_request_timestamp=None)\n"
    )
    result = build._replace_test_function(text, "deepseek-chat", "def test_x() -> None:\n    ...\n")
    assert result == TEST_CALC_HEAD + "\ndef test_x() -> None:\n    ...\n"


def test_replace_test_function_missing_returns_none():
    assert (
        build._replace_test_function(TEST_CALC_HEAD + "\n" + OLD_TEST, "other-model", "x") is None
    )


def test_prepare_update_rate_change_pins_both_sides(tmp_path):
    slot = seed_slot_priced(tmp_path)

    def calc_effect(key: str) -> str:
        return OLD_CALC if "2026-08-23" in key else NEW_CALC

    runner = quiet_runner().on("uv run python", effect=calc_effect)
    build.prepare(slot, "main", spec(update=update_spec(), entry_id="deepseek-chat"), runner)

    content = git(slot, "show", "HEAD:tests/test_price_calc.py")
    assert content.count("def ") == 1
    assert "price_before = calc_price(" in content
    assert "datetime(2026, 8, 23, 12, tzinfo=timezone.utc)" in content
    assert "price_after = calc_price(" in content
    assert "datetime(2026, 8, 24, 12, tzinfo=timezone.utc)" in content
    assert "Decimal('0.002')" in content  # the day before: old rates
    assert "Decimal('0.0027')" in content  # the day of: new rates
    assert "2025, 6, 1" not in content  # the old pin is gone
    vendor = git(slot, "show", "HEAD:prices/providers/deepseek.yml")
    assert "      - prices:\n          input_mtok: 0.2" in vendor
    assert "          start_date: 2026-08-24" in vendor
    assert '    prices_checked: "2026-08-24"' in vendor


def test_prepare_update_conversion_pins_offpeak_hour(tmp_path):
    slot = seed_slot_priced(tmp_path)
    converted = update_spec(
        case="conversion",
        peak_input_mtok=0.4,
        peak_output_mtok=0.8,
        peak_windows=(("01:00:00Z", "04:00:00Z"),),
    )
    runner = quiet_runner()
    build.prepare(slot, "main", spec(update=converted, entry_id="deepseek-chat"), runner)

    content = git(slot, "show", "HEAD:tests/test_price_calc.py")
    assert content.count("def ") == 1
    assert "price_before" not in content
    # hour 0 is the first off-peak hour outside the 01:00-04:00 window
    assert "datetime(2025, 6, 1, 0, tzinfo=timezone.utc)" in content


def test_prepare_update_mirrors_openrouter_entry(tmp_path):
    slot = seed_slot_priced(tmp_path)
    mirrored = update_spec(
        or_prices_section=(
            "    prices:\n"
            "      - prices:\n"
            "          input_mtok: 0.2\n"
            "          cache_read_mtok: 0.02\n"
            "          output_mtok: 0.4\n"
            "      - constraint:\n"
            "          # rate change\n"
            "          start_date: 2026-08-24\n"
            "        prices:\n"
            "          input_mtok: 0.27\n"
            "          cache_read_mtok: 0.02\n"
            "          output_mtok: 1.1\n"
        )
    )
    runner = quiet_runner()
    build.prepare(
        slot,
        "main",
        spec(update=mirrored, entry_id="deepseek-chat", openrouter_slug="deepseek/deepseek-chat"),
        runner,
    )

    openrouter = git(slot, "show", "HEAD:prices/providers/openrouter.yml")
    assert "      - prices:\n          input_mtok: 0.2" in openrouter
    assert "          start_date: 2026-08-24" in openrouter
    assert "          input_mtok: 0.27" in openrouter
    assert '    prices_checked: "2026-08-24"' in openrouter


def test_offpeak_hour_excludes_partial_hour_end():
    # 16:00-16:30 is inside the window: hour 16 must not be picked
    assert build._offpeak_hour((("00:30:00Z", "16:30:00Z"),)) == 17


def test_replace_test_function_keeps_neighbour_decorators():
    text = (
        TEST_CALC_HEAD
        + "\n"
        + OLD_TEST
        + "\n"
        + "@pytest.mark.parametrize('x', [1])\n"
        + "def test_next() -> None:\n"
        + "    assert True\n"
    )
    rendered = "def test_deepseek_deepseek_chat_price() -> None:\n    ...\n"
    result = build._replace_test_function(text, "deepseek-chat", rendered)
    assert result is not None
    assert "@pytest.mark.parametrize('x', [1])" in result
    assert "def test_next() -> None:" in result

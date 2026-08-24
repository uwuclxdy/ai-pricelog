import sys
import types
from pathlib import Path

import pytest

from autopr_genai_prices.pr import PrRunner


class FakeRunner:
    """Scripted PrRunner: routes commands by substring, returns scripted stdout or raises."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path]] = []
        self._outputs: dict[str, str] = {}
        self._failures: dict[str, Exception] = {}

    def on(self, pattern: str, output: str = "", failure: Exception | None = None) -> "FakeRunner":
        if failure is not None:
            self._failures[pattern] = failure
        else:
            self._outputs[pattern] = output
        return self

    def run(self, cmd: list[str], cwd: Path) -> str:
        self.calls.append((cmd, cwd))
        key = " ".join(cmd)
        for pattern, failure in self._failures.items():
            if pattern in key:
                raise failure
        for pattern, output in self._outputs.items():
            if pattern in key:
                return output
        raise AssertionError(f"unscripted command: {key}")


@pytest.fixture(autouse=True)
def isolated_git_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # keep tests hermetic: git subprocesses must not read the developer's global config
    (tmp_path / "global.gitconfig").touch()
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "global.gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    # identity env outranks git config; the global pre-commit hook runs this
    # suite while git exports the in-flight commit's GIT_AUTHOR_*/GIT_COMMITTER_*
    # vars, and identity tests read them through the config seam
    for name in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_AUTHOR_DATE",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "GIT_COMMITTER_DATE",
    ):
        monkeypatch.delenv(name, raising=False)


def git(cwd: Path, *args: str) -> str:
    return PrRunner().run(["git", *args], cwd=cwd)


def git_init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.com")


def register_fake_module(monkeypatch: pytest.MonkeyPatch, kind: str, name: str) -> types.ModuleType:
    pkg = types.ModuleType(f"autopr_genai_prices.{kind}")
    monkeypatch.setitem(sys.modules, f"autopr_genai_prices.{kind}", pkg)
    module = types.ModuleType(f"autopr_genai_prices.{kind}.{name}")
    monkeypatch.setitem(sys.modules, f"autopr_genai_prices.{kind}.{name}", module)
    return module

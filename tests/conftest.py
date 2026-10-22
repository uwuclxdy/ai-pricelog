from __future__ import annotations

import os
import sys
import types
from collections.abc import Generator
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.pr import PrRunner

# `-n auto` otherwise resolves to every CPU the process may run on, and every concurrent
# caller (a commit hook, a spawned agent, a second session) multiplies it into the same memory.
_AUTO_WORKER_CAP = 4


# `optionalhook` because the hookspec is xdist's: a run with the plugin off must still load.
@pytest.hookimpl(wrapper=True, optionalhook=True)
def pytest_xdist_auto_num_workers(config: pytest.Config) -> Generator[None, int, int]:
    """Caps xdist's own `-n auto` (or `-n logical`) answer, unless the caller named a count.

    xdist returns `PYTEST_XDIST_AUTO_NUM_WORKERS` when it parses as an integer, so a count
    that parses is the caller's and passes through; anything else was detected off the box.
    """
    count = yield
    try:
        int(os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS", ""))
    except ValueError:
        return min(_AUTO_WORKER_CAP, count)
    return count


class FakeRunner:
    """Scripted PrRunner: routes commands by substring, returns scripted stdout or raises."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path]] = []
        self._outputs: dict[str, str] = {}
        self._failures: dict[str, Exception] = {}

    def on(self, pattern: str, output: str = "", failure: Exception | None = None) -> FakeRunner:
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
    # keep tests hermetic: git subprocesses must not read the developer's
    # global config, and no leaked git env may retarget them. the global
    # pre-commit hook runs this suite while git exports the in-flight
    # commit's identity vars, and a commit from a linked worktree exports
    # absolute GIT_DIR/GIT_INDEX_FILE; both classes must be scrubbed
    (tmp_path / "global.gitconfig").touch()
    for name in list(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "global.gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    # a developer's global git hooks can run for every repo regardless of
    # core.hooksPath and rewrite a commit message (observed: a synthetic
    # Co-Authored-By subject stored empty, redding the newline-escape
    # sanitizer test); redirect HOME so no global hook or state file can
    # reach the tests
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def git(cwd: Path, *args: str) -> str:
    return PrRunner().run(["git", *args], cwd=cwd)


def git_init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.com")
    # a developer's git template can install hooks into every fresh repo
    # (a pre-commit gate, a commit-msg lint, a post-commit that rewrites
    # messages); test commits must not run them (observed: such a post-commit
    # emptied a synthetic one-line Co-Authored-By subject, redding the
    # newline-escape sanitizer test)
    (path / "no-hooks").mkdir(exist_ok=True)
    git(path, "config", "core.hooksPath", str(path / "no-hooks"))


def move_last_row_to_second_tbody(soup: BeautifulSoup) -> int:
    """Move each table's last <td> row into a fresh second tbody; return the count.

    the row-selection test's control: a reader that owns only the first tbody
    loses these rows, while the document still nests every row the same way.
    """
    moved = 0
    for table in soup.find_all("table"):
        rows = [
            row
            for row in table.find_all("tr")
            if row.find_parent("table") is table and row.find_all("td", recursive=False)
        ]
        if not rows:
            continue
        tbody = soup.new_tag("tbody")
        table.append(tbody)
        tbody.append(rows[-1].extract())
        moved += 1
    return moved


def register_fake_module(monkeypatch: pytest.MonkeyPatch, kind: str, name: str) -> types.ModuleType:
    pkg = types.ModuleType(f"ai_pricelog.{kind}")
    monkeypatch.setitem(sys.modules, f"ai_pricelog.{kind}", pkg)
    module = types.ModuleType(f"ai_pricelog.{kind}.{name}")
    monkeypatch.setitem(sys.modules, f"ai_pricelog.{kind}.{name}", module)
    return module

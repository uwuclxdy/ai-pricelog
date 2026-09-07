"""the default-branch guard's legs, pinned per input.

the guard protects the two real-tree invariants from by-construction reds
on pipeline data branches; a flipped leg would silently stop them running
where they must (or run them where they cannot hold), so each input class
gets its own assertion.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ai_pricelog import testing
from conftest import git, git_init_repo


@pytest.fixture(autouse=True)
def no_github_env(monkeypatch: pytest.MonkeyPatch):
    # a developer box can carry GITHUB_* exports (gh, a prior CI run);
    # the legs under test resolve them first, so scrub them
    for name in list(__import__("os").environ):
        if name.startswith("GITHUB_"):
            monkeypatch.delenv(name, raising=False)
    testing._resolve.cache_clear()
    yield
    testing._resolve.cache_clear()


def test_pr_event_env_skips(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GITHUB_BASE_REF", "mommy")
    assert not testing.default_branch_test
    assert testing.default_branch_test.skip_reason.startswith("pull_request against mommy")


@pytest.mark.parametrize("event", ["pull_request", "pull_request_target"])
def test_pr_event_name_skips(monkeypatch: pytest.MonkeyPatch, event: str):
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    assert not testing.default_branch_test
    assert testing.default_branch_test.skip_reason.startswith(event)


@pytest.mark.parametrize("event", ["push", "schedule", "workflow_dispatch"])
def test_ci_events_run(monkeypatch: pytest.MonkeyPatch, event: str):
    # ci.yml's push trigger fires only on the default branch, and the
    # scheduled workflows check it out, so any non-PR event is one of those
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    assert testing.default_branch_test


def seeded_repo(tmp_path: Path) -> Path:
    """an initialized repo with one commit, so HEAD resolves."""
    repo = tmp_path / "repo"
    git_init_repo(repo)
    (repo / "seed.txt").write_text("x\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "feat: seed")
    return repo


def test_local_pipeline_branch_skips(tmp_path: Path):
    repo = seeded_repo(tmp_path)
    git(repo, "switch", "-c", "pricelog/openrouter-2026-09-07-121151-sim000000")
    assert not testing._resolve(repo)[0]
    assert "pipeline branch pricelog/" in testing._resolve(repo)[1]


def test_local_detached_skips(tmp_path: Path):
    repo = seeded_repo(tmp_path)
    git(repo, "checkout", "-q", "--detach")
    assert not testing._resolve(repo)[0]
    assert "detached checkout" in testing._resolve(repo)[1]


def test_local_plain_branch_runs(tmp_path: Path):
    repo = seeded_repo(tmp_path)  # main, the default-branch stand-in
    assert testing._resolve(repo)[0]


def test_git_failure_skips_with_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        testing.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(OSError("spawn failed")),
    )
    assert not testing._resolve(tmp_path)[0]
    assert "git rev-parse failed" in testing._resolve(tmp_path)[1]


def test_local_non_utf8_branch_runs(tmp_path: Path):
    # git accepts a non-UTF-8 refname and echoes it as raw bytes; the guard
    # must decode it (errors=replace) and answer "run", because a plain local
    # branch is where the real-tree tests must hold
    repo = seeded_repo(tmp_path)
    subprocess.run(
        ["git", "switch", "-c", b"branch-\xff\xfe"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    verdict, reason = testing._resolve(repo)
    assert verdict is True
    assert _REASON_TAIL in reason


_REASON_TAIL = "until publish refreshes the default branch"

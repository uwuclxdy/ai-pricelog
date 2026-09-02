"""automerge: the pass-side union merge of verified pipeline PR branches."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_pricelog import automerge, pr, store
from ai_pricelog.announce import BILLING_RULES_FILE
from ai_pricelog.pipeline import HISTORY_FILE, INDEX_FILE, README_FILE
from conftest import git, git_init_repo


def make_row(source: str, model_id: str, observed_at: str, input_mtok: float) -> dict:
    return {
        "source": source,
        "model_id": model_id,
        "observed_at": observed_at,
        "input_mtok": input_mtok,
        "output_mtok": input_mtok * 2,
        "url": "https://example.com/pricing",
    }


def build_repo(tmp_path: Path) -> tuple[Path, Path]:
    """A clone with a bare origin: main carries one row and the pipeline files."""
    repo = tmp_path / "repo"
    git_init_repo(repo)
    (repo / "data").mkdir()
    store.save([make_row("deepseek", "deepseek-v4-pro", "2026-08-30", 0.435)], repo / HISTORY_FILE)
    store.write_index(store.load(repo / HISTORY_FILE), repo / INDEX_FILE)
    (repo / README_FILE).write_text(
        "<!-- stats:start -->x<!-- stats:end -->\n<!-- stats-row:start -->x<!-- stats-row:end -->\n"
    )
    (repo / "data" / "announce.json").write_text(json.dumps({}) + "\n")
    (repo / "data" / "absence.json").write_text(json.dumps({}) + "\n")
    (repo / BILLING_RULES_FILE).write_text(json.dumps({"rules": []}) + "\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_billing_rules.py").write_text("# pin placeholder\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "init")
    bare = tmp_path / "origin.git"
    git(repo, "clone", "--bare", str(repo), str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-u", "origin", "main")
    return repo, bare


def make_branch(
    repo: Path,
    name: str,
    rows: list[dict],
    announce: dict | None = None,
    absence: dict | None = None,
    extra_file: str | None = None,
) -> None:
    """Open a pricelog branch off main: append rows, snapshots, push, return to main."""
    git(repo, "switch", "-c", name)
    store.save(store.load(repo / HISTORY_FILE) + rows, repo / HISTORY_FILE)
    store.write_index(store.load(repo / HISTORY_FILE), repo / INDEX_FILE)
    if announce is not None:
        (repo / "data" / "announce.json").write_text(json.dumps(announce) + "\n")
    if absence is not None:
        (repo / "data" / "absence.json").write_text(json.dumps(absence) + "\n")
    if extra_file is not None:
        (repo / extra_file).parent.mkdir(parents=True, exist_ok=True)
        (repo / extra_file).write_text("# changed\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", f"feat: {name}")
    git(repo, "push", "origin", name)
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")


def history_lines(repo: Path) -> list[str]:
    return (repo / HISTORY_FILE).read_text(encoding="utf-8").splitlines()


def test_line_union_appends_only_new_exact_lines():
    head = ["a", "b"]
    branch = ["b", "a", "c", "c"]
    assert automerge._line_union(head, branch) == ["a", "b", "c"]


def test_merge_lands_union_and_regens(tmp_path):
    repo, bare = build_repo(tmp_path)
    r1 = make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.44)
    r2 = make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.45)
    # r2 shares r1's (source, model, observed_at) key: a key-based union
    # would drop it, the exact-line union must keep both
    make_branch(
        repo,
        "pricelog/alpha-00000000",
        [r1, r2],
        announce={"deepseek": {"https://example.com/u": {"text": "new"}}},
    )
    r4 = make_row("deepseek", "deepseek-v4-flash", "2026-08-31", 0.05)
    # beta carries alpha's rows (the pending union) plus its own
    beta_rows = [r1, r2, r4]
    make_branch(
        repo,
        "pricelog/beta-11111111",
        beta_rows,
        announce={"deepseek": {"https://example.com/u": {"text": "newer"}}},
        absence={"deepseek": {"gone": {"absent_runs": 1, "since": "2026-08-31"}}},
    )

    sha, results = automerge.merge_branches(
        ["pricelog/alpha-00000000", "pricelog/beta-11111111"],
        repo,
        pr.PrRunner(),
        "main",
        push=True,
    )

    assert [r.branch for r in results] == ["pricelog/alpha-00000000", "pricelog/beta-11111111"]
    assert [r.appended for r in results] == [2, 1]
    # the union: HEAD's row, alpha's pair (same-day update kept), beta's own row
    expected = history_lines(repo)
    assert len(expected) == 4
    assert r1 in [json.loads(line) for line in expected]
    assert r2 in [json.loads(line) for line in expected]
    assert r4 in [json.loads(line) for line in expected]
    # index regenerated from the union: the same-key tie resolves to the later
    # row in the file, so r2 wins
    index = json.loads((repo / INDEX_FILE).read_text(encoding="utf-8"))
    entry = index["sources"]["deepseek"]["deepseek-v4-pro"]
    assert entry["input_mtok"] == 0.45
    assert index["sources"]["deepseek"]["deepseek-v4-flash"]["input_mtok"] == 0.05
    # README stats regenerated: 2 models, 4 rows
    readme = (repo / README_FILE).read_text(encoding="utf-8")
    assert "| models tracked | **2** |" in readme
    assert "| dated rows | 4 |" in readme
    # the freshest announce/absence snapshots come from the newest branch
    announce = json.loads((repo / "data" / "announce.json").read_text(encoding="utf-8"))
    assert announce["deepseek"]["https://example.com/u"]["text"] == "newer"
    absence = json.loads((repo / "data" / "absence.json").read_text(encoding="utf-8"))
    assert absence == {"deepseek": {"gone": {"absent_runs": 1, "since": "2026-08-31"}}}
    # every merge commit has two parents: the branch heads are ancestors, so
    # github auto-marks the PRs merged
    merge_commits = git(repo, "log", "--merges", "--format=%P").splitlines()
    assert len(merge_commits) == 2
    for line in merge_commits:
        assert len(line.split()) == 2
    # the push landed on the remote and the branch refs are gone
    assert git(repo, "ls-remote", "origin", "main").split()[0] == sha
    refs = git(repo, "ls-remote", "origin").splitlines()
    assert not any("pricelog/" in ref for ref in refs)
    # the merged tree is clean
    assert git(repo, "status", "--porcelain") == ""


def test_seed_branch_refused(tmp_path):
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/seed", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    with pytest.raises(automerge.AutoMergeError, match="human-only"):
        automerge.merge_branches(["pricelog/seed"], repo, pr.PrRunner(), "main", push=False)


def test_non_pipeline_file_refused(tmp_path):
    repo, _bare = build_repo(tmp_path)
    make_branch(
        repo,
        "pricelog/gamma-22222222",
        [make_row("zai", "glm-5", "2026-08-31", 0.1)],
        extra_file="src/ai_pricelog/pipeline.py",
    )
    with pytest.raises(automerge.AutoMergeError, match="pipeline.py"):
        automerge.merge_branches(
            ["pricelog/gamma-22222222"], repo, pr.PrRunner(), "main", push=False
        )


def test_no_push_lands_locally_and_keeps_refs(tmp_path):
    repo, bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/delta-33333333", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    sha, results = automerge.merge_branches(
        ["pricelog/delta-33333333"], repo, pr.PrRunner(), "main", push=False
    )
    assert len(results) == 1
    assert git(repo, "rev-parse", "HEAD").strip() == sha
    refs = git(repo, "ls-remote", "origin").splitlines()
    assert any("pricelog/delta-33333333" in ref for ref in refs)


def test_push_failure_keeps_refs(tmp_path):
    repo, bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/epsilon-44444444", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    with pytest.raises(pr.PrError):
        # an invalid refname makes the push fail; the refs must survive
        automerge.merge_branches(
            ["pricelog/epsilon-44444444"], repo, pr.PrRunner(), "bad~name", push=True
        )
    refs = git(repo, "ls-remote", "origin").splitlines()
    assert any("pricelog/epsilon-44444444" in ref for ref in refs)

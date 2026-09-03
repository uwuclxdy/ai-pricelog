"""automerge: the pass-side union merge of verified pipeline PR branches."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_pricelog import automerge, pr, store, validate
from ai_pricelog.announce import BILLING_RULES_FILE
from conftest import git, git_init_repo

SCHEMA_VERSION = validate.load_schema_keys(Path(__file__).resolve().parents[1]).version


def make_row(source: str, model_id: str, observed_at: str, input_mtok: float) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "source": source,
        "model_id": model_id,
        "observed_at": observed_at,
        "rates": {"input": input_mtok, "output": input_mtok * 2},
        "provenance": {"url": "https://example.com/pricing"},
    }


def build_repo(tmp_path: Path) -> tuple[Path, Path]:
    """A clone with a bare origin: main carries one row and the pipeline files."""
    repo = tmp_path / "repo"
    git_init_repo(repo)
    (repo / "data").mkdir()
    # the merge regenerates the index, and write_index takes the version the
    # committed contract declares
    schema_src = Path(__file__).resolve().parents[1] / "data" / "schema" / "row.v4.json"
    (repo / "data" / "schema").mkdir()
    (repo / "data" / "schema" / "row.v4.json").write_text(
        schema_src.read_text(encoding="utf-8"), encoding="utf-8"
    )
    store.save_shard(
        [make_row("deepseek", "deepseek-v4-pro", "2026-08-30", 0.435)],
        repo / "data" / "history",
        "deepseek",
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
    shard_dir = repo / "data" / "history"
    by_source: dict[str, list[dict]] = {}
    for row in rows:
        by_source.setdefault(row["source"], []).append(row)
    for source, source_rows in by_source.items():
        store.save_shard(store.load_shard(shard_dir, source) + source_rows, shard_dir, source)
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


def shard_lines(repo: Path, source: str = "deepseek") -> list[str]:
    path = repo / "data" / "history" / f"{source}.ndjson"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def test_line_union_appends_only_new_exact_lines():
    head = ["a", "b"]
    branch = ["b", "a", "c", "c"]
    assert automerge._line_union(head, branch) == ["a", "b", "c"]


def test_merge_lands_union(tmp_path):
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
    expected = shard_lines(repo)
    assert len(expected) == 4
    assert r1 in [json.loads(line) for line in expected]
    assert r2 in [json.loads(line) for line in expected]
    assert r4 in [json.loads(line) for line in expected]
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


def test_merge_re_sorts_the_shard_it_unions(tmp_path):
    # the union appends the branch's lines at the end. without a re-sort the
    # merged shard on the default branch loses the (model_id, observed_at)
    # order every writer holds, and the review diff stops putting a new row
    # beside its siblings
    repo, _bare = build_repo(tmp_path)
    flash = make_row("deepseek", "deepseek-v4-flash", "2026-08-31", 0.05)
    pro = make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.44)
    make_branch(repo, "pricelog/alpha-00000000", [pro, flash])

    automerge.merge_branches(["pricelog/alpha-00000000"], repo, pr.PrRunner(), "main", push=False)

    rows = [json.loads(line) for line in shard_lines(repo)]
    order = [(row["model_id"], row["observed_at"]) for row in rows]
    assert order == sorted(order)
    assert order[0][0] == "deepseek-v4-flash"


def test_merge_regenerates_the_index(tmp_path):
    # the push carries the checkout's GITHUB_TOKEN and starts no workflow run,
    # so the reindex workflow never sees this path: a merge that does not
    # regenerate leaves the served index stale on the default branch
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/zeta-55555555", [make_row("zai", "glm-5", "2026-08-31", 0.1)])

    automerge.merge_branches(["pricelog/zeta-55555555"], repo, pr.PrRunner(), "main", push=False)

    index = json.loads((repo / "data" / "index.json").read_text(encoding="utf-8"))
    assert (
        index["version"] == validate.load_schema_keys(Path(__file__).resolve().parents[1]).version
    )
    assert set(index["sources"]) == {"deepseek", "zai"}
    assert index["sources"]["zai"]["glm-5"]["rates"]["input"] == 0.1
    # it rides the merge commit, never the worktree
    assert git(repo, "status", "--porcelain") == ""
    assert "data/index.json" in git(repo, "show", "--name-only", "--format=", "HEAD")


def test_merge_lands_a_new_source_shard(tmp_path):
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/zeta-55555555", [make_row("zai", "glm-5", "2026-08-31", 0.1)])

    sha, results = automerge.merge_branches(
        ["pricelog/zeta-55555555"], repo, pr.PrRunner(), "main", push=False
    )

    assert [r.appended for r in results] == [1]
    assert [json.loads(line) for line in shard_lines(repo, "zai")] == [
        make_row("zai", "glm-5", "2026-08-31", 0.1)
    ]
    assert git(repo, "rev-parse", "HEAD").strip() == sha


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


def test_unrelated_dirt_does_not_block_merge(tmp_path):
    repo, _bare = build_repo(tmp_path)
    (repo / "uv.lock").write_text("version = 1\n")
    git(repo, "add", "uv.lock")
    git(repo, "commit", "-m", "lock")
    make_branch(repo, "pricelog/zeta-55555555", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    # what a CI checkout carries every run: `uv run` rewrote the lockfile and
    # imports left cache dirs. neither can reach a commit that stages by path
    (repo / "uv.lock").write_text("version = 2\n")
    (repo / "src" / "__pycache__").mkdir(parents=True)
    (repo / "src" / "__pycache__" / "automerge.pyc").write_text("")

    sha, results = automerge.merge_branches(
        ["pricelog/zeta-55555555"], repo, pr.PrRunner(), "main", push=False
    )

    assert [r.appended for r in results] == [1]
    assert git(repo, "show", f"{sha}:uv.lock") == "version = 1\n"
    assert (repo / "uv.lock").read_text(encoding="utf-8") == "version = 2\n"


def test_dirty_pipeline_file_refused(tmp_path):
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/eta-66666666", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    # a pipeline file the branch leaves alone: git merges over it without a
    # word and the by-path stage would then commit this worktree copy
    (repo / BILLING_RULES_FILE).write_text(json.dumps({"rules": ["dirty"]}) + "\n")
    with pytest.raises(automerge.AutoMergeError, match="nothing staged: M data/billing-rules.json"):
        automerge.merge_branches(["pricelog/eta-66666666"], repo, pr.PrRunner(), "main", push=False)


def test_staged_unrelated_change_refused(tmp_path):
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/theta-77777777", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    # git refuses a merge over a dirty index, but blames the merge for a file
    # it never touches; the pre-flight check names the real cause
    (repo / "notes.txt").write_text("staged\n")
    git(repo, "add", "notes.txt")
    with pytest.raises(automerge.AutoMergeError, match="nothing staged: staged notes.txt"):
        automerge.merge_branches(
            ["pricelog/theta-77777777"], repo, pr.PrRunner(), "main", push=False
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

"""automerge: the pass-side union merge of verified pipeline PR branches."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ai_pricelog import absence, announce, automerge, models, pr, store, validate
from ai_pricelog.announce import BILLING_RULES_FILE
from conftest import FakeRunner, git, git_init_repo

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
    schema_src = Path(__file__).resolve().parents[1] / "data" / "schema" / "row.v4.json"
    (repo / "data" / "schema").mkdir(parents=True)
    (repo / "data" / "schema" / "row.v4.json").write_text(schema_src.read_text(encoding="utf-8"))
    store.save_shard(
        [make_row("deepseek", "deepseek-v4-pro", "2026-08-30", 0.435)],
        repo / "data" / "history",
        "deepseek",
    )
    (repo / "state" / "announce").mkdir(parents=True)
    (repo / "state" / "announce" / "index.json").write_text(json.dumps({}) + "\n")
    (repo / "data" / "catalog").mkdir(parents=True)
    (repo / BILLING_RULES_FILE).write_text(json.dumps({"rules": []}) + "\n")
    (repo / "data" / "catalog" / "models.json").write_text(
        json.dumps({"version": 4, "models": {}}) + "\n"
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_billing_rules.py").write_text("# pin placeholder\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "init")
    bare = tmp_path / "origin.git"
    git(repo, "clone", "--bare", str(repo), str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-u", "origin", "main")
    return repo, bare


def announce_snapshot(texts: dict[str, dict[str, str]], fetched: str = "2026-08-31") -> dict:
    """An in-memory announce snapshot from ``{source: {url: text}}``."""
    snapshot: dict[str, dict[str, dict[str, str]]] = {}
    for source, urls in texts.items():
        files = announce.channel_files(source, urls.keys())
        for url, text in urls.items():
            snapshot.setdefault(source, {})[url] = {
                "file": files[url],
                "text": text,
                "sha256": announce._sha256(text),
                "fetched": fetched,
            }
    return snapshot


def make_branch(
    repo: Path,
    name: str,
    rows: list[dict],
    announce_texts: dict[str, dict[str, str]] | None = None,
    absence_data: dict | None = None,
    extra_file: str | None = None,
    catalog_models: dict | None = None,
    announce_fetched: str = "2026-08-31",
) -> None:
    """Open a pricelog branch off main: append rows, snapshots, push, return to main."""
    git(repo, "switch", "-c", name)
    shard_dir = repo / "data" / "history"
    by_source: dict[str, list[dict]] = {}
    for row in rows:
        by_source.setdefault(row["source"], []).append(row)
    for source, source_rows in by_source.items():
        store.save_shard(store.load_shard(shard_dir, source) + source_rows, shard_dir, source)
    if announce_texts is not None:
        announce.save_snapshot(announce_snapshot(announce_texts, announce_fetched), repo)
    if absence_data is not None:
        absence.save_absence(absence_data, repo)
    if catalog_models is not None:
        models.save_models(catalog_models, repo / models.MODELS_FILE)
    if extra_file is not None:
        (repo / extra_file).parent.mkdir(parents=True, exist_ok=True)
        (repo / extra_file).write_text("# changed\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", f"feat: {name}")
    git(repo, "push", "origin", name)
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")


def commit_announce(repo: Path, texts: dict[str, dict[str, str]], fetched: str) -> None:
    """Save an announce snapshot on the current branch and commit it."""
    announce.save_snapshot(announce_snapshot(texts, fetched), repo)
    git(repo, "add", "-A", "--", "state/announce")
    git(repo, "commit", "-m", "announce snapshot")


def shard_lines(repo: Path, source: str = "deepseek") -> list[str]:
    path = repo / "data" / "history" / f"{source}.ndjson"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def test_appended_lines_hold_only_new_exact_lines():
    head = ["a", "b"]
    branch = ["b", "a", "c", "c"]
    assert automerge._appended_lines(head, branch) == ["c"]


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
        announce_texts={"deepseek": {"https://example.com/u": "new"}},
    )
    r4 = make_row("deepseek", "deepseek-v4-flash", "2026-08-31", 0.05)
    # beta carries alpha's rows (the pending union) plus its own
    beta_rows = [r1, r2, r4]
    make_branch(
        repo,
        "pricelog/beta-11111111",
        beta_rows,
        announce_texts={"deepseek": {"https://example.com/u": "newer"}},
        absence_data={"deepseek": {"gone": {"absent_runs": 1, "since": "2026-08-31"}}},
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
    # the freshest announce tree comes from the newest branch; each source's
    # absence file lands on its own branch
    index = json.loads((repo / "state" / "announce" / "index.json").read_text(encoding="utf-8"))
    channel_file = index["deepseek"]["https://example.com/u"]["file"]
    assert (repo / channel_file).read_text(encoding="utf-8") == announce.wrap("newer")
    absence = json.loads((repo / "state" / "absence" / "deepseek.json").read_text(encoding="utf-8"))
    assert absence == {"gone": {"absent_runs": 1, "since": "2026-08-31"}}
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


def test_merge_unions_catalog_models(tmp_path):
    repo, _bare = build_repo(tmp_path)
    models.save_models(
        {"m1": {"vendor": "v", "curated": True, "sources": {"a": ["m1"]}}},
        repo / models.MODELS_FILE,
    )
    git(repo, "add", models.MODELS_FILE)
    git(repo, "commit", "-m", "seed catalog")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/alpha-00000000",
        [],
        catalog_models={
            # a stale copy of a canonical HEAD changed: HEAD must win
            "m1": {"vendor": "stale", "curated": True, "sources": {"a": ["m1"]}},
            "a/new": {"vendor": None, "curated": False, "sources": {"a": ["new"]}},
        },
    )

    automerge.merge_branches(["pricelog/alpha-00000000"], repo, pr.PrRunner(), "main", push=False)

    catalog = json.loads((repo / models.MODELS_FILE).read_text(encoding="utf-8"))
    assert catalog["models"]["m1"]["vendor"] == "v"
    assert catalog["models"]["a/new"]["curated"] is False
    assert git(repo, "status", "--porcelain") == ""


def test_merge_skips_a_seed_whose_key_head_claims(tmp_path):
    # the reviewer's twin-merge scenario: HEAD merged seed a/m2 into curated y
    # and deleted a/m2; an older branch still carrying a/m2 must not resurrect it
    repo, _bare = build_repo(tmp_path)
    curated = {"y": {"vendor": "v", "curated": True, "sources": {"a": ["m2"]}}}
    models.save_models(curated, repo / models.MODELS_FILE)
    git(repo, "add", models.MODELS_FILE)
    git(repo, "commit", "-m", "merge twin")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/alpha-00000000",
        [],
        catalog_models={"a/m2": {"vendor": None, "curated": False, "sources": {"a": ["m2"]}}},
    )

    automerge.merge_branches(["pricelog/alpha-00000000"], repo, pr.PrRunner(), "main", push=False)

    catalog = json.loads((repo / models.MODELS_FILE).read_text(encoding="utf-8"))
    assert catalog["models"] == curated
    assert git(repo, "status", "--porcelain") == ""


def test_merge_refuses_an_appended_row_the_contract_forbids(tmp_path):
    # the pass is authorized to hand-edit a branch row, so the exact-line union
    # is the one path a contract-breaking shape can take into the store: the
    # merge stops naming the branch and nothing lands
    repo, _bare = build_repo(tmp_path)
    bad = make_row("zai", "glm-5", "2026-08-31", 0.1)
    bad["surprise"] = "hand edit"
    make_branch(repo, "pricelog/iota-88888888", [bad])
    before = git(repo, "rev-parse", "main").strip()

    with pytest.raises(
        automerge.AutoMergeError,
        match=(
            "pricelog/iota-88888888: origin/pricelog/iota-88888888:data/history/zai.ndjson line 1"
        ),
    ):
        automerge.merge_branches(
            ["pricelog/iota-88888888"], repo, pr.PrRunner(), "main", push=False
        )

    assert git(repo, "rev-parse", "main").strip() == before


def test_merge_leaves_rows_head_already_holds_unvalidated(tmp_path):
    # a line already in the store predates this gate: only the lines a branch
    # appends validate, or one legacy bad line would block every later merge
    repo, _bare = build_repo(tmp_path)
    shard = repo / "data" / "history" / "deepseek.ndjson"
    legacy = json.loads(shard.read_text(encoding="utf-8").splitlines()[0])
    legacy["surprise"] = "legacy"
    shard.write_text(json.dumps(legacy, separators=(",", ":")) + "\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "legacy line")
    git(repo, "push", "origin", "main")
    fresh = make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.44)
    make_branch(repo, "pricelog/kappa-99999999", [fresh])

    sha, results = automerge.merge_branches(
        ["pricelog/kappa-99999999"], repo, pr.PrRunner(), "main", push=False
    )

    assert [r.appended for r in results] == [1]
    rows = [json.loads(line) for line in shard_lines(repo)]
    assert len(rows) == 2
    assert rows[0]["surprise"] == "legacy"
    assert git(repo, "rev-parse", "HEAD").strip() == sha


def test_validation_follows_the_partition_not_its_own(tmp_path, monkeypatch):
    # the partition (which lines are new) has one implementation; when its
    # dedupe changes, the validation verdict must move with it. the drift
    # stand-in dedupes on rstripped lines, so the branch's re-serialized copy
    # of a head line (trailing space) reads as already-held: the merge follows
    # the partition instead of refusing on a second, byte-exact derivation
    repo, _bare = build_repo(tmp_path)
    shard = repo / "data" / "history" / "deepseek.ndjson"
    legacy = json.loads(shard.read_text(encoding="utf-8").splitlines()[0])
    legacy["surprise"] = "legacy"
    line = json.dumps(legacy, separators=(",", ":"))
    shard.write_text(line + "\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "legacy line")
    git(repo, "push", "origin", "main")
    git(repo, "switch", "-c", "pricelog/drift-44444444")
    shard.write_text(line + " \n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "re-serialize the legacy line with a trailing space")
    git(repo, "push", "origin", "pricelog/drift-44444444")
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")

    def rstrip_dedupe(head_lines: list[str], branch_lines: list[str]) -> list[str]:
        seen = {head.rstrip() for head in head_lines}
        appended = []
        for branch_line in branch_lines:
            if branch_line.rstrip() not in seen:
                seen.add(branch_line.rstrip())
                appended.append(branch_line)
        return appended

    monkeypatch.setattr(automerge, "_appended_lines", rstrip_dedupe)
    sha, results = automerge.merge_branches(
        ["pricelog/drift-44444444"], repo, pr.PrRunner(), "main", push=False
    )

    assert [result.appended for result in results] == [0]
    assert shard_lines(repo) == [line]


def test_merge_refused_row_names_the_branch_line(tmp_path):
    # two branches merge in one call: the first lands a good row, so HEAD gains a
    # line the second branch's copy does not carry. the bad row is then branch
    # line 2, union line 3, appended-subset line 1; the error must name line 2
    repo, _bare = build_repo(tmp_path)
    good = make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.44)
    make_branch(repo, "pricelog/alpha-11111111", [good])
    bad = make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.44)
    bad["surprise"] = "hand edit"
    make_branch(repo, "pricelog/beta-22222222", [bad])

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(
            ["pricelog/alpha-11111111", "pricelog/beta-22222222"],
            repo,
            pr.PrRunner(),
            "main",
            push=False,
        )

    assert str(excinfo.value) == (
        "branch pricelog/beta-22222222: origin/pricelog/beta-22222222:data/history/"
        "deepseek.ndjson line 2 fails the row contract: row field(s) ['surprise']"
        " are not part of the row schema; fix: drop them, or extend the schema and"
        " bump the version. do not retry: report the error and leave every PR open"
    )
    assert len(git(repo, "show", "HEAD:data/history/deepseek.ndjson").splitlines()) == 2


def test_merge_invalid_json_names_the_branch_line(tmp_path):
    # the same discriminating fixture: the first branch lands a good row, the
    # second carries an invalid-json second line. the error must name the
    # branch's line 2, not union line 3
    repo, _bare = build_repo(tmp_path)
    good = make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.44)
    make_branch(repo, "pricelog/alpha-11111111", [good])
    git(repo, "switch", "-c", "pricelog/mu-33333333")
    shard = repo / "data" / "history" / "deepseek.ndjson"
    shard.write_text(shard.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "corrupt a row")
    git(repo, "push", "origin", "pricelog/mu-33333333")
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(
            ["pricelog/alpha-11111111", "pricelog/mu-33333333"],
            repo,
            pr.PrRunner(),
            "main",
            push=False,
        )

    assert str(excinfo.value) == (
        "branch pricelog/mu-33333333: history file 'origin/pricelog/mu-33333333:data/"
        "history/deepseek.ndjson': line 2: invalid json: Expecting property name enclosed"
        " in double quotes. do not retry: report the error and leave every PR open"
    )


def test_seed_branch_refused(tmp_path):
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/seed", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    with pytest.raises(automerge.AutoMergeError, match="human-only"):
        automerge.merge_branches(["pricelog/seed"], repo, pr.PrRunner(), "main", push=False)


@pytest.mark.parametrize(
    "extra_file",
    [
        "src/ai_pricelog/pipeline.py",
        "data/index.json",
    ],
)
def test_non_pipeline_file_refused(tmp_path, extra_file):
    repo, _bare = build_repo(tmp_path)
    make_branch(
        repo,
        "pricelog/gamma-22222222",
        [make_row("zai", "glm-5", "2026-08-31", 0.1)],
        extra_file=extra_file,
    )
    with pytest.raises(automerge.AutoMergeError, match=extra_file):
        automerge.merge_branches(
            ["pricelog/gamma-22222222"], repo, pr.PrRunner(), "main", push=False
        )


@pytest.mark.parametrize(
    "extra_file",
    [
        "state/announce/deepseek/nested/updates.md",
        "state/absence/deepseek/nested.json",
        "state/announce/deepseek/notes.txt",
    ],
)
def test_nested_state_path_refused(tmp_path, extra_file):
    repo, _bare = build_repo(tmp_path)
    make_branch(
        repo,
        "pricelog/zeta-55555555",
        [make_row("zai", "glm-5", "2026-08-31", 0.1)],
        extra_file=extra_file,
    )
    with pytest.raises(automerge.AutoMergeError, match=extra_file):
        automerge.merge_branches(
            ["pricelog/zeta-55555555"], repo, pr.PrRunner(), "main", push=False
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
    with pytest.raises(
        automerge.AutoMergeError, match="nothing staged: M data/catalog/billing-rules.json"
    ):
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


def test_merged_branch_refused_by_name(tmp_path):
    # git prints "Already up to date." (capital A); a case-sensitive match
    # reads as a clean no-op and the run dies later at git commit with no
    # diagnosis. observed 2026-09-09: automerge run from a checkout already
    # on the target branch
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/merged-99999999", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    # land the branch on main directly, the state a double-merge attempt sees
    git(repo, "push", "origin", "origin/pricelog/merged-99999999:refs/heads/main")
    git(repo, "switch", "main")
    git(repo, "pull", "--ff-only", "origin", "main")
    with pytest.raises(automerge.AutoMergeError, match="merged-99999999.*already merged"):
        automerge.merge_branches(
            ["pricelog/merged-99999999"], repo, pr.PrRunner(), "main", push=False
        )
    assert git(repo, "status", "--porcelain") == ""


def test_merge_refused_from_a_non_base_checkout(tmp_path):
    # a merge run from any branch but the base rides that branch's own
    # commits into the push: every branch off the base pushes as a
    # fast-forward, so the merged history claims them as ancestors.
    # observed 2026-09-09: automerge run from the PR branch itself
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/wrong-00000000", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    make_branch(repo, "pricelog/right-11111111", [make_row("zai", "glm-5", "2026-09-01", 0.2)])
    git(repo, "switch", "pricelog/wrong-00000000")
    with pytest.raises(automerge.AutoMergeError, match="run the merge from the default branch"):
        automerge.merge_branches(
            ["pricelog/right-11111111"], repo, pr.PrRunner(), "main", push=False
        )
    assert git(repo, "status", "--porcelain") == ""


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


def test_cross_run_burst_merges(tmp_path):
    # the 09-07 shape (PRs 153-164): sibling branches span several runs, so
    # their announce snapshots carry different fetched dates and their
    # absence counters diverge per source. the merge must take each
    # announce tree in merge order (the last write wins, and every branch's
    # tree resolves the add/add conflicts on index.json) and each absence
    # file from the newest branch that carries it
    repo, _bare = build_repo(tmp_path)
    make_branch(
        repo,
        "pricelog/older-00000001",
        [make_row("deepseek", "deepseek-v4-pro", "2026-09-04", 0.44)],
        announce_texts={"deepseek": {"https://example.com/u": "old run prose"}},
        announce_fetched="2026-09-04",
        absence_data={"deepseek": {"gone-old": {"absent_runs": 1, "since": "2026-09-04"}}},
    )
    make_branch(
        repo,
        "pricelog/middle-00000002",
        [make_row("zai", "glm-5.3", "2026-09-05", 0.2)],
        announce_texts={"deepseek": {"https://example.com/u": "old run prose"}},
        announce_fetched="2026-09-05",
        absence_data={"zai": {"gone-mid": {"absent_runs": 1, "since": "2026-09-05"}}},
    )
    make_branch(
        repo,
        "pricelog/newest-00000003",
        [make_row("deepseek", "deepseek-v4-pro", "2026-09-07", 0.46)],
        announce_texts={"deepseek": {"https://example.com/u": "old run prose"}},
        announce_fetched="2026-09-07",
        # the newest branch dropped its own absence file (its entries
        # cleared); the merge still keeps the sources only older branches
        # carry
        absence_data={"zai": {"gone-mid": {"absent_runs": 2, "since": "2026-09-05"}}},
    )

    sha, results = automerge.merge_branches(
        [
            "pricelog/older-00000001",
            "pricelog/middle-00000002",
            "pricelog/newest-00000003",
        ],
        repo,
        pr.PrRunner(),
        "main",
        push=False,
    )

    # every branch's rows union into the shards (deepseek twice, zai once)
    deepseek_rows = [json.loads(line) for line in shard_lines(repo, "deepseek")]
    zai_rows = [json.loads(line) for line in shard_lines(repo, "zai")]
    assert len(deepseek_rows) == 3  # the seed row + the older and newest rows
    assert len(zai_rows) == 1  # the middle branch's row
    # the announce tree: the newest branch's copy lands (last write, the
    # freshest fetched date), and every branch's tree was written in order
    # so the merge never sees a conflict marker in index.json
    index = json.loads((repo / "state" / "announce" / "index.json").read_text(encoding="utf-8"))
    assert index["deepseek"]["https://example.com/u"]["fetched"] == "2026-09-07"
    # the absence files: each source's file comes from the newest branch
    # that carries it, not from the last branch wholesale
    deepseek = json.loads((repo / "state" / "absence" / "deepseek.json").read_text("utf-8"))
    assert deepseek == {"gone-old": {"absent_runs": 1, "since": "2026-09-04"}}
    zai = json.loads((repo / "state" / "absence" / "zai.json").read_text(encoding="utf-8"))
    assert zai == {"gone-mid": {"absent_runs": 2, "since": "2026-09-05"}}
    # the merged tree is clean and the merge commits carry the branch order
    assert git(repo, "status", "--porcelain") == ""
    assert [r.branch for r in results] == [
        "pricelog/older-00000001",
        "pricelog/middle-00000002",
        "pricelog/newest-00000003",
    ]
    assert git(repo, "rev-parse", "HEAD").strip() == sha


def test_cross_run_burst_keeps_a_landed_channel_change(tmp_path):
    # the 09-11 shape (PRs 180-184): the evening branch landed fresh channel
    # prose; the next morning's run failed the same channel's fetch, so its
    # branch carries the base's stale entry, and the newest branch's
    # whole-tree write reverted the landed change. each channel must land
    # from the last branch that CHANGED it against the burst base
    repo, _bare = build_repo(tmp_path)
    # two urls in non-alphabetical insertion order, so the byte-equality
    # assert below can tell an insertion-order serialization from a sorted
    # one; updates is the channel the evening run changed, alerts the one no
    # branch touches
    base_texts = {
        "https://example.com/updates": "old prose",
        "https://example.com/alerts": "steady prose",
    }
    commit_announce(repo, {"deepseek": base_texts}, "2026-09-09")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/evening-00000001",
        [make_row("deepseek", "deepseek-v4-pro", "2026-09-10", 0.44)],
        announce_texts={"deepseek": base_texts | {"https://example.com/updates": "fresh prose"}},
        announce_fetched="2026-09-10",
    )
    # the morning branch's fetch failed: its snapshot keeps the base's entries
    # verbatim, stale prose and stale fetched date
    make_branch(
        repo,
        "pricelog/morning-00000002",
        [make_row("deepseek", "deepseek-v4-pro", "2026-09-11", 0.45)],
        announce_texts={"deepseek": base_texts},
        announce_fetched="2026-09-09",
    )

    automerge.merge_branches(
        ["pricelog/evening-00000001", "pricelog/morning-00000002"],
        repo,
        pr.PrRunner(),
        "main",
        push=False,
    )

    index = json.loads((repo / "state" / "announce" / "index.json").read_text(encoding="utf-8"))
    entry = index["deepseek"]["https://example.com/updates"]
    # the older branch's fresh prose and fetched date survive the newer
    # branch's stale copy
    assert entry["sha256"] == announce._sha256("fresh prose")
    assert entry["fetched"] == "2026-09-10"
    assert announce.unwrap((repo / entry["file"]).read_text(encoding="utf-8")) == "fresh prose"
    # the channel no branch changed keeps the base's entry
    steady = index["deepseek"]["https://example.com/alerts"]
    assert steady["fetched"] == "2026-09-09"
    assert announce.unwrap((repo / steady["file"]).read_text(encoding="utf-8")) == "steady prose"
    # the merged announce tree is byte-identical to what save_snapshot writes
    # for the resolved snapshot: the merge's index.json write must serialize
    # exactly like the pipeline's own writer or the diff turns whole-file
    expected_root = tmp_path / "expected"
    expected_root.mkdir()
    expected_snapshot = announce_snapshot(
        {
            "deepseek": {
                "https://example.com/updates": "fresh prose",
                "https://example.com/alerts": "steady prose",
            }
        },
        "2026-09-10",
    )
    expected_snapshot["deepseek"]["https://example.com/alerts"]["fetched"] = "2026-09-09"
    announce.save_snapshot(expected_snapshot, expected_root)
    expected = {
        path.relative_to(expected_root).as_posix(): path.read_bytes()
        for path in (expected_root / "state" / "announce").rglob("*")
        if path.is_file()
    }
    merged = {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in (repo / "state" / "announce").rglob("*")
        if path.is_file()
    }
    assert merged == expected
    # the second merge's announce resolution is a no-op against the first's:
    # the morning branch changed no channel, so the tree it leaves must be
    # byte-identical to the one the evening merge wrote
    first_commit = git(repo, "log", "--format=%P", "-1").split()[0]
    second_tree = git(repo, "ls-tree", "-r", "HEAD", "state/announce/")
    first_tree = git(repo, "ls-tree", "-r", first_commit, "state/announce/")
    assert second_tree == first_tree
    assert git(repo, "status", "--porcelain") == ""


def test_merge_drops_a_url_the_newest_branch_lacks(tmp_path):
    # the newest branch's index owns the url set: a url that left
    # providers.toml no longer appears in its run's snapshot, so the merge
    # deletes the file and the index entry however older branches carry it.
    # "three" the base itself carried (git's merge deletes it); "two" only the
    # older branch added, so git's merge keeps it as a HEAD-side addition and
    # the resolution's own prune must delete it
    repo, _bare = build_repo(tmp_path)
    commit_announce(
        repo,
        {
            "deepseek": {
                "https://example.com/one": "one prose",
                "https://example.com/three": "three prose",
            }
        },
        "2026-09-09",
    )
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/older-00000001",
        [make_row("deepseek", "deepseek-v4-pro", "2026-09-10", 0.44)],
        announce_texts={
            "deepseek": {
                "https://example.com/one": "one prose",
                "https://example.com/three": "three prose",
                "https://example.com/two": "two prose",
            }
        },
        announce_fetched="2026-09-10",
    )
    make_branch(
        repo,
        "pricelog/newest-00000002",
        [make_row("deepseek", "deepseek-v4-pro", "2026-09-11", 0.45)],
        announce_texts={"deepseek": {"https://example.com/one": "one prose"}},
        announce_fetched="2026-09-09",
    )

    automerge.merge_branches(
        ["pricelog/older-00000001", "pricelog/newest-00000002"],
        repo,
        pr.PrRunner(),
        "main",
        push=False,
    )

    index = json.loads((repo / "state" / "announce" / "index.json").read_text(encoding="utf-8"))
    assert set(index["deepseek"]) == {"https://example.com/one"}
    assert not (repo / "state" / "announce" / "deepseek" / "two.md").exists()
    assert not (repo / "state" / "announce" / "deepseek" / "three.md").exists()
    # the surviving url is unchanged on every branch, so the base's entry wins
    assert index["deepseek"]["https://example.com/one"]["fetched"] == "2026-09-09"
    assert git(repo, "status", "--porcelain") == ""


def test_merge_adds_a_url_and_keeps_an_unchanged_channel_from_the_base(tmp_path):
    # a url the base never carried counts as changed by every branch that
    # carries it, so the last one wins; a url no branch changed keeps the
    # base's entry and file bytes
    repo, _bare = build_repo(tmp_path)
    commit_announce(repo, {"deepseek": {"https://example.com/base": "base prose"}}, "2026-09-08")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/older-00000001",
        [make_row("deepseek", "deepseek-v4-pro", "2026-09-10", 0.44)],
        announce_texts={
            "deepseek": {
                "https://example.com/base": "base prose",
                "https://example.com/one": "one prose",
            }
        },
        announce_fetched="2026-09-10",
    )
    make_branch(
        repo,
        "pricelog/newest-00000002",
        [make_row("deepseek", "deepseek-v4-pro", "2026-09-11", 0.45)],
        announce_texts={
            "deepseek": {
                "https://example.com/base": "base prose",
                "https://example.com/one": "one prose",
                "https://example.com/two": "two prose",
            }
        },
        announce_fetched="2026-09-11",
    )

    automerge.merge_branches(
        ["pricelog/older-00000001", "pricelog/newest-00000002"],
        repo,
        pr.PrRunner(),
        "main",
        push=False,
    )

    index = json.loads((repo / "state" / "announce" / "index.json").read_text(encoding="utf-8"))
    urls = index["deepseek"]
    # unchanged on every branch: the base's entry wins, fetched date included
    base_entry = urls["https://example.com/base"]
    assert base_entry["fetched"] == "2026-09-08"
    assert announce.unwrap((repo / base_entry["file"]).read_text(encoding="utf-8")) == "base prose"
    # added urls: the last branch that carries them wins
    assert urls["https://example.com/one"]["fetched"] == "2026-09-11"
    assert urls["https://example.com/two"]["fetched"] == "2026-09-11"
    one_entry = urls["https://example.com/one"]
    assert announce.unwrap((repo / one_entry["file"]).read_text(encoding="utf-8")) == "one prose"
    two_entry = urls["https://example.com/two"]
    assert announce.unwrap((repo / two_entry["file"]).read_text(encoding="utf-8")) == "two prose"
    assert git(repo, "status", "--porcelain") == ""


def test_merge_refuses_an_announce_index_whose_file_is_not_derived(tmp_path):
    # the pass is authorized to hand-edit a branch's announce tree, so a file
    # field pointing anywhere but the derived channel path must stop the merge
    # by name rather than write outside the announce tree
    repo, _bare = build_repo(tmp_path)
    git(repo, "switch", "-c", "pricelog/hand-00000001")
    index = {
        "deepseek": {
            "https://example.com/u": {
                "file": "state/announce/deepseek/elsewhere.md",
                "sha256": announce._sha256("prose"),
                "fetched": "2026-09-10",
            }
        }
    }
    (repo / "state" / "announce" / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "hand-edited index")
    git(repo, "push", "origin", "pricelog/hand-00000001")
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")

    with pytest.raises(automerge.AutoMergeError, match="does not match the derived path"):
        automerge.merge_branches(
            ["pricelog/hand-00000001"], repo, pr.PrRunner(), "main", push=False
        )


def test_merge_skips_the_announce_step_for_a_branch_with_no_index(tmp_path):
    # a branch whose announce tree carries no index.json is not a config drop:
    # it names no url set, so its merge leaves the announce tree exactly as
    # the previous merge resolution wrote it (git's modify/delete on the index
    # keeps HEAD's copy, and the skipped step rewrites nothing)
    repo, _bare = build_repo(tmp_path)
    commit_announce(repo, {"deepseek": {"https://example.com/u": "old prose"}}, "2026-09-09")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/older-00000001",
        [make_row("deepseek", "deepseek-v4-pro", "2026-09-10", 0.44)],
        announce_texts={"deepseek": {"https://example.com/u": "fresh prose"}},
        announce_fetched="2026-09-10",
    )
    # the newest branch's announce tree lost its index.json alone: a {} index
    # would read as a real config drop and delete the channel, an absent one
    # must not
    git(repo, "switch", "-c", "pricelog/newest-00000002")
    (repo / "state" / "announce" / "index.json").unlink()
    git(repo, "add", ".")
    git(repo, "commit", "-m", "drop the index")
    git(repo, "push", "origin", "pricelog/newest-00000002")
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")

    automerge.merge_branches(
        ["pricelog/older-00000001", "pricelog/newest-00000002"],
        repo,
        pr.PrRunner(),
        "main",
        push=False,
    )

    index = json.loads((repo / "state" / "announce" / "index.json").read_text(encoding="utf-8"))
    entry = index["deepseek"]["https://example.com/u"]
    assert entry["sha256"] == announce._sha256("fresh prose")
    assert announce.unwrap((repo / entry["file"]).read_text(encoding="utf-8")) == "fresh prose"
    assert git(repo, "status", "--porcelain") == ""


def test_merge_renames_a_channel_that_leaves_a_slug_collision(tmp_path):
    # channel_files disambiguates same-slug urls with a sha8 suffix, so a url
    # set change renames the survivor: two urls share the "notes" slug while
    # both are configured, and the survivor's path loses the suffix the moment
    # the newest branch's index carries it alone. the winner's bytes come from
    # the winner's OWN (still suffixed) path, but the file must land at the
    # path the merged url set derives — the two differ exactly here
    repo, _bare = build_repo(tmp_path)
    url_a = "https://example.com/notes"
    url_b = "https://example.com/notes?feed=rss"
    colliding = announce.channel_files("deepseek", [url_a, url_b])
    solo = announce.channel_files("deepseek", [url_a])
    assert colliding[url_a] != solo[url_a]
    commit_announce(repo, {"deepseek": {url_a: "old a prose", url_b: "old b prose"}}, "2026-09-09")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/older-00000001",
        [make_row("deepseek", "deepseek-v4-pro", "2026-09-10", 0.44)],
        announce_texts={"deepseek": {url_a: "fresh a prose", url_b: "old b prose"}},
        announce_fetched="2026-09-10",
    )
    # the newest branch dropped url_b from the config and failed url_a's
    # fetch: its index carries url_a alone (deriving the un-suffixed path)
    # with the base's stale sha
    make_branch(
        repo,
        "pricelog/newest-00000002",
        [make_row("deepseek", "deepseek-v4-pro", "2026-09-11", 0.45)],
        announce_texts={"deepseek": {url_a: "old a prose"}},
        announce_fetched="2026-09-09",
    )

    automerge.merge_branches(
        ["pricelog/older-00000001", "pricelog/newest-00000002"],
        repo,
        pr.PrRunner(),
        "main",
        push=False,
    )

    index = json.loads((repo / "state" / "announce" / "index.json").read_text(encoding="utf-8"))
    entry = index["deepseek"][url_a]
    # the older branch's fresh prose wins, and the entry names the path the
    # merged url set derives, not the winner's own suffixed path
    assert entry["file"] == solo[url_a]
    assert entry["sha256"] == announce._sha256("fresh a prose")
    assert entry["fetched"] == "2026-09-10"
    expected_root = tmp_path / "expected"
    expected_root.mkdir()
    announce.save_snapshot(
        announce_snapshot({"deepseek": {url_a: "fresh a prose"}}, "2026-09-10"), expected_root
    )
    expected = {
        path.relative_to(expected_root).as_posix(): path.read_bytes()
        for path in (expected_root / "state" / "announce").rglob("*")
        if path.is_file()
    }
    merged = {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in (repo / "state" / "announce").rglob("*")
        if path.is_file()
    }
    assert merged == expected
    for file in colliding.values():
        assert not (repo / file).exists()
    assert git(repo, "status", "--porcelain") == ""


def test_merge_lands_a_channel_file_the_newest_branch_lacks(tmp_path):
    # the rename-detection-masked shape: a newest branch whose index names a
    # url its tree carries no .md for (a hand edit; _announce_index checks the
    # file field's derived path, never the blob's existence). git's merge
    # cannot fill the newest path then, so the resolution's own write is the
    # only thing that can land the winner's bytes at it
    repo, _bare = build_repo(tmp_path)
    url_a = "https://example.com/notes"
    url_b = "https://example.com/notes?feed=rss"
    solo = announce.channel_files("deepseek", [url_a])
    commit_announce(repo, {"deepseek": {url_a: "old a prose", url_b: "old b prose"}}, "2026-09-09")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/older-00000001",
        [make_row("deepseek", "deepseek-v4-pro", "2026-09-10", 0.44)],
        announce_texts={"deepseek": {url_a: "fresh a prose", url_b: "old b prose"}},
        announce_fetched="2026-09-10",
    )
    # the newest branch names url_a alone (deriving the un-suffixed path) but
    # a hand edit dropped its .md: its index names a file its own tree lacks
    make_branch(
        repo,
        "pricelog/newest-00000002",
        [make_row("deepseek", "deepseek-v4-pro", "2026-09-11", 0.45)],
        announce_texts={"deepseek": {url_a: "old a prose"}},
        announce_fetched="2026-09-09",
    )
    git(repo, "switch", "pricelog/newest-00000002")
    git(repo, "rm", "-q", "--", "state/announce/deepseek/notes.md")
    git(repo, "commit", "-m", "hand edit: drop the channel file, keep the index")
    git(repo, "push", "origin", "pricelog/newest-00000002")
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")

    automerge.merge_branches(
        ["pricelog/older-00000001", "pricelog/newest-00000002"],
        repo,
        pr.PrRunner(),
        "main",
        push=False,
    )

    index = json.loads((repo / "state" / "announce" / "index.json").read_text(encoding="utf-8"))
    entry = index["deepseek"][url_a]
    assert entry["file"] == solo[url_a]
    # the winner's bytes land at the newest index's path even though no
    # rename pair can form for it
    assert announce.unwrap((repo / entry["file"]).read_text(encoding="utf-8")) == "fresh a prose"
    assert entry["sha256"] == announce._sha256("fresh a prose")
    assert git(repo, "status", "--porcelain") == ""


def test_announce_index_refuses_shapes_that_do_not_read(tmp_path):
    # the pass may hand-edit the announce tree, so an index that does not read
    # as source -> url -> entry stops the merge by name, never by traceback
    cases = [
        ("not json{", "is not valid json"),
        ('["a list"]', "must be an object"),
        ('{"deepseek": []}', "source 'deepseek' must map to an object"),
        ('{"deepseek": {"u": "x"}}', "must carry 'file', 'sha256' and 'fetched' as strings"),
        (
            '{"deepseek": {"u": {"file": 1, "sha256": "a", "fetched": "b"}}}',
            "must carry 'file', 'sha256' and 'fetched' as strings",
        ),
    ]
    for text, message in cases:
        runner = FakeRunner()
        runner.on(f"HEAD:{announce.ANNOUNCE_INDEX}", text)
        with pytest.raises(automerge.AutoMergeError, match=re.escape(message)):
            automerge._announce_index(runner, tmp_path, "HEAD", "base abc1234")


def test_announce_index_parses_a_valid_snapshot(tmp_path):
    url = "https://example.com/notes"
    entry = {
        "file": announce.channel_files("deepseek", [url])[url],
        "sha256": "0" * 64,
        "fetched": "2026-09-11",
    }
    runner = FakeRunner()
    runner.on(f"HEAD:{announce.ANNOUNCE_INDEX}", json.dumps({"deepseek": {url: entry}}))
    assert automerge._announce_index(runner, tmp_path, "HEAD", "base abc1234") == {
        "deepseek": {url: entry}
    }


def test_merge_refuses_when_the_winner_tree_lacks_the_channel_file(tmp_path):
    # the resolution names the last branch whose index sha differs from the
    # base; when that winner's own tree carries no file at the index's path
    # (a hand edit), the merge refuses by name and nothing lands
    repo, _bare = build_repo(tmp_path)
    url_a = "https://example.com/notes"
    commit_announce(repo, {"deepseek": {url_a: "old prose"}}, "2026-09-09")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/winner-55555555",
        [make_row("deepseek", "deepseek-v4-pro", "2026-09-11", 0.45)],
        announce_texts={"deepseek": {url_a: "fresh prose"}},
        announce_fetched="2026-09-11",
    )
    git(repo, "switch", "pricelog/winner-55555555")
    git(repo, "rm", "-q", "--", "state/announce/deepseek/notes.md")
    git(repo, "commit", "-m", "hand edit: drop the channel file, keep the index")
    git(repo, "push", "origin", "pricelog/winner-55555555")
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")
    before = git(repo, "rev-parse", "main").strip()

    with pytest.raises(
        automerge.AutoMergeError,
        match="is missing from origin/pricelog/winner-55555555",
    ):
        automerge.merge_branches(
            ["pricelog/winner-55555555"], repo, pr.PrRunner(), "main", push=False
        )

    assert git(repo, "rev-parse", "main").strip() == before

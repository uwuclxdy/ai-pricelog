"""automerge: the pass-side union merge of verified pipeline PR branches."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import pytest

from ai_pricelog import absence, announce, automerge, models, pr, stats, store, validate
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


def make_removal_row(source: str, model_id: str, observed_at: str) -> dict:
    row = make_row(source, model_id, observed_at, 0.1)
    row["removed"] = True
    return row


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
        json.dumps(
            {
                "version": 4,
                "models": {
                    "deepseek/deepseek-v4-pro": {
                        "vendor": "deepseek",
                        "curated": False,
                        "sources": {"deepseek": ["deepseek-v4-pro"]},
                    }
                },
            }
        )
        + "\n"
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_billing_rules.py").write_text("# pin placeholder\n")
    init_rows = [make_row("deepseek", "deepseek-v4-pro", "2026-08-30", 0.435)]
    init_mapping = {
        "deepseek/deepseek-v4-pro": {
            "vendor": "deepseek",
            "curated": False,
            "sources": {"deepseek": ["deepseek-v4-pro"]},
        }
    }
    (repo / "README.md").write_text(
        stats.render(
            "<!-- stats:start --><!-- stats:end -->\n"
            "<!-- stats-row:start --><!-- stats-row:end -->\n",
            stats.compute(init_rows, init_mapping),
        ),
        encoding="utf-8",
    )
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
    auto_seed: bool = True,
    announce_fetched: str = "2026-08-31",
) -> None:
    """Open a pricelog branch off main: append rows, snapshots, push, return to main.

    Like the pipeline, the branch carries a seeded catalog entry for every row
    key HEAD's catalog does not claim, unless `auto_seed` is False (the tests
    for the merge's claim check build their own seedless branches).
    """
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
    catalog = models.load_models(repo / models.MODELS_FILE)
    if catalog_models is not None:
        catalog = {**catalog, **catalog_models}
    if auto_seed and rows:
        catalog = {
            **catalog,
            **models.seed_entries({(row["source"], row["model_id"]) for row in rows}, catalog, {}),
        }
    if catalog_models is not None or (auto_seed and rows):
        models.save_models(catalog, repo / models.MODELS_FILE)
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


def merge_spy(monkeypatch) -> list[list[str]]:
    """Record each git merge invocation subprocess.run makes, passing it through.

    A pre-flight refusal must show zero merge calls and a landed merge one per
    branch, so the zero side of the refusal tests is never vacuous.
    """
    calls: list[list[str]] = []
    real_run = subprocess.run

    def spy(cmd, *args, **kwargs):
        if cmd[:2] == ["git", "merge"]:
            calls.append(list(cmd))
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    return calls


def delete_on_branch(repo: Path, branch: str, path: str) -> None:
    """Open a pricelog branch off main whose only change deletes ``path``."""
    git(repo, "switch", "-c", branch)
    git(repo, "rm", "-q", path)
    git(repo, "commit", "-m", f"drop {path}")
    git(repo, "push", "origin", branch)
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")


def commit_on_branch(repo: Path, branch: str, edit: Callable[[Path], None]) -> None:
    """Open a pricelog branch off main whose only change is the one ``edit`` stages."""
    git(repo, "switch", "-c", branch)
    edit(repo)
    git(repo, "commit", "-m", f"hand edit on {branch}")
    git(repo, "push", "origin", branch)
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")


def write_file(path: str, text: str) -> Callable[[Path], None]:
    """An edit that rewrites ``path`` with ``text`` and stages it."""

    def edit(repo: Path) -> None:
        (repo / path).write_text(text, encoding="utf-8")
        git(repo, "add", "--", path)

    return edit


def as_symlink(path: str) -> Callable[[Path], None]:
    """An edit that replaces the regular file at ``path`` with a symlink and stages it."""

    def edit(repo: Path) -> None:
        (repo / path).unlink()
        (repo / path).symlink_to("elsewhere")
        git(repo, "add", "--", path)

    return edit


def as_submodule(path: str) -> Callable[[Path], None]:
    """An edit that replaces the regular file at ``path`` with a gitlink to HEAD."""

    def edit(repo: Path) -> None:
        head = git(repo, "rev-parse", "HEAD").strip()
        git(repo, "rm", "-q", "--cached", "--", path)
        (repo / path).unlink()
        git(repo, "update-index", "--add", "--cacheinfo", f"160000,{head},{path}")

    return edit


def assert_refused_before_any_merge(repo: Path, before: str, calls: list[list[str]]) -> None:
    """A pre-flight refusal: no git merge ran, HEAD stayed put, the checkout is clean."""
    assert calls == []
    assert git(repo, "rev-parse", "HEAD").strip() == before
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / ".git" / "MERGE_HEAD").exists()


def test_retry_read_retries_a_transient_failure(monkeypatch, tmp_path):
    # one transient read failure (the git fetch class) must retry a bounded
    # number of times before raising, so a single blip does not red the merge
    monkeypatch.setattr(automerge, "_RETRY_DELAYS", (0, 0))
    calls = 0

    def flaky_run(self, cmd, cwd):
        nonlocal calls
        if " ".join(cmd).startswith("git fetch"):
            calls += 1
            if calls == 1:
                raise pr.PrError(
                    "fatal: unable to access 'https://github.com': Could not resolve host"
                )
            return "fetched\n"
        raise AssertionError(f"unscripted command: {cmd}")

    monkeypatch.setattr(pr.PrRunner, "run", flaky_run)
    assert (
        automerge._retry_read(pr.PrRunner(), tmp_path, ["git", "fetch", "origin", "main"])
        == "fetched\n"
    )
    assert calls == 2


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
    # every merge commit has two parents: each branch head is an ancestor of
    # the pushed head, which the branch-ref deletion closes the PR against
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


def test_merge_lands_a_row_whose_name_has_a_line_separator(tmp_path):
    # a raw U+2028 inside a provenance name must not tear one branch row into
    # two ndjson lines, so the burst merge lands it as one row
    repo, bare = build_repo(tmp_path)
    row = make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.44)
    row["provenance"]["name"] = "x y"
    make_branch(
        repo,
        "pricelog/alpha-00000000",
        [row],
        announce_texts={"deepseek": {"https://example.com/u": "new"}},
    )
    automerge.merge_branches(["pricelog/alpha-00000000"], repo, pr.PrRunner(), "main", push=False)
    assert store.load(repo / "data" / "history" / "deepseek.ndjson") == [
        make_row("deepseek", "deepseek-v4-pro", "2026-08-30", 0.435),
        row,
    ]


def test_merge_keeps_a_newer_base_announce_channel_over_a_stale_branch(tmp_path):
    # a branch cut before a later landed refresh carries the older snapshot
    # for a channel; the merge must not revert the base's newer prose
    # (observed 2026-09-21: PR 283 carried the 09-18 scaleway snapshot while
    # mommy had refreshed it on 09-21)
    repo, _bare = build_repo(tmp_path)
    url = "https://example.com/changelog"
    commit_announce(repo, {"scaleway": {url: "old prose"}}, "2026-09-18")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/alpha-00000000",
        [make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.44)],
        announce_texts={"scaleway": {url: "old prose"}},
        announce_fetched="2026-09-18",
    )
    # the base advances past the branch: a later run refreshed the channel
    commit_announce(repo, {"scaleway": {url: "new prose"}}, "2026-09-21")
    git(repo, "push", "origin", "main")

    automerge.merge_branches(["pricelog/alpha-00000000"], repo, pr.PrRunner(), "main", push=False)

    index = json.loads((repo / "state" / "announce" / "index.json").read_text(encoding="utf-8"))
    channel_file = index["scaleway"][url]["file"]
    assert (repo / channel_file).read_text(encoding="utf-8") == announce.wrap("new prose")


def test_merge_lands_a_branchs_newer_announce_channel_over_the_base(tmp_path):
    # the flip side: a stranded branch can carry a channel refresh newer than
    # the base's; its content lands
    repo, _bare = build_repo(tmp_path)
    url = "https://example.com/changelog"
    commit_announce(repo, {"scaleway": {url: "old prose"}}, "2026-09-18")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/alpha-00000000",
        [make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.44)],
        announce_texts={"scaleway": {url: "new prose"}},
        announce_fetched="2026-09-22",
    )

    automerge.merge_branches(["pricelog/alpha-00000000"], repo, pr.PrRunner(), "main", push=False)

    index = json.loads((repo / "state" / "announce" / "index.json").read_text(encoding="utf-8"))
    channel_file = index["scaleway"][url]["file"]
    assert (repo / channel_file).read_text(encoding="utf-8") == announce.wrap("new prose")


def test_merge_keeps_a_channel_the_base_gained_since_the_branch_was_cut(tmp_path):
    # a channel the base gained after the branch was cut (a later run added it
    # to the config) must survive the burst merge, not be pruned as a url the
    # newest branch's index no longer lists
    repo, _bare = build_repo(tmp_path)
    url = "https://example.com/changelog"
    commit_announce(repo, {"scaleway": {url: "old prose"}}, "2026-09-18")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/alpha-00000000",
        [make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.44)],
        announce_texts={"scaleway": {url: "old prose"}},
        announce_fetched="2026-09-18",
    )
    # the base gains a new channel after the branch was cut
    new_url = "https://example.com/new-channel"
    commit_announce(
        repo,
        {"scaleway": {url: "old prose"}, "together": {new_url: "new channel prose"}},
        "2026-09-21",
    )
    git(repo, "push", "origin", "main")

    automerge.merge_branches(["pricelog/alpha-00000000"], repo, pr.PrRunner(), "main", push=False)

    index = json.loads((repo / "state" / "announce" / "index.json").read_text(encoding="utf-8"))
    assert index["together"][new_url]["file"]
    channel_file = index["together"][new_url]["file"]
    assert (repo / channel_file).read_text(encoding="utf-8") == announce.wrap("new channel prose")


def test_merge_drops_a_channel_every_branch_deleted(tmp_path):
    # the config dropped a channel the base still holds: every branch cut after
    # the drop deletes the channel's file and index entry, so the merged tree
    # lacks it and the merge must land the deletion, never re-write the base's
    # stale copy into the deleted directory
    repo, _bare = build_repo(tmp_path)
    url = "https://example.com/changelog"
    commit_announce(repo, {"scaleway": {url: "old prose"}}, "2026-09-18")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/alpha-00000000",
        [make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.44)],
        announce_texts={},
    )

    automerge.merge_branches(["pricelog/alpha-00000000"], repo, pr.PrRunner(), "main", push=False)

    index = json.loads((repo / "state" / "announce" / "index.json").read_text(encoding="utf-8"))
    assert "scaleway" not in index
    assert not (repo / "state" / "announce" / "scaleway").exists()
    assert any('"deepseek-v4-pro"' in line for line in shard_lines(repo))


def test_merge_holds_a_needs_human_channel_at_the_base_copy(tmp_path):
    # a channel the pass flagged needs-human must not land via a yes-marked
    # sibling carrying the same fresh snapshot: the merge holds it at the
    # base copy until a ruling lands
    repo, _bare = build_repo(tmp_path)
    url = "https://example.com/changelog"
    commit_announce(repo, {"perplexity": {url: "old prose"}}, "2026-10-15")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/alpha-00000000",
        [make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.44)],
        announce_texts={"perplexity": {url: "new prose"}},
        announce_fetched="2026-10-16",
    )
    make_branch(
        repo,
        "pricelog/beta-11111111",
        [make_row("deepseek", "deepseek-v4-flash", "2026-08-31", 0.05)],
        announce_texts={"perplexity": {url: "new prose"}},
        announce_fetched="2026-10-16",
    )

    automerge.merge_branches(
        ["pricelog/beta-11111111"],
        repo,
        pr.PrRunner(),
        "main",
        push=False,
        held_channels=frozenset({("perplexity", url)}),
    )

    index = json.loads((repo / "state" / "announce" / "index.json").read_text(encoding="utf-8"))
    assert index["perplexity"][url]["sha256"] == announce._sha256("old prose")
    channel_file = index["perplexity"][url]["file"]
    assert (repo / channel_file).read_text(encoding="utf-8") == announce.wrap("old prose")


def test_merge_refreshes_the_committed_readme_stats(tmp_path):
    # the burst appends rows, so the committed README stats are stale by
    # construction; the pushed head must carry the recomputed README or ci on
    # the merge commit reds the stats recompute test (observed 2026-09-11,
    # 39c8ee4 -> 6be85a9)
    repo, _bare = build_repo(tmp_path)
    make_branch(
        repo,
        "pricelog/alpha-00000000",
        [make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.44)],
    )
    _sha, results = automerge.merge_branches(
        ["pricelog/alpha-00000000"], repo, pr.PrRunner(), "main", push=False
    )

    # the pushed HEAD carries the recomputed stats, not just the worktree
    readme = git(repo, "show", "HEAD:README.md")
    rows = store.load_shards(repo / store.SHARD_DIR)
    mapping = models.load_models(repo / models.MODELS_FILE)
    assert stats.render(readme, stats.compute(rows, mapping)) == readme
    # the refresh rides the final merge commit: the push stays one merge
    # commit per branch and the tip keeps the branch subject
    assert git(repo, "log", "-1", "--format=%s").strip() == "feat: pricelog/alpha-00000000"
    assert len(git(repo, "log", "--merges", "--format=%P").splitlines()) == 1
    assert results[-1].commit == git(repo, "rev-parse", "HEAD").strip()


def test_merge_skips_the_amend_when_the_stats_did_not_drift(tmp_path):
    # the drift guard is load-bearing: an amend with nothing staged still
    # rewrites the final merge commit (new sha), so a guardless merge would
    # add a spurious second commit on every stats-stable branch
    repo, _bare = build_repo(tmp_path)
    url = "https://example.com/notes"
    commit_announce(repo, {"deepseek": {url: "old prose"}}, "2026-09-09")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/announce-00000000",
        [],
        announce_texts={"deepseek": {url: "new prose"}},
    )
    base = git(repo, "rev-parse", "main").strip()
    branch_commits = git(
        repo, "rev-list", "--count", f"{base}..origin/pricelog/announce-00000000"
    ).strip()

    automerge.merge_branches(
        ["pricelog/announce-00000000"], repo, pr.PrRunner(), "main", push=False
    )

    # the merge adds exactly its one commit on top of the branch's own; a
    # spurious amend would rewrite the merge commit and leave it as HEAD@{1}
    expected = str(int(branch_commits) + 1)
    assert git(repo, "rev-list", "--count", f"{base}..HEAD").strip() == expected
    assert git(repo, "rev-parse", "HEAD@{1}").strip() == base


def test_merge_names_a_broken_readme_marker_refusal(tmp_path):
    # a committed README whose stats markers no longer pair stops the merge
    # with the repo's named refusal, never a raw traceback
    repo, _bare = build_repo(tmp_path)
    make_branch(
        repo,
        "pricelog/alpha-00000000",
        [make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.44)],
    )
    (repo / "README.md").write_text("<!-- stats:start --><!-- stats:end -->\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "break the stats markers")

    with pytest.raises(automerge.AutoMergeError, match="refreshing the README stats failed"):
        automerge.merge_branches(
            ["pricelog/alpha-00000000"], repo, pr.PrRunner(), "main", push=False
        )


def test_merge_sanitizes_a_literal_newline_escape_subject(tmp_path):
    # the pass's hand-edit commits can carry their message as one line with
    # literal \n\n escapes (a double-escaped -m); the merge commit must keep
    # the true subject line, never forward the escapes to git
    repo, _bare = build_repo(tmp_path)
    make_branch(
        repo,
        "pricelog/alpha-00000000",
        [make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.44)],
    )
    git(repo, "switch", "pricelog/alpha-00000000")
    git(
        repo,
        "commit",
        "--amend",
        "-m",
        "fix: correct transient rates\\n\\nCo-Authored-By: Claude Code <noreply@anthropic.com>",
    )
    git(repo, "push", "--force-with-lease", "origin", "pricelog/alpha-00000000")
    git(repo, "switch", "main")
    assert "\\n" in git(repo, "log", "-1", "--format=%s", "pricelog/alpha-00000000")

    automerge.merge_branches(["pricelog/alpha-00000000"], repo, pr.PrRunner(), "main", push=False)

    assert git(repo, "log", "-1", "--format=%s").strip() == "fix: correct transient rates"


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


def test_merge_does_not_restore_a_catalog_entry_head_deleted(tmp_path):
    # a branch cut before the base dropped a catalog entry still carries it
    # (the #1053 shape over the post-R6 catalog): the branch's own seed lands,
    # the deleted entry must not come back
    repo, _bare = build_repo(tmp_path)
    catalog = models.load_models(repo / models.MODELS_FILE)
    catalog["baseten/x"] = {"vendor": None, "curated": False, "sources": {"baseten": ["x"]}}
    models.save_models(catalog, repo / models.MODELS_FILE)
    git(repo, "add", models.MODELS_FILE)
    git(repo, "commit", "-m", "seed baseten")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/alpha-00000000",
        [],
        catalog_models={
            "digitalocean/own": {
                "vendor": None,
                "curated": False,
                "sources": {"digitalocean": ["own"]},
            }
        },
    )
    catalog = models.load_models(repo / models.MODELS_FILE)
    del catalog["baseten/x"]
    models.save_models(catalog, repo / models.MODELS_FILE)
    git(repo, "add", models.MODELS_FILE)
    git(repo, "commit", "-m", "drop baseten")
    git(repo, "push", "origin", "main")

    automerge.merge_branches(["pricelog/alpha-00000000"], repo, pr.PrRunner(), "main", push=False)

    merged = json.loads((repo / models.MODELS_FILE).read_text(encoding="utf-8"))["models"]
    assert "baseten/x" not in merged
    assert "digitalocean/own" in merged
    assert merged["deepseek/deepseek-v4-pro"]["sources"] == {"deepseek": ["deepseek-v4-pro"]}
    assert git(repo, "status", "--porcelain") == ""


def test_merge_lands_a_branch_added_catalog_entry(tmp_path):
    repo, _bare = build_repo(tmp_path)
    entry = {"vendor": "vendor", "curated": False, "sources": {"vendor": ["new"]}}
    make_branch(repo, "pricelog/alpha-11111111", [], catalog_models={"vendor/new": entry})

    automerge.merge_branches(["pricelog/alpha-11111111"], repo, pr.PrRunner(), "main", push=False)

    merged = json.loads((repo / models.MODELS_FILE).read_text(encoding="utf-8"))["models"]
    assert merged["vendor/new"] == entry
    assert git(repo, "status", "--porcelain") == ""


def test_merge_lands_a_branch_edited_catalog_entry(tmp_path):
    # an entry the branch changed since its merge base lands with the branch's
    # bytes; the claim guard only skips an entry HEAD's catalog already claims
    repo, _bare = build_repo(tmp_path)
    catalog = models.load_models(repo / models.MODELS_FILE)
    catalog["vendor/one"] = {"vendor": "vendor", "curated": False, "sources": {"a": ["one"]}}
    models.save_models(catalog, repo / models.MODELS_FILE)
    git(repo, "add", models.MODELS_FILE)
    git(repo, "commit", "-m", "seed vendor/one")
    git(repo, "push", "origin", "main")
    edited = {"vendor": "vendor", "curated": True, "sources": {"b": ["one-v2"]}}
    make_branch(repo, "pricelog/alpha-22222222", [], catalog_models={"vendor/one": edited})

    automerge.merge_branches(["pricelog/alpha-22222222"], repo, pr.PrRunner(), "main", push=False)

    merged = json.loads((repo / models.MODELS_FILE).read_text(encoding="utf-8"))["models"]
    assert merged["vendor/one"] == edited
    assert git(repo, "status", "--porcelain") == ""


def test_merge_burst_lands_a_seed_that_is_another_branchs_base_entry(tmp_path):
    # one branch's new entry is another branch's base entry: the older branch
    # carries it unchanged and decides nothing, the seeding branch lands it
    repo, _bare = build_repo(tmp_path)
    entry = {"vendor": "vendor", "curated": False, "sources": {"vendor": ["one"]}}
    catalog = models.load_models(repo / models.MODELS_FILE)
    catalog["vendor/one"] = entry
    models.save_models(catalog, repo / models.MODELS_FILE)
    git(repo, "add", models.MODELS_FILE)
    git(repo, "commit", "-m", "seed vendor/one")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/beta-22222222",
        [make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.44)],
    )
    catalog = models.load_models(repo / models.MODELS_FILE)
    del catalog["vendor/one"]
    models.save_models(catalog, repo / models.MODELS_FILE)
    git(repo, "add", models.MODELS_FILE)
    git(repo, "commit", "-m", "drop vendor/one")
    git(repo, "push", "origin", "main")
    make_branch(repo, "pricelog/alpha-33333333", [], catalog_models={"vendor/one": entry})

    automerge.merge_branches(
        ["pricelog/beta-22222222", "pricelog/alpha-33333333"],
        repo,
        pr.PrRunner(),
        "main",
        push=False,
    )

    merged = json.loads((repo / models.MODELS_FILE).read_text(encoding="utf-8"))["models"]
    claims = [
        canonical
        for canonical, model in merged.items()
        for source, ids in model["sources"].items()
        for model_id in ids
        if (source, model_id) == ("vendor", "one")
    ]
    assert claims == ["vendor/one"]
    assert merged["vendor/one"] == entry
    assert git(repo, "status", "--porcelain") == ""


def test_merge_reads_a_missing_merge_base_catalog_as_empty(tmp_path):
    # a branch whose merge base carries no data/catalog/models.json counts
    # every entry it carries as added against an empty base: the merge lands them
    repo, _bare = build_repo(tmp_path)
    git(repo, "rm", "-q", models.MODELS_FILE)
    git(repo, "commit", "-m", "drop the catalog")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/alpha-44444444",
        [make_row("zai", "glm-5", "2026-08-31", 0.1)],
    )
    head_entry = {"vendor": "vendor", "curated": True, "sources": {"a": ["one"]}}
    models.save_models({"vendor/one": head_entry}, repo / models.MODELS_FILE)
    git(repo, "add", models.MODELS_FILE)
    git(repo, "commit", "-m", "seed vendor/one")
    git(repo, "push", "origin", "main")

    automerge.merge_branches(["pricelog/alpha-44444444"], repo, pr.PrRunner(), "main", push=False)

    merged = json.loads((repo / models.MODELS_FILE).read_text(encoding="utf-8"))["models"]
    assert merged["vendor/one"] == head_entry
    assert merged["zai/glm-5"]["sources"] == {"zai": ["glm-5"]}
    assert git(repo, "status", "--porcelain") == ""


def test_merge_refuses_a_branch_deleting_the_catalog(tmp_path, monkeypatch):
    # _union_models json-parses the branch's catalog copy, where a deleted file
    # reads as empty text and dies with a traceback after git merge staged; the
    # refusal reads the deletion from the branch's diff and runs before any merge
    repo, _bare = build_repo(tmp_path)
    delete_on_branch(repo, "pricelog/del-11111111", models.MODELS_FILE)
    before = git(repo, "rev-parse", "main").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(
        automerge.AutoMergeError,
        match=r"pricelog/del-11111111: deletes \['data/catalog/models.json'\]",
    ):
        automerge.merge_branches(["pricelog/del-11111111"], repo, pr.PrRunner(), "main", push=False)

    assert calls == []
    assert git(repo, "rev-parse", "main").strip() == before
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / ".git" / "MERGE_HEAD").exists()


@pytest.mark.parametrize("path", [BILLING_RULES_FILE, "data/history/deepseek.ndjson"])
def test_merge_refuses_a_branch_deleting_a_parsed_pipeline_file(tmp_path, monkeypatch, path):
    # the catalog crash's class: the branch-side text of each of these reaches a
    # parser (json.loads for the billing rules, store.parse for the shard lines),
    # so a deleted file reads as empty there too and gets the same refusal
    repo, _bare = build_repo(tmp_path)
    delete_on_branch(repo, "pricelog/del-22222222", path)
    calls = merge_spy(monkeypatch)

    with pytest.raises(
        automerge.AutoMergeError,
        match=rf"pricelog/del-22222222: deletes \['{re.escape(path)}'\]",
    ):
        automerge.merge_branches(["pricelog/del-22222222"], repo, pr.PrRunner(), "main", push=False)

    assert calls == []
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / ".git" / "MERGE_HEAD").exists()


def test_merge_refuses_a_branch_deleting_the_announce_index(tmp_path, monkeypatch):
    # the branch's announce index is json-parsed (_announce_index), and nothing
    # the pipeline writes deletes it: a deleting branch would land the deletion
    # and the store would lose the url set the announce resolution reads
    repo, _bare = build_repo(tmp_path)
    delete_on_branch(repo, "pricelog/del-77777771", "state/announce/index.json")
    calls = merge_spy(monkeypatch)

    with pytest.raises(
        automerge.AutoMergeError,
        match=r"pricelog/del-77777771: deletes \['state/announce/index.json'\]",
    ):
        automerge.merge_branches(["pricelog/del-77777771"], repo, pr.PrRunner(), "main", push=False)

    assert calls == []
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / ".git" / "MERGE_HEAD").exists()


def test_merge_refuses_a_burst_before_any_branch_merges(tmp_path, monkeypatch):
    # the pre-flight runs over the whole burst, so a deleting branch stops the
    # run before the sibling ahead of it lands anything
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/first-33333331", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    delete_on_branch(repo, "pricelog/second-33333332", models.MODELS_FILE)
    before = git(repo, "rev-parse", "main").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(
        automerge.AutoMergeError,
        match=r"pricelog/second-33333332: deletes",
    ):
        automerge.merge_branches(
            ["pricelog/first-33333331", "pricelog/second-33333332"],
            repo,
            pr.PrRunner(),
            "main",
            push=False,
        )

    assert calls == []
    assert git(repo, "rev-parse", "main").strip() == before
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / ".git" / "MERGE_HEAD").exists()


def test_merge_lands_a_branch_deleting_an_absence_file(tmp_path, monkeypatch):
    # the refusal's boundary: an absence file's branch-side text is never parsed
    # and save_absence deletes a cleared source's file, so that deletion keeps
    # merging; the spy's one recorded merge proves the zero side is not vacuous
    repo, _bare = build_repo(tmp_path)
    absence.save_absence({"deepseek": {"deepseek/deepseek-v4-pro": {}}}, repo)
    git(repo, "add", "state/absence")
    git(repo, "commit", "-m", "absence snapshot")
    git(repo, "push", "origin", "main")
    delete_on_branch(repo, "pricelog/absdel-44444444", "state/absence/deepseek.json")
    calls = merge_spy(monkeypatch)

    _, results = automerge.merge_branches(
        ["pricelog/absdel-44444444"], repo, pr.PrRunner(), "main", push=False
    )

    assert len(calls) == 1
    assert [r.appended for r in results] == [0]
    assert not (repo / "state" / "absence" / "deepseek.json").exists()
    assert git(repo, "status", "--porcelain") == ""


def test_merge_refuses_a_branch_renaming_a_shard(tmp_path, monkeypatch):
    # with --no-renames a rename reads as the old path's deletion: the rows a
    # source-named shard holds would leave the store under the new name silently
    repo, _bare = build_repo(tmp_path)
    git(repo, "switch", "-c", "pricelog/mv-88888881")
    git(repo, "mv", "data/history/deepseek.ndjson", "data/history/renamed.ndjson")
    git(repo, "commit", "-m", "rename the shard")
    git(repo, "push", "origin", "pricelog/mv-88888881")
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")
    calls = merge_spy(monkeypatch)

    with pytest.raises(
        automerge.AutoMergeError,
        match=r"pricelog/mv-88888881: deletes \['data/history/deepseek.ndjson'\]",
    ):
        automerge.merge_branches(["pricelog/mv-88888881"], repo, pr.PrRunner(), "main", push=False)

    assert calls == []
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / ".git" / "MERGE_HEAD").exists()


def test_merge_does_not_read_a_head_gained_catalog_as_a_branch_deletion(tmp_path):
    # the deletion pre-flight reads the branch's diff against its merge base:
    # a catalog HEAD gained since the branch forked is HEAD's gain, never the
    # branch's deletion, so the branch merges instead of false-refusing
    repo, _bare = build_repo(tmp_path)
    git(repo, "rm", "-q", models.MODELS_FILE)
    git(repo, "commit", "-m", "drop the catalog")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/late-66666661",
        [make_row("zai", "glm-5", "2026-08-31", 0.1)],
        auto_seed=False,
    )
    head_entry = {"vendor": "zai", "curated": True, "sources": {"zai": ["glm-5"]}}
    models.save_models({"zai/glm-5": head_entry}, repo / models.MODELS_FILE)
    git(repo, "add", models.MODELS_FILE)
    git(repo, "commit", "-m", "seed zai/glm-5")
    git(repo, "push", "origin", "main")

    _, results = automerge.merge_branches(
        ["pricelog/late-66666661"], repo, pr.PrRunner(), "main", push=False
    )

    assert [r.appended for r in results] == [1]
    merged = json.loads((repo / models.MODELS_FILE).read_text(encoding="utf-8"))["models"]
    assert merged["zai/glm-5"] == head_entry
    assert git(repo, "status", "--porcelain") == ""


def test_merge_refuses_a_branch_deleting_the_billing_pin(tmp_path, monkeypatch):
    # the merge rewrites the pin from HEAD's copy and stages it by path, so a
    # branch deleting it fails the by-path git add after git merge staged the
    # deletion; the pre-flight refuses it by name before any merge
    repo, _bare = build_repo(tmp_path)
    pin = "tests/test_billing_rules.py"
    delete_on_branch(repo, "pricelog/pindel-55555551", pin)
    before = git(repo, "rev-parse", "main").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(
        automerge.AutoMergeError,
        match=rf"pricelog/pindel-55555551: deletes \['{re.escape(pin)}'\]",
    ):
        automerge.merge_branches(
            ["pricelog/pindel-55555551"], repo, pr.PrRunner(), "main", push=False
        )

    assert calls == []
    assert git(repo, "rev-parse", "main").strip() == before
    assert (repo / pin).is_file()
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / ".git" / "MERGE_HEAD").exists()


def test_merge_refuses_a_branch_renaming_an_outside_file_into_the_pipeline(tmp_path, monkeypatch):
    # rename detection would hide the old path: the outside check would see
    # only the pipeline destination and main's schema would vanish as the
    # rename's other half; the --no-renames read names the old path as a change
    # outside the pipeline set
    repo, _bare = build_repo(tmp_path)
    schema = "data/schema/row.v4.json"
    git(repo, "switch", "-c", "pricelog/mvout-99999991")
    (repo / "state" / "absence").mkdir()
    git(repo, "mv", schema, "state/absence/row.json")
    git(repo, "commit", "-m", "rename the schema into the absence tree")
    git(repo, "push", "origin", "pricelog/mvout-99999991")
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")
    before = git(repo, "rev-parse", "main").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(
        automerge.AutoMergeError,
        match=rf"pricelog/mvout-99999991: changes \['{re.escape(schema)}'\]",
    ):
        automerge.merge_branches(
            ["pricelog/mvout-99999991"], repo, pr.PrRunner(), "main", push=False
        )

    assert calls == []
    assert git(repo, "rev-parse", "main").strip() == before
    assert (repo / schema).is_file()
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / ".git" / "MERGE_HEAD").exists()


ENTRY_SHAPE = (
    "entry 'x/y' must be an object whose 'sources' map each source to one id or a list of ids"
)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "is not valid json: Expecting value"),
        ("not json{", "is not valid json: Expecting value"),
        ("[]", "must carry a 'models' object"),
        ('{"version": 4}', "must carry a 'models' object"),
        ('{"models": null}', "must carry a 'models' object"),
        ('{"version": 4, "models": {"x/y": "an entry"}}', ENTRY_SHAPE),
        ('{"version": 4, "models": {"x/y": {"sources": 5}}}', ENTRY_SHAPE),
        (
            '{"version": 4, "models": {"x/y": {"vendor": "x", "curated": false,'
            ' "sources": {"x": 5}}}}',
            ENTRY_SHAPE,
        ),
        (
            '{"version": 4, "models": {"x/y": {"vendor": "x", "curated": false,'
            ' "sources": {"x": [5]}}}}',
            ENTRY_SHAPE,
        ),
    ],
    ids=[
        "emptied",
        "not-json",
        "not-an-object",
        "models-missing",
        "models-null",
        "entry-not-an-object",
        "sources-not-a-dict",
        "ids-not-a-list",
        "ids-not-strings",
    ],
)
def test_merge_refuses_a_branch_whose_catalog_does_not_read(tmp_path, monkeypatch, text, reason):
    # _union_models walks the branch's catalog after git merge staged: an
    # emptied copy (a change, not a deletion) or an entry the union cannot walk
    # would die there, so the pre-flight parses the copy and refuses by name
    repo, _bare = build_repo(tmp_path)
    commit_on_branch(repo, "pricelog/cat-00000001", write_file(models.MODELS_FILE, text))
    before = git(repo, "rev-parse", "HEAD").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(["pricelog/cat-00000001"], repo, pr.PrRunner(), "main", push=False)

    assert str(excinfo.value) == (
        f"branch pricelog/cat-00000001: data/catalog/models.json {reason};"
        " fix: correct the named copy on the branch, or close the PR"
    )
    assert_refused_before_any_merge(repo, before, calls)


def test_merge_lands_a_branch_entry_naming_its_id_as_a_string(tmp_path):
    # the catalog parse's boundary: a source mapping to one id as a bare
    # string is the catalog contract's other id shape, so the branch merges
    repo, _bare = build_repo(tmp_path)
    catalog = json.loads((repo / models.MODELS_FILE).read_text(encoding="utf-8"))
    entry = {"vendor": "zai", "curated": True, "sources": {"zai": "glm-5"}}
    catalog["models"]["zai/glm-5"] = entry
    commit_on_branch(
        repo, "pricelog/strid-00000001", write_file(models.MODELS_FILE, json.dumps(catalog))
    )

    _sha, results = automerge.merge_branches(
        ["pricelog/strid-00000001"], repo, pr.PrRunner(), "main", push=False
    )

    assert [r.branch for r in results] == ["pricelog/strid-00000001"]
    merged = json.loads((repo / models.MODELS_FILE).read_text(encoding="utf-8"))["models"]
    assert merged["zai/glm-5"] == entry
    assert git(repo, "status", "--porcelain") == ""


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("not json{\n", "is not valid json: Expecting value"),
        ("[]", "must carry a 'models' object"),
        ('{"version": 4, "models": {"x/y": "an entry"}}', ENTRY_SHAPE),
    ],
    ids=["not-json", "not-an-object", "entry-not-an-object"],
)
def test_merge_refuses_a_branch_whose_merge_base_catalog_does_not_read(
    tmp_path, monkeypatch, text, reason
):
    # _union_models also json-parses the merge base's catalog when the branch
    # changes its own; a branch cut from a commit whose copy does not read
    # would die after git merge staged, even with HEAD's copy repaired since
    repo, _bare = build_repo(tmp_path)
    good = (repo / models.MODELS_FILE).read_text(encoding="utf-8")
    (repo / models.MODELS_FILE).write_text(text, encoding="utf-8")
    git(repo, "commit", "-am", "break the catalog")
    git(repo, "push", "origin", "main")
    commit_on_branch(repo, "pricelog/mb-00000001", write_file(models.MODELS_FILE, good))
    (repo / models.MODELS_FILE).write_text(good, encoding="utf-8")
    git(repo, "commit", "-am", "repair the catalog")
    git(repo, "push", "origin", "main")
    before = git(repo, "rev-parse", "HEAD").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(["pricelog/mb-00000001"], repo, pr.PrRunner(), "main", push=False)

    assert str(excinfo.value) == (
        f"branch pricelog/mb-00000001's merge base: data/catalog/models.json {reason};"
        " fix: rebase the branch onto a base whose copy parses, or close the PR"
    )
    assert_refused_before_any_merge(repo, before, calls)


def test_merge_refuses_a_branch_whose_merge_base_catalog_is_not_utf8(tmp_path, monkeypatch):
    # the pre-flight decodes the merge base's catalog copy, so bytes there that
    # are not UTF-8 text stop the run by name; both tips carry a repaired copy
    # and only the commit they descend from holds the undecodable bytes
    repo, _bare = build_repo(tmp_path)
    good = (repo / models.MODELS_FILE).read_text(encoding="utf-8")
    (repo / models.MODELS_FILE).write_bytes(b"\xff\n")
    git(repo, "commit", "-am", "break the catalog")
    git(repo, "push", "origin", "main")
    commit_on_branch(repo, "pricelog/mb-00000001", write_file(models.MODELS_FILE, good))
    (repo / models.MODELS_FILE).write_text(good, encoding="utf-8")
    git(repo, "commit", "-am", "repair the catalog")
    git(repo, "push", "origin", "main")
    sha = git(repo, "merge-base", "HEAD", "origin/pricelog/mb-00000001").strip()[:7]
    before = git(repo, "rev-parse", "HEAD").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(["pricelog/mb-00000001"], repo, pr.PrRunner(), "main", push=False)

    assert str(excinfo.value) == (
        f"branch pricelog/mb-00000001's merge base: {sha}:data/catalog/models.json"
        " is not UTF-8 text (invalid start byte at byte 0); fix: rebase the branch onto"
        " a base whose copy parses, or close the PR"
    )
    assert_refused_before_any_merge(repo, before, calls)


def test_merge_refuses_a_branch_catalog_entry_unchanged_from_a_junk_merge_base(
    tmp_path, monkeypatch
):
    # _check_carried_claims parses every branch's catalog, changed or not, so a
    # branch cut from a base whose entry is junk reads through the same parse
    # even though its own diff never names the catalog
    repo, _bare = build_repo(tmp_path)
    good = (repo / models.MODELS_FILE).read_text(encoding="utf-8")
    (repo / models.MODELS_FILE).write_text(
        '{"version": 4, "models": {"x/y": "an entry"}}\n', encoding="utf-8"
    )
    git(repo, "commit", "-am", "junk catalog on the base")
    git(repo, "push", "origin", "main")
    git(repo, "switch", "-c", "pricelog/junkbase-00000001")
    store.save_shard(
        store.load_shard(repo / "data" / "history", "deepseek")
        + [make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.44)],
        repo / "data" / "history",
        "deepseek",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "append a row")
    git(repo, "push", "origin", "pricelog/junkbase-00000001")
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")
    (repo / models.MODELS_FILE).write_text(good, encoding="utf-8")
    git(repo, "commit", "-am", "repair the catalog")
    git(repo, "push", "origin", "main")
    before = git(repo, "rev-parse", "HEAD").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(
            ["pricelog/junkbase-00000001"], repo, pr.PrRunner(), "main", push=False
        )

    assert str(excinfo.value) == (
        "branch pricelog/junkbase-00000001: data/catalog/models.json entry 'x/y' must"
        " be an object whose 'sources' map each source to one id or a list of ids;"
        " fix: correct the named copy on the branch, or close the PR"
    )
    assert_refused_before_any_merge(repo, before, calls)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "is not valid json: Expecting value"),
        ("not json{", "is not valid json: Expecting value"),
        ("{}", "must carry a 'rules' list"),
        ('{"rules": null}', "must carry a 'rules' list"),
        ('["a list"]', "must carry a 'rules' list"),
        ('{"rules": [1]}', "rule 0 must be an object carrying a string 'id'"),
        ('{"rules": [{"id": 3}]}', "rule 0 must be an object carrying a string 'id'"),
    ],
    ids=[
        "emptied",
        "not-json",
        "no-rules-key",
        "rules-null",
        "not-an-object",
        "rule-not-an-object",
        "id-not-a-string",
    ],
)
def test_merge_refuses_a_branch_whose_billing_rules_do_not_read(
    tmp_path, monkeypatch, text, reason
):
    # _union_billing_rules json-parses the branch's copy after git merge
    # staged, so a copy that does not read as a rules list refuses by name first
    repo, _bare = build_repo(tmp_path)
    commit_on_branch(repo, "pricelog/rules-00000001", write_file(BILLING_RULES_FILE, text))
    before = git(repo, "rev-parse", "HEAD").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(
            ["pricelog/rules-00000001"], repo, pr.PrRunner(), "main", push=False
        )

    assert str(excinfo.value) == (
        f"branch pricelog/rules-00000001: data/catalog/billing-rules.json {reason};"
        " fix: correct the named copy on the branch, or close the PR"
    )
    assert_refused_before_any_merge(repo, before, calls)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("not json{\n", "is not valid json: Expecting value"),
        ("{}", "must carry a 'rules' list"),
        ('{"rules": null}', "must carry a 'rules' list"),
    ],
    ids=["not-json", "no-rules-key", "rules-null"],
)
def test_merge_refuses_head_billing_rules_that_do_not_read(tmp_path, monkeypatch, text, reason):
    # the union parses HEAD's rules beside the branch's whenever the branch
    # changes them, so HEAD's copy parses in the pre-flight too
    repo, _bare = build_repo(tmp_path)
    rule = {"id": "zai-plan-quotas", "provider": "zai", "effective": "2026-09-01"}
    commit_on_branch(
        repo,
        "pricelog/rules-00000002",
        write_file(BILLING_RULES_FILE, json.dumps({"rules": [rule]}) + "\n"),
    )
    (repo / BILLING_RULES_FILE).write_text(text, encoding="utf-8")
    git(repo, "commit", "-am", "break the rules on the base")
    git(repo, "push", "origin", "main")
    before = git(repo, "rev-parse", "HEAD").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(
            ["pricelog/rules-00000002"], repo, pr.PrRunner(), "main", push=False
        )

    assert str(excinfo.value) == (
        f"HEAD: data/catalog/billing-rules.json {reason};"
        " fix: correct the named copy on the base branch, then re-run"
    )
    assert_refused_before_any_merge(repo, before, calls)


def _base_carries_a_channel(repo: Path) -> None:
    commit_announce(repo, {"deepseek": {"https://example.com/notes": "old prose"}}, "2026-09-09")
    git(repo, "push", "origin", "main")


def _base_carries_an_absence_file(repo: Path) -> None:
    absence.save_absence({"deepseek": {"deepseek/deepseek-v4-pro": {}}}, repo)
    git(repo, "add", "state/absence")
    git(repo, "commit", "-m", "absence snapshot")
    git(repo, "push", "origin", "main")


@pytest.mark.parametrize(
    ("path", "make_edit", "kind", "setup"),
    [
        (models.MODELS_FILE, as_symlink, "symlink", None),
        (models.MODELS_FILE, as_submodule, "submodule", None),
        (BILLING_RULES_FILE, as_symlink, "symlink", None),
        ("state/announce/index.json", as_symlink, "symlink", None),
        ("data/history/deepseek.ndjson", as_symlink, "symlink", None),
        ("tests/test_billing_rules.py", as_symlink, "symlink", None),
        ("state/announce/deepseek/notes.md", as_symlink, "symlink", _base_carries_a_channel),
        ("state/absence/deepseek.json", as_symlink, "symlink", _base_carries_an_absence_file),
    ],
    ids=[
        "catalog-symlink",
        "catalog-submodule",
        "billing-rules",
        "announce-index",
        "shard",
        "billing-pin",
        "channel-file",
        "absence-file",
    ],
)
def test_merge_refuses_a_branch_type_changing_a_file_the_merge_reads(
    tmp_path, monkeypatch, path, make_edit, kind, setup
):
    # git show prints a symlink's target and a gitlink's commit as if they were
    # file bytes, so a type change (status T) reaches a parser as garbage or
    # lands a non-file in the store; the branch's tree mode refuses it by name
    repo, _bare = build_repo(tmp_path)
    if setup is not None:
        setup(repo)
    commit_on_branch(repo, "pricelog/type-00000001", make_edit(path))
    before = git(repo, "rev-parse", "HEAD").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(
            ["pricelog/type-00000001"], repo, pr.PrRunner(), "main", push=False
        )

    assert str(excinfo.value) == (
        f"branch pricelog/type-00000001: carries ['{path} ({kind})'] as non-regular files;"
        " the merge reads or stages each from the branch side as a file's bytes;"
        " fix: commit each as a regular file on the branch, or close the PR"
    )
    assert_refused_before_any_merge(repo, before, calls)


def test_merge_refuses_a_branch_whose_index_names_an_inherited_symlink(tmp_path, monkeypatch):
    # the branch's own index names a channel file the branch never changed but
    # whose copy is a symlink: the announce resolution still reads it by path,
    # so the indexed files are type-checked as well as the changed ones
    repo, _bare = build_repo(tmp_path)
    _base_carries_a_channel(repo)
    as_symlink("state/announce/deepseek/notes.md")(repo)
    git(repo, "commit", "-m", "the channel file turns into a symlink on the base")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/inherit-00000001",
        [make_row("deepseek", "deepseek-v4-pro", "2026-09-11", 0.45)],
    )
    before = git(repo, "rev-parse", "HEAD").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(
            ["pricelog/inherit-00000001"], repo, pr.PrRunner(), "main", push=False
        )

    assert str(excinfo.value) == (
        "branch pricelog/inherit-00000001: carries ['state/announce/deepseek/notes.md"
        " (symlink)'] as non-regular files; the merge reads or stages each from the"
        " branch side as a file's bytes; fix: commit each as a regular file on the"
        " branch, or close the PR"
    )
    assert_refused_before_any_merge(repo, before, calls)


@pytest.mark.parametrize(
    ("path", "payload", "reason", "setup"),
    [
        (
            "state/announce/deepseek/notes.md",
            b"caf\xe9\n",
            "invalid continuation byte at byte 3",
            _base_carries_a_channel,
        ),
        (
            "state/absence/deepseek.json",
            b"\xff\n",
            "invalid start byte at byte 0",
            _base_carries_an_absence_file,
        ),
    ],
    ids=["channel-file", "absence-file"],
)
def test_merge_refuses_a_branch_file_that_is_not_utf8_text(
    tmp_path, monkeypatch, path, payload, reason, setup
):
    # the merge reads a channel file or an absence file from the branch side
    # as text and writes it back verbatim; bytes that do not decode would stop
    # it after git merge staged, so the pre-flight reads them first
    repo, _bare = build_repo(tmp_path)
    setup(repo)

    def write_undecodable(repo: Path) -> None:
        (repo / path).write_bytes(payload)
        git(repo, "add", "--", path)

    commit_on_branch(repo, "pricelog/bytes-00000001", write_undecodable)
    before = git(repo, "rev-parse", "HEAD").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(
            ["pricelog/bytes-00000001"], repo, pr.PrRunner(), "main", push=False
        )

    assert str(excinfo.value) == (
        f"branch pricelog/bytes-00000001: origin/pricelog/bytes-00000001:{path} is not"
        f" UTF-8 text ({reason}); fix: re-encode it as UTF-8 on the branch, or close"
        " the PR"
    )
    assert_refused_before_any_merge(repo, before, calls)


def test_merge_lands_a_branch_marking_the_catalog_executable(tmp_path):
    # the type refusal's boundary: an executable bit keeps the path a regular
    # file (mode 100755), so the branch still merges
    repo, _bare = build_repo(tmp_path)

    def make_executable(repo: Path) -> None:
        (repo / models.MODELS_FILE).chmod(0o755)
        git(repo, "add", "--", models.MODELS_FILE)

    commit_on_branch(repo, "pricelog/exec-00000001", make_executable)

    _sha, results = automerge.merge_branches(
        ["pricelog/exec-00000001"], repo, pr.PrRunner(), "main", push=False
    )

    assert [r.branch for r in results] == ["pricelog/exec-00000001"]
    assert git(repo, "ls-tree", "HEAD", "--", models.MODELS_FILE).split(" ", 1)[0] == "100755"
    assert git(repo, "status", "--porcelain") == ""


def test_merge_refuses_a_branch_without_an_index_deleting_a_channel_head_names(
    tmp_path, monkeypatch
):
    # a branch carrying no announce index skips the announce step, so its
    # deletion of a channel file HEAD's index still names would land and leave
    # that index entry pointing at nothing; the merge base carries the file but
    # no index, so the branch's missing index is no deletion of its own
    repo, _bare = build_repo(tmp_path)
    _base_carries_a_channel(repo)
    git(repo, "rm", "-q", "state/announce/index.json")
    git(repo, "commit", "-m", "drop the index from the base")
    git(repo, "push", "origin", "main")
    delete_on_branch(repo, "pricelog/noidx-00000001", "state/announce/deepseek/notes.md")
    commit_announce(repo, {"deepseek": {"https://example.com/notes": "old prose"}}, "2026-09-09")
    git(repo, "push", "origin", "main")
    before = git(repo, "rev-parse", "HEAD").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(
            ["pricelog/noidx-00000001"], repo, pr.PrRunner(), "main", push=False
        )

    assert str(excinfo.value) == (
        "branch pricelog/noidx-00000001: deletes ['state/announce/deepseek/notes.md'];"
        " the merge reads or stages these from the branch side and a deleted copy"
        " reaches it as absent or unstageable; fix: restore the file(s) on the branch,"
        " or close the PR"
    )
    assert_refused_before_any_merge(repo, before, calls)


def test_merge_refuses_a_branch_without_an_index_deleting_a_channel_a_sibling_indexes(
    tmp_path, monkeypatch
):
    # HEAD carries no index at the burst base, but a sibling branch's own index
    # lands in the same burst: its merge writes the entry, and the no-index
    # branch's later merge would leave that entry pointing at nothing
    repo, _bare = build_repo(tmp_path)
    _base_carries_a_channel(repo)
    git(repo, "rm", "-q", "state/announce/index.json")
    git(repo, "commit", "-m", "drop the index from the base")
    git(repo, "push", "origin", "main")
    git(repo, "switch", "-c", "pricelog/idx-00000001")
    commit_announce(repo, {"deepseek": {"https://example.com/notes": "old prose"}}, "2026-09-10")
    git(repo, "push", "origin", "pricelog/idx-00000001")
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")
    delete_on_branch(repo, "pricelog/noidx-00000002", "state/announce/deepseek/notes.md")
    before = git(repo, "rev-parse", "HEAD").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(
            ["pricelog/idx-00000001", "pricelog/noidx-00000002"],
            repo,
            pr.PrRunner(),
            "main",
            push=False,
        )

    assert str(excinfo.value) == (
        "branch pricelog/noidx-00000002: deletes ['state/announce/deepseek/notes.md'];"
        " the merge reads or stages these from the branch side and a deleted copy"
        " reaches it as absent or unstageable; fix: restore the file(s) on the branch,"
        " or close the PR"
    )
    assert_refused_before_any_merge(repo, before, calls)


def test_merge_lands_a_burst_whose_later_index_drops_the_deleted_channel(tmp_path):
    # a later branch's index drops the channel before the no-index branch's
    # merge, so the index in effect names no file the deletion removes
    repo, _bare = build_repo(tmp_path)
    _base_carries_a_channel(repo)
    git(repo, "rm", "-q", "state/announce/index.json")
    git(repo, "commit", "-m", "drop the index from the base")
    git(repo, "push", "origin", "main")
    git(repo, "switch", "-c", "pricelog/idx-00000001")
    commit_announce(repo, {"deepseek": {"https://example.com/notes": "old prose"}}, "2026-09-10")
    git(repo, "push", "origin", "pricelog/idx-00000001")
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")
    git(repo, "switch", "-c", "pricelog/drop-00000002")
    announce.save_snapshot({}, repo)
    git(repo, "add", "-A", "--", "state/announce")
    git(repo, "commit", "-m", "drop every channel")
    git(repo, "push", "origin", "pricelog/drop-00000002")
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")
    delete_on_branch(repo, "pricelog/noidx-00000003", "state/announce/deepseek/notes.md")

    _sha, results = automerge.merge_branches(
        ["pricelog/idx-00000001", "pricelog/drop-00000002", "pricelog/noidx-00000003"],
        repo,
        pr.PrRunner(),
        "main",
        push=False,
    )

    assert [r.branch for r in results] == [
        "pricelog/idx-00000001",
        "pricelog/drop-00000002",
        "pricelog/noidx-00000003",
    ]
    index = json.loads((repo / "state" / "announce" / "index.json").read_text(encoding="utf-8"))
    assert index == {}
    assert not (repo / "state" / "announce" / "deepseek" / "notes.md").exists()
    assert git(repo, "status", "--porcelain") == ""


def test_merge_lands_a_burst_whose_later_index_restores_the_deleted_channel(tmp_path):
    # a later sibling's index names the channel the no-index branch deletes:
    # that sibling's own merge rewrites the file, so the deletion strands no
    # index entry and the burst lands with the index naming every channel file
    # on disk. the later sibling merges after, so no index of it is in effect
    # at the deletion's merge. the source dir keeps a second channel, so the
    # deletion leaves its directory in place
    repo, _bare = build_repo(tmp_path)
    channels = {
        "deepseek": {
            "https://example.com/notes": "old prose",
            "https://example.com/updates": "update prose",
        }
    }
    commit_announce(repo, channels, "2026-09-09")
    git(repo, "rm", "-q", "state/announce/index.json")
    git(repo, "commit", "-m", "drop the index from the base")
    git(repo, "push", "origin", "main")
    delete_on_branch(repo, "pricelog/noidx-00000001", "state/announce/deepseek/notes.md")
    git(repo, "switch", "-c", "pricelog/idx-00000002")
    commit_announce(repo, channels, "2026-09-10")
    git(repo, "push", "origin", "pricelog/idx-00000002")
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")

    _sha, results = automerge.merge_branches(
        ["pricelog/noidx-00000001", "pricelog/idx-00000002"],
        repo,
        pr.PrRunner(),
        "main",
        push=False,
    )

    assert [r.branch for r in results] == [
        "pricelog/noidx-00000001",
        "pricelog/idx-00000002",
    ]
    index = json.loads((repo / "state" / "announce" / "index.json").read_text(encoding="utf-8"))
    named: set[str] = set()
    for source, urls in index.items():
        derived = announce.channel_files(source, urls.keys())
        for url, entry in urls.items():
            assert entry["file"] == derived[url]
            named.add(entry["file"])
            text = (repo / entry["file"]).read_text(encoding="utf-8")
            assert announce._sha256(announce.unwrap(text)) == entry["sha256"]
    assert named == {
        "state/announce/deepseek/notes.md",
        "state/announce/deepseek/updates.md",
    }
    on_disk = {
        path.relative_to(repo).as_posix() for path in (repo / "state" / "announce").rglob("*.md")
    }
    assert on_disk == named
    assert git(repo, "status", "--porcelain") == ""


def test_merge_lands_a_burst_whose_merged_sibling_index_does_not_read(tmp_path):
    # the skip loop drops a stranded sibling without reading its index, so a
    # no-index branch's merge finds no index to check its deletion against
    repo, _bare = build_repo(tmp_path)
    _base_carries_a_channel(repo)
    git(repo, "switch", "-c", "pricelog/stranded-00000001")
    (repo / "state" / "announce" / "index.json").write_text("not json{\n", encoding="utf-8")
    git(repo, "add", "--", "state/announce/index.json")
    git(repo, "commit", "-m", "unreadable index")
    git(repo, "push", "origin", "pricelog/stranded-00000001")
    git(repo, "switch", "main")
    git(
        repo,
        "merge",
        "--no-ff",
        "-m",
        "land the stranded branch",
        "origin/pricelog/stranded-00000001",
    )
    git(repo, "rm", "-q", "state/announce/index.json")
    git(repo, "commit", "-m", "drop the index from the base")
    git(repo, "push", "origin", "main")
    delete_on_branch(repo, "pricelog/noidx-00000002", "state/announce/deepseek/notes.md")

    _sha, results = automerge.merge_branches(
        ["pricelog/stranded-00000001", "pricelog/noidx-00000002"],
        repo,
        pr.PrRunner(),
        "main",
        push=False,
    )

    assert [r.branch for r in results] == ["pricelog/noidx-00000002"]
    assert not (repo / "state" / "announce" / "deepseek" / "notes.md").exists()
    assert git(repo, "status", "--porcelain") == ""


def test_merge_refuses_a_sibling_type_changing_its_index_before_a_no_index_branch(
    tmp_path, monkeypatch
):
    # a sibling's non-regular index lands no entry, so the no-index branch
    # before it is not checked against it; the sibling's own type check names
    # the symlink rather than reading it as bad json
    repo, _bare = build_repo(tmp_path)
    _base_carries_a_channel(repo)
    git(repo, "rm", "-q", "state/announce/index.json")
    git(repo, "commit", "-m", "drop the index from the base")
    git(repo, "push", "origin", "main")
    delete_on_branch(repo, "pricelog/noidx-00000001", "state/announce/deepseek/notes.md")

    def add_index_symlink(repo: Path) -> None:
        (repo / "state" / "announce" / "index.json").symlink_to("elsewhere")
        git(repo, "add", "--", "state/announce/index.json")

    commit_on_branch(repo, "pricelog/type-00000002", add_index_symlink)
    before = git(repo, "rev-parse", "HEAD").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(
            ["pricelog/noidx-00000001", "pricelog/type-00000002"],
            repo,
            pr.PrRunner(),
            "main",
            push=False,
        )

    assert str(excinfo.value) == (
        "branch pricelog/type-00000002: carries ['state/announce/index.json (symlink)']"
        " as non-regular files; the merge reads or stages each from the branch side"
        " as a file's bytes; fix: commit each as a regular file on the branch, or"
        " close the PR"
    )
    assert_refused_before_any_merge(repo, before, calls)


def test_merge_refuses_an_appended_row_the_contract_forbids(tmp_path, monkeypatch):
    # the pass is authorized to hand-edit a branch row, so the exact-line union
    # is the one path a contract-breaking shape can take into the store: the
    # pre-flight stops the merge naming the branch, before any git merge
    repo, _bare = build_repo(tmp_path)
    bad = make_row("zai", "glm-5", "2026-08-31", 0.1)
    bad["surprise"] = "hand edit"
    make_branch(repo, "pricelog/iota-88888888", [bad])
    before = git(repo, "rev-parse", "main").strip()
    calls = merge_spy(monkeypatch)

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
    assert_refused_before_any_merge(repo, before, calls)


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


def test_merge_refused_row_names_the_branch_line(tmp_path, monkeypatch):
    # HEAD gains a good row after the branch was cut, a line the branch's copy
    # does not carry. the bad row is then branch line 2, union line 3,
    # appended-subset line 1; the error must name line 2, before any git merge
    repo, _bare = build_repo(tmp_path)
    bad = make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.44)
    bad["surprise"] = "hand edit"
    make_branch(repo, "pricelog/beta-22222222", [bad])
    good = make_row("deepseek", "deepseek-v4-pro", "2026-08-31", 0.44)
    shard_dir = repo / "data" / "history"
    store.save_shard(store.load_shard(shard_dir, "deepseek") + [good], shard_dir, "deepseek")
    git(repo, "commit", "-am", "land a good row on the base")
    git(repo, "push", "origin", "main")
    before = git(repo, "rev-parse", "HEAD").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(
            ["pricelog/beta-22222222"], repo, pr.PrRunner(), "main", push=False
        )

    assert str(excinfo.value) == (
        "branch pricelog/beta-22222222: origin/pricelog/beta-22222222:data/history/"
        "deepseek.ndjson line 2 fails the row contract: row field(s) ['surprise']"
        " are not part of the row schema; fix: drop them, or extend the schema and"
        " bump the version. do not retry: report the error and leave every PR open"
    )
    assert len(git(repo, "show", "HEAD:data/history/deepseek.ndjson").splitlines()) == 2
    assert_refused_before_any_merge(repo, before, calls)


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


def _rule_branch(repo: Path, name: str, model_id: str, rules: list[dict], pin: int) -> None:
    """A pricelog branch carrying one row, a rules append and the bumped pin."""
    git(repo, "switch", "-c", name)
    store.save_shard(
        store.load_shard(repo / "data" / "history", "deepseek")
        + [make_row("deepseek", model_id, "2026-08-31", 0.44)],
        repo / "data" / "history",
        "deepseek",
    )
    catalog = models.load_models(repo / models.MODELS_FILE)
    catalog = {
        **catalog,
        **models.seed_entries({("deepseek", model_id)}, catalog, {}),
    }
    models.save_models(catalog, repo / models.MODELS_FILE)
    (repo / BILLING_RULES_FILE).write_text(
        json.dumps({"rules": rules}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (repo / "tests" / "test_billing_rules.py").write_text(
        f"def test_pin():\n    assert len(rules) == {pin}\n", encoding="utf-8"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", f"feat: {name}")
    git(repo, "push", "origin", name)
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")


def _rules_repo(tmp_path: Path) -> tuple[Path, list[dict]]:
    """A build_repo clone whose main carries two rules and a matching pin."""
    repo, _bare = build_repo(tmp_path)
    rules = [
        {"id": "deepseek-weekend-off-peak", "provider": "deepseek", "effective": "2026-08-23"},
        {"id": "zai-plan-quotas", "provider": "zai", "effective": "2026-09-01"},
    ]
    (repo / BILLING_RULES_FILE).write_text(
        json.dumps({"rules": rules}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (repo / "tests" / "test_billing_rules.py").write_text(
        "def test_pin():\n    assert len(rules) == 2\n", encoding="utf-8"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "rules")
    git(repo, "push", "origin", "main")
    return repo, rules


def test_merge_unions_duplicate_billing_rules_across_branches(tmp_path):
    # the pass writes the same confirmed rule onto every branch it judges
    # after the confirmation, so a burst carries identical copies of one
    # append; the union lands one, the pin matches the landed count, and the
    # staged tree carries no conflict markers
    repo, base_rules = _rules_repo(tmp_path)
    duplicate = {"id": "google-gemini-deprecation", "provider": "google", "effective": "2026-12-01"}
    _rule_branch(repo, "pricelog/alpha-00000000", "deepseek-v4-pro", [*base_rules, duplicate], 3)
    _rule_branch(repo, "pricelog/beta-11111111", "deepseek-v4-flash", [*base_rules, duplicate], 3)

    sha, results = automerge.merge_branches(
        ["pricelog/alpha-00000000", "pricelog/beta-11111111"],
        repo,
        pr.PrRunner(),
        "main",
        push=False,
    )

    assert [r.appended for r in results] == [1, 1]
    landed = json.loads(git(repo, "show", f"{sha}:{BILLING_RULES_FILE}"))
    assert [rule["id"] for rule in landed["rules"]] == [
        "deepseek-weekend-off-peak",
        "zai-plan-quotas",
        "google-gemini-deprecation",
    ]
    assert "assert len(rules) == 3" in git(repo, "show", f"{sha}:tests/test_billing_rules.py")


def test_merge_lands_two_distinct_billing_rules_and_recomputes_the_pin(tmp_path):
    repo, base_rules = _rules_repo(tmp_path)
    first = {"id": "google-gemini-deprecation", "provider": "google", "effective": "2026-12-01"}
    second = {"id": "minimax-m3-flash-tier", "provider": "minimax", "effective": "2026-11-01"}
    _rule_branch(repo, "pricelog/alpha-00000000", "deepseek-v4-pro", [*base_rules, first], 3)
    _rule_branch(repo, "pricelog/beta-11111111", "deepseek-v4-flash", [*base_rules, second], 3)

    sha, _results = automerge.merge_branches(
        ["pricelog/alpha-00000000", "pricelog/beta-11111111"],
        repo,
        pr.PrRunner(),
        "main",
        push=False,
    )

    landed = json.loads(git(repo, "show", f"{sha}:{BILLING_RULES_FILE}"))
    assert [rule["id"] for rule in landed["rules"]] == [
        "deepseek-weekend-off-peak",
        "zai-plan-quotas",
        "google-gemini-deprecation",
        "minimax-m3-flash-tier",
    ]
    assert "assert len(rules) == 4" in git(repo, "show", f"{sha}:tests/test_billing_rules.py")


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


def test_merged_branch_skipped_without_a_push(tmp_path):
    # a branch whose tip HEAD already holds (the state a failed branch-ref
    # cleanup strands: the merge landed, the PR stayed open) must skip
    # instead of red-ing every later run on "Already up to date".
    # observed 2026-11-05..06: PR 846's branch-ref cleanup failed once and
    # the open PR red-ed 30 hourly runs while 18 verified PRs piled up.
    # with --no-push the skip lands nothing and keeps the ref for the
    # pushing run to clean up
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/merged-99999999", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    # land the branch on main directly, the state a stranded PR sits in
    git(repo, "push", "origin", "origin/pricelog/merged-99999999:refs/heads/main")
    git(repo, "switch", "main")
    git(repo, "pull", "--ff-only", "origin", "main")
    head_before = git(repo, "rev-parse", "HEAD").strip()
    sha, results = automerge.merge_branches(
        ["pricelog/merged-99999999"], repo, pr.PrRunner(), "main", push=False
    )
    assert results == []
    assert sha == head_before
    assert git(repo, "rev-parse", "HEAD").strip() == head_before
    refs = git(repo, "ls-remote", "origin").splitlines()
    assert any("pricelog/merged-99999999" in ref for ref in refs)
    assert git(repo, "status", "--porcelain") == ""


def test_merged_branch_skipped_and_ref_deleted(tmp_path, capsys):
    # the pushing merge heals the stranded state: the skip deletes the
    # branch ref, which is what closes the stuck PR on github (the merge
    # push alone left PR 846 open: github does not auto-close a PR whose
    # commits land by push)
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/merged-99999998", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    git(repo, "push", "origin", "origin/pricelog/merged-99999998:refs/heads/main")
    git(repo, "switch", "main")
    git(repo, "pull", "--ff-only", "origin", "main")
    head_before = git(repo, "rev-parse", "HEAD").strip()
    sha, results = automerge.merge_branches(
        ["pricelog/merged-99999998"], repo, pr.PrRunner(), "main", push=True
    )
    assert results == []
    assert sha == head_before
    assert git(repo, "rev-parse", "HEAD").strip() == head_before
    refs = git(repo, "ls-remote", "origin").splitlines()
    assert not any("pricelog/merged-99999998" in ref for ref in refs)
    assert "skipping pricelog/merged-99999998: already merged into HEAD" in (
        capsys.readouterr().out
    )
    assert git(repo, "status", "--porcelain") == ""


def test_merged_branch_with_an_unreadable_index_is_skipped_and_ref_deleted(tmp_path, capsys):
    # a stranded PR whose tip index does not parse (a hand edit, or a merge
    # commit resolved to the base's copy) never merges: the skip path drops it
    # before any read of its index, and the ref deletion still closes the PR
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/badidx-00000009", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    git(repo, "switch", "pricelog/badidx-00000009")
    (repo / "state" / "announce" / "index.json").write_text("not json{\n")
    git(repo, "add", "state/announce/index.json")
    git(repo, "commit", "-m", "hand edit: unreadable index")
    git(repo, "push", "origin", "pricelog/badidx-00000009")
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")
    git(repo, "merge", "--no-ff", "--no-commit", "origin/pricelog/badidx-00000009")
    git(repo, "checkout", "HEAD", "--", "state/announce/index.json")
    git(repo, "commit", "-m", "land pricelog/badidx-00000009, resolved to the base index")
    git(repo, "push", "origin", "main")
    head_before = git(repo, "rev-parse", "HEAD").strip()

    sha, results = automerge.merge_branches(
        ["pricelog/badidx-00000009"], repo, pr.PrRunner(), "main", push=True
    )

    assert results == []
    assert sha == head_before
    assert git(repo, "rev-parse", "HEAD").strip() == head_before
    assert "skipping pricelog/badidx-00000009: already merged into HEAD" in (
        capsys.readouterr().out
    )
    refs = git(repo, "ls-remote", "origin").splitlines()
    assert not any("pricelog/badidx-00000009" in ref for ref in refs)
    assert git(repo, "status", "--porcelain") == ""


def test_merged_branch_with_an_unreadable_index_is_skipped_without_a_push(tmp_path, capsys):
    # the skip keys on HEAD, never origin/main: a --no-push run that landed the
    # branch locally leaves origin/main behind it, and reading that branch's
    # index there would red a run that has nothing left to merge
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/badidx-00000011", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    git(repo, "switch", "pricelog/badidx-00000011")
    (repo / "state" / "announce" / "index.json").write_text("not json{\n")
    git(repo, "add", "state/announce/index.json")
    git(repo, "commit", "-m", "hand edit: unreadable index")
    git(repo, "push", "origin", "pricelog/badidx-00000011")
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")
    git(repo, "merge", "--no-ff", "--no-commit", "origin/pricelog/badidx-00000011")
    git(repo, "checkout", "HEAD", "--", "state/announce/index.json")
    git(repo, "commit", "-m", "land pricelog/badidx-00000011 locally, resolved to the base index")
    head_before = git(repo, "rev-parse", "HEAD").strip()

    sha, results = automerge.merge_branches(
        ["pricelog/badidx-00000011"], repo, pr.PrRunner(), "main", push=False
    )

    assert results == []
    assert sha == head_before
    assert git(repo, "rev-parse", "HEAD").strip() == head_before
    assert "skipping pricelog/badidx-00000011: already merged into HEAD" in (
        capsys.readouterr().out
    )
    refs = git(repo, "ls-remote", "origin").splitlines()
    assert any("pricelog/badidx-00000011" in ref for ref in refs)
    assert git(repo, "status", "--porcelain") == ""


def test_merge_refuses_a_branch_whose_index_does_not_read(tmp_path, monkeypatch):
    # the branch-index read is skipped only for a branch HEAD already holds, so
    # a branch that will merge still stops by name before the first git merge
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/badidx-00000010", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    git(repo, "switch", "pricelog/badidx-00000010")
    (repo / "state" / "announce" / "index.json").write_text("not json{\n")
    git(repo, "add", "state/announce/index.json")
    git(repo, "commit", "-m", "hand edit: unreadable index")
    git(repo, "push", "origin", "pricelog/badidx-00000010")
    git(repo, "switch", "main")
    git(repo, "fetch", "origin")
    before = git(repo, "rev-parse", "main").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(
        automerge.AutoMergeError,
        match=r"pricelog/badidx-00000010: state/announce/index\.json is not valid json",
    ):
        automerge.merge_branches(
            ["pricelog/badidx-00000010"], repo, pr.PrRunner(), "main", push=False
        )

    assert calls == []
    assert git(repo, "rev-parse", "main").strip() == before
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / ".git" / "MERGE_HEAD").exists()


def test_partial_burst_skips_the_merged_branch(tmp_path):
    # one stuck branch must not red the burst or strand its siblings: the
    # skip drops it and the rest still merge and push
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/stuck-22222222", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    git(repo, "push", "origin", "origin/pricelog/stuck-22222222:refs/heads/main")
    git(repo, "switch", "main")
    git(repo, "pull", "--ff-only", "origin", "main")
    make_branch(repo, "pricelog/fresh-33333333", [make_row("zai", "glm-6", "2026-09-01", 0.2)])
    sha, results = automerge.merge_branches(
        ["pricelog/stuck-22222222", "pricelog/fresh-33333333"],
        repo,
        pr.PrRunner(),
        "main",
        push=True,
    )
    assert [result.branch for result in results] == ["pricelog/fresh-33333333"]
    refs = git(repo, "ls-remote", "origin").splitlines()
    assert not any("pricelog/stuck-22222222" in ref for ref in refs)
    assert not any("pricelog/fresh-33333333" in ref for ref in refs)
    assert "glm-6" in "\n".join(shard_lines(repo, "zai"))


def test_merged_branch_ref_deletion_retries(monkeypatch, tmp_path):
    # the observed failure (2026-11-05, PR 846): one failed branch-ref
    # deletion stranded a merged PR and red-ed 30 runs. a deletion blip
    # retries a bounded number of times before warning
    monkeypatch.setattr(automerge, "_RETRY_DELAYS", (0, 0))
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/merged-22222223", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    git(repo, "push", "origin", "origin/pricelog/merged-22222223:refs/heads/main")
    git(repo, "switch", "main")
    git(repo, "pull", "--ff-only", "origin", "main")
    real_run = pr.PrRunner.run
    deletes = 0

    def flaky_run(self, cmd, cwd):
        nonlocal deletes
        if "--delete" in cmd:
            deletes += 1
            if deletes == 1:
                raise pr.PrError("failed to delete ref (transient)")
        return real_run(self, cmd, cwd)

    monkeypatch.setattr(pr.PrRunner, "run", flaky_run)
    _sha, results = automerge.merge_branches(
        ["pricelog/merged-22222223"], repo, pr.PrRunner(), "main", push=True
    )
    assert results == []
    assert deletes == 2
    refs = git(repo, "ls-remote", "origin").splitlines()
    assert not any("pricelog/merged-22222223" in ref for ref in refs)


def test_pushed_merge_ref_deletion_retries(monkeypatch, tmp_path):
    # the post-push cleanup shares the retry: a blip there is what stranded
    # PR 846 in the first place
    monkeypatch.setattr(automerge, "_RETRY_DELAYS", (0, 0))
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/fresh-44444444", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    real_run = pr.PrRunner.run
    deletes = 0

    def flaky_run(self, cmd, cwd):
        nonlocal deletes
        if "--delete" in cmd:
            deletes += 1
            if deletes == 1:
                raise pr.PrError("failed to delete ref (transient)")
        return real_run(self, cmd, cwd)

    monkeypatch.setattr(pr.PrRunner, "run", flaky_run)
    _sha, results = automerge.merge_branches(
        ["pricelog/fresh-44444444"], repo, pr.PrRunner(), "main", push=True
    )
    assert [result.branch for result in results] == ["pricelog/fresh-44444444"]
    assert deletes == 2
    refs = git(repo, "ls-remote", "origin").splitlines()
    assert not any("pricelog/fresh-44444444" in ref for ref in refs)


def test_merged_branch_strict_ancestor_skipped_and_ref_deleted(tmp_path):
    # the real stranded shape is a strict ancestor: the merge commit advanced
    # the base past the branch tip, so an ancestry check that really answers
    # tip == HEAD must fail here, not pass
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/merged-55555555", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    git(repo, "push", "origin", "origin/pricelog/merged-55555555:refs/heads/main")
    git(repo, "switch", "main")
    git(repo, "pull", "--ff-only", "origin", "main")
    (repo / "notes.txt").write_text("advance\n")
    git(repo, "add", "notes.txt")
    git(repo, "commit", "-m", "advance base past the branch tip")
    git(repo, "push", "origin", "main")
    head_before = git(repo, "rev-parse", "HEAD").strip()
    sha, results = automerge.merge_branches(
        ["pricelog/merged-55555555"], repo, pr.PrRunner(), "main", push=True
    )
    assert results == []
    assert sha == head_before
    refs = git(repo, "ls-remote", "origin").splitlines()
    assert not any("pricelog/merged-55555555" in ref for ref in refs)


def test_merged_branch_local_only_rows_keep_the_ref(tmp_path, capsys):
    # a checkout ahead of origin/main (the sanctioned --no-push rerun state)
    # holds the branch's rows only locally: deleting the ref there would
    # close the PR with its rows never landed on the base, so the push path
    # keeps the ref by name
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/local-66666666", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    git(repo, "switch", "main")
    git(repo, "merge", "--no-ff", "--no-commit", "origin/pricelog/local-66666666")
    git(repo, "commit", "-m", "land locally, nothing pushed")
    head_before = git(repo, "rev-parse", "HEAD").strip()
    sha, results = automerge.merge_branches(
        ["pricelog/local-66666666"], repo, pr.PrRunner(), "main", push=True
    )
    assert results == []
    assert sha == head_before
    assert "keeping pricelog/local-66666666" in capsys.readouterr().out
    refs = git(repo, "ls-remote", "origin").splitlines()
    assert any("pricelog/local-66666666" in ref for ref in refs)
    assert git(repo, "status", "--porcelain") == ""


def test_merged_branch_ref_deletion_warns_after_the_retry_cap(monkeypatch, tmp_path, capsys):
    # the cleanup must never red the run: every attempt failing warns once
    # and keeps the ref for the next run's skip path to retry
    monkeypatch.setattr(automerge, "_RETRY_DELAYS", (0, 0))
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/merged-77777777", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    git(repo, "push", "origin", "origin/pricelog/merged-77777777:refs/heads/main")
    git(repo, "switch", "main")
    git(repo, "pull", "--ff-only", "origin", "main")
    real_run = pr.PrRunner.run
    deletes = 0

    def failing_run(self, cmd, cwd):
        nonlocal deletes
        if "--delete" in cmd:
            deletes += 1
            raise pr.PrError("failed to delete ref (permanent)")
        return real_run(self, cmd, cwd)

    monkeypatch.setattr(pr.PrRunner, "run", failing_run)
    _sha, results = automerge.merge_branches(
        ["pricelog/merged-77777777"], repo, pr.PrRunner(), "main", push=True
    )
    assert results == []
    assert deletes == automerge._RETRY_ATTEMPTS
    assert "warning: remote branch cleanup for pricelog/merged-77777777 failed" in (
        capsys.readouterr().err
    )
    refs = git(repo, "ls-remote", "origin").splitlines()
    assert any("pricelog/merged-77777777" in ref for ref in refs)


def test_cli_all_merged_prints_nothing_to_push(tmp_path, monkeypatch, capsys):
    # the human CLI path keeps its tail honest the same way: an all-skipped
    # burst prints the already-merged line and never claims a push
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/merged-88888888", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    git(repo, "push", "origin", "origin/pricelog/merged-88888888:refs/heads/main")
    git(repo, "switch", "main")
    git(repo, "pull", "--ff-only", "origin", "main")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        sys, "argv", ["ai-pricelog-automerge", "pricelog/merged-88888888", "--base", "main"]
    )
    assert automerge.main() == 0
    out = capsys.readouterr().out
    assert "every branch already merged into main; nothing to push" in out
    assert not any(line.startswith("pushed ") for line in out.splitlines())


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


def test_burst_keeps_a_landed_absence_bump_a_later_stale_tree_carries(tmp_path):
    # the 2026-09-13 shape (PRs 196/197): main already holds an absence file,
    # an older branch bumps its counter, and a newer branch cut from the same
    # main inherits the pre-bump copy without touching it. the newer branch's
    # tree copy is stale, not a carrier: the landed bump must survive
    repo, _bare = build_repo(tmp_path)
    absence.save_absence({"deepseek": {"gone": {"absent_runs": 1, "since": "2026-09-10"}}}, repo)
    git(repo, "add", "--", "state/absence")
    git(repo, "commit", "-m", "absence counter 1")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/older-00000001",
        [make_row("deepseek", "deepseek-v4-pro", "2026-09-11", 0.44)],
        absence_data={"deepseek": {"gone": {"absent_runs": 2, "since": "2026-09-10"}}},
    )
    make_branch(
        repo,
        "pricelog/newer-00000002",
        [make_row("zai", "glm-5.3", "2026-09-12", 0.2)],
    )

    automerge.merge_branches(
        ["pricelog/older-00000001", "pricelog/newer-00000002"],
        repo,
        pr.PrRunner(),
        "main",
        push=False,
    )

    landed = json.loads((repo / "state" / "absence" / "deepseek.json").read_text("utf-8"))
    assert landed == {"gone": {"absent_runs": 2, "since": "2026-09-10"}}


def _branch_at(
    monkeypatch, repo: Path, when: str, name: str, committed: str | None = None, **kwargs
) -> None:
    # the pipeline commits a branch at its run's instant, the stamp its name
    # carries; `committed` stands in for a later amend or rebase of that commit
    monkeypatch.setenv("GIT_AUTHOR_DATE", when)
    monkeypatch.setenv("GIT_COMMITTER_DATE", committed or when)
    make_branch(repo, name, **kwargs)
    monkeypatch.delenv("GIT_AUTHOR_DATE")
    monkeypatch.delenv("GIT_COMMITTER_DATE")


def test_later_burst_keeps_a_newer_run_absence_file_over_an_older_run_copy(
    tmp_path, monkeypatch, capsys
):
    # an older run's PR held for review merges in a later burst than a newer
    # run's PR for the same source: its stale absence copy must not revert
    # the newer counters, while its rows still land
    repo, _bare = build_repo(tmp_path)
    older = "pricelog/deepseek-2026-09-12-090000-aaaaaaaa"
    newer = "pricelog/deepseek-2026-09-12-100000-bbbbbbbb"
    _branch_at(
        monkeypatch,
        repo,
        "2026-09-12T09:00:00+00:00",
        older,
        rows=[make_row("deepseek", "deepseek-v4-pro", "2026-09-12", 0.44)],
        absence_data={"deepseek": {"gone": {"absent_runs": 1, "since": "2026-09-12"}}},
    )
    _branch_at(
        monkeypatch,
        repo,
        "2026-09-12T10:00:00+00:00",
        newer,
        rows=[make_row("deepseek", "deepseek-chat", "2026-09-12", 0.27)],
        absence_data={"deepseek": {"gone": {"absent_runs": 2, "since": "2026-09-12"}}},
    )

    automerge.merge_branches([newer], repo, pr.PrRunner(), "main", push=False)
    capsys.readouterr()
    automerge.merge_branches([older], repo, pr.PrRunner(), "main", push=False)

    landed = json.loads((repo / "state" / "absence" / "deepseek.json").read_text("utf-8"))
    assert landed == {"gone": {"absent_runs": 2, "since": "2026-09-12"}}
    models_landed = sorted({json.loads(line)["model_id"] for line in shard_lines(repo)})
    assert models_landed == ["deepseek-chat", "deepseek-v4-pro"]
    assert git(repo, "status", "--porcelain") == ""
    # the keep reaches the ci log: merge_verified calls merge_branches directly
    assert (
        "kept HEAD's state/absence/deepseek.json over"
        " pricelog/deepseek-2026-09-12-090000-aaaaaaaa: HEAD's copy is from a newer run"
        " (2026-09-12T10:00:00Z > 2026-09-12T09:00:00Z)"
    ) in capsys.readouterr().out.splitlines()


def test_later_burst_keeps_a_newer_run_deletion_over_an_older_run_copy(tmp_path, monkeypatch):
    # the newer run cleared every entry, so its branch deleted the file; the
    # held older run's copy must not bring it back, and never as an empty file
    repo, _bare = build_repo(tmp_path)
    absence.save_absence({"deepseek": {"gone": {"absent_runs": 1, "since": "2026-09-11"}}}, repo)
    git(repo, "add", "--", "state/absence")
    git(repo, "commit", "-m", "absence counter 1", "--date", "2026-09-11T09:00:00+00:00")
    git(repo, "push", "origin", "main")
    older = "pricelog/deepseek-2026-09-12-090000-aaaaaaaa"
    newer = "pricelog/deepseek-2026-09-12-100000-bbbbbbbb"
    _branch_at(
        monkeypatch,
        repo,
        "2026-09-12T09:00:00+00:00",
        older,
        rows=[make_row("deepseek", "deepseek-v4-pro", "2026-09-12", 0.44)],
        absence_data={"deepseek": {"gone": {"absent_runs": 2, "since": "2026-09-11"}}},
    )
    _branch_at(
        monkeypatch,
        repo,
        "2026-09-12T10:00:00+00:00",
        newer,
        rows=[make_row("deepseek", "deepseek-chat", "2026-09-12", 0.27)],
        absence_data={"deepseek": {}},
    )

    automerge.merge_branches([newer], repo, pr.PrRunner(), "main", push=False)
    assert not (repo / "state" / "absence" / "deepseek.json").exists()
    automerge.merge_branches([older], repo, pr.PrRunner(), "main", push=False)

    assert not (repo / "state" / "absence" / "deepseek.json").exists()
    assert git(repo, "ls-tree", "--name-only", "HEAD", "--", "state/absence/deepseek.json") == ""
    models_landed = sorted({json.loads(line)["model_id"] for line in shard_lines(repo)})
    assert models_landed == ["deepseek-chat", "deepseek-v4-pro"]
    assert git(repo, "status", "--porcelain") == ""


def _base_absence(repo: Path) -> None:
    absence.save_absence({"deepseek": {"gone": {"absent_runs": 1, "since": "2026-09-11"}}}, repo)
    git(repo, "add", "--", "state/absence")
    git(repo, "commit", "-m", "absence counter 1", "--date", "2026-09-11T09:00:00+00:00")
    git(repo, "push", "origin", "main")


def test_burst_lands_a_newer_run_deletion_over_an_older_run_copy(tmp_path, monkeypatch):
    # one burst, oldest first: the older run bumps the counter, the newer run
    # saw the model again and cleared the file; the newer clear must win
    repo, _bare = build_repo(tmp_path)
    _base_absence(repo)
    older = "pricelog/deepseek-2026-09-12-090000-aaaaaaaa"
    newer = "pricelog/deepseek-2026-09-12-100000-bbbbbbbb"
    _branch_at(
        monkeypatch,
        repo,
        "2026-09-12T09:00:00+00:00",
        older,
        rows=[make_row("deepseek", "deepseek-v4-pro", "2026-09-12", 0.44)],
        absence_data={"deepseek": {"gone": {"absent_runs": 2, "since": "2026-09-11"}}},
    )
    _branch_at(
        monkeypatch,
        repo,
        "2026-09-12T10:00:00+00:00",
        newer,
        rows=[make_row("deepseek", "deepseek-chat", "2026-09-12", 0.27)],
        absence_data={"deepseek": {}},
    )

    automerge.merge_branches([older, newer], repo, pr.PrRunner(), "main", push=False)

    assert not (repo / "state" / "absence" / "deepseek.json").exists()
    assert git(repo, "ls-tree", "--name-only", "HEAD", "--", "state/absence/deepseek.json") == ""
    assert git(repo, "status", "--porcelain") == ""


def test_later_burst_keeps_a_newer_run_copy_over_an_older_run_deletion(tmp_path, monkeypatch):
    # the older run cleared the file, the newer run bumped it and landed
    # first; the held older deletion must not erase the newer counters
    repo, _bare = build_repo(tmp_path)
    _base_absence(repo)
    older = "pricelog/deepseek-2026-09-12-090000-aaaaaaaa"
    newer = "pricelog/deepseek-2026-09-12-100000-bbbbbbbb"
    _branch_at(
        monkeypatch,
        repo,
        "2026-09-12T09:00:00+00:00",
        older,
        rows=[make_row("deepseek", "deepseek-v4-pro", "2026-09-12", 0.44)],
        absence_data={"deepseek": {}},
    )
    _branch_at(
        monkeypatch,
        repo,
        "2026-09-12T10:00:00+00:00",
        newer,
        rows=[make_row("deepseek", "deepseek-chat", "2026-09-12", 0.27)],
        absence_data={"deepseek": {"gone": {"absent_runs": 2, "since": "2026-09-11"}}},
    )

    automerge.merge_branches([newer], repo, pr.PrRunner(), "main", push=False)
    automerge.merge_branches([older], repo, pr.PrRunner(), "main", push=False)

    landed = json.loads((repo / "state" / "absence" / "deepseek.json").read_text("utf-8"))
    assert landed == {"gone": {"absent_runs": 2, "since": "2026-09-11"}}
    assert git(repo, "status", "--porcelain") == ""


def test_later_burst_keeps_the_last_absence_file_over_a_cleanly_merged_older_deletion(
    tmp_path, monkeypatch
):
    # HEAD's newer run wrote back the base's exact bytes, so git merges the
    # older branch's deletion cleanly and removes the now-empty state/absence
    # directory; the newer copy must still be kept
    repo, _bare = build_repo(tmp_path)
    _base_absence(repo)
    older = "pricelog/deepseek-2026-09-12-090000-aaaaaaaa"
    _branch_at(
        monkeypatch,
        repo,
        "2026-09-12T09:00:00+00:00",
        older,
        rows=[make_row("deepseek", "deepseek-v4-pro", "2026-09-12", 0.44)],
        absence_data={"deepseek": {}},
    )
    base_entries = {"gone": {"absent_runs": 1, "since": "2026-09-11"}}
    for when, entries in (
        ("2026-09-12T10:00:00+00:00", {"gone": {"absent_runs": 2, "since": "2026-09-11"}}),
        ("2026-09-12T10:30:00+00:00", base_entries),
    ):
        monkeypatch.setenv("GIT_AUTHOR_DATE", when)
        monkeypatch.setenv("GIT_COMMITTER_DATE", when)
        absence.save_absence({"deepseek": entries}, repo)
        git(repo, "add", "--", "state/absence")
        git(repo, "commit", "-m", f"absence at {when}")
    monkeypatch.delenv("GIT_AUTHOR_DATE")
    monkeypatch.delenv("GIT_COMMITTER_DATE")
    git(repo, "push", "origin", "main")

    automerge.merge_branches([older], repo, pr.PrRunner(), "main", push=False)

    landed = json.loads((repo / "state" / "absence" / "deepseek.json").read_text("utf-8"))
    assert landed == base_entries
    assert git(repo, "status", "--porcelain") == ""


def test_later_burst_stamps_a_rewritten_older_branch_by_its_run(tmp_path, monkeypatch):
    # an amend or rebase moves the older branch's committer date past the
    # newer run; its copy still dates from its own run and must not win
    repo, _bare = build_repo(tmp_path)
    older = "pricelog/deepseek-2026-09-12-090000-aaaaaaaa"
    newer = "pricelog/deepseek-2026-09-12-100000-bbbbbbbb"
    _branch_at(
        monkeypatch,
        repo,
        "2026-09-12T09:00:00+00:00",
        older,
        committed="2026-09-12T11:00:00+00:00",
        rows=[make_row("deepseek", "deepseek-v4-pro", "2026-09-12", 0.44)],
        absence_data={"deepseek": {"gone": {"absent_runs": 1, "since": "2026-09-12"}}},
    )
    _branch_at(
        monkeypatch,
        repo,
        "2026-09-12T10:00:00+00:00",
        newer,
        rows=[make_row("deepseek", "deepseek-chat", "2026-09-12", 0.27)],
        absence_data={"deepseek": {"gone": {"absent_runs": 2, "since": "2026-09-12"}}},
    )

    automerge.merge_branches([newer], repo, pr.PrRunner(), "main", push=False)
    automerge.merge_branches([older], repo, pr.PrRunner(), "main", push=False)

    landed = json.loads((repo / "state" / "absence" / "deepseek.json").read_text("utf-8"))
    assert landed == {"gone": {"absent_runs": 2, "since": "2026-09-12"}}


def test_later_burst_lands_a_newer_run_absence_file_over_an_older_landed_copy(
    tmp_path, monkeypatch
):
    repo, _bare = build_repo(tmp_path)
    older = "pricelog/deepseek-2026-09-12-090000-aaaaaaaa"
    newer = "pricelog/deepseek-2026-09-12-100000-bbbbbbbb"
    _branch_at(
        monkeypatch,
        repo,
        "2026-09-12T09:00:00+00:00",
        older,
        rows=[make_row("deepseek", "deepseek-v4-pro", "2026-09-12", 0.44)],
        absence_data={"deepseek": {"gone": {"absent_runs": 1, "since": "2026-09-12"}}},
    )
    _branch_at(
        monkeypatch,
        repo,
        "2026-09-12T10:00:00+00:00",
        newer,
        rows=[make_row("deepseek", "deepseek-chat", "2026-09-12", 0.27)],
        absence_data={"deepseek": {"gone": {"absent_runs": 2, "since": "2026-09-12"}}},
    )

    automerge.merge_branches([older], repo, pr.PrRunner(), "main", push=False)
    automerge.merge_branches([newer], repo, pr.PrRunner(), "main", push=False)

    landed = json.loads((repo / "state" / "absence" / "deepseek.json").read_text("utf-8"))
    assert landed == {"gone": {"absent_runs": 2, "since": "2026-09-12"}}


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


def test_churn_gate_refuses_a_branch_creating_too_many_models(tmp_path):
    repo, _bare = build_repo(tmp_path)
    rows = [make_row("zai", f"glm-{i}", "2026-09-01", 0.1 + i * 0.01) for i in range(51)]
    make_branch(repo, "pricelog/too-many-00000001", rows)
    before = git(repo, "rev-parse", "main").strip()

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(
            ["pricelog/too-many-00000001"], repo, pr.PrRunner(), "main", push=False
        )

    message = str(excinfo.value)
    assert "unsafe" in message
    assert "creates 51" in message
    assert "bound 50" in message
    assert git(repo, "rev-parse", "main").strip() == before


def test_churn_gate_merges_at_the_bound(tmp_path):
    # the bound itself is legal: only a branch beyond it is unsafe
    repo, _bare = build_repo(tmp_path)
    rows = [make_row("zai", f"glm-{i}", "2026-09-01", 0.1 + i * 0.01) for i in range(50)]
    make_branch(repo, "pricelog/at-bound-00000001", rows)

    sha, results = automerge.merge_branches(
        ["pricelog/at-bound-00000001"], repo, pr.PrRunner(), "main", push=False
    )

    assert [r.appended for r in results] == [50]
    assert git(repo, "rev-parse", "HEAD").strip() == sha


def test_churn_gate_refuses_too_many_removals(tmp_path):
    repo, _bare = build_repo(tmp_path)
    rows = [make_removal_row("zai", f"glm-{i}", "2026-09-01") for i in range(51)]
    make_branch(repo, "pricelog/too-many-gone-00000001", rows)

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(
            ["pricelog/too-many-gone-00000001"], repo, pr.PrRunner(), "main", push=False
        )

    message = str(excinfo.value)
    assert "unsafe" in message
    assert "removes 51" in message
    assert "bound 50" in message


def test_churn_gate_refuses_too_many_appended_rows(tmp_path):
    repo, _bare = build_repo(tmp_path)
    start = date(2026, 9, 1)
    rows = [
        make_row("deepseek", "deepseek-v4-pro", (start + timedelta(days=i)).isoformat(), 0.44)
        for i in range(501)
    ]
    make_branch(repo, "pricelog/too-many-rows-00000001", rows)

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(
            ["pricelog/too-many-rows-00000001"], repo, pr.PrRunner(), "main", push=False
        )

    message = str(excinfo.value)
    assert "unsafe" in message
    assert "appends 501" in message
    assert "bound 500" in message


def test_churn_gate_counts_updates_as_appended_not_created(tmp_path):
    # 60 price updates of one stored model: under every bound, and the
    # created count must not read an update as a new model or it would trip
    # the created bound with nothing new on the branch
    repo, _bare = build_repo(tmp_path)
    start = date(2026, 9, 1)
    rows = [
        make_row("deepseek", "deepseek-v4-pro", (start + timedelta(days=i)).isoformat(), 0.44)
        for i in range(60)
    ]
    make_branch(repo, "pricelog/updates-00000001", rows)

    sha, results = automerge.merge_branches(
        ["pricelog/updates-00000001"], repo, pr.PrRunner(), "main", push=False
    )

    assert [r.appended for r in results] == [60]
    assert git(repo, "rev-parse", "HEAD").strip() == sha


def test_churn_gate_human_waiver_lands_an_over_bound_branch(tmp_path, capsys):
    repo, _bare = build_repo(tmp_path)
    rows = [make_row("zai", f"glm-{i}", "2026-09-01", 0.1 + i * 0.01) for i in range(51)]
    make_branch(repo, "pricelog/human-00000001", rows)

    sha, results = automerge.merge_branches(
        ["pricelog/human-00000001"], repo, pr.PrRunner(), "main", push=False, human=True
    )

    assert [r.appended for r in results] == [51]
    assert "waived churn bounds" in capsys.readouterr().out
    assert git(repo, "rev-parse", "HEAD").strip() == sha


def test_human_waiver_never_waives_the_claim_check(tmp_path):
    # --human waives the churn bounds only: an over-bound seedless branch
    # still refuses on the claim check, or the coverage-invariant breach the
    # check closes would reopen through the human path
    repo, _bare = build_repo(tmp_path)
    rows = [make_row("zai", f"glm-{i}", "2026-09-01", 0.1 + i * 0.01) for i in range(51)]
    make_branch(repo, "pricelog/human-gap-00000001", rows, auto_seed=False)
    before = git(repo, "rev-parse", "main").strip()

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(
            ["pricelog/human-gap-00000001"], repo, pr.PrRunner(), "main", push=False, human=True
        )

    assert "no catalog claim" in str(excinfo.value)
    assert git(repo, "rev-parse", "main").strip() == before


def test_carried_row_without_a_catalog_claim_refuses_the_merge(tmp_path):
    repo, _bare = build_repo(tmp_path)
    make_branch(
        repo,
        "pricelog/carried-00000001",
        [make_row("zai", "glm-5", "2026-09-01", 0.1)],
        auto_seed=False,
    )
    before = git(repo, "rev-parse", "main").strip()

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(
            ["pricelog/carried-00000001"], repo, pr.PrRunner(), "main", push=False
        )

    message = str(excinfo.value)
    assert "pricelog/carried-00000001" in message
    assert "zai" in message
    assert "glm-5" in message
    assert git(repo, "rev-parse", "main").strip() == before


def test_carried_row_lands_when_the_seed_rides_a_sibling_branch(tmp_path):
    # the row's own PR is needs-human, the carrier's PR is verified: the seed
    # rides the row's own branch, so the burst lands row and seed together
    repo, _bare = build_repo(tmp_path)
    row = make_row("zai", "glm-5", "2026-09-01", 0.1)
    make_branch(repo, "pricelog/carried-00000001", [row], auto_seed=False)
    make_branch(
        repo,
        "pricelog/seeder-00000002",
        [],
        catalog_models={
            "zai/glm-5": {"vendor": None, "curated": False, "sources": {"zai": ["glm-5"]}}
        },
    )

    sha, results = automerge.merge_branches(
        ["pricelog/carried-00000001", "pricelog/seeder-00000002"],
        repo,
        pr.PrRunner(),
        "main",
        push=False,
    )

    assert [r.branch for r in results] == ["pricelog/carried-00000001", "pricelog/seeder-00000002"]
    assert json.loads(shard_lines(repo, "zai")[0]) == row
    catalog = json.loads((repo / models.MODELS_FILE).read_text(encoding="utf-8"))
    claims = {
        (source, model_id)
        for entry in catalog["models"].values()
        for source, ids in entry["sources"].items()
        for model_id in ids
    }
    assert ("zai", "glm-5") in claims
    assert git(repo, "status", "--porcelain") == ""
    assert git(repo, "rev-parse", "HEAD").strip() == sha


def test_removal_row_needs_no_catalog_claim(tmp_path):
    # a removal row's claim predates it (the first price row landed its seed);
    # refusing it would block a delisting on a coverage gap this merge did not
    # create
    repo, _bare = build_repo(tmp_path)
    row = make_removal_row("zai", "gone-model", "2026-09-01")
    make_branch(repo, "pricelog/removal-00000001", [row], auto_seed=False)

    sha, results = automerge.merge_branches(
        ["pricelog/removal-00000001"], repo, pr.PrRunner(), "main", push=False
    )

    assert [r.appended for r in results] == [1]
    assert json.loads(shard_lines(repo, "zai")[0]) == row
    assert git(repo, "rev-parse", "HEAD").strip() == sha


def test_merge_skips_the_announce_step_for_a_branch_with_no_index(tmp_path):
    # a branch whose announce tree carries no index.json is not a config drop:
    # it names no url set, so its merge leaves the announce tree exactly as
    # the previous merge resolution wrote it. the newest branch forks after
    # the base dropped its index, so its absent index is no deletion
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
    git(repo, "rm", "-q", "state/announce/index.json")
    git(repo, "commit", "-m", "drop the index from the base")
    git(repo, "push", "origin", "main")
    make_branch(repo, "pricelog/newest-00000002", [make_row("zai", "glm-5", "2026-09-11", 0.1)])

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


def test_merge_lands_a_pipeline_channel_drop(tmp_path):
    # the pipeline's own channel drop removes the index entry with the .md
    # (announce.save_snapshot prunes it), so the branch's own index never names
    # a file it deleted: the drop is no hand-edit deletion and merges, with the
    # url gone from the store
    repo, _bare = build_repo(tmp_path)
    url = "https://example.com/notes"
    commit_announce(repo, {"deepseek": {url: "old prose"}}, "2026-09-09")
    git(repo, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/drop-00000003",
        [make_row("deepseek", "deepseek-v4-pro", "2026-09-11", 0.45)],
        announce_texts={},
        announce_fetched="2026-09-11",
    )

    _sha, results = automerge.merge_branches(
        ["pricelog/drop-00000003"], repo, pr.PrRunner(), "main", push=False
    )

    assert [r.appended for r in results] == [1]
    index = json.loads((repo / "state" / "announce" / "index.json").read_text(encoding="utf-8"))
    assert index == {}
    assert not (repo / "state" / "announce" / "deepseek" / "notes.md").exists()
    assert git(repo, "status", "--porcelain") == ""


def test_merge_refuses_a_newest_branch_indexing_a_channel_file_its_tree_lacks(
    tmp_path, monkeypatch
):
    # a newest branch whose index names a url its tree carries no .md for (a
    # hand edit; _announce_index checks the file field's derived path, never
    # the blob's existence), and neither its merge base nor the older branch
    # carries that path: no deletion record exists, so the index itself is
    # checked against the branch's tree, and the burst stops before any merge
    repo, _bare = build_repo(tmp_path)
    url_a = "https://example.com/notes"
    url_b = "https://example.com/notes?feed=rss"
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
    before = git(repo, "rev-parse", "HEAD").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(automerge.AutoMergeError) as excinfo:
        automerge.merge_branches(
            ["pricelog/older-00000001", "pricelog/newest-00000002"],
            repo,
            pr.PrRunner(),
            "main",
            push=False,
        )

    assert str(excinfo.value) == (
        "branch pricelog/newest-00000002: its state/announce/index.json names"
        " ['state/announce/deepseek/notes.md'] that its tree lacks; the merge reads each"
        " indexed channel file from the branch side; fix: restore the file(s) on the"
        " branch or drop their index entries, or close the PR"
    )
    assert_refused_before_any_merge(repo, before, calls)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("not json{", "is not valid json"),
        ('["a list"]', "must be an object"),
        ('{"deepseek": []}', "source 'deepseek' must map to an object"),
        ('{"deepseek": {"u": "x"}}', "must carry 'file', 'sha256' and 'fetched' as strings"),
        (
            '{"deepseek": {"u": {"file": 1, "sha256": "a", "fetched": "b"}}}',
            "must carry 'file', 'sha256' and 'fetched' as strings",
        ),
    ],
)
def test_announce_index_refuses_shapes_that_do_not_read(tmp_path, text, message):
    # the pass may hand-edit the announce tree, so an index that does not read
    # as source -> url -> entry stops the merge by name, never by traceback
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


def test_merge_refuses_when_the_winner_tree_lacks_the_channel_file(tmp_path, monkeypatch):
    # the resolution reads a channel file by path from the branch side when the
    # branch's own index names it; a hand edit that drops the file keeps the
    # entry, so the pre-flight refuses the deletion by name before any merge
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
    calls = merge_spy(monkeypatch)

    with pytest.raises(
        automerge.AutoMergeError,
        match=r"pricelog/winner-55555555: deletes \['state/announce/deepseek/notes.md'\]",
    ):
        automerge.merge_branches(
            ["pricelog/winner-55555555"], repo, pr.PrRunner(), "main", push=False
        )

    assert calls == []
    assert git(repo, "rev-parse", "main").strip() == before
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / ".git" / "MERGE_HEAD").exists()


def test_merge_fetches_a_branch_pushed_after_the_checkout(tmp_path):
    # the CI checkout fetches at job start; a sibling run pushes its branch
    # afterwards and the merge red'd reading the stale local origin/* ref
    # (observed 2026-09-22: `unknown revision` on the branch diff). deleting
    # the tracking ref reproduces the state; the merge must fetch it back
    repo, _bare = build_repo(tmp_path)
    make_branch(
        repo,
        "pricelog/alpha-00000000",
        [make_row("deepseek", "deepseek-v4-flash", "2026-09-01", 0.05)],
    )
    git(repo, "update-ref", "-d", "refs/remotes/origin/pricelog/alpha-00000000")

    _sha, results = automerge.merge_branches(
        ["pricelog/alpha-00000000"], repo, pr.PrRunner(), "main", push=False
    )

    assert results[0].appended == 1


def test_merge_refuses_a_checkout_behind_the_remote_base(tmp_path):
    # a merge from a stale base drops the rows that landed upstream; before
    # the guard it surfaced only as a push rejection after the merge commits
    # (observed 2026-09-18, and on a 2026-09-22 hand merge)
    repo, bare = build_repo(tmp_path)
    other = tmp_path / "other"
    git(tmp_path, "clone", str(bare), str(other))
    git(other, "config", "user.name", "Test")
    git(other, "config", "user.email", "test@example.com")
    (other / "no-hooks").mkdir()
    git(other, "config", "core.hooksPath", str(other / "no-hooks"))
    store.save_shard(
        store.load_shard(other / "data" / "history", "deepseek")
        + [make_row("deepseek", "deepseek-v4-flash", "2026-08-31", 0.05)],
        other / "data" / "history",
        "deepseek",
    )
    git(other, "add", ".")
    git(other, "commit", "-m", "landed upstream")
    git(other, "push", "origin", "main")
    make_branch(
        repo,
        "pricelog/alpha-00000000",
        [make_row("deepseek", "deepseek-v4-pro", "2026-09-01", 0.44)],
    )

    with pytest.raises(automerge.AutoMergeError, match="behind"):
        automerge.merge_branches(
            ["pricelog/alpha-00000000"], repo, pr.PrRunner(), "main", push=False
        )


def test_merge_refuses_a_behind_checkout_before_the_branch_checks(tmp_path, monkeypatch):
    # a branch landed upstream whose tip index does not parse: the branch
    # checks would answer for the landed state, while the checkout behind
    # origin/<base> is the real cause, so the checkout is refused first
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/badidx-00000012", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    git(repo, "switch", "pricelog/badidx-00000012")
    (repo / "state" / "announce" / "index.json").write_text("not json{\n")
    git(repo, "add", "state/announce/index.json")
    git(repo, "commit", "-m", "hand edit: unreadable index")
    git(repo, "push", "origin", "pricelog/badidx-00000012")
    git(repo, "switch", "main")
    # the branch lands upstream; the local checkout stays behind it
    git(repo, "push", "origin", "origin/pricelog/badidx-00000012:refs/heads/main")
    head_before = git(repo, "rev-parse", "HEAD").strip()
    calls = merge_spy(monkeypatch)

    with pytest.raises(automerge.AutoMergeError, match="the checkout is behind main's remote tip"):
        automerge.merge_branches(
            ["pricelog/badidx-00000012"], repo, pr.PrRunner(), "main", push=False
        )

    assert calls == []
    assert git(repo, "rev-parse", "HEAD").strip() == head_before
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / ".git" / "MERGE_HEAD").exists()


def test_staged_leftover_merge_refused_before_a_behind_checkout(tmp_path, monkeypatch):
    # a rerun over a checkout behind origin/<base> can hold the state of a run
    # that raised after `git merge --no-commit`: MERGE_HEAD and staged pipeline
    # files. git refuses the `git pull` a behind refusal asks for while that
    # merge is unconcluded, so the staged files are the real cause to name first
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/alpha-00000000", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    # the branch lands upstream; the local checkout stays behind it
    git(repo, "push", "origin", "origin/pricelog/alpha-00000000:refs/heads/main")
    # the state a run that raised mid-merge leaves: the merge staged, unconcluded
    git(repo, "merge", "--no-ff", "--no-commit", "origin/pricelog/alpha-00000000")
    head_before = git(repo, "rev-parse", "HEAD").strip()
    assert (repo / ".git" / "MERGE_HEAD").exists()
    calls = merge_spy(monkeypatch)

    with pytest.raises(automerge.AutoMergeError, match="nothing staged: .*data/history/zai.ndjson"):
        automerge.merge_branches(
            ["pricelog/alpha-00000000"], repo, pr.PrRunner(), "main", push=False
        )

    assert calls == []
    assert git(repo, "rev-parse", "HEAD").strip() == head_before
    assert (repo / ".git" / "MERGE_HEAD").exists()


def test_staged_change_refused_before_the_branch_checks(tmp_path, monkeypatch):
    # the checkout-state refusals report the real cause before any branch-side
    # read: a staged file stops the run even when a branch refusal would
    # otherwise answer for the burst first
    repo, _bare = build_repo(tmp_path)
    make_branch(repo, "pricelog/seed", [make_row("zai", "glm-5", "2026-08-31", 0.1)])
    (repo / "notes.txt").write_text("staged\n")
    git(repo, "add", "notes.txt")
    calls = merge_spy(monkeypatch)

    with pytest.raises(automerge.AutoMergeError, match="nothing staged: staged notes.txt"):
        automerge.merge_branches(["pricelog/seed"], repo, pr.PrRunner(), "main", push=False)

    assert calls == []

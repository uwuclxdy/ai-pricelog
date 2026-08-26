"""git/gh plumbing for the pipeline: runners, specs, branch names, pending scans."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ai_pricelog import announce, store

log = logging.getLogger(__name__)

AUTOPR_REPO = "https://github.com/uwuclxdy/ai-pricelog"
SEED_BRANCH = "pricelog/seed"


def run_url_from_env() -> str | None:
    """The actions run url for the current run, or None outside a runner."""
    server = os.environ.get("GITHUB_SERVER_URL")
    repo = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not (server and repo and run_id):
        return None
    return f"{server.rstrip('/')}/{repo}/actions/runs/{run_id}"


class PrError(Exception):
    def __init__(self, message: str, stderr: str = "", stdout: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr
        self.stdout = stdout


class PrRunner:
    def run(self, cmd: list[str], cwd: Path) -> str:
        try:
            result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise PrError(f"command {cmd} failed to start: {exc}") from exc
        if result.returncode != 0:
            raise PrError(
                f"command {cmd} failed: {_stderr_tail(result.stderr)}",
                stderr=result.stderr,
                stdout=result.stdout,
            )
        return result.stdout


@dataclass(frozen=True)
class PrSpec:
    """One price-history PR: the new rows, the branch, the title and body."""

    source: str
    model_id: str
    provider: str
    source_url: str
    rows: tuple[dict[str, object], ...]
    update: bool = False
    seed: bool = False
    run_url: str | None = None
    announce: tuple[announce.ChannelChange, ...] = ()

    @property
    def branch(self) -> str:
        return SEED_BRANCH if self.seed else branch_name(self.model_id)

    @property
    def title(self) -> str:
        if self.seed:
            return "Seed price history"
        verb = "Update" if self.update else "Add"
        return f"{verb} {self.model_id} pricing for {self.provider}"

    @property
    def body(self) -> str:
        lines = [self._disclaimer(), ""]
        if self.seed:
            lines += [
                f"first price-history snapshot: {len(self.rows)} rows "
                f"across {len({row['source'] for row in self.rows})} sources.",
                "",
            ]
        lines += [
            "## new rows",
            "",
            "| source | model | observed | input (/1M) | cache read (/1M) | output (/1M) |"
            " peak (/1M) |",
            "|---|---|---|---|---|---|---|",
        ]
        for row in self.rows:
            lines.append(self._row_line(row))
        if self.source_url:
            lines += ["", f"source: {self.source_url}"]
        if self.announce:
            lines += [
                "",
                "## announcement channels",
                "",
                "| provider | channel | change |",
                "|---|---|---|",
            ]
            for change in self.announce:
                lines.append(
                    f"| {change.provider} | {change.url} | "
                    f"`{change.old_sha256[:8]}` -> `{change.new_sha256[:8]}` |"
                )
            lines += [
                "",
                "full old/new prose: the `data/announce.json` diff on this branch",
            ]
        lines.extend(self._review_section())
        return "\n".join(lines) + "\n"

    def _row_line(self, row: dict[str, object]) -> str:
        peak = "—"
        if "peak_windows" in row:
            windows = " and ".join(f"{start} - {end}" for start, end in row["peak_windows"])
            peak = (
                f"{_fmt(row.get('peak_input_mtok'))}/{_fmt(row.get('peak_output_mtok'))} {windows}"
            )
        return (
            f"| {row['source']} | `{row['model_id']}` | {row['observed_at']} | "
            f"{_fmt(row.get('input_mtok'))} | {_fmt(row.get('cache_read_mtok'))} | "
            f"{_fmt(row.get('output_mtok'))} | {peak} |"
        )

    def _disclaimer(self) -> str:
        link = self.run_url or f"{AUTOPR_REPO}/actions"
        return f"- **opened automatically by the [GitHub Action]({link}).**"

    def _review_section(self) -> list[str]:
        return [
            "",
            "## review checklist",
            "",
            "- [ ] prices verified against the source page",
            "- [ ] provider name correct",
            "- [ ] peak/off-peak rates match the page",
            "- [ ] a sibling merge conflict: concatenate both histories, dedupe"
            " exact lines only (a key-based union drops same-day updates);"
            " index.json heals on the next push",
        ]


def _fmt(value: object) -> str:
    return "—" if value is None else f"{value:g}"


def default_branch(runner: PrRunner, cwd: Path) -> str:
    """The default branch of THIS repo, read from the gh api."""
    return runner.run(
        ["gh", "repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"],
        cwd=cwd,
    ).strip()


def branch_name(key: str) -> str:
    """`pricelog/<slug>-<sha8>`: the slugged model id plus a digest suffix.

    The slash becomes a dash because a slash nests the refname and lets one id
    be a path prefix of another, which the remote rejects once both branches
    exist. The first 8 hex chars of the id's sha256 keep distinct ids distinct
    after slugging. The branch is automation-owned, so the run pushes it with
    --force-with-lease.
    """
    slug = re.sub(r"[^A-Za-z0-9._-]", "-", key.replace("/", "-"))
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    return f"pricelog/{slug}-{digest}"


@dataclass(frozen=True)
class OpenPr:
    """One open PR as gh pr list reports it; what the pending checks key on."""

    title: str
    body: str
    head_ref: str


def open_pull_requests(runner: PrRunner, cwd: Path) -> list[OpenPr]:
    """All open PRs in THIS repo, one gh call per run (never per model)."""
    out = runner.run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--limit",
            "100",
            "--json",
            "title,body,headRefName",
        ],
        cwd=cwd,
    )
    try:
        entries = json.loads(out)
    except json.JSONDecodeError as exc:
        raise PrError(f"gh pr list returned invalid json: {exc.msg}") from exc
    if not isinstance(entries, list):
        raise PrError("gh pr list returned a non-list json value")
    prs: list[OpenPr] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        prs.append(
            OpenPr(
                title=str(entry.get("title") or ""),
                body=str(entry.get("body") or ""),
                head_ref=str(entry.get("headRefName") or ""),
            )
        )
    return prs


def pending_pr(model_id: str, open_prs: Sequence[OpenPr]) -> bool:
    """Whether an open PR in THIS repo names model_id in its title or body.

    Case-insensitive substring match over the run's one pr list. The pipeline
    checks it before scraping, so a closed-unmerged PR re-candidates the model
    on the next run while an open one settles it.
    """
    needle = model_id.lower()
    return any(needle in entry.title.lower() or needle in entry.body.lower() for entry in open_prs)


def seed_pending(open_prs: Sequence[OpenPr]) -> bool:
    """Whether the seed PR is still open (matched by branch, not by title)."""
    return any(entry.head_ref == SEED_BRANCH for entry in open_prs)


def open_pr(base: str, branch: str, spec: PrSpec, runner: PrRunner, cwd: Path) -> str:
    return runner.run(
        [
            "gh",
            "pr",
            "create",
            "--draft",
            "--base",
            base,
            "--head",
            branch,
            "--title",
            spec.title,
            "--body",
            spec.body,
        ],
        cwd=cwd,
    ).strip()


def fetch_pending_rows(
    runner: PrRunner,
    repo_root: Path,
    history_file: str,
    open_prs: Sequence[OpenPr],
) -> list[dict[str, object]]:
    """The rows on open PRs' pricelog branches of origin, under refs/remotes/pending.

    Every open PR branch carries a full store snapshot; its rows unique over
    the local store are what a new PR branch must union in, so sibling PRs
    stop rewriting the same files. A branch whose pr was closed keeps its
    head ref out of open_prs and contributes no rows, so a rejected pr's rows
    drop out of the union and its model re-candidates on the next run. The
    fetch is forced and pruned: pending branches are force-pushed, and refs
    of branches deleted upstream must not linger. A run without an origin
    remote (local dev) or a branch without the file just yields no pending
    rows.
    """
    try:
        runner.run(
            ["git", "fetch", "origin", "+refs/heads/pricelog/*:refs/remotes/pending/*", "--prune"],
            cwd=repo_root,
        )
    except PrError as exc:
        log.info("pending branch fetch failed; continuing with no pending rows: %s", exc)
        return []
    try:
        refs = runner.run(
            ["git", "for-each-ref", "refs/remotes/pending", "--format=%(refname)"],
            cwd=repo_root,
        ).splitlines()
    except PrError as exc:
        log.info("pending ref listing failed; continuing with no pending rows: %s", exc)
        return []
    open_heads = {entry.head_ref for entry in open_prs}
    rows: list[dict[str, object]] = []
    for ref in refs:
        if f"pricelog/{ref.removeprefix('refs/remotes/pending/')}" not in open_heads:
            log.debug("pending ref %s has no open pr; skipping", ref)
            continue
        try:
            text = runner.run(["git", "show", f"{ref}:{history_file}"], cwd=repo_root)
        except PrError as exc:
            log.info("pending branch %s has no %s; skipping: %s", ref, history_file, exc)
            continue
        try:
            rows.extend(store.parse(text, ref))
        except ValueError as exc:
            log.warning("pending branch %s history unreadable; skipping: %s", ref, exc)
            continue
    return rows


def ensure_author(slot: Path, runner: PrRunner) -> None:
    """set repo-local user.name/email from gh when git has no identity."""
    try:
        email = runner.run(["git", "config", "user.email"], cwd=slot).strip()
    except PrError as exc:
        # git exits 1 when the key is unset; only a real failure carries stderr
        if exc.stderr.strip():
            raise
        email = ""
    if email:
        return
    login = runner.run(["gh", "api", "user", "--jq", ".login"], cwd=slot).strip()
    runner.run(["git", "config", "user.name", login], cwd=slot)
    runner.run(["git", "config", "user.email", f"{login}@users.noreply.github.com"], cwd=slot)


def _stderr_tail(stderr: str) -> str:
    tail = stderr.strip()[-500:]
    return tail if tail else "(no stderr)"

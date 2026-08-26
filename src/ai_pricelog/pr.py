import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

AUTOPR_REPO = "https://github.com/uwuclxdy/ai-pricelog"


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

    @property
    def branch(self) -> str:
        return "pricelog/seed" if self.seed else branch_name(self.model_id)

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
        return (
            f"- **opened automatically by the [GitHub Action]({link}) from {AUTOPR_REPO}.** "
            "i read replies and will review the prices before marking it ready."
        )

    def _review_section(self) -> list[str]:
        return [
            "",
            "## review checklist",
            "",
            "- [ ] prices verified against the source page",
            "- [ ] provider name correct",
            "- [ ] peak/off-peak rates match the page",
        ]


def _fmt(value: object) -> str:
    return "—" if value is None else f"{value:g}"


def default_branch(runner: PrRunner) -> str:
    """The default branch of THIS repo, read from the gh api."""
    return runner.run(
        ["gh", "repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"],
        cwd=Path.cwd(),
    ).strip()


def branch_name(key: str) -> str:
    return "pricelog/" + re.sub(r"[^A-Za-z0-9._/-]", "-", key)


def pending_pr(model_id: str, runner: PrRunner) -> bool:
    """Whether an open PR in THIS repo names model_id in its title or body.

    Case-insensitive substring match, one gh call per model. The pipeline
    checks it before scraping, so a closed-unmerged PR re-candidates the model
    on the next run while an open one settles it.
    """
    out = runner.run(
        ["gh", "pr", "list", "--state", "open", "--json", "title,body"],
        cwd=Path.cwd(),
    )
    try:
        entries = json.loads(out)
    except json.JSONDecodeError as exc:
        raise PrError(f"gh pr list returned invalid json: {exc.msg}") from exc
    needle = model_id.lower()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if any(needle in str(entry.get(key, "")).lower() for key in ("title", "body")):
            return True
    return False


def open_pr(base: str, branch: str, spec: PrSpec, runner: PrRunner) -> str:
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
        cwd=Path.cwd(),
    ).strip()


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

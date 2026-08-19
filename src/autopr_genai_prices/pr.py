import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from autopr_genai_prices.config import Config
from autopr_genai_prices.openrouter import OPENROUTER_MODELS_URL

UPSTREAM = "pydantic/genai-prices"


class PrError(Exception):
    def __init__(self, message: str, stderr: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr


class PrRunner:
    def run(self, cmd: list[str], cwd: Path) -> str:
        try:
            result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise PrError(f"command {cmd} failed to start: {exc}") from exc
        if result.returncode != 0:
            raise PrError(
                f"command {cmd} failed: {_stderr_tail(result.stderr)}", stderr=result.stderr
            )
        return result.stdout


@dataclass(frozen=True)
class PrSpec:
    """Everything one candidate PR needs: entries, table numbers, deferrals."""

    key: str
    model_id: str
    vendor_yml: str
    vendor_name: str
    vendor_entry: str
    vendor_input_mtok: float
    vendor_output_mtok: float
    vendor_peak_input_mtok: float | None
    vendor_peak_output_mtok: float | None
    vendor_peak_windows: tuple[tuple[str, str], ...]
    skipped_latest: tuple[str, ...]
    source_url: str
    openrouter_entry: str | None
    openrouter_slug: str
    openrouter_input_mtok: float | None
    openrouter_output_mtok: float | None
    openrouter_cache_read_mtok: float | None
    openrouter_note: str

    @property
    def branch(self) -> str:
        return branch_name(f"{self.key}/{self.model_id}")

    @property
    def title(self) -> str:
        if self.openrouter_entry is not None:
            return f"Add {self.model_id} pricing for {self.vendor_name} and OpenRouter"
        return f"Add {self.model_id} pricing for {self.vendor_name}"

    @property
    def body(self) -> str:
        lines: list[str] = []
        lines.append(f"Add `{self.model_id}` pricing for {self.vendor_name}.")
        lines.append("")
        lines.append(f"## {self.vendor_name}")
        lines.append("")
        lines.append("| model | input (/1M) | output (/1M) |")
        lines.append("|---|---|---|")
        if self.vendor_peak_input_mtok is not None:
            windows = " and ".join(f"{start} - {end}" for start, end in self.vendor_peak_windows)
            lines.append(
                f"| `{self.model_id}` off-peak | {self.vendor_input_mtok:g} "
                f"| {self.vendor_output_mtok:g} |"
            )
            lines.append(
                f"| `{self.model_id}` peak {windows} | {self.vendor_peak_input_mtok:g} "
                f"| {self.vendor_peak_output_mtok:g} |"
            )
        else:
            lines.append(
                f"| `{self.model_id}` | {self.vendor_input_mtok:g} | {self.vendor_output_mtok:g} |"
            )
        lines.append("")
        lines.append(f"source: {self.source_url}")
        lines.append("")
        lines.append("## OpenRouter")
        lines.append("")
        if self.openrouter_entry is not None:
            lines.append("| model | input (/1M) | cache read (/1M) | output (/1M) |")
            lines.append("|---|---|---|---|")
            if self.openrouter_input_mtok is None:
                lines.append(f"| `{self.openrouter_slug}` | free | — | — |")
            else:
                row = " | ".join(
                    f"{value:g}" if value is not None else "—"
                    for value in (
                        self.openrouter_input_mtok,
                        self.openrouter_cache_read_mtok,
                        self.openrouter_output_mtok,
                    )
                )
                lines.append(f"| `{self.openrouter_slug}` | {row} |")
            lines.append("")
            lines.append(f"source: {OPENROUTER_MODELS_URL}")
        else:
            lines.append(self.openrouter_note)
        lines.append("")
        lines.append("## notes")
        lines.append("")
        lines.append(
            "- no cache-read pricing on the vendor page: the vendor entry carries no "
            "`cache_read_mtok`"
        )
        if self.skipped_latest:
            aliases = ", ".join(f"`{value}`" for value in self.skipped_latest)
            lines.append(
                f"- `-latest` alias clauses skipped: {aliases} "
                "(family/version aliases, not separately priced models)"
            )
        return "\n".join(lines) + "\n"


def parse_github_url(repo: str) -> tuple[str, str]:
    prefix = "https://github.com/"
    if not repo.startswith(prefix):
        raise PrError(f"repo url must start with '{prefix}': {repo!r}")
    parts = repo.removeprefix(prefix).split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise PrError(f"repo url must be '{prefix}<owner>/<name>': {repo!r}")
    return parts[0], parts[1]


def default_branch(owner: str, name: str, runner: PrRunner) -> str:
    return runner.run(
        ["gh", "api", f"repos/{owner}/{name}", "--jq", ".default_branch"], cwd=Path.cwd()
    ).strip()


def branch_name(key: str) -> str:
    return "autopr/" + re.sub(r"[^A-Za-z0-9._/-]", "-", key)


def pending_pr(model_id: str, runner: PrRunner) -> str | None:
    """The url of an open PR on the real upstream naming model_id, or None.

    The upstream repo is hardcoded: this is the one place that ignores REPO, so
    a fork or a test clone never shadows the real pending-work scan. A hit is a
    plain skip in the pipeline: no state change, the id re-candidates when the
    PR closes.
    """
    out = runner.run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            UPSTREAM,
            "--state",
            "open",
            "--search",
            f"{model_id} in:title,body",
            "--json",
            "url",
            "--jq",
            ".[0].url",
        ],
        cwd=Path.cwd(),
    ).strip()
    return out or None


def open_pr(
    owner: str,
    name: str,
    base: str,
    branch: str,
    head_owner: str,
    spec: PrSpec,
    runner: PrRunner,
) -> str:
    return runner.run(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            f"{owner}/{name}",
            "--draft",
            "--base",
            base,
            "--head",
            f"{head_owner}:{branch}",
            "--title",
            spec.title,
            "--body",
            spec.body,
        ],
        cwd=Path.cwd(),
    ).strip()


def existing_pr(owner: str, name: str, branch: str, runner: PrRunner) -> str | None:
    """the url of an open PR for branch, or None.

    --head matches any owner's branch of that name, not just ours. branch
    names are deterministic (autopr/<key>), so an earlier run's PR is found
    after a fork or re-push. concurrent runs are not serialized: this assumes
    the sequential daily cron, not parallel invocations racing one branch.
    """
    out = runner.run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            f"{owner}/{name}",
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "url",
            "--jq",
            ".[0].url",
        ],
        cwd=Path.cwd(),
    ).strip()
    return out or None


def push_or_fork(repo_url: str, branch: str, slot: Path, runner: PrRunner) -> str:
    owner, _name = parse_github_url(repo_url)
    runner.run(["gh", "auth", "setup-git"], cwd=slot)
    try:
        runner.run(["git", "push", "origin", branch], cwd=slot)
    except PrError as exc:
        if not _is_permission_denied(exc):
            raise
        fork_url = runner.run(
            ["gh", "repo", "fork", repo_url, "--clone=false", "--remote=false"], cwd=slot
        ).strip()
        fork_owner, _name = parse_github_url(fork_url)
        runner.run(["git", "remote", "add", "fork", fork_url], cwd=slot)
        runner.run(["git", "push", "fork", branch], cwd=slot)
        return fork_owner
    return owner


def open_draft_pr(cfg: Config, base: str, slot: Path, spec: PrSpec, runner: PrRunner) -> str:
    owner, name = parse_github_url(cfg.repo)
    found = existing_pr(owner, name, spec.branch, runner)
    if found:
        return found
    from autopr_genai_prices import build

    build.prepare(slot, base, spec, runner)
    head_owner = push_or_fork(cfg.repo, spec.branch, slot, runner)
    return open_pr(owner, name, base, spec.branch, head_owner, spec, runner)


_PERMISSION_MARKERS = ("403", "denied", "permission")


def _is_permission_denied(exc: PrError) -> bool:
    text = f"{exc} {exc.stderr}".lower()
    return any(marker in text for marker in _PERMISSION_MARKERS)


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

import json
import re
import shutil
import subprocess
from pathlib import Path

from litellm_autopr.config import Config

PRICES_FILE = Path("model_prices_and_context_window.json")


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


def prepare_branch(
    workdir: Path,
    repo_url: str,
    base: str,
    branch: str,
    entry_key: str,
    entry: dict,
    file_path: Path,
    runner: PrRunner,
) -> Path | None:
    workdir.mkdir(parents=True, exist_ok=True)
    slot = workdir / branch
    shutil.rmtree(slot, ignore_errors=True)
    runner.run(["git", "clone", "--depth", "1", "--branch", base, repo_url, str(slot)], cwd=workdir)
    target = slot / file_path
    data = json.loads(target.read_text())
    if data.get(entry_key) == entry:
        return None
    data[entry_key] = entry
    target.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")
    runner.run(["git", "checkout", "-b", branch], cwd=slot)
    ensure_author(slot, runner)
    runner.run(["git", "add", "--", str(file_path)], cwd=slot)
    # the clone inherits the operator's global core.hooksPath; the commit runs
    # in an ephemeral clone, so bypass external hooks (repo hooks in .git/hooks
    # stay active, none exist in the target repo's layout)
    runner.run(
        ["git", "-c", "core.hooksPath=/dev/null", "commit", "-m", f"add {entry_key} pricing"],
        cwd=slot,
    )
    return slot


def open_pr(
    owner: str,
    name: str,
    base: str,
    branch: str,
    head_owner: str,
    entry_key: str,
    source_url: str,
    runner: PrRunner,
) -> str:
    title = f"add {entry_key} pricing"
    body = f"add `{entry_key}` pricing\n\nsource: `{source_url}`"
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
            title,
            "--body",
            body,
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


def open_draft_pr(
    cfg: Config,
    entry_key: str,
    entry: dict,
    source_url: str,
    workdir: Path,
    runner: PrRunner,
) -> str:
    owner, name = parse_github_url(cfg.repo)
    base = default_branch(owner, name, runner)
    branch = branch_name(entry_key)
    found = existing_pr(owner, name, branch, runner)
    if found:
        return found
    slot = prepare_branch(workdir, cfg.repo, base, branch, entry_key, entry, PRICES_FILE, runner)
    if slot is None:
        return ""
    head_owner = push_or_fork(cfg.repo, branch, slot, runner)
    return open_pr(owner, name, base, branch, head_owner, entry_key, source_url, runner)


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

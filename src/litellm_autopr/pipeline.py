import argparse
import logging
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from litellm_autopr import config, litellm, pr, validate
from litellm_autopr.state import ProviderState, append_unique
from litellm_autopr.state import load as load_state
from litellm_autopr.state import new_ids as state_new_ids
from litellm_autopr.state import save as save_state

log = logging.getLogger(__name__)


@dataclass
class ProviderReport:
    detected: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    prs: list[tuple[str, str]] = field(default_factory=list)
    skipped_no_pricing: list[str] = field(default_factory=list)
    skipped_cap: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class RunReport:
    providers: dict[str, ProviderReport] = field(default_factory=dict)


def run(
    cfg: config.Config, workdir: Path, repo_root: Path, runner: pr.PrRunner | None = None
) -> RunReport:
    runner = runner or pr.PrRunner()
    workdir.mkdir(parents=True, exist_ok=True)
    live = litellm.fetch_live()

    repo_slot = workdir / "repo"
    shutil.rmtree(repo_slot, ignore_errors=True)
    runner.run(["git", "clone", "--depth", "1", cfg.repo, str(repo_slot)], cwd=workdir)
    repo_entries = validate.validate_repo_file(repo_slot / pr.PRICES_FILE)

    state = load_state(repo_root / "state.json")
    report = RunReport()
    open_drafts = 0
    state_changed = False

    for pcfg in cfg.providers:
        provider_report = report.providers[pcfg.key] = ProviderReport()
        try:
            detector = config.resolve_provider_module("detectors", pcfg.detector)
            current = list(detector.detect(pcfg))
        except Exception as exc:
            log.exception("detector for %s failed", pcfg.key)
            provider_report.error = _describe(exc)
            continue
        provider_report.detected = current

        created = pcfg.key not in state.providers
        provider_state = state.providers.setdefault(pcfg.key, ProviderState())
        if created:
            state_changed = True
        candidates = state_new_ids(state, pcfg.key, current)
        provider_report.candidates = candidates

        for model_id in candidates:
            entry_key = f"{pcfg.namespace}/{model_id}"
            if entry_key in repo_entries:
                append_unique(provider_state.last_seen, model_id)
                state_changed = True
                continue
            try:
                scraper = config.resolve_provider_module("scrapers", pcfg.scraper)
                pricing = scraper.scrape(pcfg, model_id)
            except Exception as exc:
                log.exception("scraper %s failed for %s", pcfg.key, model_id)
                provider_report.error = _describe(exc)
                break
            if pricing is None:
                provider_report.skipped_no_pricing.append(model_id)
                continue
            new_key, entry = litellm.build_entry(pcfg.namespace, pcfg.provider, model_id, pricing)
            try:
                validate.validate_entry(new_key, entry, live, cfg)
            except validate.ValidationError as exc:
                log.exception("entry %s failed validation", new_key)
                provider_report.error = _describe(exc)
                continue
            if open_drafts >= cfg.cap:
                provider_report.skipped_cap.append(model_id)
                continue
            try:
                url = pr.open_draft_pr(cfg, new_key, entry, pcfg.scraper_url, workdir, runner)
            except Exception as exc:
                log.exception("pr open failed for %s", new_key)
                provider_report.error = _describe(exc)
                break
            if not url:
                # entry merged upstream between clones: nothing to open, but the
                # id is settled against the live repo and must not re-candidate
                append_unique(provider_state.last_seen, model_id)
                state_changed = True
                log.info("entry %s already merged upstream; settled without a pr", new_key)
                continue
            provider_report.prs.append((model_id, url))
            append_unique(provider_state.handled, model_id)
            append_unique(provider_state.last_seen, model_id)
            state_changed = True
            open_drafts += 1
            log.info("opened pr for %s: %s", new_key, url)

    save_state(state, repo_root / "state.json")
    if state_changed:
        try:
            runner.run(["git", "add", "state.json"], cwd=repo_root)
            runner.run(["git", "commit", "-m", "chore: advance watchdog state"], cwd=repo_root)
        except pr.PrError as exc:
            # an unchanged file or gitignored state.json makes the commit a
            # no-op: nothing staged. distinguish that from a real failure by
            # asking git whether staged changes exist (exit 1 = changes stay).
            try:
                runner.run(["git", "diff", "--cached", "--quiet"], cwd=repo_root)
            except pr.PrError:
                log.warning("state commit failed: %s", _describe(exc))
            else:
                log.info("state commit skipped: nothing staged (%s)", _describe(exc))
        try:
            runner.run(["git", "push", "origin"], cwd=repo_root)
        except pr.PrError:
            log.warning(
                "state push failed; pr urls are recorded locally, next run re-checks open prs"
            )
    return report


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", help="working dir for clones (default: $AUTOPR_WORKDIR)")
    args = parser.parse_args()
    try:
        cfg = config.load()
        workdir = Path(args.workdir) if args.workdir else default_workdir()
        run(cfg, workdir, repo_root=Path.cwd())
    except (config.ConfigError, pr.PrError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def default_workdir() -> Path:
    env = os.environ.get("AUTOPR_WORKDIR")
    if env:
        return Path(env)
    if Path("/mnt/scratch").exists():
        return Path(f"/mnt/scratch/autopr-run-{os.getpid()}")
    return Path(tempfile.mkdtemp(prefix="autopr-run-"))


def _describe(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"

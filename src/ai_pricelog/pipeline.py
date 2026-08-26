"""The daily run: append observed price rows, open one draft PR per change.

Watches the provider pages through the detector/scraper pairs, plus the
OpenRouter models API. Every PR branch carries the same full store (the
load-time rows plus the pending branches' rows plus this run's rows) on a
`pricelog/<slug>-<sha8>` branch (never the default branch), so sibling PRs
stop conflicting on the data files at merge: the first merged PR lands
everything pending and the later ones merge as empty diffs. The index and the
seen-state ride the same branch commit, and one human-reviewed draft PR is
opened per (source, model_id) pair. The tree is restored to HEAD after each
PR, so every PR branch starts from the default branch tip. When the store was
empty at load, one seed PR carries all rows with no draft cap; while that
seed PR is still open, the run skips itself.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from ai_pricelog import config, openrouter, pr, store, validate
from ai_pricelog.state import ProviderState, State, append_unique
from ai_pricelog.state import load as load_state
from ai_pricelog.state import new_ids as state_new_ids
from ai_pricelog.state import save as save_state

log = logging.getLogger(__name__)

HISTORY_FILE = "data/history.ndjson"
INDEX_FILE = "data/index.json"
STATE_FILE = "state.json"


@dataclass
class ProviderReport:
    detected: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    rows: list[str] = field(default_factory=list)
    prs: list[tuple[str, str]] = field(default_factory=list)
    skipped_pending: list[str] = field(default_factory=list)
    skipped_no_pricing: list[str] = field(default_factory=list)
    skipped_cap: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class RunReport:
    providers: dict[str, ProviderReport] = field(default_factory=dict)


@dataclass
class _PrGroup:
    """The new rows one PR carries, keyed by (source, model_id)."""

    source: str
    model_id: str
    provider: str
    source_url: str
    rows: list[dict[str, object]] = field(default_factory=list)
    state_ids: list[str] = field(default_factory=list)
    update: bool = False


def run(
    cfg: config.Config,
    repo_root: Path,
    runner: pr.PrRunner | None = None,
    today: str | None = None,
) -> RunReport:
    runner = runner or pr.PrRunner()
    today = today or date.today().isoformat()
    history_path = repo_root / HISTORY_FILE
    state_path = repo_root / STATE_FILE

    rows = store.load(history_path)
    state = load_state(state_path)
    seed = not rows
    report = RunReport()
    run_url = pr.run_url_from_env()

    base = pr.default_branch(runner, repo_root)
    base_sha = runner.run(["git", "rev-parse", "HEAD"], cwd=repo_root).strip()
    original_branch = runner.run(["git", "branch", "--show-current"], cwd=repo_root).strip()
    pr.ensure_author(repo_root, runner)
    runner.run(["gh", "auth", "setup-git"], cwd=repo_root)

    open_prs = pr.open_pull_requests(runner, repo_root)
    if seed and pr.seed_pending(open_prs):
        log.info("store empty at load and the seed pr is still open; skipping the run")
        return report

    rows = store.union(rows, pr.fetch_pending_rows(runner, repo_root, HISTORY_FILE))

    plan: dict[tuple[str, str], _PrGroup] = {}

    for pcfg in cfg.providers:
        provider_report = report.providers[pcfg.key] = ProviderReport()
        try:
            detector = config.resolve_provider_module("detectors", pcfg.detector)
            detected = list(detector.detect(pcfg))
        except Exception as exc:
            log.exception("detector for %s failed", pcfg.key)
            provider_report.errors.append(_describe(exc))
            continue
        provider_report.detected = detected
        try:
            scraper = config.resolve_provider_module("scrapers", pcfg.scraper)
        except Exception as exc:
            log.exception("scraper module for %s failed", pcfg.key)
            provider_report.errors.append(_describe(exc))
            continue
        dedup_keys = getattr(scraper, "dedup_keys", None)

        _add_candidates(
            pcfg, scraper, detected, rows, state, plan, provider_report, open_prs, today
        )
        _refresh_drift(
            pcfg, scraper, dedup_keys, detected, rows, plan, provider_report, open_prs, today
        )

    _openrouter_rows(rows, plan, report, open_prs, today)

    if not plan:
        return report

    run_rows = [row for group in plan.values() for row in group.rows]
    full_rows = rows + run_rows
    state_updates: dict[str, list[str]] = {}
    for group in plan.values():
        if group.state_ids:
            state_updates.setdefault(group.source, []).extend(group.state_ids)
    updated_state = _with_new_ids(state, state_updates) if state_updates else state

    if seed:
        spec = pr.PrSpec(
            source="seed",
            model_id="seed",
            provider="",
            source_url="",
            rows=tuple(run_rows),
            seed=True,
            run_url=run_url,
        )
        url = _open_group_pr(
            repo_root,
            base,
            base_sha,
            original_branch,
            spec,
            full_rows,
            state,
            updated_state,
            "feat: seed price history",
            runner,
        )
        if url is None:
            for group in plan.values():
                _record_error(report, group.source, f"seed pr failed for {group.model_id}")
            return report
        for group in plan.values():
            _record_pr(report, group, url)
        return report

    opened = 0
    for group in plan.values():
        if opened >= cfg.cap:
            report.providers[group.source].skipped_cap.append(group.model_id)
            log.info("pr for %s skipped: draft cap", group.model_id)
            continue
        spec = pr.PrSpec(
            source=group.source,
            model_id=group.model_id,
            provider=group.provider,
            source_url=group.source_url,
            rows=tuple(group.rows),
            update=group.update,
            run_url=run_url,
        )
        verb = "update" if group.update else "add"
        url = _open_group_pr(
            repo_root,
            base,
            base_sha,
            original_branch,
            spec,
            full_rows,
            state,
            updated_state,
            f"feat: {verb} {group.model_id} price history",
            runner,
        )
        if url is None:
            _record_error(report, group.source, f"pr open failed for {group.model_id}")
            continue
        _record_pr(report, group, url)
        opened += 1
        log.info("opened pr for %s: %s", group.model_id, url)
    return report


def _add_candidates(
    pcfg: config.ProviderCfg,
    scraper: Any,
    detected: list[str],
    rows: list[dict[str, object]],
    state: State,
    plan: dict[tuple[str, str], _PrGroup],
    provider_report: ProviderReport,
    open_prs: Sequence[pr.OpenPr],
    today: str,
) -> None:
    """First rows for ids the store has never seen.

    Store membership (a row under the exact page id, pending branches
    included) and last_seen settle an id silently; an open draft PR naming it
    skips it without a state change, so a closed-unmerged PR re-candidates it
    next run.
    """
    candidates: list[str] = []
    for model_id in state_new_ids(state, pcfg.key, detected):
        if store.last(rows, pcfg.key, model_id) is not None:
            continue
        if pr.pending_pr(model_id, open_prs):
            provider_report.skipped_pending.append(model_id)
            continue
        candidates.append(model_id)
    provider_report.candidates = candidates
    for model_id in candidates:
        try:
            pricing = scraper.scrape(pcfg, model_id)
        except Exception as exc:
            log.exception("scraper %s failed for %s", pcfg.key, model_id)
            provider_report.errors.append(_describe(exc))
            continue
        if pricing is None:
            # skip-and-retry: the page carries no row for the id yet
            provider_report.skipped_no_pricing.append(model_id)
            continue
        try:
            row = store.build_row(pcfg.key, model_id, pricing, today, pcfg.scraper_url)
            validate.validate_row(row)
        except validate.ValidationError as exc:
            log.warning("entry %s failed validation: %s", model_id, exc)
            provider_report.errors.append(_describe(exc))
            continue
        group = plan.setdefault(
            (pcfg.key, model_id),
            _PrGroup(pcfg.key, model_id, pcfg.provider, pcfg.scraper_url),
        )
        group.rows.append(row)
        group.state_ids.append(model_id)


def _refresh_drift(
    pcfg: config.ProviderCfg,
    scraper: Any,
    dedup_keys: Any,
    detected: list[str],
    rows: list[dict[str, object]],
    plan: dict[tuple[str, str], _PrGroup],
    provider_report: ProviderReport,
    open_prs: Sequence[pr.OpenPr],
    today: str,
) -> None:
    """Drift-check every detected page id against its stored rows.

    Maps the page id through the scraper's dedup_keys to the stored spelling
    (the first spelling that has a row, pending branches included), scrapes
    with the PAGE id (the scrapers key their rows by page spelling), and
    appends a row under the STORED spelling when the rates changed. Stateless:
    a merged PR settles by itself (the next run diffs against the landed row),
    an open one is skipped by the pending check.
    """
    for page_id in detected:
        spellings = [page_id] + list(dedup_keys(page_id) if dedup_keys is not None else [])
        stored = next(
            (
                spelling
                for spelling in spellings
                if store.last(rows, pcfg.key, spelling) is not None
            ),
            None,
        )
        if stored is None or (pcfg.key, stored) in plan:
            continue  # nothing stored yet, or the row is fresh from this run
        if pr.pending_pr(stored, open_prs):
            log.info("refresh for %s skipped: pending pr", stored)
            provider_report.skipped_pending.append(stored)
            continue
        try:
            pricing = scraper.scrape(pcfg, page_id)
        except Exception as exc:
            log.exception("refresh scrape failed for %s", stored)
            provider_report.errors.append(_describe(exc))
            continue
        if pricing is None:
            provider_report.skipped_no_pricing.append(stored)
            continue
        try:
            row = store.build_row(pcfg.key, stored, pricing, today, pcfg.scraper_url)
            validate.validate_row(row)
        except validate.ValidationError as exc:
            log.warning("refresh for %s skipped: %s", stored, exc)
            provider_report.errors.append(_describe(exc))
            continue
        if not store.changed(row, store.last(rows, pcfg.key, stored)):
            log.debug("refresh for %s: unchanged", stored)
            continue
        group = plan.setdefault(
            (pcfg.key, stored),
            _PrGroup(pcfg.key, stored, pcfg.provider, pcfg.scraper_url, update=True),
        )
        group.rows.append(row)
        group.state_ids.append(stored)


def _openrouter_rows(
    rows: list[dict[str, object]],
    plan: dict[tuple[str, str], _PrGroup],
    report: RunReport,
    open_prs: Sequence[pr.OpenPr],
    today: str,
) -> None:
    """OpenRouter rows: the API is the source, store membership settles ids."""
    or_report = report.providers["openrouter"] = ProviderReport()
    try:
        models = openrouter.fetch_models()
    except Exception as exc:
        log.exception("openrouter fetch failed")
        or_report.errors.append(_describe(exc))
        return
    or_report.detected = [model.id for model in models]
    for model in models:
        row = openrouter.build_row(model, today)
        if row is None:
            # alias entries and dated-canonical snapshots are not priced rows
            or_report.skipped_no_pricing.append(model.id)
            continue
        model_id = row["model_id"]
        last_row = store.last(rows, "openrouter", model_id)
        if not store.changed(row, last_row):
            continue
        if pr.pending_pr(model_id, open_prs):
            or_report.skipped_pending.append(model_id)
            continue
        or_report.candidates.append(model_id)
        group = plan.setdefault(
            ("openrouter", model_id),
            _PrGroup(
                "openrouter",
                model_id,
                "OpenRouter",
                openrouter.OPENROUTER_MODELS_URL,
                update=last_row is not None,
            ),
        )
        group.rows.append(row)


def _open_group_pr(
    repo_root: Path,
    base: str,
    base_sha: str,
    original_branch: str,
    spec: pr.PrSpec,
    full_rows: list[dict[str, object]],
    state: State,
    updated_state: State,
    message: str,
    runner: pr.PrRunner,
) -> str | None:
    """Write the PR branch, push it, open the draft, restore the tree.

    Every branch of a run carries the same full_rows and seen-state, so the
    first merged PR lands everything pending and the later sibling PRs merge
    as empty diffs instead of conflicting on the data files. The default
    branch is never committed or pushed, and the tree is restored to the
    pre-run head after every PR, so each branch starts from the same base.
    """
    branch = spec.branch
    history_path = repo_root / HISTORY_FILE
    index_path = repo_root / INDEX_FILE
    state_path = repo_root / STATE_FILE
    try:
        runner.run(["git", "switch", "-C", branch], cwd=repo_root)
        store.save(full_rows, history_path)
        store.write_index(full_rows, index_path)
        add_cmd = ["git", "add", HISTORY_FILE, INDEX_FILE]
        if updated_state is not state:
            save_state(updated_state, state_path)
            add_cmd.append(STATE_FILE)
        runner.run(add_cmd, cwd=repo_root)
        runner.run(["git", "commit", "-m", message], cwd=repo_root)
    except pr.PrError:
        log.exception("branch commit failed for %s", branch)
        _restore(repo_root, original_branch, base_sha, runner)
        return None
    try:
        runner.run(["git", "push", "--force-with-lease", "origin", branch], cwd=repo_root)
        url = pr.open_pr(base, branch, spec, runner, repo_root)
    except pr.PrError:
        log.exception("push or pr open failed for %s", branch)
        _delete_remote_branch(repo_root, branch, runner)
        _restore(repo_root, original_branch, base_sha, runner)
        return None
    _restore(repo_root, original_branch, base_sha, runner)
    return url


def _delete_remote_branch(repo_root: Path, branch: str, runner: pr.PrRunner) -> None:
    """Drop the just-pushed branch from origin so the next run can re-create it.

    The push succeeded but the PR never opened; the orphaned branch would
    otherwise ride the next run's pending-branch union as rows no PR carries.
    """
    try:
        runner.run(["git", "push", "origin", "--delete", branch], cwd=repo_root)
    except pr.PrError:
        log.warning("remote branch cleanup for %s failed", branch)


def _restore(repo_root: Path, original_branch: str, base_sha: str, runner: pr.PrRunner) -> None:
    """Return the tree to the pre-run head after a PR branch.

    A named local branch is switched back to; a detached head (the actions
    checkout) returns to the base sha. Everything the PR changed is committed
    on the branch, so the switch itself reverts the tracked files.
    """
    if original_branch and original_branch != "HEAD":
        target = ["git", "switch", original_branch]
    else:
        target = ["git", "switch", "--detach", base_sha]
    try:
        runner.run(target, cwd=repo_root)
    except pr.PrError:
        log.exception("restore failed; the next PR branch would start from the previous one")


def _with_new_ids(state: State, updates: dict[str, list[str]]) -> State:
    updated = State(
        providers={
            key: ProviderState(last_seen=list(provider_state.last_seen))
            for key, provider_state in state.providers.items()
        }
    )
    for source, ids in updates.items():
        target = updated.providers.setdefault(source, ProviderState())
        for model_id in ids:
            append_unique(target.last_seen, model_id)
    return updated


def _record_pr(report: RunReport, group: _PrGroup, url: str) -> None:
    provider_report = report.providers[group.source]
    provider_report.rows.extend([group.model_id] * len(group.rows))
    provider_report.prs.append((group.model_id, url))


def _record_error(report: RunReport, source: str, message: str) -> None:
    report.providers[source].errors.append(message)


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        cfg = config.load()
        run(cfg, Path.cwd())
    except (config.ConfigError, pr.PrError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _describe(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"

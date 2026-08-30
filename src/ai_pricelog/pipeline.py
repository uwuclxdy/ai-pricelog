"""The 6-hourly run: append observed price and removal rows, open one draft PR per source.

Watches the provider pages through the detector/scraper pairs, plus the
OpenRouter models API. A run groups its new rows into one draft pr per
source (removal rows included), with no cap: every pr branch carries the
landed store (the load-time rows plus the open prs' pending branches' rows)
plus only the rows its own pr covers, on a `pricelog/<slug>-<sha8>` batch
branch (never the default branch). Rows for models whose pr cannot open stay
out of every branch: the human review of each draft pr is the only guard
against a misread price, so a row lands only under its own pr or the seed,
and a skipped model re-candidates against the landed store on the next run.
The index and the recomputed README stats ride the same branch commit. The
tree is restored to HEAD after each pr, so every pr branch starts from the
default branch tip. When the store was empty at load, one seed pr carries
all rows; while that seed pr is still open, the run skips itself.

A stored model absent from its source's page twice (both observations landed
through prs) gets a removal row; the counters live in data/absence.json,
which only ever lands on pr branches, so a flaky page never fakes a
delisting. When the run opens a pr it touches `.run-changed` for the CI step
that reads it; a state-only diff with no pr opens nothing reviewable and
leaves the marker alone.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import partial
from pathlib import Path
from typing import Any

from ai_pricelog import absence, announce, config, openrouter, pr, stats, store, validate

log = logging.getLogger(__name__)

HISTORY_FILE = "data/history.ndjson"
INDEX_FILE = "data/index.json"
FX_FILE = "data/fx-rates.json"
README_FILE = "README.md"
MARKER_FILE = ".run-changed"


@dataclass
class ProviderReport:
    detected: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    rows: list[str] = field(default_factory=list)
    prs: list[tuple[str, str]] = field(default_factory=list)
    skipped_pending: list[str] = field(default_factory=list)
    skipped_no_pricing: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class RunReport:
    providers: dict[str, ProviderReport] = field(default_factory=dict)
    announce: list[announce.ChannelChange] = field(default_factory=list)
    announce_errors: list[str] = field(default_factory=list)


@dataclass
class _PrGroup:
    """The new rows one pr carries, grouped per source."""

    source: str
    provider: str
    source_url: str
    rows: list[dict[str, object]] = field(default_factory=list)


def run(
    cfg: config.Config,
    repo_root: Path,
    runner: pr.PrRunner | None = None,
    today: str | None = None,
    now: str | None = None,
) -> RunReport:
    runner = runner or pr.PrRunner()
    today = today or date.today().isoformat()
    stamp = now or datetime.now().strftime("%H%M%S")
    history_path = repo_root / HISTORY_FILE
    marker_path = repo_root / MARKER_FILE
    marker_path.unlink(missing_ok=True)

    rows = store.load(history_path)
    fx = store.load_fx(repo_root / FX_FILE)
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

    landed_rows = rows
    rows = store.union(rows, pr.fetch_pending_rows(runner, repo_root, HISTORY_FILE, open_prs))

    snapshot = announce.load_snapshot(repo_root / announce.ANNOUNCE_FILE)
    fetch = announce.fetch_channels(cfg, snapshot, today)
    report.announce = list(fetch.changes)
    report.announce_errors = list(fetch.errors)
    for change in fetch.changes:
        log.info(
            "announce change: %s %s %s -> %s",
            change.provider,
            change.url,
            change.old_sha256[:8],
            change.new_sha256[:8],
        )
    # the fresh snapshot rides the next pr branch (skip-and-retry): with no pr
    # opened it stays uncommitted, the changes re-surface, and the snapshot
    # settles only under a human-reviewed pr
    announce_updates = fetch.snapshot if announce.differs(snapshot, fetch.snapshot) else None

    absence_state = absence.load_absence(repo_root / absence.ABSENCE_FILE)
    fresh_absence = {
        source: {model_id: dict(entry) for model_id, entry in entries.items()}
        for source, entries in absence_state.items()
    }

    plan: dict[tuple[str, str], _PrGroup] = {}
    removal_groups: list[_PrGroup] = []

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
        resolve = partial(store.resolve_rate, fx, pcfg.currency_rate)

        absence_ids = detected
        detect_priced = getattr(detector, "detect_priced", None)
        if detect_priced is not None:
            try:
                absence_ids = list(detect_priced(pcfg))
            except Exception as exc:
                log.exception("priced detection for %s failed", pcfg.key)
                provider_report.errors.append(_describe(exc))
                absence_ids = None

        _add_candidates(
            pcfg,
            scraper,
            dedup_keys,
            detected,
            rows,
            plan,
            provider_report,
            open_prs,
            today,
            resolve,
        )
        _refresh_drift(
            pcfg,
            scraper,
            dedup_keys,
            detected,
            rows,
            plan,
            provider_report,
            open_prs,
            today,
            resolve,
        )
        _track_provider_absence(
            pcfg,
            dedup_keys,
            absence_ids,
            rows,
            landed_rows,
            fresh_absence,
            removal_groups,
            open_prs,
            today,
        )

    _openrouter_rows(
        rows, landed_rows, plan, report, open_prs, today, fresh_absence, removal_groups
    )

    fresh_absence = {source: entries for source, entries in fresh_absence.items() if entries}
    absence_diff = fresh_absence != absence_state

    if not plan and not removal_groups:
        # no pr opened, so nothing reviewable landed: no marker, whatever the
        # in-memory state diff says (skip-and-retry re-derives it next run)
        return report

    if seed:
        run_rows = [row for group in plan.values() for row in group.rows]
        spec = pr.PrSpec(
            source="seed",
            provider="",
            source_url="",
            rows=tuple(run_rows),
            seed=True,
            run_url=run_url,
            announce=fetch.changes,
            absence_update=absence_diff,
        )
        url = _open_group_pr(
            repo_root,
            base,
            base_sha,
            original_branch,
            spec,
            rows + run_rows,
            "feat: seed price history",
            runner,
            announce_updates,
            fresh_absence if absence_diff else None,
        )
        if url is None:
            for group in plan.values():
                for row in group.rows:
                    _record_error(report, group.source, f"seed pr failed for {row['model_id']}")
            return report
        for group in plan.values():
            _record_pr(report, group, url)
        _touch_marker(marker_path)
        return report

    # one pr per source per run: a source's removal rows and price rows ride
    # the same pr, so a burst groups into a handful of prs and nothing is
    # capped (the pending scan still settles models behind open prs)
    batches: dict[str, _PrGroup] = {}
    for group in plan.values():
        target = batches.setdefault(
            group.source, _PrGroup(group.source, group.provider, group.source_url)
        )
        target.rows.extend(group.rows)
    for group in removal_groups:
        target = batches.setdefault(
            group.source, _PrGroup(group.source, group.provider, group.source_url)
        )
        target.rows.extend(group.rows)

    opened = 0
    for group in batches.values():
        spec = pr.PrSpec(
            source=group.source,
            provider=group.provider,
            source_url=group.source_url,
            rows=tuple(group.rows),
            run_url=run_url,
            announce=fetch.changes,
            absence_update=absence_diff,
            batch_key=f"{group.source}@{today}-{stamp}",
        )
        url = _open_group_pr(
            repo_root,
            base,
            base_sha,
            original_branch,
            spec,
            rows + group.rows,
            _commit_message(spec),
            runner,
            announce_updates,
            fresh_absence if absence_diff else None,
        )
        if url is None:
            # a failed open commits nothing: the rows re-derive against the
            # landed store on the next run, the counters against the
            # committed baseline (skip-and-retry)
            _record_error(report, group.source, f"pr open failed for {len(group.rows)} rows")
            continue
        _record_pr(report, group, url)
        opened += 1
        log.info("opened pr for %s: %s", group.source, url)
    if opened > 0:
        _touch_marker(marker_path)
    return report


def _touch_marker(path: Path) -> None:
    """One line, no content: the signal for the CI step that reads it."""
    path.write_text("\n", encoding="utf-8")


def _stored_spelling(
    rows: list[dict[str, object]],
    source: str,
    model_id: str,
    dedup_keys: Any,
) -> str | None:
    """The first spelling of model_id with a stored row, or None when unseen.

    A removal row still counts as stored: a delisted model reappearing must
    map back to its stored spelling instead of re-candidating under the page
    spelling.
    """
    spellings = [model_id] + list(dedup_keys(model_id) if dedup_keys is not None else [])
    return next(
        (spelling for spelling in spellings if store.newest(rows, source, spelling) is not None),
        None,
    )


def _add_candidates(
    pcfg: config.ProviderCfg,
    scraper: Any,
    dedup_keys: Any,
    detected: list[str],
    rows: list[dict[str, object]],
    plan: dict[tuple[str, str], _PrGroup],
    provider_report: ProviderReport,
    open_prs: Sequence[pr.OpenPr],
    today: str,
    resolve: Callable[[str, str], tuple[float, str] | None],
) -> None:
    """First rows for ids the store has never seen under any spelling.

    Store membership (the page id or a dedup spelling, pending branches
    included) settles an id silently; an open draft PR naming it skips it,
    so a closed-unmerged PR re-candidates it next run. an id without a store
    row keeps re-candidating until its first row lands (decision 8,
    skip-and-retry).
    """
    candidates: list[str] = []
    for model_id in dict.fromkeys(detected):
        if _stored_spelling(rows, pcfg.key, model_id, dedup_keys) is not None:
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
            row = store.build_row(
                pcfg.key, model_id, pricing, today, pcfg.scraper_url, resolve=resolve
            )
            validate.validate_row(row)
        except validate.ValidationError as exc:
            log.warning("entry %s failed validation: %s", model_id, exc)
            provider_report.errors.append(_describe(exc))
            continue
        group = plan.setdefault(
            (pcfg.key, model_id),
            _PrGroup(pcfg.key, pcfg.provider, pcfg.scraper_url),
        )
        group.rows.append(row)


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
    resolve: Callable[[str, str], tuple[float, str] | None],
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
        stored = _stored_spelling(rows, pcfg.key, page_id, dedup_keys)
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
            row = store.build_row(
                pcfg.key, stored, pricing, today, pcfg.scraper_url, resolve=resolve
            )
            validate.validate_row(row)
        except validate.ValidationError as exc:
            log.warning("refresh for %s skipped: %s", stored, exc)
            provider_report.errors.append(_describe(exc))
            continue
        newest = store.newest(rows, pcfg.key, stored)
        if (newest is None or newest.get("removed") is not True) and not store.changed(
            row, store.last(rows, pcfg.key, stored)
        ):
            log.debug("refresh for %s: unchanged", stored)
            continue
        # a removal row as the newest row means the model reappeared: append
        # the fresh row even at unchanged prices so the index drops removed_at
        group = plan.setdefault(
            (pcfg.key, stored),
            _PrGroup(pcfg.key, pcfg.provider, pcfg.scraper_url),
        )
        group.rows.append(row)


def _openrouter_rows(
    rows: list[dict[str, object]],
    landed_rows: list[dict[str, object]],
    plan: dict[tuple[str, str], _PrGroup],
    report: RunReport,
    open_prs: Sequence[pr.OpenPr],
    today: str,
    state: dict[str, dict[str, dict[str, object]]],
    removal_groups: list[_PrGroup],
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
    rowable: set[str] = set()
    for model in models:
        row = openrouter.build_row(model, today)
        if row is None:
            # alias entries and dated-canonical snapshots are not priced rows
            or_report.skipped_no_pricing.append(model.id)
            continue
        rowable.add(row["model_id"])
        try:
            validate.validate_row(row)
        except validate.ValidationError as exc:
            log.warning("openrouter entry %s failed validation: %s", model.id, exc)
            or_report.errors.append(_describe(exc))
            continue
        model_id = row["model_id"]
        last_row = store.last(rows, "openrouter", model_id)
        newest = store.newest(rows, "openrouter", model_id)
        if (newest is None or newest.get("removed") is not True) and not store.changed(
            row, last_row
        ):
            continue
        if pr.pending_pr(model_id, open_prs):
            or_report.skipped_pending.append(model_id)
            continue
        or_report.candidates.append(model_id)
        group = plan.setdefault(
            ("openrouter", model_id),
            _PrGroup("openrouter", "OpenRouter", openrouter.OPENROUTER_MODELS_URL),
        )
        group.rows.append(row)
    stored_ids = {entry["model_id"] for entry in rows if entry.get("source") == "openrouter"}
    _track_absence(
        "openrouter",
        "OpenRouter",
        openrouter.OPENROUTER_MODELS_URL,
        stored_ids,
        rowable,
        rows,
        landed_rows,
        state,
        removal_groups,
        open_prs,
        today,
    )


def _track_provider_absence(
    pcfg: config.ProviderCfg,
    dedup_keys: Any,
    absence_ids: list[str] | None,
    rows: list[dict[str, object]],
    landed_rows: list[dict[str, object]],
    state: dict[str, dict[str, dict[str, object]]],
    removal_groups: list[_PrGroup],
    open_prs: Sequence[pr.OpenPr],
    today: str,
) -> None:
    """Absence counters for one provider: page ids mapped to stored spellings.

    `absence_ids` is the priced set when the detector exposes `detect_priced`
    (a model still carded but no longer priced counts absent), else the full
    detected set. a `None` set means priced detection failed and the counters
    skip this run (skip-and-retry). Only stored ids can be absent, and the
    scraper's dedup decides which page id covers which stored spelling, so a
    deduped spelling never counts as absent while its page twin is listed.
    """
    if absence_ids is None:
        return
    stored_ids = {row["model_id"] for row in rows if row.get("source") == pcfg.key}
    if not stored_ids:
        state.pop(pcfg.key, None)
        return
    present: set[str] = set()
    for page_id in dict.fromkeys(absence_ids):
        spelling = _stored_spelling(rows, pcfg.key, page_id, dedup_keys)
        if spelling is not None:
            present.add(spelling)
    _track_absence(
        pcfg.key,
        pcfg.provider,
        pcfg.scraper_url,
        stored_ids,
        present,
        rows,
        landed_rows,
        state,
        removal_groups,
        open_prs,
        today,
    )


def _track_absence(
    source: str,
    provider: str,
    source_url: str,
    stored_ids: set[str],
    present_ids: set[str],
    rows: list[dict[str, object]],
    landed_rows: list[dict[str, object]],
    state: dict[str, dict[str, dict[str, object]]],
    removal_groups: list[_PrGroup],
    open_prs: Sequence[pr.OpenPr],
    today: str,
) -> None:
    """Move the per-model absence counters and plan removal rows.

    A present id clears its entry; an absent id raises its counter, and the
    second landed absent observation plans a removal row whose pr opens like
    any price row (same per-source batch). The raised entry stays in the
    state: the landed-removal cleanup drops it once the row reaches the
    store, and a rejected pr leaves the committed baseline untouched for the
    next run to re-derive. Ids behind an open pr are skipped entirely.
    """
    source_state = state.setdefault(source, {})
    # entries only ever describe stored ids; drop anything else
    for model_id in [mid for mid in source_state if mid not in stored_ids]:
        del source_state[model_id]
    for model_id in [mid for mid in source_state if mid in present_ids]:
        del source_state[model_id]
    # a landed removal ends tracking: the row is the record, and re-counting
    # would churn the state (and the CI marker) on every later run. only a
    # LANDED row counts: a pending removal still has an open pr, and dropping
    # its entry early would lose the counters if that pr gets rejected
    for model_id in [
        mid for mid in source_state if store.newest(landed_rows, source, mid).get("removed") is True
    ]:
        del source_state[model_id]
    absent_ids = {
        model_id
        for model_id in stored_ids
        if model_id not in present_ids
        and not pr.pending_pr(model_id, open_prs)
        and store.newest(rows, source, model_id).get("removed") is not True
    }
    for model_id in sorted(absent_ids):
        entry = source_state.get(model_id)
        if entry is None:
            source_state[model_id] = {"absent_runs": 1, "since": today}
            continue
        entry["absent_runs"] = min(entry["absent_runs"] + 1, 2)
        if entry["absent_runs"] < 2:
            continue
        newest = store.newest(rows, source, model_id)
        if newest is not None and newest.get("removed") is True:
            # the removal row is already on record: one per key ever
            del source_state[model_id]
            continue
        row = store.build_removal_row(source, model_id, today, store.last(rows, source, model_id))
        validate.validate_row(row)
        group = _PrGroup(source, provider, source_url)
        group.rows.append(row)
        removal_groups.append(group)


def _open_group_pr(
    repo_root: Path,
    base: str,
    base_sha: str,
    original_branch: str,
    spec: pr.PrSpec,
    full_rows: list[dict[str, object]],
    message: str,
    runner: pr.PrRunner,
    announce_updates: dict[str, dict[str, dict[str, str]]] | None = None,
    absence_updates: dict[str, dict[str, dict[str, object]]] | None = None,
) -> str | None:
    """Write the PR branch, push it, open the draft, restore the tree.

    The branch carries the landed store plus only the rows its own PR covers,
    plus the fresh announce snapshot and absence state when they changed this
    run. The default branch is never committed or pushed, and the tree is
    restored to the pre-run head after every PR, so each branch starts from
    the same base.
    """
    branch = spec.branch
    history_path = repo_root / HISTORY_FILE
    index_path = repo_root / INDEX_FILE
    try:
        runner.run(["git", "switch", "-C", branch], cwd=repo_root)
        store.save(full_rows, history_path)
        store.write_index(full_rows, index_path)
        readme_path = repo_root / README_FILE
        readme_path.write_text(
            stats.render(readme_path.read_text(encoding="utf-8"), stats.compute(full_rows)),
            encoding="utf-8",
        )
        add_cmd = ["git", "add", HISTORY_FILE, INDEX_FILE, README_FILE]
        if announce_updates is not None:
            announce.save_snapshot(announce_updates, repo_root / announce.ANNOUNCE_FILE)
            add_cmd.append(announce.ANNOUNCE_FILE)
        if absence_updates is not None:
            absence.save_absence(absence_updates, repo_root / absence.ABSENCE_FILE)
            add_cmd.append(absence.ABSENCE_FILE)
        runner.run(add_cmd, cwd=repo_root)
        runner.run(["git", "commit", "-m", message], cwd=repo_root)
    except pr.PrError:
        log.exception("branch commit failed for %s", branch)
        _restore(repo_root, original_branch, base_sha, runner)
        return None
    try:
        runner.run(["git", "push", "--force-with-lease", "origin", branch], cwd=repo_root)
    except pr.PrError:
        # the branch is not on origin, so a delete would be wrong: a rejected
        # force-with-lease push may mean a peer run pushed the branch first
        log.exception("push failed for %s", branch)
        _restore(repo_root, original_branch, base_sha, runner)
        return None
    try:
        url = pr.open_pr(base, branch, spec, runner, repo_root)
    except pr.PrError:
        log.exception("pr open failed for %s", branch)
        _delete_remote_branch(repo_root, branch, runner)
        _restore(repo_root, original_branch, base_sha, runner)
        return None
    _restore(repo_root, original_branch, base_sha, runner)
    return url


def _delete_remote_branch(repo_root: Path, branch: str, runner: pr.PrRunner) -> None:
    """Drop the just-pushed branch from origin after a failed pr open.

    Only the push-success/pr-open-failure path calls this, so a rejected
    force-with-lease push never deletes a peer run's branch. The dead branch
    would otherwise linger on origin, and the next run recreates it with a
    fresh force-with-lease push.
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


def _record_pr(report: RunReport, group: _PrGroup, url: str) -> None:
    provider_report = report.providers[group.source]
    provider_report.rows.extend(row["model_id"] for row in group.rows)
    provider_report.prs.extend((row["model_id"], url) for row in group.rows)


def _commit_message(spec: pr.PrSpec) -> str:
    """The branch commit subject: the pr title as a feat line."""
    return f"feat: {spec.title[0].lower()}{spec.title[1:]}"


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

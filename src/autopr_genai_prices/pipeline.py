import argparse
import logging
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from autopr_genai_prices import build, config, openrouter, pr, refresh, validate, yml
from autopr_genai_prices.pricing import Pricing
from autopr_genai_prices.state import ProviderState, append_unique
from autopr_genai_prices.state import load as load_state
from autopr_genai_prices.state import new_ids as state_new_ids
from autopr_genai_prices.state import save as save_state

log = logging.getLogger(__name__)

PROVIDERS_DIR = "prices/providers"
OPENROUTER_YML = "openrouter.yml"


@dataclass
class ProviderReport:
    detected: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    prs: list[tuple[str, str]] = field(default_factory=list)
    refreshes: list[tuple[str, str]] = field(default_factory=list)
    skipped_pending: list[str] = field(default_factory=list)
    skipped_no_pricing: list[str] = field(default_factory=list)
    skipped_cap: list[str] = field(default_factory=list)
    skipped_build: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class RunReport:
    providers: dict[str, ProviderReport] = field(default_factory=dict)
    or_followups: list[tuple[str, str]] = field(default_factory=list)


def run(
    cfg: config.Config, workdir: Path, repo_root: Path, runner: pr.PrRunner | None = None
) -> RunReport:
    runner = runner or pr.PrRunner()
    workdir.mkdir(parents=True, exist_ok=True)
    owner, name = pr.parse_github_url(cfg.repo)
    base = pr.default_branch(owner, name, runner)

    repo_slot = workdir / "repo"
    shutil.rmtree(repo_slot, ignore_errors=True)
    runner.run(
        ["git", "clone", "--depth", "1", "--branch", base, cfg.repo, str(repo_slot)],
        cwd=workdir,
    )
    providers_dir = repo_slot / PROVIDERS_DIR
    or_yml = yml.parse(providers_dir / OPENROUTER_YML)
    or_models = openrouter.fetch_models()
    or_text = (providers_dir / OPENROUTER_YML).read_text()

    state = load_state(repo_root / "state.json")
    report = RunReport()
    open_drafts = 0
    state_changed = False
    parsed: dict[str, tuple[yml.ProviderYml, Any]] = {}

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

        try:
            vendor_yml = yml.parse(providers_dir / pcfg.yml)
            scraper = config.resolve_provider_module("scrapers", pcfg.scraper)
        except Exception as exc:
            log.exception("provider setup for %s failed", pcfg.key)
            provider_report.error = _describe(exc)
            continue
        parsed[pcfg.key] = (vendor_yml, scraper)
        dedup_keys = getattr(scraper, "dedup_keys", None)

        created = pcfg.key not in state.providers
        provider_state = state.providers.setdefault(pcfg.key, ProviderState())
        if created:
            state_changed = True
        candidates = state_new_ids(state, pcfg.key, current)
        provider_report.candidates = candidates

        for model_id in candidates:
            try:
                pending = pr.pending_pr(model_id, runner)
            except Exception as exc:
                log.exception("pending check failed for %s", model_id)
                provider_report.error = _describe(exc)
                break
            if pending:
                # someone is already adding this model: plain skip, no state
                # change, so a closed-unmerged PR re-candidates the model
                provider_report.skipped_pending.append(model_id)
                continue
            if yml.is_tracked(vendor_yml, model_id) or (
                dedup_keys is not None
                and any(yml.is_tracked(vendor_yml, key) for key in dedup_keys(model_id))
            ):
                # upstream (or a provider-specific key spelling) already tracks
                # this model: settled against the live repo, never re-candidates
                append_unique(provider_state.last_seen, model_id)
                state_changed = True
                continue
            try:
                pricing = scraper.scrape(pcfg, model_id)
            except Exception as exc:
                log.exception("scraper %s failed for %s", pcfg.key, model_id)
                provider_report.error = _describe(exc)
                break
            if pricing is None:
                provider_report.skipped_no_pricing.append(model_id)
                continue
            try:
                validate.validate_entry(model_id, pricing)
            except validate.ValidationError as exc:
                log.exception("entry %s failed validation", model_id)
                provider_report.error = _describe(exc)
                continue
            if open_drafts >= cfg.cap:
                provider_report.skipped_cap.append(model_id)
                continue
            spec = _pr_spec(pcfg, vendor_yml, or_yml, or_models, model_id, pricing, scraper)
            try:
                url = pr.open_draft_pr(cfg, base, repo_slot, spec, runner)
            except build.BuildError as exc:
                log.warning("build failed for %s: %s", model_id, exc)
                provider_report.skipped_build.append(model_id)
                continue
            except Exception as exc:
                log.exception("pr open failed for %s", model_id)
                provider_report.error = _describe(exc)
                break
            provider_report.prs.append((model_id, url))
            append_unique(provider_state.handled, model_id)
            append_unique(provider_state.last_seen, model_id)
            state_changed = True
            open_drafts += 1
            log.info("opened pr for %s: %s", model_id, url)

        if provider_report.error is None:
            try:
                refreshed, drafts = _refresh_provider(
                    cfg,
                    pcfg,
                    vendor_yml,
                    scraper,
                    current,
                    base,
                    repo_slot,
                    or_text,
                    or_yml,
                    or_models,
                    open_drafts,
                    runner,
                )
            except Exception as exc:
                log.exception("refresh for %s failed", pcfg.key)
                provider_report.error = _describe(exc)
            else:
                provider_report.refreshes.extend(refreshed)
                open_drafts += drafts

    report.or_followups = _or_followups(
        cfg, state, parsed, or_yml, or_models, base, repo_slot, open_drafts, runner
    )

    save_state(state, repo_root / "state.json")
    if state_changed:
        try:
            pr.ensure_author(repo_root, runner)
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
        # the actions checkout is a detached head; GITHUB_REF_NAME names the
        # branch it came from. locally the current branch is the target.
        try:
            branch = (
                os.environ.get("GITHUB_REF_NAME")
                or runner.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root).strip()
            )
        except pr.PrError as exc:
            log.warning("state push skipped: %s", _describe(exc))
            branch = ""
        if branch == "HEAD" or not branch:
            log.warning("state push skipped: no branch resolved")
        else:
            try:
                runner.run(["git", "push", "origin", f"HEAD:refs/heads/{branch}"], cwd=repo_root)
            except pr.PrError:
                log.warning(
                    "state push failed; pr urls are recorded locally, next run re-checks open prs"
                )
    return report


def _refresh_provider(
    cfg: config.Config,
    pcfg: config.ProviderCfg,
    vendor_yml: yml.ProviderYml,
    scraper: Any,
    detected: list[str],
    base: str,
    repo_slot: Path,
    or_text: str,
    or_yml: yml.ProviderYml,
    or_models: list[openrouter.OpenrouterModel],
    open_drafts: int,
    runner: pr.PrRunner,
) -> tuple[list[tuple[str, str]], int]:
    """Drift-check the tracked models; returns (opened prs, drafts used).

    Iterates the detector's page ids, maps each through the scraper's
    dedup_keys to the tracked entry spelling, scrapes with the page id (the
    scrapers key their rows by page spelling), and opens an update pr on
    drift. Stateless: a landed update settles by itself (the next run diffs
    against it), an open one is skipped by the pending-pr check, and the
    draft cap is shared with additions.
    """
    tracked = {model.id: model for model in vendor_yml.models if not model.removed}
    dedup_keys = getattr(scraper, "dedup_keys", None)
    opened: list[tuple[str, str]] = []
    drafts = open_drafts
    seen: set[str] = set()
    for page_id in detected:
        spellings = [page_id] + list(dedup_keys(page_id) if dedup_keys is not None else [])
        entry = next((tracked[spelling] for spelling in spellings if spelling in tracked), None)
        if entry is None or entry.id in seen or entry.prices is None:
            continue
        seen.add(entry.id)
        try:
            pending = pr.pending_pr(entry.id, runner)
        except Exception:
            log.exception("refresh pending check failed for %s", entry.id)
            continue
        if pending:
            log.info("refresh for %s skipped: pending pr", entry.id)
            continue
        try:
            pricing = scraper.scrape(pcfg, page_id)
        except Exception:
            log.exception("refresh scrape failed for %s", entry.id)
            continue
        if pricing is None:
            log.debug("refresh for %s skipped: no pricing on the page", entry.id)
            continue
        try:
            validate.validate_entry(entry.id, pricing)
        except validate.ValidationError as exc:
            log.warning("refresh for %s skipped: %s", entry.id, exc)
            continue
        drift = refresh.compare(entry.prices, pricing)
        if drift.action == "none":
            log.debug("refresh for %s: %s", entry.id, drift.note)
            continue
        if drafts >= cfg.cap:
            log.info("refresh for %s skipped: draft cap", entry.id)
            continue
        spec = _update_pr_spec(
            pcfg, vendor_yml, entry, pricing, drift, repo_slot, or_text, or_yml, or_models
        )
        try:
            url = pr.open_draft_pr(cfg, base, repo_slot, spec, runner)
        except build.BuildError as exc:
            log.warning("refresh build failed for %s: %s", entry.id, exc)
            continue
        opened.append((entry.id, url))
        drafts += 1
        log.info("opened refresh pr for %s: %s", entry.id, url)
    return opened, drafts - open_drafts


def _update_pr_spec(
    pcfg: config.ProviderCfg,
    vendor_yml: yml.ProviderYml,
    entry: yml.TrackedModel,
    pricing: Pricing,
    drift: refresh.Drift,
    repo_slot: Path,
    or_text: str,
    or_yml: yml.ProviderYml,
    or_models: list[openrouter.OpenrouterModel],
) -> pr.PrSpec:
    checked = date.today().isoformat()
    update = refresh.build_update_spec(
        pcfg,
        (repo_slot / PROVIDERS_DIR / pcfg.yml).read_text(),
        entry,
        pricing,
        drift,
        checked,
        or_text,
        or_yml,
        or_models,
    )
    return pr.PrSpec(
        key=pcfg.key,
        model_id=entry.id,
        entry_id=entry.id,
        vendor_yml=pcfg.yml,
        vendor_name=vendor_yml.name,
        vendor_entry=None,
        vendor_input_mtok=update.input_mtok,
        vendor_output_mtok=update.output_mtok,
        vendor_peak_input_mtok=update.peak_input_mtok,
        vendor_peak_output_mtok=update.peak_output_mtok,
        vendor_peak_windows=update.peak_windows,
        skipped_latest=(),
        source_url=pcfg.scraper_url,
        openrouter_entry=None,
        openrouter_slug=f"{pcfg.or_prefix}/{entry.id.lower()}",
        openrouter_input_mtok=None,
        openrouter_output_mtok=None,
        openrouter_cache_read_mtok=None,
        openrouter_note="",
        update=update,
    )


def _or_followups(
    cfg: config.Config,
    state: object,
    parsed: dict[str, tuple[yml.ProviderYml, Any]],
    or_yml: yml.ProviderYml,
    or_models: list[openrouter.OpenrouterModel],
    base: str,
    repo_slot: Path,
    open_drafts: int,
    runner: pr.PrRunner,
) -> list[tuple[str, str]]:
    """Open the follow-up prs for vendor additions whose openrouter entry deferred.

    Derives the candidate set from the live clone, never from state, so a
    closed-unmerged vendor pr cannot trigger a follow-up for an entry that
    never landed, and a landed follow-up goes quiet by itself (the slug then
    reads as tracked). Best-effort: a failure here skips the slug, it never
    fails the run.
    """
    opened: list[tuple[str, str]] = []
    drafts = open_drafts
    seen_slugs: set[str] = set()
    for pcfg in cfg.providers:
        provider_state = getattr(state, "providers", {}).get(pcfg.key)
        if provider_state is None or not provider_state.handled:
            continue
        pair = parsed.get(pcfg.key)
        if pair is None:
            continue
        vendor_yml, scraper = pair
        dedup_keys = getattr(scraper, "dedup_keys", None)
        for model_id in provider_state.handled:
            entry_id = (dedup_keys(model_id) or [model_id])[0] if dedup_keys else model_id
            if not yml.is_tracked(vendor_yml, entry_id):
                continue  # the vendor pr never landed: no openrouter entry to fill
            slug = f"{pcfg.or_prefix}/{entry_id.lower()}"
            if slug in seen_slugs:
                continue  # two page ids dedup to one slug: one follow-up per run
            seen_slugs.add(slug)
            if yml.is_tracked(or_yml, slug):
                continue  # landed
            try:
                if pr.pending_pr(slug, runner):
                    log.info("or follow-up for %s skipped: pending pr", slug)
                    continue
                or_model = openrouter.find(or_models, pcfg.or_prefix, entry_id)
            except Exception as exc:
                log.warning("or follow-up check failed for %s: %s", slug, exc)
                continue
            if or_model is None or drafts >= cfg.cap:
                continue  # still deferred, or cap reached
            spec = pr.PrSpec(
                key=pcfg.key,
                model_id=model_id,
                entry_id=slug,
                vendor_yml=OPENROUTER_YML,
                vendor_name="OpenRouter",
                vendor_entry=None,
                vendor_input_mtok=0.0,
                vendor_output_mtok=0.0,
                vendor_peak_input_mtok=None,
                vendor_peak_output_mtok=None,
                vendor_peak_windows=(),
                skipped_latest=(),
                source_url=openrouter.OPENROUTER_MODELS_URL,
                openrouter_entry=yml.build_openrouter_entry(
                    slug,
                    or_model.name,
                    or_model.input_mtok,
                    or_model.output_mtok,
                    or_model.cache_read_mtok,
                ),
                openrouter_slug=slug,
                openrouter_input_mtok=or_model.input_mtok,
                openrouter_output_mtok=or_model.output_mtok,
                openrouter_cache_read_mtok=or_model.cache_read_mtok,
                openrouter_note="",
            )
            try:
                url = pr.open_draft_pr(cfg, base, repo_slot, spec, runner)
            except build.BuildError as exc:
                log.warning("or follow-up build failed for %s: %s", slug, exc)
                continue
            except Exception as exc:
                log.warning("or follow-up pr failed for %s: %s", slug, exc)
                continue
            opened.append((slug, url))
            drafts += 1
            log.info("opened or follow-up pr for %s: %s", slug, url)
    return opened


def _pr_spec(
    pcfg: config.ProviderCfg,
    vendor_yml: yml.ProviderYml,
    or_yml: yml.ProviderYml,
    or_models: list[openrouter.OpenrouterModel],
    model_id: str,
    pricing: Pricing,
    scraper: Any,
) -> pr.PrSpec:
    checked = date.today().isoformat()
    # the page spelling may diverge from the target's tracked spelling
    # (mistral dashed dates vs compacted); the entry and the openrouter slug
    # carry the target spelling, state and branch keep the page id
    dedup_keys = getattr(scraper, "dedup_keys", None)
    entry_id = (dedup_keys(model_id) or [model_id])[0] if dedup_keys else model_id
    vendor_entry, skipped = yml.build_vendor_entry(
        vendor_yml, entry_id, pricing, checked, pcfg.scraper_url
    )
    slug = f"{pcfg.or_prefix}/{entry_id.lower()}"
    or_model = openrouter.find(or_models, pcfg.or_prefix, entry_id)
    if or_model is None:
        or_entry, or_note = (
            None,
            (
                f"`{slug}` is not listed on the OpenRouter models API; "
                "the openrouter entry is deferred"
            ),
        )
    elif yml.is_tracked(or_yml, slug):
        or_entry, or_note = (
            None,
            (f"`{slug}` is already tracked in openrouter.yml; no openrouter entry in this pr"),
        )
    else:
        or_entry = yml.build_openrouter_entry(
            slug, or_model.name, or_model.input_mtok, or_model.output_mtok, or_model.cache_read_mtok
        )
        or_note = ""
    or_values = or_model if or_entry is not None else None
    return pr.PrSpec(
        key=pcfg.key,
        model_id=model_id,
        entry_id=entry_id,
        vendor_yml=pcfg.yml,
        vendor_name=vendor_yml.name,
        vendor_entry=vendor_entry,
        vendor_input_mtok=yml.to_mtok(pricing.input_cost_per_token),
        vendor_output_mtok=yml.to_mtok(pricing.output_cost_per_token),
        vendor_peak_input_mtok=(
            yml.to_mtok(pricing.peak_input_cost_per_token)
            if pricing.peak_input_cost_per_token is not None
            else None
        ),
        vendor_peak_output_mtok=(
            yml.to_mtok(pricing.peak_output_cost_per_token)
            if pricing.peak_output_cost_per_token is not None
            else None
        ),
        vendor_peak_windows=pricing.peak_windows,
        skipped_latest=skipped,
        source_url=pcfg.scraper_url,
        openrouter_entry=or_entry,
        openrouter_slug=slug,
        openrouter_input_mtok=or_values.input_mtok if or_values is not None else None,
        openrouter_output_mtok=or_values.output_mtok if or_values is not None else None,
        openrouter_cache_read_mtok=or_values.cache_read_mtok if or_values is not None else None,
        openrouter_note=or_note,
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
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

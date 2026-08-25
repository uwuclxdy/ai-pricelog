"""Candidate preparation inside the target clone.

Owns everything that runs inside the clone for one candidate: the yml edits,
`uv sync`, `make build`, the generated calc_price test and its self-verify
loop, `make test`, pre-commit on the changed files, staging the explicit file
list, and the commit. Every external command runs through the PrRunner seam so
the pipeline tests stay offline. BuildError marks candidate-attributable
failures: the pipeline skips the candidate and retries next run.
"""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

from ai_pricelog import yml
from ai_pricelog.pr import PrError, PrRunner, PrSpec, _stderr_tail
from ai_pricelog.pr import ensure_author as ensure_clone_author

_STAGE_PATHS = frozenset(
    {
        "prices/providers/openrouter.yml",
        "prices/new_data/v2/data.json",
        "prices/new_data/v2/data_slim.json",
        "prices/providers/.schema.json",
        "prices/new_data/v2/data.schema.json",
        "prices/new_data/v2/data_slim.schema.json",
        "packages/python/genai_prices/data.py",
        "packages/python/genai_prices/data_units.py",
        "packages/js/src/data.ts",
        "packages/js/src/dataUnits.ts",
        "README.md",
        "tests/test_price_calc.py",
        "tests/test_cli.py",
        "tests/dataset/usages.json",
    }
)

_CALC_SCRIPT = """\
import json
import sys
from datetime import datetime, timezone

from genai_prices import Usage, calc_price

model_ref = sys.argv[1]
hour = int(sys.argv[2])
api_url = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
kwargs = {"provider_api_url": api_url} if api_url is not None else {}
day = (
    datetime.fromisoformat(sys.argv[4])
    if len(sys.argv) > 4 and sys.argv[4]
    else datetime(2025, 6, 1)
)
timestamp = datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)
try:
    price = calc_price(
        Usage(input_tokens=1_000, output_tokens=100),
        model_ref=model_ref,
        genai_request_timestamp=timestamp,
        **kwargs,
    )
except Exception as exc:
    print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
    raise SystemExit(0)
print(
    json.dumps(
        {
            "ok": True,
            "provider_id": price.provider.id,
            "model_id": price.model.id,
            "input_price": str(price.input_price),
            "output_price": str(price.output_price),
            "total_price": str(price.total_price),
        }
    )
)
"""


class BuildError(Exception):
    """a build step in the clone failed; the candidate retries next run."""


@dataclass(frozen=True)
class _CalcOutcome:
    ok: bool
    provider_id: str | None
    model_id: str | None
    input_price: str | None
    output_price: str | None
    total_price: str | None
    error: str | None


@dataclass(frozen=True)
class _CalcResult:
    provider_id: str
    model_id: str
    input_price: str
    output_price: str
    total_price: str
    api_url: str | None
    hour: int
    day: str = "2025-06-01"


def prepare(slot: Path, base: str, spec: PrSpec, runner: PrRunner) -> None:
    """Build and commit one candidate PR inside the shared clone slot."""
    runner.run(["git", "checkout", "-B", spec.branch, base], cwd=slot)
    # a failed candidate leaves uncommitted edits in the shared slot, and
    # checkout -B keeps them when HEAD already equals base: reset to base so
    # the next candidate never inherits a previous one's yml edits
    runner.run(["git", "reset", "--hard"], cwd=slot)
    ensure_clone_author(slot, runner)
    _insert_entries(slot, spec)
    runner.run(["uv", "sync", "--frozen", "--all-packages", "--all-extras"], cwd=slot)
    # the target's js hooks and make build both call npx; without node_modules
    # npx would fetch the latest unpinned toolchain (same reason the target's
    # own CI installs before pre-commit). npm ci installs exactly the
    # committed lock (an unpinned prettier would rewrite the README provider
    # markers and break inject-providers); a bun-shimmed npm maps ci to a
    # frozen-lockfile install and refuses the npm lock, so the fallback
    # install runs there and the shim's own lock must never reach the commit
    try:
        runner.run(["npm", "ci"], cwd=slot)
    except PrError:
        runner.run(["npm", "install", "--no-package-lock"], cwd=slot)
    (slot / "bun.lock").unlink(missing_ok=True)
    _run_make(slot, "build", runner)
    _generate_test(slot, spec, runner)
    _run_make_test(slot, runner)
    _precommit_and_stage(slot, spec, runner)
    # the clone inherits the operator's global core.hooksPath; the commit runs
    # in an ephemeral clone, so bypass external hooks (repo hooks in
    # .git/hooks stay active, none exist in the target repo's layout)
    runner.run(
        ["git", "-c", "core.hooksPath=/dev/null", "commit", "-m", spec.title],
        cwd=slot,
    )


def _insert_entries(slot: Path, spec: PrSpec) -> None:
    providers = slot / "prices" / "providers"
    if spec.update is not None:
        # a drift spec rewrites a tracked block in place (dated append or
        # split conversion), never inserts: the model already has an entry
        update = spec.update
        vendor_path = providers / spec.vendor_yml
        # openrouter.yml entries carry no prices_checked upstream; only the
        # vendor side gets the checked update
        checked = None if spec.vendor_yml == "openrouter.yml" else update.start_date
        vendor_path.write_text(
            yml.rewrite_entry(
                vendor_path.read_text(),
                update.model_id,
                update.prices_section,
                checked=checked,
            )
        )
        if update.or_prices_section is not None:
            openrouter_path = providers / "openrouter.yml"
            openrouter_path.write_text(
                yml.rewrite_entry(
                    openrouter_path.read_text(),
                    spec.openrouter_slug,
                    update.or_prices_section,
                    checked=None,
                )
            )
        return
    if spec.vendor_entry is not None:
        # the entry id sorts the insert: the page spelling may diverge from
        # the target's tracked spelling (mistral dashed vs compacted dates)
        vendor_path = providers / spec.vendor_yml
        vendor_path.write_text(
            yml.insert_entry(vendor_path.read_text(), spec.entry_id, spec.vendor_entry)
        )
    if spec.openrouter_entry is not None:
        openrouter_path = providers / "openrouter.yml"
        openrouter_path.write_text(
            yml.insert_entry(
                openrouter_path.read_text(), spec.openrouter_slug, spec.openrouter_entry
            )
        )


def _tail(exc: PrError) -> str:
    """stderr tail, falling back to stdout: pre-commit reports on stdout."""
    return _stderr_tail(exc.stderr) if exc.stderr.strip() else _stderr_tail(exc.stdout)


def _run_make(slot: Path, target: str, runner: PrRunner) -> None:
    try:
        runner.run(["make", target], cwd=slot)
    except PrError as exc:
        raise BuildError(f"make {target} failed in the clone: {_tail(exc)}") from exc


def _generate_test(slot: Path, spec: PrSpec, runner: PrRunner) -> None:
    """Pin the calc_price resolution, self-verified; red or unresolved -> no test.

    Additions append a new test. Updates regenerate the model's existing
    test: a rate change pins both sides of the start_date boundary (a
    one-sided pin passes against an overwritten history too), a structural
    conversion pins the off-peak hour of the new split schedule.
    """
    test_path = slot / "tests" / "test_price_calc.py"
    original = test_path.read_text()
    provider_data = yaml.safe_load((slot / "prices" / "providers" / spec.vendor_yml).read_text())
    provider_id = provider_data["id"]
    api_url = _unescape(provider_data.get("api_pattern"))
    test_name = _test_name(provider_id, spec.entry_id)
    if spec.update is None:
        hour = _offpeak_hour(spec.vendor_peak_windows)
        values = _calc_values(slot, spec.entry_id, provider_id, api_url, hour, runner)
        if values is None:
            return
        rendered = _render_test(test_name, spec.entry_id, values)
        new_text = original.rstrip("\n") + "\n\n\n" + rendered + "\n"
    else:
        new_text = _regenerate_test(slot, spec, provider_id, api_url, original, runner)
        if new_text is None:
            return
    test_path.write_text(new_text)
    try:
        runner.run(["uv", "run", "pytest", "tests/test_price_calc.py", "-k", test_name], cwd=slot)
    except PrError:
        test_path.write_text(original)


def _regenerate_test(
    slot: Path,
    spec: PrSpec,
    provider_id: str,
    api_url: str | None,
    original: str,
    runner: PrRunner,
) -> str | None:
    """The test file with the model's pin replaced, or None when it cannot be pinned."""
    assert spec.update is not None
    update = spec.update
    hour = _offpeak_hour(update.peak_windows)
    if update.case == "rate_change":
        before = _calc_values(
            slot,
            spec.entry_id,
            provider_id,
            api_url,
            hour,
            runner,
            day=_day_before(update.start_date),
        )
        on = _calc_values(
            slot, spec.entry_id, provider_id, api_url, hour, runner, day=update.start_date
        )
        if before is None or on is None:
            return None
        rendered = _render_two_side_test(
            _test_name(provider_id, spec.entry_id), spec.entry_id, before, on
        )
    else:
        values = _calc_values(slot, spec.entry_id, provider_id, api_url, hour, runner)
        if values is None:
            return None
        rendered = _render_test(_test_name(provider_id, spec.entry_id), spec.entry_id, values)
    replaced = _replace_test_function(original, spec.entry_id, rendered)
    if replaced is None:
        replaced = original.rstrip("\n") + "\n\n\n" + rendered + "\n"
    return replaced


def _day_before(start_date: str) -> str:
    return (date.fromisoformat(start_date) - timedelta(days=1)).isoformat()


def _replace_test_function(text: str, model_id: str, rendered: str) -> str | None:
    """Swap the test function pinning model_id for `rendered`, or None.

    The function is found by its model_ref argument (either quote style),
    then replaced from its def line to the next top-level def. Tests
    hand-edited since our own add pr keep working: whatever the function's
    name, its span is what gets swapped.
    """
    lines = text.splitlines(keepends=True)
    target = None
    for index, line in enumerate(lines):
        if f"model_ref='{model_id}'" in line or f'model_ref="{model_id}"' in line:
            target = index
            break
    if target is None:
        return None
    start = target
    while start > 0 and not lines[start].startswith("def "):
        start -= 1
    if not lines[start].startswith("def "):
        return None
    end = target + 1
    while end < len(lines) and not lines[end].startswith("def "):
        end += 1
    if end < len(lines):
        # a neighbour def follows: everything from the blank separator up to
        # it belongs to that def's decorator block, and replacing it would
        # silently delete the neighbour's marks. stop the span at our own
        # last body line instead
        while end > start and lines[end - 1].strip():
            end -= 1
        while end > start and not lines[end - 1].strip():
            end -= 1
    else:
        while end > start and not lines[end - 1].strip():
            end -= 1
    lines[start:end] = [rendered]
    return "".join(lines)


def _offpeak_hour(windows: tuple[tuple[str, str], ...]) -> int:
    """An hour outside every peak window, for a wall-clock-independent pin.

    The target resolves TimeOfDateConstraint against the request timestamp, so
    a test generated during peak hours would pin peak prices and go red when
    CI runs later. hour 12 is the default for flat entries.
    """
    if not windows:
        return 12
    covered: set[int] = set()
    for start, end in windows:
        start_h = int(start.split(":")[0])
        end_h = int(end.split(":")[0])
        if end_h <= start_h:  # window wraps midnight
            covered.update(range(start_h, 24))
            covered.update(range(0, end_h))
            if not end.endswith(":00:00Z"):  # partial hour after midnight
                covered.add(end_h)
        else:
            covered.update(range(start_h, end_h))
            # a 16:30 end keeps 16:00-16:30 in-window: an on-the-hour pick of
            # 16 would pin peak rates under an off-peak label
            if not end.endswith(":00:00Z"):
                covered.add(end_h)
    for hour in range(24):
        if hour not in covered:
            return hour
    raise BuildError(f"peak windows {windows} cover every hour; no off-peak pin exists")


def _calc_values(
    slot: Path,
    model_id: str,
    provider_id: str,
    api_url: str | None,
    hour: int,
    runner: PrRunner,
    day: str = "2025-06-01",
) -> _CalcResult | None:
    script = slot.parent / ".autopr_calc.py"
    script.write_text(_CALC_SCRIPT)
    try:
        first = _run_calc(script, slot, [model_id, str(hour), "", day], runner)
        if first.ok and first.provider_id == provider_id:
            return _to_result(first, hour, day=day)
        # LookupError (bare ref resolves nothing) and wrong-provider (a shared
        # id resolving to another vendor) both retry scoped by the api url
        retriable = first.ok or "LookupError" in (first.error or "")
        if not retriable or api_url is None:
            return None
        second = _run_calc(script, slot, [model_id, str(hour), api_url, day], runner)
        if second.ok and second.provider_id == provider_id:
            return _to_result(second, hour, api_url=api_url, day=day)
        return None
    finally:
        script.unlink(missing_ok=True)


def _run_calc(script: Path, slot: Path, args: list[str], runner: PrRunner) -> _CalcOutcome:
    out = runner.run(["uv", "run", "python", str(script), *args], cwd=slot)
    parsed = json.loads(out)
    if not isinstance(parsed, dict):
        return _CalcOutcome(False, None, None, None, None, None, "non-object output")
    if not parsed.get("ok"):
        return _CalcOutcome(False, None, None, None, None, None, parsed.get("error") or "")
    return _CalcOutcome(
        True,
        parsed.get("provider_id"),
        parsed.get("model_id"),
        parsed.get("input_price"),
        parsed.get("output_price"),
        parsed.get("total_price"),
        None,
    )


def _to_result(
    outcome: _CalcOutcome, hour: int, api_url: str | None = None, day: str = "2025-06-01"
) -> _CalcResult:
    assert outcome.provider_id is not None
    return _CalcResult(
        provider_id=outcome.provider_id,
        model_id=outcome.model_id or "",
        input_price=outcome.input_price or "",
        output_price=outcome.output_price or "",
        total_price=outcome.total_price or "",
        api_url=api_url,
        hour=hour,
        day=day,
    )


def _unescape(pattern: str | None) -> str | None:
    """Strip regex escape backslashes: the yml api_pattern is a regex, the
    calc_price provider_api_url argument takes a plain url."""
    if not pattern:
        return None
    return re.sub(r"\\(.)", r"\1", pattern)


def _test_name(provider_id: str, model_id: str) -> str:
    provider = re.sub(r"[^A-Za-z0-9]+", "_", provider_id)
    model = re.sub(r"[^A-Za-z0-9]+", "_", model_id)
    return f"test_{provider}_{model}_price"


def _render_test(test_name: str, model_ref: str, values: _CalcResult) -> str:
    return "\n".join(
        [
            f"def {test_name}() -> None:",
            "    from datetime import datetime, timezone",
            "",
            *_render_call(model_ref, values, "price"),
            "",
            *_render_asserts(values, "price"),
        ]
    )


def _render_call(model_ref: str, values: _CalcResult, var: str) -> list[str]:
    year, month, day = (int(part) for part in values.day.split("-"))
    call_lines = [
        f"    {var} = calc_price(",
        "        Usage(input_tokens=1_000, output_tokens=100),",
        f"        model_ref={model_ref!r},",
        (
            "        genai_request_timestamp=datetime("
            f"{year}, {month}, {day}, {values.hour}, tzinfo=timezone.utc),"
        ),
    ]
    if values.api_url is not None:
        call_lines.append(f"        provider_api_url={values.api_url!r},")
    call_lines.append("    )")
    return call_lines


def _render_asserts(values: _CalcResult, var: str) -> list[str]:
    return [
        f"    assert {var}.provider.id == {values.provider_id!r}",
        f"    assert {var}.model.id == {values.model_id!r}",
        f"    assert {var}.input_price == Decimal({values.input_price!r})",
        f"    assert {var}.output_price == Decimal({values.output_price!r})",
        f"    assert {var}.total_price == Decimal({values.total_price!r})",
    ]


def _render_two_side_test(
    test_name: str, model_ref: str, before: _CalcResult, on: _CalcResult
) -> str:
    """A test pinning both sides of a rate-change boundary.

    The day before the start_date resolves the old unconstrained entry, the
    start_date itself the new dated one. A one-sided pin passes against an
    overwritten history too, the failure mode the target's #531 fixed.
    """
    return "\n".join(
        [
            f"def {test_name}() -> None:",
            "    from datetime import datetime, timezone",
            "",
            *_render_call(model_ref, before, "price_before"),
            "",
            *_render_asserts(before, "price_before"),
            "",
            *_render_call(model_ref, on, "price_after"),
            "",
            *_render_asserts(on, "price_after"),
        ]
    )


def _run_make_test(slot: Path, runner: PrRunner) -> None:
    try:
        runner.run(["make", "test"], cwd=slot)
        return
    except PrError:
        # two known first-run failure modes, both self-healing: the target's
        # make test rewrites tests/dataset/usages.json and exits 1, and an
        # added model drifts the provider-list snapshot in tests/test_cli.py
        # (upstream PR #365 hand-updated it; the plugin's fix mode is the
        # same update). a real failure survives both and fails the rerun.
        with contextlib.suppress(PrError):
            runner.run(
                ["uv", "run", "pytest", "tests/test_cli.py", "--inline-snapshot=fix"],
                cwd=slot,
            )
        try:
            runner.run(["make", "test"], cwd=slot)
        except PrError as retry_exc:
            raise BuildError(
                f"make test failed on the rerun in the clone: {_tail(retry_exc)}"
            ) from retry_exc


def _precommit_and_stage(slot: Path, spec: PrSpec, runner: PrRunner) -> None:
    allowed = _STAGE_PATHS | {f"prices/providers/{spec.vendor_yml}"}
    porcelain = runner.run(["git", "status", "--porcelain"], cwd=slot)
    changed = [line[3:] for line in porcelain.splitlines() if line.strip()]
    unexpected = sorted(path for path in changed if path not in allowed)
    if unexpected:
        raise BuildError(f"unexpected modified file(s) in the clone: {', '.join(unexpected)}")
    if not changed:
        raise BuildError("no files changed in the clone; the entries were not inserted")
    _precommit(slot, changed, runner)
    runner.run(["git", "add", "--", *changed], cwd=slot)
    porcelain = runner.run(["git", "status", "--porcelain"], cwd=slot)
    stray = sorted(
        line[3:] for line in porcelain.splitlines() if line.strip() and line[3:] not in allowed
    )
    if stray:
        raise BuildError(
            f"unexpected modified file(s) after staging in the clone: {', '.join(stray)}"
        )


def _precommit(slot: Path, paths: list[str], runner: PrRunner) -> None:
    try:
        runner.run(["uvx", "pre-commit", "run", "--files", *paths], cwd=slot)
    except PrError:
        # fixers apply changes and exit 1 on the first run; the rerun is the
        # gate (same semantics as the target's own CI)
        try:
            runner.run(["uvx", "pre-commit", "run", "--files", *paths], cwd=slot)
        except PrError as retry_exc:
            raise BuildError(f"pre-commit failed in the clone: {_tail(retry_exc)}") from retry_exc

"""default-branch scope guard for the real-tree tests.

two committed-tree invariants (README stats recompute, catalog coverage)
read the checkout's rows against the checkout's committed README and
catalog, so they hold only on the default branch: a pipeline PR branch
carries the default branch's committed derived files plus its own new
rows, and reds there by construction (todo row "ci reds on every pipeline
pr", 2026-09-05) until publish refreshes the default branch. the guard
resolves once per process:

- a PR event (`GITHUB_BASE_REF` names the base) checks out the PR head, so
  it skips; ci's push gate runs only for pushes to the default branch
  (its own trigger pins that), and the scheduled workflows check out the
  default branch, so those events run.
- locally, a `pricelog/` branch is an automation-owned data branch
  (`pr.branch_name`) and skips; a detached local checkout cannot prove
  which tree it holds and skips; every other local checkout runs (rows
  change only on pipeline branches, so the invariants hold elsewhere
  unless genuinely broken).

the guard is an object with a bool value and a `skip_reason` attribute so
`pytest.mark.skipif` renders the reason without a call at import time.
"""

from __future__ import annotations

import os
import subprocess
from functools import cache
from pathlib import Path

_REASON = (
    "real-tree invariants read the checkout's rows against its committed "
    "README stats and models.json; a pipeline data branch carries rows the "
    "committed derived files do not reflect yet, so they red by construction "
    "until publish refreshes the default branch (docs/todo.md, ci reds row)"
)


@cache
def _resolve(repo_root: Path) -> tuple[bool, str]:
    """(is-default-checkout, reason) once per process; never raises."""
    base_ref = os.environ.get("GITHUB_BASE_REF")
    if base_ref:
        return False, f"pull_request against {base_ref}: {_REASON}"
    event = os.environ.get("GITHUB_EVENT_NAME")
    if event in ("pull_request", "pull_request_target"):
        return False, f"{event} event: {_REASON}"
    if event:
        # push: ci.yml's own trigger gates pushes to the default branch;
        # schedule and workflow_dispatch check out the default branch
        return True, _REASON
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        return False, f"git rev-parse failed ({exc}): {_REASON}"
    if branch.startswith("pricelog/"):
        return False, f"pipeline branch {branch}: {_REASON}"
    if branch == "HEAD":
        return False, f"detached checkout: {_REASON}"
    return True, _REASON


class _DefaultBranchTest:
    """import-time guard value: truthy on the default-branch checkout."""

    def __bool__(self) -> bool:
        return _resolve(Path(__file__).resolve().parents[2])[0]

    @property
    def skip_reason(self) -> str:
        return _resolve(Path(__file__).resolve().parents[2])[1]


default_branch_test = _DefaultBranchTest()

"""pin the autopr fallback decision logic (.github/autopr-fallback.sh).

the box-side timer dispatches the autopr workflow hourly; the six-marks-an-hour
github cron exists for when the box is down, and this check keeps that to one
real run per hour: it reads the autopr workflow's runs and dispatches only
when none started in the last 55 minutes and none is active. a broken check
reds its workflow job, so the decision script must exit nonzero on unparseable
input rather than guess.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

FALLBACK = Path(__file__).resolve().parents[1] / ".github" / "autopr-fallback.sh"


def iso(age_seconds: int) -> str:
    return (datetime.now(UTC) - timedelta(seconds=age_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def row(age_seconds: int | None, status: str) -> dict:
    run: dict = {"databaseId": 1, "status": status}
    if age_seconds is not None:
        run["startedAt"] = iso(age_seconds)
    return run


def run_check(runs: list[dict]) -> tuple[int, str]:
    proc = subprocess.run(
        ["bash", str(FALLBACK)],
        input=json.dumps(runs),
        text=True,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    return proc.returncode, proc.stdout.strip()


@pytest.mark.parametrize(
    ("specs", "expected"),
    [
        ([], "dispatch"),  # no autopr run yet (fresh repo edge): dispatch
        ([(3000, "completed")], "skip"),
        ([(4000, "completed")], "dispatch"),
        ([(3000, "in_progress")], "skip"),
        ([(None, "queued")], "skip"),  # queued has no startedAt; status decides
        ([(None, "waiting")], "skip"),  # same: any non-completed status is active
        ([(None, "completed")], "dispatch"),  # completed but never started: no work done
        ([(3000, "completed"), (4000, "completed")], "skip"),  # newest row decides
    ],
)
def test_fallback_verdict(specs: list[tuple[int | None, str]], expected: str) -> None:
    # rows are stamped here, at run time: a timestamp taken at collection ages
    # by the time the test runs, and a run slower than 300 s pushed the
    # 3000 s rows past the 3300 s window
    rc, out = run_check([row(age, status) for age, status in specs])
    assert rc == 0
    assert out == expected


def test_fallback_rejects_unparseable_input() -> None:
    proc = subprocess.run(
        ["bash", str(FALLBACK)],
        input="not json",
        text=True,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode != 0

"""pins on the autopr workflow's run-shape surfaces.

the 2026-09-22 double dispatch (a late fallback mark 14s before the box
timer) raced two runs into duplicate PRs, a stale-ref merge failure and a
stranded queue, so the guards that serialize and refresh the runs are
pinned here: a rewrite of the workflow file that drops one reds the suite
instead of silently reopening the class.
"""

from __future__ import annotations

import re
from pathlib import Path

AUTOPR_WF = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "autopr.yml"


def test_autopr_serializes_duplicate_dispatches():
    # the fallback script prices a duplicate dispatch as a no-op, which only
    # holds while the concurrency group keeps it from overlapping the live run
    text = AUTOPR_WF.read_text()
    assert re.search(
        r"^concurrency:\n\s+group: autopr\n\s+cancel-in-progress: false",
        text,
        re.M,
    ), "autopr lost its concurrency group; duplicate dispatches race again"

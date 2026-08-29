"""Absence tracking: which stored models a source stopped listing.

data/absence.json mirrors announce.json: the pipeline computes a fresh state
each run, and the state lands only on PR branches (skip-and-retry). A stored
model absent from its source's page twice, both observations landed, gets a
removal row in history.ndjson; its entry stays at 2 on the branch until the
pipeline's landed-removal cleanup drops it. a present model's entry is
deleted too. With no PR opened the state stays stale and the next run
re-derives it, so a flaky page never fakes a delisting.
"""

from __future__ import annotations

import json
from pathlib import Path

from ai_pricelog.store import _atomic_write

ABSENCE_FILE = "data/absence.json"


def load_absence(path: Path) -> dict[str, dict[str, dict[str, object]]]:
    """The committed absence state, or an empty one when absent.

    The inner shape gets checked so a hand-edited or badly merged state fails
    at load, naming the file, instead of mid-run at the counter math.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"absence file '{path}': invalid json: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"absence file '{path}': must be an object")
    for source, entries in data.items():
        if not isinstance(source, str) or not isinstance(entries, dict):
            raise ValueError(f"absence file '{path}': source {source!r} must map to an object")
        for model_id, entry in entries.items():
            if not isinstance(entry, dict):
                raise ValueError(
                    f"absence file '{path}': entry {source!r}/{model_id!r} must be an object"
                )
            runs = entry.get("absent_runs")
            if isinstance(runs, bool) or not isinstance(runs, int) or runs not in (1, 2):
                raise ValueError(
                    f"absence file '{path}': entry {source!r}/{model_id!r} "
                    f"absent_runs must be 1 or 2 (got {runs!r})"
                )
            since = entry.get("since")
            if not isinstance(since, str) or not since:
                raise ValueError(
                    f"absence file '{path}': entry {source!r}/{model_id!r} "
                    f"since must be a non-empty string (got {since!r})"
                )
    return data


def save_absence(state: dict[str, dict[str, dict[str, object]]], path: Path) -> None:
    _atomic_write(json.dumps(state, ensure_ascii=False) + "\n", path)

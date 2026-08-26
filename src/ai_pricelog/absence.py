"""Absence tracking: which stored models a source stopped listing.

data/absence.json mirrors announce.json: the pipeline computes a fresh state
each run, and the state lands only on PR branches (skip-and-retry). A stored
model absent from its source's page twice, both observations landed, gets a
removal row in history.ndjson and its entry is deleted; a present model's
entry is deleted too. With no PR opened the state stays stale and the next
run re-derives it, so a flaky page never fakes a delisting.
"""

from __future__ import annotations

import json
from pathlib import Path

from ai_pricelog.store import _atomic_write

ABSENCE_FILE = "data/absence.json"


def load_absence(path: Path) -> dict[str, dict[str, dict[str, object]]]:
    """The committed absence state, or an empty one when absent."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"absence file '{path}': invalid json: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"absence file '{path}': must be an object")
    return data


def save_absence(state: dict[str, dict[str, dict[str, object]]], path: Path) -> None:
    _atomic_write(json.dumps(state, ensure_ascii=False) + "\n", path)

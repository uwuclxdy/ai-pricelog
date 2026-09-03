"""Absence tracking: which stored models a source stopped listing.

state/absence/<source>.json holds one source's counters. The pipeline computes
a fresh state each run, and the state lands only on PR branches (skip-and-retry):
a source's branch writes that source's file alone, the seed branch writes every
source's file. A stored model absent from its source's page twice, both
observations landed, gets a removal row in the source's history shard; its entry
stays at 2 on the branch until the pipeline's landed-removal cleanup drops it. a
present model's entry is deleted too. With no PR opened the state stays stale and
the next run re-derives it, so a flaky page never fakes a delisting.
"""

from __future__ import annotations

import json
from pathlib import Path

from ai_pricelog.store import _atomic_write

ABSENCE_DIR = "state/absence"


def _validate(path: Path, entries: dict[str, dict[str, object]]) -> None:
    for model_id, entry in entries.items():
        if not isinstance(entry, dict):
            raise ValueError(f"absence file '{path}': entry {model_id!r} must be an object")
        runs = entry.get("absent_runs")
        if isinstance(runs, bool) or not isinstance(runs, int) or runs not in (1, 2):
            raise ValueError(
                f"absence file '{path}': entry {model_id!r} "
                f"absent_runs must be 1 or 2 (got {runs!r})"
            )
        since = entry.get("since")
        if not isinstance(since, str) or not since:
            raise ValueError(
                f"absence file '{path}': entry {model_id!r} "
                f"since must be a non-empty string (got {since!r})"
            )


def _load_one(path: Path) -> dict[str, dict[str, object]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"absence file '{path}': invalid json: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"absence file '{path}': must be an object")
    _validate(path, data)
    return data


def load_absence(repo_root: Path) -> dict[str, dict[str, dict[str, object]]]:
    """The committed absence state across state/absence/*.json, or empty when absent.

    The inner shape gets checked so a hand-edited or badly merged state fails
    at load, naming the file, instead of mid-run at the counter math.
    """
    state: dict[str, dict[str, dict[str, object]]] = {}
    ann_dir = repo_root / ABSENCE_DIR
    if not ann_dir.is_dir():
        return state
    for path in sorted(ann_dir.glob("*.json")):
        state[path.stem] = _load_one(path)
    return state


def save_absence(state: dict[str, dict[str, dict[str, object]]], repo_root: Path) -> None:
    """Write one file per named source; delete a named source's file when empty.

    The caller hands only the sources this branch owns, so sibling branches
    never touch the same absence path. A source cleared to zero entries has its
    file deleted, never left holding ``{}``.
    """
    ann_dir = repo_root / ABSENCE_DIR
    ann_dir.mkdir(parents=True, exist_ok=True)
    for source, entries in state.items():
        path = ann_dir / f"{source}.json"
        if entries:
            _atomic_write(json.dumps(entries, ensure_ascii=False) + "\n", path)
        else:
            path.unlink(missing_ok=True)

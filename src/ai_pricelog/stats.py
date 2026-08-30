"""Live counts for the README, recomputed from the store rows on every run.

the README carries two fenced blocks (a stats table under the badges and a
stats row in the comparison table); the pipeline re-renders them from the
rows the PR branch carries, so the printed numbers always recompute from
the data files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_STATS_BLOCK = re.compile(r"<!-- stats:start -->.*?<!-- stats:end -->", re.DOTALL)
_STATS_ROW = re.compile(r"<!-- stats-row:start -->.*?<!-- stats-row:end -->", re.DOTALL)


@dataclass(frozen=True)
class Stats:
    models: int
    sources: int
    rows: int
    first_seen: str
    days: int
    mapped: int


def compute(rows: list[dict[str, object]], mapping: dict[str, dict[str, object]]) -> Stats:
    """Counts over the store rows: models, sources, rows, date span, mapping."""
    models = {(row["source"], row["model_id"]) for row in rows}
    sources = {row["source"] for row in rows}
    dates = sorted({str(row["observed_at"])[:10] for row in rows})
    first = dates[0] if dates else "-"
    days = 0
    if len(dates) > 1:
        days = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days + 1
    return Stats(len(models), len(sources), len(rows), first, days, len(mapping))


def _table(stats: Stats) -> str:
    return (
        "<!-- stats:start -->\n"
        "| metric | value |\n"
        "|---|---|\n"
        f"| models tracked | **{stats.models:,}** |\n"
        f"| sources | {stats.sources} |\n"
        f"| dated rows | {stats.rows:,} |\n"
        f"| canonical models | {stats.mapped:,} |\n"
        f"| history | since {stats.first_seen} ({stats.days:,} days) |\n"
        "<!-- stats:end -->"
    )


def _row(stats: Stats) -> str:
    return (
        "<!-- stats-row:start -->"
        f"| models | **{stats.models:,}** tracked across {stats.sources} sources, "
        f"history back to {stats.first_seen} | "
        "~1.5k models, 36 providers in the generated dataset (measured 2026-08-26) |"
        "<!-- stats-row:end -->"
    )


def render(text: str, stats: Stats) -> str:
    """Replace the two stats blocks; a missing block is a repo error."""
    text, table_hits = _STATS_BLOCK.subn(lambda _match: _table(stats), text)
    text, row_hits = _STATS_ROW.subn(lambda _match: _row(stats), text)
    if table_hits != 1 or row_hits != 1:
        raise ValueError(
            f"README stats blocks: found {table_hits} table and {row_hits} row markers, "
            "need exactly one of each"
        )
    return text

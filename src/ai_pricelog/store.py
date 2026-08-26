"""Append-only price history: one compact ndjson row per line plus a generated index."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from ai_pricelog.pricing import Pricing, to_mtok


def load(path: Path) -> list[dict[str, object]]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    rows: list[dict[str, object]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"history file '{path}': line {number}: invalid json: {exc.msg}"
            ) from exc
        if not isinstance(row, dict):
            raise ValueError(f"history file '{path}': line {number}: must be an object")
        rows.append(row)
    return rows


def save(rows: list[dict[str, object]], path: Path) -> None:
    payload = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows
    )
    _atomic_write(payload, path)


def append_row(rows: list[dict[str, object]], row: dict[str, object]) -> None:
    rows.append(row)


def last(rows: list[dict[str, object]], source: str, model_id: str) -> dict[str, object] | None:
    for row in reversed(rows):
        if row["source"] == source and row["model_id"] == model_id:
            return row
    return None


def changed(row: dict[str, object], last_row: dict[str, object] | None) -> bool:
    if last_row is None:
        return True
    return {k: v for k, v in row.items() if k != "observed_at"} != {
        k: v for k, v in last_row.items() if k != "observed_at"
    }


def write_index(rows: list[dict[str, object]], path: Path) -> None:
    first_seen: dict[tuple[str, str], str] = {}
    latest: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        key = (row["source"], row["model_id"])
        observed_at = row["observed_at"]
        # rows are appended in observation order, but a backfill can land an
        # older timestamp later; keep the earliest seen rather than the first
        if key not in first_seen or observed_at < first_seen[key]:
            first_seen[key] = observed_at
        latest[key] = row
    sources: dict[str, dict[str, dict[str, object]]] = {}
    for (source, model_id), row in sorted(latest.items()):
        entry = dict(row)
        entry["first_seen"] = first_seen[(source, model_id)]
        sources.setdefault(source, {})[model_id] = entry
    _atomic_write(json.dumps({"sources": sources}, ensure_ascii=False) + "\n", path)


def build_row(
    source: str, model_id: str, pricing: Pricing, observed_at: str, url: str
) -> dict[str, object]:
    row: dict[str, object] = {
        "source": source,
        "model_id": model_id,
        "observed_at": observed_at,
        "input_mtok": to_mtok(pricing.input_cost_per_token),
        "output_mtok": to_mtok(pricing.output_cost_per_token),
    }
    if pricing.cache_read_cost_per_token is not None:
        row["cache_read_mtok"] = to_mtok(pricing.cache_read_cost_per_token)
    if pricing.max_tokens > 0:
        row["max_tokens"] = pricing.max_tokens
    if (
        pricing.peak_input_cost_per_token is not None
        or pricing.peak_output_cost_per_token is not None
    ):
        assert pricing.peak_windows, "peak prices set without peak windows"
        row["peak_windows"] = [list(window) for window in pricing.peak_windows]
        if pricing.peak_input_cost_per_token is not None:
            row["peak_input_mtok"] = to_mtok(pricing.peak_input_cost_per_token)
        if pricing.peak_output_cost_per_token is not None:
            row["peak_output_mtok"] = to_mtok(pricing.peak_output_cost_per_token)
    row["url"] = url
    return row


def _atomic_write(payload: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, path)
        tmp_name = None
    finally:
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)

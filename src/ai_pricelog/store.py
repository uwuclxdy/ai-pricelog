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
    return parse(text, str(path))


def parse(text: str, label: str) -> list[dict[str, object]]:
    """Parse ndjson rows from text; errors name the label and the line."""
    rows: list[dict[str, object]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"history file '{label}': line {number}: invalid json: {exc.msg}"
            ) from exc
        if not isinstance(row, dict):
            raise ValueError(f"history file '{label}': line {number}: must be an object")
        rows.append(row)
    return rows


def save(rows: list[dict[str, object]], path: Path) -> None:
    payload = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows
    )
    _atomic_write(payload, path)


def union(rows: list[dict[str, object]], extra: list[dict[str, object]]) -> list[dict[str, object]]:
    """rows plus the extra rows not already present, keyed by (source, model_id, observed_at).

    Pending PR branches each carry a full store snapshot, so their union over
    the loaded store repeats every load-time row; the key dedupe collapses
    those while keeping the rows unique to a pending branch.
    """
    seen = {(row.get("source"), row.get("model_id"), row.get("observed_at")) for row in rows}
    merged = list(rows)
    for row in extra:
        key = (row.get("source"), row.get("model_id"), row.get("observed_at"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def last(rows: list[dict[str, object]], source: str, model_id: str) -> dict[str, object] | None:
    for row in reversed(rows):
        if row["source"] == source and row["model_id"] == model_id:
            return row
    return None


# provenance fields describe where a row came from, never what it costs; a
# difference in them alone is not an observed price change
_PROVENANCE_FIELDS = frozenset({"observed_at", "url", "name"})


def changed(row: dict[str, object], last_row: dict[str, object] | None) -> bool:
    if last_row is None:
        return True
    return {k: v for k, v in row.items() if k not in _PROVENANCE_FIELDS} != {
        k: v for k, v in last_row.items() if k not in _PROVENANCE_FIELDS
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
        # pick the newest observed_at; ties resolve to the later row in the
        # file, so the index never depends on the file's global sort
        if key not in latest or observed_at >= latest[key]["observed_at"]:
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
        # no assert on peak_windows here: the row must build even when the
        # scrape left the windows empty, so validate.validate_row rejects
        # THIS row instead of an AssertionError killing the whole run
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

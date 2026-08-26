"""Append-only model history: one compact ndjson row per line plus a generated index.

Price rows carry the pricing fields; a removal row marks a model delisted
from its source. The index entry keeps the last priced row's fields and gains
a removed_at stamp while the newest row for the key is a removal.
"""

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
    those while keeping the rows unique to a pending branch. removal rows
    bypass the dedupe: a same-day landed price row shares the key with a
    pending removal row, and dropping the removal would hide removed_at from
    sibling branches until the removal PR merges.
    """
    seen = {(row.get("source"), row.get("model_id"), row.get("observed_at")) for row in rows}
    merged = list(rows)
    for row in extra:
        key = (row.get("source"), row.get("model_id"), row.get("observed_at"))
        if row.get("removed") is not True and key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def last(rows: list[dict[str, object]], source: str, model_id: str) -> dict[str, object] | None:
    """The last priced row for the key: removal rows never feed price diffs."""
    for row in reversed(rows):
        if (
            row["source"] == source
            and row["model_id"] == model_id
            and row.get("removed") is not True
        ):
            return row
    return None


def newest(rows: list[dict[str, object]], source: str, model_id: str) -> dict[str, object] | None:
    """The newest row for the key, removal rows included."""
    for row in reversed(rows):
        if row["source"] == source and row["model_id"] == model_id:
            return row
    return None


# provenance fields describe where a row came from, never what it costs; a
# difference in them alone is not an observed price change
_PROVENANCE_FIELDS = frozenset({"observed_at", "url", "name"})


def changed(row: dict[str, object], last_row: dict[str, object] | None) -> bool:
    if last_row is None or last_row.get("removed") is True:
        return True
    return {k: v for k, v in row.items() if k not in _PROVENANCE_FIELDS} != {
        k: v for k, v in last_row.items() if k not in _PROVENANCE_FIELDS
    }


def write_index(rows: list[dict[str, object]], path: Path) -> None:
    first_seen: dict[tuple[str, str], str] = {}
    priced: dict[tuple[str, str], dict[str, object]] = {}
    newest: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        key = (row["source"], row["model_id"])
        observed_at = row["observed_at"]
        # rows are appended in observation order, but a backfill can land an
        # older timestamp later; keep the earliest seen rather than the first
        if key not in first_seen or observed_at < first_seen[key]:
            first_seen[key] = observed_at
        # pick the newest observed_at; ties resolve to the later row in the
        # file, so the index never depends on the file's global sort. a
        # removal row competes for newest (it stamps removed_at) but never
        # for the entry's own fields
        if row.get("removed") is True:
            if key not in newest or observed_at >= newest[key]["observed_at"]:
                newest[key] = row
        else:
            if key not in priced or observed_at >= priced[key]["observed_at"]:
                priced[key] = row
            if key not in newest or observed_at >= newest[key]["observed_at"]:
                newest[key] = row
    sources: dict[str, dict[str, dict[str, object]]] = {}
    for (source, model_id), row in sorted(newest.items()):
        base = priced.get((source, model_id))
        if base is None:
            # removal rows only ever follow a priced row for the key; fall
            # back to the removal's own provenance fields if one sneaks in
            base = {k: v for k, v in row.items() if k != "removed"}
        entry = dict(base)
        entry["first_seen"] = first_seen[(source, model_id)]
        if row.get("removed") is True:
            entry["removed_at"] = row["observed_at"]
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
        or pricing.peak_cache_read_cost_per_token is not None
    ):
        # no assert on peak_windows here: the row must build even when the
        # scrape left the windows empty, so validate.validate_row rejects
        # THIS row instead of an AssertionError killing the whole run
        row["peak_windows"] = [list(window) for window in pricing.peak_windows]
        if pricing.peak_input_cost_per_token is not None:
            row["peak_input_mtok"] = to_mtok(pricing.peak_input_cost_per_token)
        if pricing.peak_output_cost_per_token is not None:
            row["peak_output_mtok"] = to_mtok(pricing.peak_output_cost_per_token)
        if pricing.peak_cache_read_cost_per_token is not None:
            row["peak_cache_read_mtok"] = to_mtok(pricing.peak_cache_read_cost_per_token)
    row["url"] = url
    return row


def build_removal_row(source: str, model_id: str, observed_at: str) -> dict[str, object]:
    """The removal row: one per (source, model_id) ever, no price fields."""
    return {"source": source, "model_id": model_id, "observed_at": observed_at, "removed": True}


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

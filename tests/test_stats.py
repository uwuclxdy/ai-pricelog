from __future__ import annotations

from pathlib import Path

import pytest

from ai_pricelog import models, stats
from ai_pricelog.store import load_shards

ROOT = Path(__file__).resolve().parents[1]

_MAPPING = {
    "m1": {"name": "M1", "curated": True, "sources": {"a": "m1", "b": "m1"}},
    "a/seed": {"vendor": None, "curated": False, "sources": {"a": ["seed"]}},
}


def _rows() -> list[dict[str, object]]:
    return [
        {"source": "a", "model_id": "m1", "observed_at": "2026-08-20", "input_mtok": 1.0},
        {"source": "a", "model_id": "m2", "observed_at": "2026-08-22", "input_mtok": 2.0},
        {"source": "b", "model_id": "m1", "observed_at": "2026-08-26", "input_mtok": 3.0},
        {"source": "a", "model_id": "m1", "observed_at": "2026-08-24", "removed": True},
    ]


def test_compute_counts_models_sources_rows_and_span():
    result = stats.compute(_rows(), _MAPPING)
    assert result == stats.Stats(
        models=3, sources=2, rows=4, first_seen="2026-08-20", days=7, mapped=1
    )


def test_compute_empty_rows_yields_zeros():
    result = stats.compute([], {})
    assert result == stats.Stats(models=0, sources=0, rows=0, first_seen="-", days=0, mapped=0)


def test_render_replaces_both_blocks_and_is_idempotent():
    text = (
        "<!-- stats:start -->old<!-- stats:end -->\n"
        "<!-- stats-row:start -->old row<!-- stats-row:end -->\n"
    )
    rendered = stats.render(text, stats.Stats(3, 2, 4, "2026-08-20", 7, 1))
    assert "**3** tracked across 2 sources, history back to 2026-08-20" in rendered
    assert "| history | since 2026-08-20 (7 days) |" in rendered
    assert "| canonical models | 1 |" in rendered
    assert "old" not in rendered
    assert stats.render(rendered, stats.Stats(3, 2, 4, "2026-08-20", 7, 1)) == rendered


def test_render_missing_marker_raises():
    with pytest.raises(ValueError, match="need exactly one of each"):
        stats.render("<!-- stats:start -->x<!-- stats:end -->", stats.Stats(0, 0, 0, "-", 0, 0))
    with pytest.raises(ValueError, match="need exactly one of each"):
        stats.render(
            "<!-- stats-row:start -->x<!-- stats-row:end -->",
            stats.Stats(0, 0, 0, "-", 0, 0),
        )


def test_committed_readme_stats_recompute_from_data():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    rows = load_shards(ROOT / "data" / "history")
    mapping = models.load_models(ROOT / "data" / "catalog" / "models.json")
    assert stats.render(readme, stats.compute(rows, mapping)) == readme

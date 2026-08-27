from __future__ import annotations

import pytest

from ai_pricelog import absence


def test_absence_file_constant():
    assert absence.ABSENCE_FILE == "data/absence.json"


def test_load_missing_is_empty(tmp_path):
    assert absence.load_absence(tmp_path / "nope.json") == {}


def test_roundtrip(tmp_path):
    state = {"deepseek": {"deepseek-chat": {"absent_runs": 1, "since": "2026-08-26"}}}
    path = tmp_path / "absence.json"
    absence.save_absence(state, path)
    assert absence.load_absence(path) == state
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_load_bad_json_names_file(tmp_path):
    path = tmp_path / "absence.json"
    path.write_text("{nope")
    with pytest.raises(ValueError, match="absence file"):
        absence.load_absence(path)


def test_load_non_object_rejected(tmp_path):
    path = tmp_path / "absence.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="must be an object"):
        absence.load_absence(path)


def test_load_bad_entry_shapes_name_file_and_entry(tmp_path):
    path = tmp_path / "absence.json"
    path.write_text('{"deepseek": {"deepseek-chat": {"absent_runs": "1", "since": "x"}}}')
    with pytest.raises(ValueError, match=r"absence file.*deepseek-chat.*absent_runs"):
        absence.load_absence(path)
    path.write_text('{"deepseek": {"deepseek-chat": {"absent_runs": 1}}}')
    with pytest.raises(ValueError, match=r"absence file.*deepseek-chat.*since"):
        absence.load_absence(path)
    path.write_text('{"deepseek": {"deepseek-chat": {"absent_runs": 3, "since": "x"}}}')
    with pytest.raises(
        ValueError, match=r"absence file.*deepseek-chat.*absent_runs must be 1 or 2"
    ):
        absence.load_absence(path)

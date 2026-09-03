from __future__ import annotations

import pytest

from ai_pricelog import absence


def test_absence_dir_constant():
    assert absence.ABSENCE_DIR == "state/absence"


def test_load_missing_is_empty(tmp_path):
    assert absence.load_absence(tmp_path) == {}


def test_roundtrip(tmp_path):
    state = {"deepseek": {"deepseek-chat": {"absent_runs": 1, "since": "2026-08-26"}}}
    absence.save_absence(state, tmp_path)
    assert absence.load_absence(tmp_path) == state
    assert (tmp_path / "state/absence/deepseek.json").read_text(encoding="utf-8").endswith("\n")


def test_load_bad_json_names_file(tmp_path):
    path = tmp_path / "state/absence/deepseek.json"
    path.parent.mkdir(parents=True)
    path.write_text("{nope")
    with pytest.raises(ValueError, match="absence file"):
        absence.load_absence(tmp_path)


def test_load_non_object_rejected(tmp_path):
    path = tmp_path / "state/absence/deepseek.json"
    path.parent.mkdir(parents=True)
    path.write_text("[]")
    with pytest.raises(ValueError, match="must be an object"):
        absence.load_absence(tmp_path)


def test_load_bad_entry_shapes_name_file_and_entry(tmp_path):
    path = tmp_path / "state/absence/deepseek.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"deepseek-chat": {"absent_runs": "1", "since": "x"}}')
    with pytest.raises(ValueError, match=r"absence file.*deepseek-chat.*absent_runs"):
        absence.load_absence(tmp_path)
    path.write_text('{"deepseek-chat": {"absent_runs": 1}}')
    with pytest.raises(ValueError, match=r"absence file.*deepseek-chat.*since"):
        absence.load_absence(tmp_path)
    path.write_text('{"deepseek-chat": {"absent_runs": 3, "since": "x"}}')
    with pytest.raises(
        ValueError, match=r"absence file.*deepseek-chat.*absent_runs must be 1 or 2"
    ):
        absence.load_absence(tmp_path)


def test_save_deletes_cleared_source_file(tmp_path):
    state = {"deepseek": {"deepseek-chat": {"absent_runs": 1, "since": "2026-08-26"}}}
    absence.save_absence(state, tmp_path)
    assert (tmp_path / "state/absence/deepseek.json").exists()
    absence.save_absence({"deepseek": {}}, tmp_path)
    assert not (tmp_path / "state/absence/deepseek.json").exists()


def test_save_writes_only_named_sources(tmp_path):
    absence.save_absence({"zai": {"zai-chat": {"absent_runs": 1, "since": "2026-08-26"}}}, tmp_path)
    absence.save_absence(
        {"deepseek": {"deepseek-chat": {"absent_runs": 1, "since": "2026-08-26"}}}, tmp_path
    )
    absence.save_absence({"zai": {}}, tmp_path)
    assert not (tmp_path / "state/absence/zai.json").exists()
    assert (tmp_path / "state/absence/deepseek.json").exists()

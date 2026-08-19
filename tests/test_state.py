import json

import pytest

from litellm_autopr import state as state_mod
from litellm_autopr.state import ProviderState, State, load, new_ids, save


def test_roundtrip(tmp_path):
    original = State(providers={"deepseek": ProviderState(["a", "b"], ["a"])})
    path = tmp_path / "state.json"
    save(original, path)
    assert load(path) == original


def test_load_missing_file(tmp_path):
    assert load(tmp_path / "nope.json") == State()


def test_load_bad_json(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{oops")
    with pytest.raises(ValueError, match="state.json"):
        load(path)


def test_load_providers_not_an_object(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"providers": []}))
    with pytest.raises(ValueError, match="'providers'"):
        load(path)


def test_load_provider_not_an_object(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"providers": {"deepseek": []}}))
    with pytest.raises(ValueError, match="'deepseek'"):
        load(path)


def test_load_field_not_a_list(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"providers": {"deepseek": {"last_seen": "a"}}}))
    with pytest.raises(ValueError, match="'last_seen'"):
        load(path)


def test_load_field_holds_non_strings(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"providers": {"deepseek": {"handled": [1]}}}))
    with pytest.raises(ValueError, match="'handled'"):
        load(path)


def test_new_ids_diff_semantics():
    s = State(providers={"deepseek": ProviderState(last_seen=["a"], handled=["b"])})
    assert new_ids(s, "deepseek", ["a", "b", "c", "a"]) == ["c"]
    assert new_ids(s, "deepseek", ["a", "b"]) == []


def test_new_ids_unknown_provider():
    assert new_ids(State(), "other", ["x", "y"]) == ["x", "y"]


def test_new_ids_keeps_current_order():
    s = State()
    assert new_ids(s, "deepseek", ["c", "a", "b"]) == ["c", "a", "b"]


def test_save_dedupes_preserving_order(tmp_path):
    original = State(providers={"deepseek": ProviderState(["a", "b", "a"], ["b", "b"])})
    path = tmp_path / "state.json"
    save(original, path)
    loaded = load(path)
    assert loaded.providers["deepseek"].last_seen == ["a", "b"]
    assert loaded.providers["deepseek"].handled == ["b"]


def test_save_atomic_leaves_no_temp_files(tmp_path):
    original = State(providers={"deepseek": ProviderState(["a", "b"], ["a"])})
    path = tmp_path / "state.json"
    save(original, path)
    save(original, path)  # overwrite an existing file, same guarantee
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "global.gitconfig"]
    assert leftovers == ["state.json"]
    assert json.loads(path.read_text())["providers"]["deepseek"]["last_seen"] == ["a", "b"]
    assert load(path) == original


def test_save_failed_commit_keeps_old_file_and_no_temp_files(tmp_path, monkeypatch):
    original = State(providers={"deepseek": ProviderState(["a"], ["a"])})
    path = tmp_path / "state.json"
    save(original, path)
    old_bytes = path.read_text()

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(state_mod.os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        save(State(providers={"deepseek": ProviderState(["b"], ["b"])}), path)
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "global.gitconfig"]
    assert leftovers == ["state.json"]
    assert path.read_text() == old_bytes
    assert load(path) == original

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_pricelog.models import MappingError, canonical_spelling, hint_candidates, load_models

DATA = Path(__file__).resolve().parents[1] / "data"


def models_file(tmp_path: Path, **overrides) -> Path:
    path = tmp_path / "models-test.json"
    data = {
        "version": 2,
        "models": {
            "m1": {"name": "M1", "sources": {"a": "m1", "b": "vendor/m1"}},
        },
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_committed_models_file_passes_schema():
    mapping = load_models(DATA / "models.json")
    assert mapping["deepseek-v4-pro"]["sources"]["openrouter"] == ["deepseek/deepseek-v4-pro"]
    assert mapping["deepseek-v4-pro"]["name"] == "DeepSeek V4 Pro"
    assert mapping["deepseek-v4-flash"]["sources"]["deepseek"] == [
        "deepseek-v4-flash",
        "deepseek-chat",
        "deepseek-reasoner",
    ]


def test_load_models_normalizes_source_spellings_to_lists(tmp_path):
    path = models_file(
        tmp_path,
        models={"m1": {"sources": {"a": "m1", "b": ["vendor/m1", "vendor/m1-alias"]}}},
    )
    mapping = load_models(path)
    assert mapping["m1"]["sources"] == {"a": ["m1"], "b": ["vendor/m1", "vendor/m1-alias"]}


def test_load_models_accepts_a_missing_file():
    assert load_models(Path("/tmp") / "no-such-models.json") == {}


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"version": 1}, "version"),
        ({"version": 3}, "version"),
        ({"version": True}, "version"),
        ({"models": []}, "'models'"),
        ({"models": {"": {"sources": {"a": "m1"}}}}, "canonical id"),
        ({"models": {"m1": {"bogus": 1}}}, "unknown key"),
        ({"models": {"m1": {"name": ""}}}, "name"),
        ({"models": {"m1": {"sources": {}}}}, "sources"),
        ({"models": {"m1": {"sources": {"a": ""}}}}, "sources"),
        ({"models": {"m1": {"sources": {"a": []}}}}, "sources"),
        ({"models": {"m1": {"sources": {"a": [""]}}}}, "sources"),
        ({"models": {"m1": {"sources": {"a": [1]}}}}, "sources"),
        ({"models": {"m1": {"sources": {"a": {"b": 1}}}}}, "sources"),
    ],
)
def test_bad_models_file_rejected(tmp_path, overrides, match):
    with pytest.raises(MappingError, match=match):
        load_models(models_file(tmp_path, **overrides))


def test_canonical_spelling_strips_vendor_prefixes():
    assert canonical_spelling("deepseek/deepseek-v4-pro") == "deepseek-v4-pro"
    assert canonical_spelling("deepseek-v4-pro") == "deepseek-v4-pro"


def test_hint_candidates_propose_cross_source_matches():
    rows = [
        {"source": "openrouter", "model_id": "deepseek/deepseek-v4-pro", "observed_at": "t"},
        {"source": "deepseek", "model_id": "deepseek-v4-pro", "observed_at": "t"},
    ]
    # a fresh first-party landing beside the stored openrouter twin hints
    hints = hint_candidates(rows, {}, {("deepseek", "deepseek-v4-pro")})
    assert hints == [("deepseek", "deepseek-v4-pro", "deepseek-v4-pro")]


def test_hint_candidates_skip_mapped_pairs():
    rows = [
        {"source": "openrouter", "model_id": "deepseek/deepseek-v4-pro", "observed_at": "t"},
        {"source": "deepseek", "model_id": "deepseek-v4-pro", "observed_at": "t"},
    ]
    mapping = {
        "deepseek-v4-pro": {
            "sources": {"deepseek": "deepseek-v4-pro", "openrouter": "deepseek/deepseek-v4-pro"}
        }
    }
    assert hint_candidates(rows, mapping, {("deepseek", "deepseek-v4-pro")}) == []


def test_hint_candidates_skip_pairs_mapped_through_a_list():
    rows = [
        {"source": "deepseek", "model_id": "deepseek-chat", "observed_at": "t"},
        {"source": "openrouter", "model_id": "deepseek-chat", "observed_at": "t"},
    ]
    mapping = {
        "deepseek-v4-flash": {"sources": {"deepseek": ["deepseek-v4-flash", "deepseek-chat"]}}
    }
    assert hint_candidates(rows, mapping, {("deepseek", "deepseek-chat")}) == []


def test_hint_candidates_ignore_same_source_and_unrelated_spellings():
    rows = [
        {"source": "a", "model_id": "m1", "observed_at": "t"},
        {"source": "b", "model_id": "other", "observed_at": "t"},
    ]
    # same source only: no cross-source twin
    assert hint_candidates(rows, {}, {("a", "m1")}) == []
    # no spelling match anywhere
    assert hint_candidates(rows, {}, {("a", "m9")}) == []

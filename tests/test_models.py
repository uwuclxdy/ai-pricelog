from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_pricelog.models import MappingError, canonical_spelling, hint_candidates, load_models

DATA = Path(__file__).resolve().parents[1] / "data"


def models_file(tmp_path: Path, **overrides) -> Path:
    path = tmp_path / "models-test.json"
    data = {
        "version": 3,
        "models": {
            "m1": {"name": "M1", "sources": {"a": "m1", "b": "vendor/m1"}},
        },
        "aliases": {},
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def alias_record(start="2024-12-26", end="2025-03-24", **overrides) -> dict:
    record = {
        "from": start,
        "to": end,
        "canonical": "m1",
        "citation": "https://example.com/#date-2024-12-26",
    }
    record.update(overrides)
    return record


def test_committed_models_file_passes_schema():
    mapping = load_models(DATA / "models.json")
    assert mapping["deepseek-v4-pro"]["sources"]["openrouter"] == ["deepseek/deepseek-v4-pro"]
    assert mapping["deepseek-v4-pro"]["name"] == "DeepSeek V4 Pro"
    assert mapping["deepseek-v4-flash"]["sources"]["deepseek"] == ["deepseek-v4-flash"]


def test_committed_deepseek_alias_chains_are_dated_and_contiguous():
    data = json.loads((DATA / "models.json").read_text(encoding="utf-8"))
    chat = data["aliases"]["deepseek-chat"]
    reasoner = data["aliases"]["deepseek-reasoner"]
    assert [record["canonical"] for record in chat] == [
        "deepseek-v3",
        "deepseek-v3-0324",
        "deepseek-v3.1",
        "deepseek-v3.1-terminus",
        "deepseek-v3.2-exp",
        "deepseek-v3.2",
        "deepseek-v4-flash",
    ]
    assert [record["canonical"] for record in reasoner] == [
        "deepseek-r1",
        "deepseek-r1-0528",
        "deepseek-v3.1",
        "deepseek-v3.1-terminus",
        "deepseek-v3.2-exp",
        "deepseek-v3.2",
        "deepseek-v4-flash",
    ]
    assert chat[0]["from"] == "2024-12-26"
    assert reasoner[0]["from"] == "2025-01-20"
    for chain in (chat, reasoner):
        assert chain[-1]["to"] == "2026-07-24"
        assert all(a["to"] == b["from"] for a, b in zip(chain, chain[1:], strict=False))
        assert all(
            record["citation"].startswith("https://api-docs.deepseek.com/updates/")
            for record in chain
        )


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
        ({"version": 2}, "version"),
        ({"version": 4}, "version"),
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
        ({"aliases": "x"}, "'aliases'"),
        ({"aliases": {"": [alias_record()]}}, "alias id"),
        ({"aliases": {"a": []}}, "records"),
        ({"aliases": {"a": "x"}}, "records"),
        ({"aliases": {"a": [1]}}, "record must be an object"),
        ({"aliases": {"a": [{"bogus": 1}]}}, "unknown key"),
        ({"aliases": {"a": [alias_record(canonical="m9")]}}, "canonical"),
        (
            {"aliases": {"a": [{"from": "2024-12-26", "to": None, "citation": "https://e.com"}]}},
            "canonical",
        ),
        ({"aliases": {"a": [alias_record(citation="example.com")]}}, "citation"),
        ({"aliases": {"a": [{"from": "2024-12-26", "to": None, "canonical": "m1"}]}}, "citation"),
        (
            {"aliases": {"a": [{"to": None, "canonical": "m1", "citation": "https://e.com"}]}},
            "missing 'from'",
        ),
        (
            {
                "aliases": {
                    "a": [{"from": "2024-12-26", "canonical": "m1", "citation": "https://e.com"}]
                }
            },
            "missing 'to'",
        ),
        ({"aliases": {"a": [alias_record(start="2024")]}}, "'from'"),
        ({"aliases": {"a": [alias_record(start="2024-13-01")]}}, "'from'"),
        ({"aliases": {"a": [alias_record(start="20240101")]}}, "'from'"),
        ({"aliases": {"a": [alias_record(end="2024-02-30")]}}, "'to'"),
        (
            {
                "aliases": {
                    "a": [
                        {"from": None, "to": None, "canonical": "m1", "citation": "https://e.com"}
                    ]
                }
            },
            "carry a 'from' or 'to'",
        ),
        (
            {"aliases": {"a": [alias_record(start="2025-01-02", end="2025-01-01")]}},
            "before 'to'",
        ),
        (
            {"aliases": {"a": [alias_record(start="2025-01-01", end="2025-01-01")]}},
            "before 'to'",
        ),
    ],
)
def test_bad_models_file_rejected(tmp_path, overrides, match):
    with pytest.raises(MappingError, match=match):
        load_models(models_file(tmp_path, **overrides))


def test_load_models_accepts_dated_alias_records(tmp_path):
    path = models_file(
        tmp_path,
        aliases={
            "alias-open-start": [
                {
                    "from": None,
                    "to": "2025-01-01",
                    "canonical": "m1",
                    "citation": "https://example.com/one",
                }
            ],
            "alias-open-end": [
                {
                    "from": "2025-01-01",
                    "to": None,
                    "canonical": "m1",
                    "citation": "http://example.com/two",
                }
            ],
            "alias-dated": [alias_record()],
        },
    )
    mapping = load_models(path)
    assert mapping["m1"]["sources"] == {"a": ["m1"], "b": ["vendor/m1"]}


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

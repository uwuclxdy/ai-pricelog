from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_pricelog import models
from ai_pricelog.models import (
    MappingError,
    derive_vendor,
    is_resold,
    load_aliases,
    load_models,
    seed_entries,
)

DATA = Path(__file__).resolve().parents[1] / "data"


def models_file(tmp_path: Path, **overrides) -> Path:
    path = tmp_path / "models-test.json"
    data = {
        "version": 4,
        "models": {
            "m1": {"vendor": "v1", "curated": True, "sources": {"a": "m1", "b": "vendor/m1"}},
        },
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def aliases_file(tmp_path: Path, aliases: dict) -> Path:
    path = tmp_path / "aliases-test.json"
    path.write_text(json.dumps({"version": 4, "aliases": aliases}), encoding="utf-8")
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


def test_committed_catalog_passes_schema():
    mapping = load_models(DATA / "catalog" / "models.json")
    assert mapping["deepseek-v4-pro"]["sources"]["openrouter"] == ["deepseek/deepseek-v4-pro"]
    assert mapping["deepseek-v4-pro"]["name"] == "DeepSeek V4 Pro"
    assert mapping["deepseek-v4-pro"]["vendor"] == "deepseek"
    assert mapping["deepseek-v4-pro"]["curated"] is True


def test_committed_aliases_pass_schema():
    mapping = load_models(DATA / "catalog" / "models.json")
    aliases = load_aliases(DATA / "catalog" / "aliases.json", models=mapping)
    assert aliases["deepseek-chat"][0]["canonical"] == "deepseek-v3"
    assert aliases["deepseek-reasoner"][-1]["to"] == "2026-07-24"


def test_committed_alias_canonicals_name_models():
    mapping = load_models(DATA / "catalog" / "models.json")
    aliases = load_aliases(DATA / "catalog" / "aliases.json", models=mapping)
    for chain in aliases.values():
        for record in chain:
            assert record["canonical"] in mapping


def test_committed_deepseek_alias_chains_are_dated_and_contiguous():
    data = json.loads((DATA / "catalog" / "aliases.json").read_text(encoding="utf-8"))
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


def test_committed_vendor_alias_dates():
    data = json.loads((DATA / "catalog" / "aliases.json").read_text(encoding="utf-8"))
    assert data["aliases"]["gemini-2.5-pro-preview-03-25"][0]["from"] == "2025-06-26"
    assert data["aliases"]["gemini-2.5-pro-preview-05-06"][0]["from"] == "2025-06-26"
    pro = [(r["from"], r["to"], r["canonical"]) for r in data["aliases"]["gemini-pro-latest"]]
    assert pro == [
        ("2025-06-17", "2026-01-21", "gemini-2.5-pro"),
        ("2026-01-21", "2026-03-09", "gemini-3-pro-preview"),
        ("2026-03-09", None, "gemini-3.1-pro-preview"),
    ]
    flash = [(r["from"], r["to"], r["canonical"]) for r in data["aliases"]["gemini-flash-latest"]]
    assert flash == [
        ("2025-06-17", "2026-01-21", "gemini-2.5-flash"),
        ("2026-01-21", "2026-05-19", "gemini-3-flash-preview"),
        ("2026-05-19", None, "gemini-3.5-flash"),
    ]
    assert [
        (r["from"], r["to"], r["canonical"]) for r in data["aliases"]["mistral-large-latest"]
    ] == [
        ("2024-07-24", "2024-11-18", "mistral-large-2407"),
        ("2025-12-02", None, "mistral-large-2512"),
    ]


def test_committed_alias_records_are_ordered_and_non_overlapping():
    data = json.loads((DATA / "catalog" / "aliases.json").read_text(encoding="utf-8"))
    for alias, chain in data["aliases"].items():
        assert chain, alias
        for a, b in zip(chain, chain[1:], strict=False):
            assert a["to"] is not None, f"{alias}: an open-ended record must end the chain"
            assert a["to"] <= b["from"], f"{alias}: {a} overlaps or reorders against {b}"


def test_load_models_normalizes_source_spellings_to_lists(tmp_path):
    path = models_file(
        tmp_path,
        models={
            "m1": {
                "vendor": "v1",
                "curated": True,
                "sources": {"a": "m1", "b": ["vendor/m1", "vendor/m1-alias"]},
            }
        },
    )
    mapping = load_models(path)
    assert mapping["m1"]["sources"] == {"a": ["m1"], "b": ["vendor/m1", "vendor/m1-alias"]}


def test_load_models_accepts_a_missing_file():
    assert load_models(Path("/tmp") / "no-such-models.json") == {}


def test_load_models_required_missing_raises():
    with pytest.raises(MappingError, match="missing"):
        load_models(Path("/tmp") / "no-such-models.json", allow_missing=False)


def test_load_models_accepts_a_null_vendor(tmp_path):
    path = models_file(
        tmp_path,
        models={"m1": {"vendor": None, "curated": False, "sources": {"a": "m1"}}},
    )
    assert load_models(path)["m1"]["vendor"] is None


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"version": 3}, "version"),
        ({"version": 5}, "version"),
        ({"version": True}, "version"),
        ({"models": []}, "'models'"),
        (
            {"models": {"": {"vendor": "v", "curated": True, "sources": {"a": "m1"}}}},
            "canonical id",
        ),
        ({"models": {"m1": {"bogus": 1}}}, "unknown key"),
        ({"models": {"m1": {"vendor": "v", "curated": True, "name": ""}}}, "name"),
        ({"models": {"m1": {"curated": True, "sources": {"a": "m1"}}}}, "missing 'vendor'"),
        ({"models": {"m1": {"vendor": "", "curated": True, "sources": {"a": "m1"}}}}, "vendor"),
        ({"models": {"m1": {"vendor": 1, "curated": True, "sources": {"a": "m1"}}}}, "vendor"),
        ({"models": {"m1": {"vendor": "v", "sources": {"a": "m1"}}}}, "curated"),
        ({"models": {"m1": {"vendor": "v", "curated": "yes", "sources": {"a": "m1"}}}}, "curated"),
        ({"models": {"m1": {"vendor": "v", "curated": True, "sources": {}}}}, "sources"),
        ({"models": {"m1": {"vendor": "v", "curated": True, "sources": {"a": ""}}}}, "sources"),
        ({"models": {"m1": {"vendor": "v", "curated": True, "sources": {"a": []}}}}, "sources"),
        ({"models": {"m1": {"vendor": "v", "curated": True, "sources": {"a": [""]}}}}, "sources"),
        ({"models": {"m1": {"vendor": "v", "curated": True, "sources": {"a": [1]}}}}, "sources"),
        (
            {"models": {"m1": {"vendor": "v", "curated": True, "sources": {"a": {"b": 1}}}}},
            "sources",
        ),
    ],
)
def test_bad_models_file_rejected(tmp_path, overrides, match):
    with pytest.raises(MappingError, match=match):
        load_models(models_file(tmp_path, **overrides))


def test_load_aliases_accepts_dated_records(tmp_path):
    path = aliases_file(
        tmp_path,
        {
            "alias-open-start": [
                {
                    "from": None,
                    "to": "2025-01-01",
                    "canonical": "m1",
                    "citation": "https://example.com/one",
                }
            ],
            "alias-open-both": [
                {
                    "from": None,
                    "to": None,
                    "canonical": "m1",
                    "citation": "http://example.com/two",
                }
            ],
            "alias-dated": [alias_record()],
        },
    )
    assert set(load_aliases(path, models=None)) == {
        "alias-open-start",
        "alias-open-both",
        "alias-dated",
    }


def test_load_aliases_checks_canonical_against_models(tmp_path):
    path = aliases_file(tmp_path, {"a": [alias_record(canonical="m9")]})
    assert load_aliases(path, models=None) == {"a": [alias_record(canonical="m9")]}
    with pytest.raises(MappingError, match="canonical"):
        load_aliases(path, models={"m1": {}})


def test_load_aliases_accepts_a_missing_file():
    assert load_aliases(Path("/tmp") / "no-such-aliases.json", models=None) == {}


@pytest.mark.parametrize(
    ("aliases", "match"),
    [
        ({"": [alias_record()]}, "alias id"),
        ({"a": []}, "records"),
        ({"a": "x"}, "records"),
        ({"a": [1]}, "record must be an object"),
        ({"a": [{"bogus": 1}]}, "unknown key"),
        ({"a": [{"from": "2024-12-26", "to": None, "citation": "https://e.com"}]}, "canonical"),
        ({"a": [alias_record(citation="example.com")]}, "citation"),
        ({"a": [{"from": "2024-12-26", "to": None, "canonical": "m1"}]}, "citation"),
        (
            {"a": [{"to": None, "canonical": "m1", "citation": "https://e.com"}]},
            "missing 'from'",
        ),
        (
            {"a": [{"from": "2024-12-26", "canonical": "m1", "citation": "https://e.com"}]},
            "missing 'to'",
        ),
        ({"a": [alias_record(start="2024")]}, "'from'"),
        ({"a": [alias_record(start="2024-13-01")]}, "'from'"),
        ({"a": [alias_record(start="20240101")]}, "'from'"),
        ({"a": [alias_record(end="2024-02-30")]}, "'to'"),
        ({"a": [alias_record(start="2025-01-02", end="2025-01-01")]}, "before 'to'"),
        ({"a": [alias_record(start="2025-01-01", end="2025-01-01")]}, "before 'to'"),
    ],
)
def test_bad_aliases_file_rejected(tmp_path, aliases, match):
    with pytest.raises(MappingError, match=match):
        load_aliases(aliases_file(tmp_path, aliases), models=None)


@pytest.mark.parametrize(
    ("model_id", "provider_vendor", "provider_kind", "expected"),
    [
        ("@cf/deepseek-ai/deepseek-v4-flash-0731", None, "reseller", "deepseek-ai"),
        ("@cf/DeepSeek-AI/deepseek-v4-flash-0731", None, "reseller", "deepseek-ai"),
        ("anthropic/claude-fable-5", None, "reseller", "anthropic"),
        ("Sao10K/L3-8B-Stheno-v3.2", None, "reseller", "sao10k"),
        ("LLaMa-3-70b", None, "reseller", "meta"),
        ("claude-fable-5", "anthropic", "first_party", "anthropic"),
        ("claude-fable-5", None, "reseller", "anthropic"),
        ("unlisted-id", "ANTHROPIC", "first_party", "anthropic"),
        ("claude-fable-5", "anthropic", None, "anthropic"),
        ("a/b/c", None, "reseller", None),
        ("", None, "reseller", None),
    ],
)
def test_derive_vendor(model_id, provider_vendor, provider_kind, expected):
    assert derive_vendor(model_id, provider_vendor, provider_kind) == expected


def test_derive_vendor_family_token_beats_first_party_guess():
    # a mixed first-party source reselling another maker's family
    assert derive_vendor("llama-3-3-70b-instruct", "ibm", "first_party") == "meta"
    assert derive_vendor("zai-glm-5-2", "mistral", "first_party") == "zai"


def test_seed_entries_one_per_uncovered_key():
    mapping = {
        "m1": {"vendor": "v", "curated": True, "sources": {"a": ["m1"]}},
    }
    seeded = seed_entries(
        [("a", "m1"), ("a", "new"), ("b", "vendor/new")],
        mapping,
        {"a": ("va", "first_party"), "b": (None, "reseller")},
    )
    assert set(seeded) == {"a/new", "b/vendor/new"}
    assert seeded["a/new"] == {"vendor": "va", "curated": False, "sources": {"a": ["new"]}}
    assert seeded["b/vendor/new"] == {
        "vendor": "vendor",
        "curated": False,
        "sources": {"b": ["vendor/new"]},
    }


def test_seed_entries_canonical_ids_never_collide():
    seeded = seed_entries(
        [("openrouter", "anthropic/claude-fable-5"), ("deepinfra", "claude-fable-5")],
        {},
        {"openrouter": (None, "reseller"), "deepinfra": (None, "reseller")},
    )
    assert set(seeded) == {"openrouter/anthropic/claude-fable-5", "deepinfra/claude-fable-5"}


def test_seed_entries_refuse_a_canonical_id_a_curated_entry_holds():
    mapping = {
        "google/gemini-3-pro": {
            "vendor": "google",
            "curated": True,
            "name": "Gemini 3 Pro",
            "sources": {"openrouter": ["google/gemini-3-pro"]},
        }
    }
    with pytest.raises(MappingError, match="collides"):
        seed_entries(
            [("google", "gemini-3-pro")],
            mapping,
            {"google": ("google", "first_party")},
        )


def test_is_resold_compares_model_and_provider_vendors():
    entry = {"vendor": "meta", "curated": False, "sources": {"watsonx": ["llama-3-3-70b"]}}
    assert is_resold(entry, {"vendor": "ibm", "kind": "first_party"}) is True
    assert is_resold(entry, {"vendor": "meta", "kind": "first_party"}) is False
    assert is_resold(entry, {"kind": "reseller"}) is True


def test_save_models_round_trips(tmp_path):
    mapping = {
        "m1": {"vendor": "v", "curated": True, "sources": {"a": ["m1"]}},
        "b/new": {"vendor": None, "curated": False, "sources": {"b": ["new"]}},
    }
    path = tmp_path / "catalog" / "models.json"
    models.save_models(mapping, path)
    assert load_models(path) == mapping
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 4

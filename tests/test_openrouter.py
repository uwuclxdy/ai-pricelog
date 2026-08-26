from pathlib import Path

import pytest

from ai_pricelog import openrouter
from ai_pricelog.openrouter import OBSERVED_KEYS, OpenrouterModel, build_row, fetch_models, find

FIXTURE = Path(__file__).parent / "fixtures" / "openrouter_models.json"


@pytest.fixture()
def fake_fetch(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def fake(url: str) -> str:
        calls.append(url)
        return FIXTURE.read_text()

    monkeypatch.setattr(openrouter, "fetch_text", fake)
    return calls


def test_fetch_models_parses_fixture(fake_fetch: list[str]) -> None:
    models = fetch_models()
    by_id = {m.id: m for m in models}
    glm53 = by_id["z-ai/glm-5.3"]
    assert glm53 == OpenrouterModel("z-ai/glm-5.3", "GLM 5.3", 1.4, 4.4, 0.26)
    v4pro = by_id["deepseek/deepseek-v4-pro"]
    assert v4pro.input_mtok == 1.44
    assert v4pro.cache_read_mtok == 0.1215
    assert v4pro.output_mtok == 2.88
    assert by_id["minimax/minimax-m3"].cache_read_mtok == 0.06
    # extra pricing keys (overrides, web_search) are ignored
    assert by_id["x-ai/grok-4.5"].input_mtok == 2.0


def test_fetch_models_skips_alias_entries(fake_fetch: list[str]) -> None:
    ids = [m.id for m in fetch_models()]
    assert "~z-ai/glm-latest" not in ids
    assert len(ids) == 14


def test_fetch_models_free_model_and_missing_cache_read(fake_fetch: list[str]) -> None:
    by_id = {m.id: m for m in fetch_models()}
    free = by_id["dots-studio/dots-3-note-preview:free"]
    # free models ship all-zero pricing strings; the fetch layer parses
    # zero as None
    assert free.input_mtok is None
    assert free.output_mtok is None
    assert free.cache_read_mtok is None
    seed = by_id["bytedance-seed/seed-2-1-turbo"]
    assert seed.input_mtok == 0.5
    assert seed.output_mtok == 2.5
    assert seed.cache_read_mtok is None


def test_fetch_models_empty_pricing_mapping_is_all_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(url: str) -> str:
        return '{"data": [{"id": "x/y", "name": "X", "pricing": {}}]}'

    monkeypatch.setattr(openrouter, "fetch_text", fake)
    assert fetch_models() == [OpenrouterModel("x/y", "X", None, None, None)]


def test_fetch_models_uses_default_url_and_passes_custom_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def fake(url: str) -> str:
        seen.append(url)
        return FIXTURE.read_text()

    monkeypatch.setattr(openrouter, "fetch_text", fake)
    fetch_models()
    assert seen == ["https://openrouter.ai/api/v1/models"]
    fetch_models("https://example.test/models")
    assert seen[-1] == "https://example.test/models"


def test_find_lowercases_model_id(fake_fetch: list[str]) -> None:
    models = fetch_models()
    minimax = find(models, "minimax", "MiniMax-M3")
    assert minimax is not None
    assert minimax.id == "minimax/minimax-m3"
    deepseek = find(models, "deepseek", "DeepSeek-V4-Pro")
    assert deepseek is not None
    assert deepseek.id == "deepseek/deepseek-v4-pro"


def test_find_missing_model_returns_none(fake_fetch: list[str]) -> None:
    models = fetch_models()
    assert find(models, "z-ai", "GLM-5.4") is None
    assert find(models, "minimax", "MiniMax-M3 ") is None


def test_fetch_models_rounds_to_six_decimals(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(url: str) -> str:
        return '{"data": [{"id": "a/b", "name": "A", "pricing": {"prompt": "0.0000001234567"}}]}'

    monkeypatch.setattr(openrouter, "fetch_text", fake)
    (model,) = fetch_models()
    assert model.input_mtok == 0.123457


def test_fetch_models_root_shape_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openrouter, "fetch_text", lambda url: "[1, 2]")
    with pytest.raises(ValueError, match="data"):
        fetch_models()
    monkeypatch.setattr(
        openrouter,
        "fetch_text",
        lambda url: '{"data": [{"id": "a/b", "name": "A", "pricing": {"prompt": 5}}]}',
    )
    with pytest.raises(ValueError, match="per-token strings"):
        fetch_models()


def test_openrouter_fixture_is_valid_json() -> None:
    import json

    data = json.loads(FIXTURE.read_text())
    assert isinstance(data, dict)
    assert isinstance(data["data"], list)


def test_fetch_models_strips_vendor_name_prefix(fake_fetch: list[str]) -> None:
    by_id = {m.id: m for m in fetch_models()}
    assert by_id["x-ai/grok-4.5"].name == "Grok 4.5"
    assert by_id["deepseek/deepseek-v4-pro"].name == "DeepSeek V4 Pro 0423"
    assert by_id["dots-studio/dots-3-note-preview:free"].name == "Dots3-Note Preview (free)"


def test_build_row_skips_alias_entries():
    model = OpenrouterModel("~x/y", "X", 1.0, 2.0, None, alias_target={"slug": "x/y"})
    assert build_row(model, "2026-08-26T00:00:00Z") is None


def test_build_row_skips_dated_canonical_snapshots():
    snapshot = OpenrouterModel("a/b", "A", 1.0, 2.0, None, canonical_slug="a/b-20260101")
    assert build_row(snapshot, "t") is None
    canonical = OpenrouterModel("a/b-20260101", "A", 1.0, 2.0, None, canonical_slug="a/b-20260101")
    assert build_row(canonical, "t") is not None


def test_build_row_maps_pricing_keys_and_rounds():
    model = OpenrouterModel(
        "a/b",
        "A",
        None,
        None,
        None,
        context_length=131072,
        pricing={
            "prompt": "0.000000435",
            "completion": "0.0000012",
            "input_cache_read": "0.0000001",
        },
    )
    row = build_row(model, "2026-08-26T00:00:00Z")
    assert row is not None
    assert list(row) == [
        "source",
        "model_id",
        "observed_at",
        "name",
        "input_mtok",
        "output_mtok",
        "cache_read_mtok",
        "max_tokens",
    ]
    assert row["source"] == "openrouter"
    assert row["model_id"] == "a/b"
    assert row["name"] == "A"
    assert row["input_mtok"] == 0.435
    assert row["output_mtok"] == 1.2
    assert row["cache_read_mtok"] == 0.1
    assert row["max_tokens"] == 131072


def test_build_row_omits_missing_prompt_and_empty_name():
    model = OpenrouterModel("a/b", "", None, None, None, pricing={"completion": "0.0000012"})
    row = build_row(model, "t")
    assert row is not None
    assert "name" not in row
    assert "input_mtok" not in row
    assert row["output_mtok"] == 1.2


def test_build_row_passes_unconsumed_pricing_keys_through_extra():
    model = OpenrouterModel(
        "x/y",
        "X",
        None,
        None,
        None,
        pricing={
            "prompt": "0.000001",
            "completion": "0.000002",
            "web_search": "0.005",
            "overrides": [{"min_prompt_tokens": 200000, "prompt": "0.000004"}],
        },
    )
    row = build_row(model, "t")
    assert row is not None
    assert row["extra"] == {
        "web_search": "0.005",
        "overrides": [{"min_prompt_tokens": 200000, "prompt": "0.000004"}],
    }
    assert list(row)[-1] == "extra"


def test_build_row_omits_extra_when_all_pricing_keys_consumed():
    model = OpenrouterModel(
        "x/y", "X", None, None, None, pricing={"prompt": "0.000001", "completion": "0.000002"}
    )
    row = build_row(model, "t")
    assert row is not None
    assert "extra" not in row


def test_build_row_keeps_zero_pricing_strings():
    model = OpenrouterModel(
        "x/y", "X", None, None, None, pricing={"prompt": "0", "completion": "0"}
    )
    row = build_row(model, "t")
    assert row is not None
    assert row["input_mtok"] == 0.0
    assert row["output_mtok"] == 0.0


def test_observed_keys_lists_the_consumed_pricing_keys():
    assert frozenset({"prompt", "completion", "input_cache_read"}) == OBSERVED_KEYS


def test_build_row_keeps_only_fixture_models_without_dated_canonical(fake_fetch: list[str]) -> None:
    models = fetch_models()
    rows = []
    for model in models:
        row = build_row(model, "2026-08-26T00:00:00Z")
        if row is not None:
            rows.append(row)
    assert [row["model_id"] for row in rows] == [
        "minimax/minimax-m1",
        "perplexity/sonar-pro",
        "mistralai/codestral-2508",
    ]
    sonar = rows[1]
    assert sonar["name"] == "Sonar Pro"
    assert sonar["extra"] == {"web_search": "0.005"}
    assert all("max_tokens" not in row for row in rows)

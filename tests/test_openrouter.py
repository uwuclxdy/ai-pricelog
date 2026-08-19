from pathlib import Path

import pytest

from autopr_genai_prices import openrouter
from autopr_genai_prices.openrouter import OpenrouterModel, fetch_models, find

FIXTURE = Path(__file__).parent / "fixtures" / "genai_prices" / "openrouter_models.json"


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
    assert glm53 == OpenrouterModel("z-ai/glm-5.3", "Z.ai: GLM 5.3", 1.4, 4.4, 0.26)
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
    # free models ship all-zero pricing strings; zero parses as None so the
    # yml entry renders as `prices: {}` (the target's schema forbids zero)
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

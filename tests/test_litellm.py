from pathlib import Path

import pytest

from litellm_autopr import litellm
from litellm_autopr.pricing import Pricing
from litellm_autopr.web import FetchError

FIXTURE = Path(__file__).parent / "fixtures" / "litellm_live.json"


def test_build_entry_exact_shape():
    key, entry = litellm.build_entry(
        "deepseek", "deepseek", "deepseek-chat", Pricing(2.7e-07, 1.1e-06, "chat", 65536)
    )
    assert key == "deepseek/deepseek-chat"
    assert list(entry) == [
        "input_cost_per_token",
        "output_cost_per_token",
        "litellm_provider",
        "mode",
        "max_tokens",
    ]
    assert entry == {
        "input_cost_per_token": 2.7e-07,
        "output_cost_per_token": 1.1e-06,
        "litellm_provider": "deepseek",
        "mode": "chat",
        "max_tokens": 65536,
    }


def test_build_entry_omits_unknown_max_tokens():
    key, entry = litellm.build_entry("zai", "zai", "glm-4", Pricing(1.0e-06, 2.0e-06, "chat", 0))
    assert key == "zai/glm-4"
    assert "max_tokens" not in entry
    assert entry["mode"] == "chat"


def test_load_parses_fixture():
    loaded = litellm.load(FIXTURE)
    assert loaded.providers == frozenset({"deepseek", "zai"})
    assert loaded.modes == frozenset({"chat"})
    assert loaded.entries["deepseek/deepseek-chat"]["litellm_provider"] == "deepseek"
    assert "max_tokens" not in loaded.entries["zai/glm-4"]


def test_load_bad_json(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text("{nope")
    with pytest.raises(ValueError, match="prices.json"):
        litellm.load(path)


def test_load_non_dict_root(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text("[1, 2]")
    with pytest.raises(ValueError, match="root"):
        litellm.load(path)


def test_load_non_dict_value(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text('{"deepseek/deepseek-chat": 1}')
    with pytest.raises(ValueError, match="deepseek/deepseek-chat"):
        litellm.load(path)


def test_fetch_live_env_url_override(monkeypatch):
    monkeypatch.setenv("LITELLM_FILE_URL", "https://override.example/prices.json")
    seen: list[str] = []

    def fake_fetch(url: str) -> str:
        seen.append(url)
        return '{"deepseek/deepseek-chat": {"litellm_provider": "deepseek", "mode": "chat"}}'

    monkeypatch.setattr(litellm, "fetch_text", fake_fetch)
    live = litellm.fetch_live()
    assert seen == ["https://override.example/prices.json"]
    assert live.providers == frozenset({"deepseek"})
    assert live.modes == frozenset({"chat"})


def test_fetch_live_default_url(monkeypatch):
    monkeypatch.delenv("LITELLM_FILE_URL", raising=False)
    seen: list[str] = []

    def fake_fetch(url: str) -> str:
        seen.append(url)
        return "{}"

    monkeypatch.setattr(litellm, "fetch_text", fake_fetch)
    litellm.fetch_live()
    assert seen == [litellm.LITELLM_FILE_URL]


def test_fetch_live_arg_beats_env(monkeypatch):
    monkeypatch.setenv("LITELLM_FILE_URL", "https://env.example/prices.json")
    seen: list[str] = []

    def fake_fetch(url: str) -> str:
        seen.append(url)
        return "{}"

    monkeypatch.setattr(litellm, "fetch_text", fake_fetch)
    litellm.fetch_live("https://arg.example/prices.json")
    assert seen == ["https://arg.example/prices.json"]


def test_fetch_live_bad_json_raises_fetch_error(monkeypatch):
    monkeypatch.setattr(litellm, "fetch_text", lambda url: "not json")
    with pytest.raises(FetchError, match="arg.example"):
        litellm.fetch_live("https://arg.example/prices.json")

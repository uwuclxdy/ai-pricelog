import json

import pytest

from autopr_genai_prices import litellm, validate
from autopr_genai_prices.config import Config, ProviderCfg
from autopr_genai_prices.validate import ValidationError, validate_entry


def make_live(providers=("deepseek",), modes=("chat", "completion")) -> litellm.LitellmFile:
    return litellm.LitellmFile(entries={}, providers=frozenset(providers), modes=frozenset(modes))


def make_cfg() -> Config:
    return Config(
        repo="https://github.com/octo/litellm",
        providers=(
            ProviderCfg(
                key="deepseek",
                provider="deepseek",
                namespace="deepseek",
                detector="d",
                detector_url="https://example.com/d",
                scraper="s",
                scraper_url="https://example.com/s",
            ),
        ),
        cap=3,
    )


def good_entry() -> dict:
    return {
        "input_cost_per_token": 2.7e-07,
        "output_cost_per_token": 1.1e-06,
        "litellm_provider": "deepseek",
        "mode": "chat",
        "max_tokens": 65536,
    }


def test_valid_entry_passes():
    validate_entry("deepseek/deepseek-chat", good_entry(), make_live(), make_cfg())


def test_max_tokens_absent_is_valid():
    entry = good_entry()
    del entry["max_tokens"]
    validate_entry("deepseek/deepseek-chat", entry, make_live(), make_cfg())


@pytest.mark.parametrize("key", ["unknown/x", "deepseek/", "deepseek", "deepseek-x/x"])
def test_key_outside_configured_namespaces(key):
    with pytest.raises(ValidationError, match="namespace"):
        validate_entry(key, good_entry(), make_live(), make_cfg())


def test_provider_not_in_live_vocabulary():
    entry = good_entry()
    live = make_live(providers=("zai",))
    with pytest.raises(ValidationError, match="vocabulary"):
        validate_entry("deepseek/deepseek-chat", entry, live, make_cfg())


def test_provider_mismatches_configured_value():
    entry = good_entry()
    entry["litellm_provider"] = "zai"
    live = make_live(providers=("deepseek", "zai"))
    with pytest.raises(ValidationError, match="litellm_provider"):
        validate_entry("deepseek/deepseek-chat", entry, live, make_cfg())


def test_mode_not_in_live_modes():
    entry = good_entry()
    entry["mode"] = "embedding"
    with pytest.raises(ValidationError, match="mode"):
        validate_entry("deepseek/deepseek-chat", entry, make_live(), make_cfg())


@pytest.mark.parametrize("field", ["input_cost_per_token", "output_cost_per_token"])
@pytest.mark.parametrize("bad", [0, 0.0, -1.0, float("inf"), True, 5, None])
def test_bad_cost_rejected(field, bad):
    entry = good_entry()
    entry[field] = bad
    with pytest.raises(ValidationError, match=field):
        validate_entry("deepseek/deepseek-chat", entry, make_live(), make_cfg())


@pytest.mark.parametrize("bad", [True, 1.5, 0, -1])
def test_bad_max_tokens_rejected(bad):
    entry = good_entry()
    entry["max_tokens"] = bad
    with pytest.raises(ValidationError, match="max_tokens"):
        validate_entry("deepseek/deepseek-chat", entry, make_live(), make_cfg())


def test_validate_repo_file_ok(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text(json.dumps({"a": {}}) + "\n")
    assert validate.validate_repo_file(path) == {"a": {}}


def test_validate_repo_file_bad_json(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text("{nope")
    with pytest.raises(ValidationError, match="prices.json"):
        validate.validate_repo_file(path)


def test_validate_repo_file_non_dict_root(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text("[]")
    with pytest.raises(ValidationError, match="root"):
        validate.validate_repo_file(path)

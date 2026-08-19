import types

import pytest

from autopr_genai_prices import config
from conftest import register_fake_module

HAPPY_TOML = """
[settings]
cap = 5

[deepseek]
yml = "deepseek.yml"
or_prefix = "deepseek"
detector = "deepseek_page"
detector_url = "https://api-docs.deepseek.com/pricing"
scraper = "deepseek_page"
scraper_url = "https://api-docs.deepseek.com/pricing"
"""


def test_load_happy_path(tmp_path, monkeypatch):
    path = tmp_path / "providers.toml"
    path.write_text(HAPPY_TOML)
    monkeypatch.delenv("REPO", raising=False)
    cfg = config.load(repo="https://github.com/octo/genai-prices/", providers_path=path)
    assert cfg.repo == "https://github.com/octo/genai-prices"
    assert cfg.cap == 5
    assert len(cfg.providers) == 1
    pcfg = cfg.providers[0]
    assert pcfg.key == "deepseek"
    assert pcfg.yml == "deepseek.yml"
    assert pcfg.or_prefix == "deepseek"
    assert pcfg.detector == "deepseek_page"
    assert pcfg.detector_url == "https://api-docs.deepseek.com/pricing"
    assert pcfg.scraper == "deepseek_page"
    assert pcfg.scraper_url == "https://api-docs.deepseek.com/pricing"


def test_load_default_cap(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text(HAPPY_TOML.replace("[settings]\ncap = 5\n", ""))
    cfg = config.load(repo="https://github.com/octo/genai-prices", providers_path=path)
    assert cfg.cap == 3


def test_load_missing_repo(monkeypatch):
    monkeypatch.delenv("REPO", raising=False)
    with pytest.raises(config.ConfigError, match="REPO env var"):
        config.load(providers=())


def test_load_bad_url_prefix():
    with pytest.raises(config.ConfigError, match="github"):
        config.load(repo="https://gitlab.com/octo/genai-prices", providers=(), cap=1)


def test_load_unknown_provider_key(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text('[deepseek]\nyml = "deepseek.yml"\nbogus = "x"\n')
    with pytest.raises(config.ConfigError, match="bogus"):
        config.load_providers(path)


def test_load_rejects_dead_litellm_keys(tmp_path):
    # provider/namespace/token_env died with the litellm pivot; a stale toml
    # must fail loudly instead of silently ignoring the keys
    path = tmp_path / "providers.toml"
    path.write_text(
        '[deepseek]\nyml = "deepseek.yml"\nprovider = "deepseek"\nnamespace = "deepseek"\n'
        'token_env = "DEEPSEEK_KEY"\n'
    )
    with pytest.raises(config.ConfigError, match="provider"):
        config.load_providers(path)


def test_load_unknown_settings_key(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text("[settings]\ncap = 3\nbogus = 1\n")
    with pytest.raises(config.ConfigError, match="bogus"):
        config.load_providers(path)


def test_load_missing_required_key(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text('[deepseek]\nyml = "deepseek.yml"\n')
    with pytest.raises(config.ConfigError, match="scraper"):
        config.load_providers(path)


def test_load_missing_or_prefix(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text(
        '[deepseek]\nyml = "deepseek.yml"\ndetector = "deepseek_page"\n'
        'detector_url = "https://x"\nscraper = "deepseek_page"\nscraper_url = "https://x"\n'
    )
    with pytest.raises(config.ConfigError, match="or_prefix"):
        config.load_providers(path)


def test_resolve_provider_module(monkeypatch):
    module = register_fake_module(monkeypatch, "detectors", "fake_det")
    module.detect = lambda cfg: ["x"]  # noqa: E731
    assert config.resolve_provider_module("detectors", "fake_det") is module


def test_resolve_provider_module_unknown_name(monkeypatch):
    register_fake_module(monkeypatch, "detectors", "fake_det")
    with pytest.raises(config.ConfigError, match="fake_missing"):
        config.resolve_provider_module("detectors", "fake_missing")


def test_resolve_provider_module_bad_kind():
    with pytest.raises(config.ConfigError, match="nope"):
        config.resolve_provider_module("nope", "whatever")


def test_fake_module_is_a_module(monkeypatch):
    module = register_fake_module(monkeypatch, "scrapers", "fake_scr")
    assert isinstance(module, types.ModuleType)


def test_load_bad_toml_names_the_file(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text("[deepseek\nprovider = \n")
    with pytest.raises(config.ConfigError, match="invalid toml"):
        config.load_providers(path)


@pytest.mark.parametrize("cap", [0, -3])
def test_load_rejects_cap_below_one(tmp_path, cap):
    path = tmp_path / "providers.toml"
    path.write_text(f"[settings]\ncap = {cap}\n")
    with pytest.raises(config.ConfigError, match="cap"):
        config.load_providers(path)


def test_load_rejects_injected_cap_below_one(monkeypatch):
    monkeypatch.delenv("REPO", raising=False)
    with pytest.raises(config.ConfigError, match="cap"):
        config.load(repo="https://github.com/octo/genai-prices", providers=(), cap=0)


def test_load_injected_providers_missing_file_defaults_cap(tmp_path, monkeypatch):
    monkeypatch.delenv("REPO", raising=False)
    cfg = config.load(
        repo="https://github.com/octo/genai-prices",
        providers=(),
        providers_path=tmp_path / "nope.toml",
    )
    assert cfg.cap == 3

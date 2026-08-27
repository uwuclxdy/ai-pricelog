from __future__ import annotations

import types

import pytest

from ai_pricelog import config
from conftest import register_fake_module

HAPPY_TOML = """
[settings]
cap = 5

[deepseek]
provider = "DeepSeek"
detector = "deepseek_page"
detector_url = "https://api-docs.deepseek.com/pricing"
scraper = "deepseek_page"
scraper_url = "https://api-docs.deepseek.com/pricing"
"""


def test_load_happy_path(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text(HAPPY_TOML)
    cfg = config.load(providers_path=path)
    assert cfg.cap == 5
    assert len(cfg.providers) == 1
    pcfg = cfg.providers[0]
    assert pcfg.key == "deepseek"
    assert pcfg.provider == "DeepSeek"
    assert pcfg.detector == "deepseek_page"
    assert pcfg.detector_url == "https://api-docs.deepseek.com/pricing"
    assert pcfg.scraper == "deepseek_page"
    assert pcfg.scraper_url == "https://api-docs.deepseek.com/pricing"


def test_config_holds_no_repo(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text(HAPPY_TOML)
    cfg = config.load(providers_path=path)
    assert set(vars(cfg)) == {"providers", "cap"}
    assert set(vars(cfg.providers[0])) == {
        "key",
        "provider",
        "detector",
        "detector_url",
        "scraper",
        "scraper_url",
        "announce_urls",
    }


def test_load_default_cap(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text(HAPPY_TOML.replace("[settings]\ncap = 5\n", ""))
    cfg = config.load(providers_path=path)
    assert cfg.cap == 3


def test_load_announce_urls(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text(
        '[deepseek]\nprovider = "DeepSeek"\ndetector = "deepseek_page"\n'
        'detector_url = "https://x"\nscraper = "deepseek_page"\nscraper_url = "https://x"\n'
        'announce_urls = ["https://a.example/updates", "https://a.example/rss"]\n'
    )
    cfg = config.load(providers_path=path)
    assert cfg.providers[0].announce_urls == (
        "https://a.example/updates",
        "https://a.example/rss",
    )


def test_load_announce_urls_defaults_empty(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text(HAPPY_TOML)
    assert config.load(providers_path=path).providers[0].announce_urls == ()


def test_load_rejects_non_list_announce_urls(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text(
        '[deepseek]\nprovider = "DeepSeek"\ndetector = "deepseek_page"\n'
        'detector_url = "https://x"\nscraper = "deepseek_page"\nscraper_url = "https://x"\n'
        'announce_urls = "https://x"\n'
    )
    with pytest.raises(config.ConfigError, match="announce_urls"):
        config.load_providers(path)


def test_load_rejects_empty_announce_url_element(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text(
        '[deepseek]\nprovider = "DeepSeek"\ndetector = "deepseek_page"\n'
        'detector_url = "https://x"\nscraper = "deepseek_page"\nscraper_url = "https://x"\n'
        'announce_urls = [""]\n'
    )
    with pytest.raises(config.ConfigError, match="announce_urls"):
        config.load_providers(path)


def test_load_rejects_target_era_keys(tmp_path):
    # yml/or_prefix died with the target-repo pivot; a stale toml must fail
    # loudly instead of silently ignoring the keys
    path = tmp_path / "providers.toml"
    path.write_text(
        '[deepseek]\nyml = "deepseek.yml"\nprovider = "DeepSeek"\n'
        'detector = "deepseek_page"\ndetector_url = "https://x"\n'
        'scraper = "deepseek_page"\nscraper_url = "https://x"\n'
    )
    with pytest.raises(config.ConfigError, match="yml"):
        config.load_providers(path)


def test_load_unknown_provider_key(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text('[deepseek]\nprovider = "DeepSeek"\nbogus = "x"\n')
    with pytest.raises(config.ConfigError, match="bogus"):
        config.load_providers(path)


def test_load_unknown_settings_key(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text("[settings]\ncap = 3\nbogus = 1\n")
    with pytest.raises(config.ConfigError, match="bogus"):
        config.load_providers(path)


def test_load_missing_required_key(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text('[deepseek]\nprovider = "DeepSeek"\n')
    with pytest.raises(config.ConfigError, match="scraper"):
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


def test_load_rejects_injected_cap_below_one():
    with pytest.raises(config.ConfigError, match="cap"):
        config.load(providers=(), cap=0)


def test_load_injected_providers_missing_file_defaults_cap(tmp_path):
    cfg = config.load(providers=(), providers_path=tmp_path / "nope.toml")
    assert cfg.cap == 3

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from ai_pricelog import config
from conftest import register_fake_module

HAPPY_TOML = """
[deepseek]
provider = "DeepSeek"
vendor = "deepseek"
kind = "first_party"
detector = "deepseek_page"
detector_url = "https://api-docs.deepseek.com/pricing"
scraper = "deepseek_page"
scraper_url = "https://api-docs.deepseek.com/pricing"
"""

ROOT = Path(__file__).resolve().parents[1]


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return json.dumps(value)
    return repr(value)


def section(**overrides: object) -> str:
    values = {
        "provider": "DeepSeek",
        "vendor": "deepseek",
        "kind": "first_party",
        "detector": "deepseek_page",
        "detector_url": "https://x",
        "scraper": "deepseek_page",
        "scraper_url": "https://x",
    }
    values.update(overrides)
    lines = ["[deepseek]"]
    for key, value in values.items():
        if value is None:
            continue
        lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines) + "\n"


def test_load_happy_path(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text(HAPPY_TOML)
    cfg = config.load(providers_path=path)
    assert len(cfg.providers) == 1
    pcfg = cfg.providers[0]
    assert pcfg.key == "deepseek"
    assert pcfg.provider == "DeepSeek"
    assert pcfg.vendor == "deepseek"
    assert pcfg.kind == "first_party"
    assert pcfg.detector == "deepseek_page"
    assert pcfg.detector_url == "https://api-docs.deepseek.com/pricing"
    assert pcfg.scraper == "deepseek_page"
    assert pcfg.scraper_url == "https://api-docs.deepseek.com/pricing"


def test_config_holds_no_repo(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text(HAPPY_TOML)
    cfg = config.load(providers_path=path)
    assert set(vars(cfg)) == {"providers"}


def test_load_currency_rate(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text(section(currency_rate=0.55))
    cfg = config.load(providers_path=path)
    assert cfg.providers[0].currency_rate == 0.55


def test_load_missing_currency_rate_defaults_none(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text(HAPPY_TOML)
    assert config.load(providers_path=path).providers[0].currency_rate is None


@pytest.mark.parametrize("bad", ["x", True, -1.0, 0, [], float("inf"), float("nan")])
def test_load_rejects_bad_currency_rate(tmp_path, bad):
    path = tmp_path / "providers.toml"
    path.write_text(section(currency_rate=bad))
    with pytest.raises(config.ConfigError, match="currency_rate"):
        config.load_providers(path)


def test_load_announce_urls(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text(section(announce_urls=["https://a.example/updates", "https://a.example/rss"]))
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
    path.write_text(section(announce_urls='"https://x"'))
    with pytest.raises(config.ConfigError, match="announce_urls"):
        config.load_providers(path)


def test_load_rejects_empty_announce_url_element(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text(section(announce_urls=[""]))
    with pytest.raises(config.ConfigError, match="announce_urls"):
        config.load_providers(path)


def test_load_rejects_target_era_keys(tmp_path):
    # yml/or_prefix died with the target-repo pivot; a stale toml must fail
    # loudly instead of silently ignoring the keys
    path = tmp_path / "providers.toml"
    path.write_text(section(yml="deepseek.yml"))
    with pytest.raises(config.ConfigError, match="yml"):
        config.load_providers(path)


def test_load_unknown_provider_key(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text(section(bogus="x"))
    with pytest.raises(config.ConfigError, match="bogus"):
        config.load_providers(path)


def test_load_rejects_stale_settings_section(tmp_path):
    # the cap-era [settings] section is gone; a stale toml must fail loudly
    # instead of silently ignoring the keys
    path = tmp_path / "providers.toml"
    path.write_text("[settings]\ncap = 3\n")
    with pytest.raises(config.ConfigError, match="cap"):
        config.load_providers(path)


def test_load_rejects_an_openrouter_section(tmp_path):
    # openrouter is generated, so a toml section would be silently overwritten
    path = tmp_path / "providers.toml"
    path.write_text(
        '[openrouter]\nprovider = "OpenRouter"\nkind = "reseller"\n'
        'detector = "x"\ndetector_url = "https://x"\nscraper = "x"\nscraper_url = "https://x"\n'
    )
    with pytest.raises(config.ConfigError, match="openrouter"):
        config.load_providers(path)


def test_load_missing_required_key(tmp_path):
    path = tmp_path / "providers.toml"
    path.write_text('[deepseek]\nprovider = "DeepSeek"\n')
    with pytest.raises(config.ConfigError, match="scraper"):
        config.load_providers(path)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"kind": "mixed"}, "kind"),
        ({"kind": None}, "missing"),
        ({"vendor": None}, "vendor"),
        ({"vendor": ""}, "vendor"),
        ({"vendor": "deepseek", "kind": "reseller"}, "reseller"),
    ],
)
def test_load_rejects_bad_kind_or_vendor(tmp_path, overrides, match):
    path = tmp_path / "providers.toml"
    path.write_text(section(**overrides))
    with pytest.raises(config.ConfigError, match=match):
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


def test_load_injected_providers_missing_file_is_ok(tmp_path):
    cfg = config.load(providers=(), providers_path=tmp_path / "nope.toml")
    assert cfg.providers == ()


def test_provider_key_that_cannot_name_a_shard_is_refused(tmp_path):
    # the key names data/history/<key>.ndjson, so a bad one reaches a
    # filesystem path. refusing at load keeps the failure off a PR branch,
    # where the raise lands after `git switch -C` and strands the checkout
    path = tmp_path / "providers.toml"
    path.write_text(HAPPY_TOML.replace("[deepseek]", "[DeepSeek]"))
    with pytest.raises(config.ConfigError, match="cannot name a shard file"):
        config.load(providers_path=path)


def test_generate_providers_matches_the_committed_file():
    generated = config.generate_providers(ROOT / "providers.toml")
    committed = json.loads((ROOT / "data" / "catalog" / "providers.json").read_text())
    assert committed == generated


def test_generate_providers_kind_is_binary_and_vendor_tracks_kind():
    providers = config.generate_providers(ROOT / "providers.toml")["providers"]
    for entry in providers.values():
        assert entry["kind"] in {"first_party", "reseller"}
        if entry["kind"] == "first_party":
            assert isinstance(entry.get("vendor"), str) and entry["vendor"]
        else:
            assert "vendor" not in entry
    assert providers["openrouter"] == config.OPENROUTER

"""provider config: parse the providers toml into frozen config dataclasses."""

from __future__ import annotations

import importlib
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_pricelog import store
from ai_pricelog.models import CATALOG_VERSION


class ConfigError(Exception):
    """provider config or provider-module resolution failure."""


@dataclass(frozen=True)
class ProviderCfg:
    key: str
    provider: str
    detector: str
    detector_url: str
    scraper: str
    scraper_url: str
    announce_urls: tuple[str, ...] = ()
    # USD per one source unit: the dbu->usd rate for providers quoting DBUs
    currency_rate: float | None = None
    # who made the models a first-party source serves; a reseller carries none
    vendor: str | None = None
    kind: str = "reseller"


@dataclass(frozen=True)
class Config:
    providers: tuple[ProviderCfg, ...]


_REQUIRED_KEYS = ("provider", "detector", "detector_url", "scraper", "scraper_url", "kind")
_MODULE_KINDS = ("detectors", "scrapers")
_KINDS = ("first_party", "reseller")

# openrouter is the one watched source with no toml section; its provider
# record derives here so the generator and the pipeline agree on one value.
OPENROUTER = {"name": "OpenRouter", "kind": "reseller"}


def load_providers(path: Path) -> tuple[ProviderCfg, ...]:
    data = _toml(path)
    providers: list[ProviderCfg] = []
    for section, values in data.items():
        if not isinstance(values, dict):
            raise ConfigError(f"providers file '{path}': section '{section}' must be a table")
        if section == "openrouter":
            raise ConfigError(
                f"providers file '{path}': 'openrouter' is generated, not a toml section"
            )
        # the key names the source's history shard file, so it has to be one
        # plain path segment; refusing here keeps the failure at load time
        try:
            store.shard_name(section)
        except ValueError as exc:
            raise ConfigError(f"providers file '{path}': {exc}") from exc
        for key in values:
            if key not in _REQUIRED_KEYS and key not in (
                "announce_urls",
                "currency_rate",
                "vendor",
            ):
                raise ConfigError(
                    f"providers file '{path}': provider '{section}' has unknown key '{key}'"
                )
        missing = [key for key in _REQUIRED_KEYS if key not in values]
        if missing:
            raise ConfigError(
                f"providers file '{path}': provider '{section}' is missing required keys {missing}"
            )
        kind = values["kind"]
        if kind not in _KINDS:
            raise ConfigError(
                f"providers file '{path}': provider '{section}' kind must be one of {_KINDS}"
            )
        vendor = values.get("vendor")
        if kind == "first_party":
            if not isinstance(vendor, str) or not vendor:
                raise ConfigError(
                    f"providers file '{path}': provider '{section}' kind"
                    " 'first_party' needs a non-empty 'vendor'"
                )
        elif "vendor" in values:
            raise ConfigError(
                f"providers file '{path}': provider '{section}' kind"
                " 'reseller' must not carry a 'vendor'"
            )
        announce = values.get("announce_urls", [])
        if not isinstance(announce, list) or not all(
            isinstance(url, str) and url for url in announce
        ):
            raise ConfigError(
                f"providers file '{path}': provider '{section}' announce_urls"
                " must be a list of non-empty strings"
            )
        rate = values.get("currency_rate")
        if rate is not None and (
            isinstance(rate, bool)
            or not isinstance(rate, (int, float))
            or not math.isfinite(rate)
            or rate <= 0
        ):
            raise ConfigError(
                f"providers file '{path}': provider '{section}' currency_rate must"
                " be a finite positive float"
            )
        providers.append(
            ProviderCfg(
                key=section,
                provider=values["provider"],
                detector=values["detector"],
                detector_url=values["detector_url"],
                scraper=values["scraper"],
                scraper_url=values["scraper_url"],
                announce_urls=tuple(announce),
                currency_rate=float(rate) if rate is not None else None,
                vendor=values.get("vendor"),
                kind=values["kind"],
            )
        )
    return tuple(providers)


def generate_providers(path: Path) -> dict[str, object]:
    """The committed providers.json content: providers.toml plus openrouter.

    A first-party section carries its `vendor`; a reseller section carries no
    `vendor` (it resells everybody). openrouter is the one watched source with
    no toml section, so the generator adds it as a vendorless reseller.
    """
    providers: dict[str, dict[str, str]] = {}
    for pcfg in load_providers(path):
        entry: dict[str, str] = {"name": pcfg.provider}
        if pcfg.vendor is not None:
            entry["vendor"] = pcfg.vendor
        entry["kind"] = pcfg.kind
        providers[pcfg.key] = entry
    providers["openrouter"] = dict(OPENROUTER)
    return {"version": CATALOG_VERSION, "providers": providers}


def load(
    providers: tuple[ProviderCfg, ...] | None = None,
    providers_path: Path | None = None,
) -> Config:
    path = Path("providers.toml") if providers_path is None else providers_path
    resolved_providers = tuple(providers) if providers is not None else load_providers(path)
    return Config(providers=resolved_providers)


def resolve_provider_module(kind: str, name: str) -> Any:
    if kind not in _MODULE_KINDS:
        raise ConfigError(
            f"unknown provider module kind '{kind}' (expected one of {_MODULE_KINDS})"
        )
    target = f"ai_pricelog.{kind}.{name}"
    try:
        return importlib.import_module(target)
    except ModuleNotFoundError as exc:
        if exc.name != target:
            raise
        raise ConfigError(f"provider '{name}': {kind} module '{target}' not found") from None


def _toml(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"providers file '{path}': {exc.strerror}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"providers file '{path}': invalid toml: {exc}") from exc

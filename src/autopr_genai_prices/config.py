import importlib
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    """provider config or provider-module resolution failure."""


@dataclass(frozen=True)
class ProviderCfg:
    key: str
    provider: str
    namespace: str
    detector: str
    detector_url: str
    scraper: str
    scraper_url: str
    token_env: str | None = None


@dataclass(frozen=True)
class Config:
    repo: str
    providers: tuple[ProviderCfg, ...]
    cap: int


_REQUIRED_KEYS = ("provider", "namespace", "detector", "detector_url", "scraper", "scraper_url")
_OPTIONAL_KEYS = ("token_env",)
_MODULE_KINDS = ("detectors", "scrapers")


def load_providers(path: Path) -> tuple[ProviderCfg, ...]:
    data = _toml(path)
    providers: list[ProviderCfg] = []
    for section, values in data.items():
        if section == "settings":
            _settings_cap(data, path)
            continue
        if not isinstance(values, dict):
            raise ConfigError(f"providers file '{path}': section '{section}' must be a table")
        for key in values:
            if key not in _REQUIRED_KEYS + _OPTIONAL_KEYS:
                raise ConfigError(
                    f"providers file '{path}': provider '{section}' has unknown key '{key}'"
                )
        missing = [key for key in _REQUIRED_KEYS if key not in values]
        if missing:
            raise ConfigError(
                f"providers file '{path}': provider '{section}' is missing required keys {missing}"
            )
        providers.append(
            ProviderCfg(
                key=section,
                provider=values["provider"],
                namespace=values["namespace"],
                detector=values["detector"],
                detector_url=values["detector_url"],
                scraper=values["scraper"],
                scraper_url=values["scraper_url"],
                token_env=values.get("token_env"),
            )
        )
    return tuple(providers)


def load(
    repo: str | None = None,
    providers: tuple[ProviderCfg, ...] | None = None,
    cap: int | None = None,
    providers_path: Path | None = None,
) -> Config:
    path = Path("providers.toml") if providers_path is None else providers_path
    repo_url = repo if repo is not None else os.environ.get("REPO", "")
    if not repo_url:
        raise ConfigError(
            "REPO env var missing or empty; pass repo= or set REPO to the target repo url"
        )
    repo_url = repo_url.rstrip("/")
    if not repo_url.startswith("https://github.com/"):
        raise ConfigError(f"repo must be a https://github.com/<owner>/<name> url: {repo_url!r}")
    resolved_providers = tuple(providers) if providers is not None else load_providers(path)
    if cap is not None:
        resolved_cap = cap
    elif providers is not None and not path.exists():
        # injected providers make the file optional; fall back to the default cap
        resolved_cap = 3
    else:
        resolved_cap = _settings_cap(_toml(path), path)
    if resolved_cap < 1:
        raise ConfigError(f"cap must be >= 1 (got {resolved_cap})")
    return Config(repo=repo_url, providers=resolved_providers, cap=resolved_cap)


def resolve_provider_module(kind: str, name: str) -> Any:
    if kind not in _MODULE_KINDS:
        raise ConfigError(
            f"unknown provider module kind '{kind}' (expected one of {_MODULE_KINDS})"
        )
    target = f"autopr_genai_prices.{kind}.{name}"
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


def _settings_cap(data: dict, path: Path) -> int:
    settings = data.get("settings", {})
    if not isinstance(settings, dict):
        raise ConfigError(f"providers file '{path}': [settings] must be a table")
    unknown = [key for key in settings if key != "cap"]
    if unknown:
        raise ConfigError(f"providers file '{path}': [settings] has unknown key '{unknown[0]}'")
    cap = settings.get("cap", 3)
    if isinstance(cap, bool) or not isinstance(cap, int):
        raise ConfigError(f"providers file '{path}': [settings] cap must be an int")
    if cap < 1:
        raise ConfigError(f"providers file '{path}': [settings] cap must be >= 1 (got {cap})")
    return cap

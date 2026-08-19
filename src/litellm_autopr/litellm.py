import json
import os
from dataclasses import dataclass
from pathlib import Path

from litellm_autopr.pricing import Pricing
from litellm_autopr.web import FetchError, fetch_text

LITELLM_FILE_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)


@dataclass
class LitellmFile:
    entries: dict[str, dict]
    providers: frozenset[str]
    modes: frozenset[str]


def load(path: Path) -> LitellmFile:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"file '{path}': invalid json: {exc.msg}") from exc
    return _from_json(data, f"file '{path}'")


def fetch_live(url: str | None = None) -> LitellmFile:
    url = url or os.environ.get("LITELLM_FILE_URL") or LITELLM_FILE_URL
    text = fetch_text(url)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FetchError(f"fetch for {url}: invalid json: {exc.msg}") from exc
    return _from_json(data, f"url '{url}'")


def build_entry(namespace: str, provider: str, model_id: str, pricing: Pricing) -> tuple[str, dict]:
    entry: dict = {
        "input_cost_per_token": pricing.input_cost_per_token,
        "output_cost_per_token": pricing.output_cost_per_token,
        "litellm_provider": provider,
        "mode": pricing.mode,
    }
    if pricing.max_tokens > 0:
        entry["max_tokens"] = pricing.max_tokens
    return f"{namespace}/{model_id}", entry


def _from_json(data: object, source: str) -> LitellmFile:
    if not isinstance(data, dict):
        raise ValueError(f"{source}: root must be a json object")
    entries: dict[str, dict] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise ValueError(f"{source}: entry '{key}' must be an object")
        entries[key] = value
    return LitellmFile(
        entries=entries,
        providers=frozenset(
            e["litellm_provider"] for e in entries.values() if "litellm_provider" in e
        ),
        modes=frozenset(e["mode"] for e in entries.values() if "mode" in e),
    )

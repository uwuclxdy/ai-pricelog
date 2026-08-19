import json
import math
from pathlib import Path

from autopr_genai_prices.config import Config, ProviderCfg
from autopr_genai_prices.litellm import LitellmFile


class ValidationError(ValueError):
    """an entry failed validation; the message names key, field, bad value, fix."""


def validate_entry(key: str, entry: dict, live: LitellmFile, cfg: Config) -> None:
    pcfg = _match_provider(key, cfg)
    if pcfg is None:
        raise ValidationError(
            f"entry '{key}': key must be '<namespace>/<model_id>' of a configured provider; "
            f"fix: use one of the namespaces {[p.namespace for p in cfg.providers]}"
        )
    provider = entry.get("litellm_provider")
    if provider != pcfg.provider:
        raise ValidationError(
            f"entry '{key}': field 'litellm_provider' must be {pcfg.provider!r} for namespace "
            f"{pcfg.namespace!r} (got {provider!r}); fix: write the configured provider value"
        )
    if provider not in live.providers:
        raise ValidationError(
            f"entry '{key}': litellm_provider {provider!r} not in the live file's vocabulary; "
            f"fix: check the live file for the current provider names"
        )
    mode = entry.get("mode")
    if mode not in live.modes:
        raise ValidationError(
            f"entry '{key}': field 'mode' has bad value {mode!r}; "
            f"fix: use one of the live file's modes {sorted(live.modes)}"
        )
    for field in ("input_cost_per_token", "output_cost_per_token"):
        value = entry.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, float)
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValidationError(
                f"entry '{key}': field '{field}' has bad value {value!r}; "
                f"fix: use a finite float > 0"
            )
    if "max_tokens" in entry:
        value = entry["max_tokens"]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValidationError(
                f"entry '{key}': field 'max_tokens' has bad value {value!r}; fix: use an int > 0"
            )


def validate_repo_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"repo file '{path}': invalid json: {exc.msg}; fix: restore the file"
        ) from exc
    if not isinstance(data, dict):
        raise ValidationError(f"repo file '{path}': root must be an object")
    return data


def _match_provider(key: str, cfg: Config) -> ProviderCfg | None:
    for pcfg in cfg.providers:
        prefix = f"{pcfg.namespace}/"
        if key.startswith(prefix) and key[len(prefix) :]:
            return pcfg
    return None

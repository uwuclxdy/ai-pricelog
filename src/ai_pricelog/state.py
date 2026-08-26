import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProviderState:
    last_seen: list[str] = field(default_factory=list)


@dataclass
class State:
    providers: dict[str, ProviderState] = field(default_factory=dict)


def load(path: Path) -> State:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return State()
    except json.JSONDecodeError as exc:
        raise ValueError(f"state file '{path}': invalid json: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"state file '{path}': root must be an object")
    providers_raw = data.get("providers")
    if not isinstance(providers_raw, dict):
        raise ValueError(f"state file '{path}': field 'providers' must be an object")
    state = State()
    for key, raw in providers_raw.items():
        if not isinstance(raw, dict):
            raise ValueError(f"state file '{path}': provider '{key}' must be an object")
        values = raw.get("last_seen", [])
        if not isinstance(values, list):
            raise ValueError(
                f"state file '{path}': provider '{key}' field 'last_seen' must be a list"
            )
        if not all(isinstance(value, str) for value in values):
            raise ValueError(
                f"state file '{path}': provider '{key}' field 'last_seen' must hold strings"
            )
        state.providers[key] = ProviderState(list(dict.fromkeys(values)))
    return state


def save(state: State, path: Path) -> None:
    data = {
        "providers": {
            key: {"last_seen": list(dict.fromkeys(provider_state.last_seen))}
            for key, provider_state in state.providers.items()
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2) + "\n"
    # atomic replace: write a temp file in the same directory, then swap it in.
    # a crash mid-write leaves the previous state intact instead of half a file.
    tmp_name: str | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        with os.fdopen(fd, "w") as handle:
            handle.write(payload)
        os.replace(tmp_name, path)
        tmp_name = None
    finally:
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)


def new_ids(state: State, key: str, current: list[str]) -> list[str]:
    provider_state = state.providers.get(key)
    if provider_state is None:
        return list(dict.fromkeys(current))
    excluded = set(provider_state.last_seen)
    return [model_id for model_id in dict.fromkeys(current) if model_id not in excluded]


def append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)

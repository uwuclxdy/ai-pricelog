"""Billing-rule announcement watch: per-provider public channels vs a committed snapshot.

Every configured channel is fetched each run, reduced to normalized prose, and
hashed. A hash differing from the committed data/announce.json snapshot is an
announcement change: the pipeline reports it old->new on every draft PR it
opens and commits the updated snapshot on the PR branch, so a channel settles
only under a human-reviewed PR. With no PR opened the snapshot stays stale and
the change re-surfaces next run (skip-and-retry). Confirmed billing-rule
semantics land in the committed data/billing-rules.json, human-written per
rule; the pipeline never writes it.
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import warnings
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from ai_pricelog import web
from ai_pricelog.config import Config
from ai_pricelog.store import _atomic_write

ANNOUNCE_FILE = "data/announce.json"
BILLING_RULES_FILE = "data/billing-rules.json"


@dataclass(frozen=True)
class ChannelChange:
    """One watched channel whose prose differs from the committed snapshot."""

    provider: str
    url: str
    old_sha256: str
    new_sha256: str
    old_text: str
    new_text: str


@dataclass(frozen=True)
class FetchResult:
    """One announce fetch pass: the changes, the fresh snapshot, the fetch errors."""

    changes: tuple[ChannelChange, ...]
    snapshot: dict[str, dict[str, dict[str, str]]]
    errors: tuple[str, ...]


def extract_prose(url: str, text: str) -> str:
    """The normalized prose of a channel fetch: visible text, one spacing.

    Markdown mirrors pass through with whitespace collapsed; html and feed
    pages lose markup, script, and style blocks (html.parser tolerates feed
    xml fine, and lxml is not a dependency). Hashing the prose rather than
    the raw bytes keeps rebuild noise (lastmod attributes, timestamps outside
    prose) from faking changes.
    """
    if urllib.parse.urlsplit(url).path.lower().endswith((".md", ".txt")):
        return " ".join(text.split())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_snapshot(path: Path) -> dict[str, dict[str, dict[str, str]]]:
    """The committed channel snapshot, or an empty one when absent."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"announce file '{path}': invalid json: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"announce file '{path}': must be an object")
    return data


def save_snapshot(snapshot: dict[str, dict[str, dict[str, str]]], path: Path) -> None:
    _atomic_write(json.dumps(snapshot, ensure_ascii=False) + "\n", path)


def differs(
    old: dict[str, dict[str, dict[str, str]]], new: dict[str, dict[str, dict[str, str]]]
) -> bool:
    """Whether the fresh snapshot differs from the committed one: any url added,
    removed, or hash-changed."""
    keys = {(p, u) for p, urls in old.items() for u in urls} | {
        (p, u) for p, urls in new.items() for u in urls
    }
    return any(
        old.get(provider, {}).get(url, {}).get("sha256")
        != new.get(provider, {}).get(url, {}).get("sha256")
        for provider, url in keys
    )


def fetch_channels(
    cfg: Config, snapshot: dict[str, dict[str, dict[str, str]]], today: str
) -> FetchResult:
    """Fetch every configured channel; a prose hash differing from the snapshot is a change.

    A failed fetch keeps the snapshot entry, so the stale entry re-diffs next
    run. Entries for urls no longer configured drop on the next save.
    """
    changes: list[ChannelChange] = []
    errors: list[str] = []
    fresh: dict[str, dict[str, dict[str, str]]] = {}
    for pcfg in cfg.providers:
        for url in pcfg.announce_urls:
            try:
                prose = extract_prose(url, web.fetch_text(url))
            except (web.FetchError, ValueError) as exc:
                errors.append(f"{pcfg.key} {url}: {type(exc).__name__}: {exc}")
                old = snapshot.get(pcfg.key, {}).get(url)
                if old is not None:
                    fresh.setdefault(pcfg.key, {})[url] = old
                continue
            new_entry = {"text": prose, "sha256": _sha256(prose), "fetched": today}
            old = snapshot.get(pcfg.key, {}).get(url)
            fresh.setdefault(pcfg.key, {})[url] = new_entry
            if old is not None and old.get("sha256") != new_entry["sha256"]:
                changes.append(
                    ChannelChange(
                        pcfg.key,
                        url,
                        old.get("sha256", ""),
                        new_entry["sha256"],
                        old.get("text", ""),
                        prose,
                    )
                )
    return FetchResult(tuple(changes), fresh, tuple(errors))


_BILLING_RULE_KEYS = frozenset({"id", "provider", "effective", "timezone", "statement", "citation"})


def load_billing_rules(path: Path) -> list[dict[str, object]]:
    """The committed billing rules, schema-checked; errors name the rule."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"billing-rules file '{path}': missing") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"billing-rules file '{path}': invalid json: {exc.msg}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise ValueError(f"billing-rules file '{path}': must carry a 'rules' list")
    seen_ids: set[str] = set()
    for rule in data["rules"]:
        label = rule.get("id", "?") if isinstance(rule, dict) else "?"
        if not isinstance(rule, dict):
            raise ValueError(f"billing-rules file '{path}': rule '{label}' must be an object")
        unknown = [key for key in rule if key not in _BILLING_RULE_KEYS]
        if unknown:
            raise ValueError(
                f"billing-rules file '{path}': rule '{label}' has unknown key '{unknown[0]}'"
            )
        for key in _BILLING_RULE_KEYS:
            if key not in rule:
                raise ValueError(f"billing-rules file '{path}': rule '{label}' is missing '{key}'")
        for key in ("id", "provider", "statement"):
            if not isinstance(rule[key], str) or not rule[key]:
                raise ValueError(
                    f"billing-rules file '{path}': rule '{label}' '{key}'"
                    " must be a non-empty string"
                )
        if rule["id"] in seen_ids:
            raise ValueError(f"billing-rules file '{path}': duplicate rule id '{rule['id']}'")
        seen_ids.add(rule["id"])
        try:
            date.fromisoformat(rule["effective"])
        except ValueError as exc:
            raise ValueError(
                f"billing-rules file '{path}': rule '{label}' effective must be YYYY-MM-DD"
            ) from exc
        try:
            ZoneInfo(rule["timezone"])
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                f"billing-rules file '{path}': rule '{label}'"
                f" timezone '{rule['timezone']}' is unknown"
            ) from exc
        if (
            not isinstance(rule["citation"], list)
            or not rule["citation"]
            or not all(isinstance(entry, str) and entry for entry in rule["citation"])
        ):
            raise ValueError(
                f"billing-rules file '{path}': rule '{label}' citation"
                " must be a non-empty list of non-empty strings"
            )
    return data["rules"]

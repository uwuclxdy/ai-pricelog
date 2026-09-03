"""Billing-rule announcement watch: per-provider public channels vs a committed snapshot.

Every configured channel is fetched each run, reduced to normalized prose, and
hashed. The committed snapshot lives under state/announce/: one sentence-per-line
.md file per channel plus an index.json that owns url -> file. A hash differing
from the committed snapshot is an announcement change: the pipeline reports it
old->new on every draft PR it opens and commits the fresh snapshot on the PR
branch, so a channel settles only under a human-reviewed PR. With no PR opened
the snapshot stays stale and the change re-surfaces next run (skip-and-retry).
Confirmed billing-rule semantics land in the committed data/billing-rules.json,
human-written per rule; the pipeline never writes it.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import warnings
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from ai_pricelog import web
from ai_pricelog.config import Config
from ai_pricelog.store import _atomic_write

ANNOUNCE_DIR = "state/announce"
ANNOUNCE_INDEX = "state/announce/index.json"
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


_FEED_ROOTS = frozenset({"rss", "feed"})
_FEED_DATE_TAGS = ("lastbuilddate", "pubdate", "published", "updated", "dc:date")


def extract_prose(url: str, text: str) -> str:
    """The normalized prose of a channel fetch: visible text, one spacing.

    Markdown mirrors pass through with whitespace collapsed; html and feed
    pages lose markup, script, and style blocks (html.parser tolerates feed
    xml fine, and lxml is not a dependency). A feed document (root rss or
    feed) also drops its date metadata elements; a re-publish re-dates the
    feed with zero content change, and the dates would fake a change.
    Hashing the prose rather than the raw bytes keeps rebuild noise (lastmod
    attributes, timestamps outside prose) from faking changes.
    """
    if urllib.parse.urlsplit(url).path.lower().endswith((".md", ".txt")):
        return " ".join(text.split())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    root = soup.find()
    if root is not None and root.name in _FEED_ROOTS:
        for tag in soup(_FEED_DATE_TAGS):
            tag.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slug(url: str) -> str:
    """The channel filename stem: the url's last path segment, slugged.

    The segment lowercases, every run of non-alphanumeric characters collapses
    to one dash, and leading/trailing dashes strip; an empty segment reads as
    ``index``.
    """
    segments = [part for part in urllib.parse.urlsplit(url).path.split("/") if part]
    segment = segments[-1] if segments else ""
    return re.sub(r"[^a-z0-9]+", "-", segment.lower()).strip("-") or "index"


def channel_files(source: str, urls: Iterable[str]) -> dict[str, str]:
    """Map each url to its repo-relative .md path, disambiguating slug collisions.

    When two urls of one source share a slug, every colliding member gains the
    url's sha256 prefix, so the naming never depends on config order.
    """
    urls = list(urls)
    stems = {url: slug(url) for url in urls}
    counts = Counter(stems.values())
    files: dict[str, str] = {}
    for url in urls:
        stem = stems[url]
        if counts[stem] > 1:
            stem = f"{stem}-{_sha256(url)[:8]}"
        files[url] = f"{ANNOUNCE_DIR}/{source}/{stem}.md"
    return files


# sentence-per-line leaves url lists and rss bodies as one giant line; wrap
# only those, above the p90 line length (537 chars) measured 2026-09-03
_LINE_CEILING = 600


def wrap(prose: str) -> str:
    """The canonical prose one sentence per line, then long lines word-wrapped.

    The sentence split owns the boundaries, so an edit reflows only its own
    sentence. The ceiling then subdivides only the lines the sentence split
    left too long, breaking at a space, never inside a word. The canonical
    prose already carries single spaces and no newlines, so both passes are
    exact: ``unwrap`` recovers it byte-for-byte.
    """
    lines: list[str] = []
    for sentence in re.sub(r"(?<=[.!?]) ", "\n", prose).splitlines():
        lines.extend(_wrap_line(sentence))
    return "\n".join(lines) + "\n"


def _wrap_line(line: str) -> list[str]:
    """One sentence split into lines no longer than the ceiling, at spaces only."""
    if len(line) <= _LINE_CEILING:
        return [line]
    out: list[str] = []
    current = ""
    for word in line.split(" "):
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= _LINE_CEILING:
            current += " " + word
        else:
            out.append(current)
            current = word
    if current:
        out.append(current)
    return out


def unwrap(text: str) -> str:
    """The canonical prose: every whitespace run folds back to one space."""
    return " ".join(text.split())


def load_snapshot(repo_root: Path) -> dict[str, dict[str, dict[str, str]]]:
    """The committed channel snapshot, or an empty one when absent.

    index.json is the authority on url -> file; the prose is recovered from
    each .md file, so the in-memory entry keeps the ``text`` the change report
    needs.
    """
    path = repo_root / ANNOUNCE_INDEX
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"announce index '{path}': invalid json: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"announce index '{path}': must be an object")
    snapshot: dict[str, dict[str, dict[str, str]]] = {}
    for source, urls in data.items():
        if not isinstance(source, str) or not isinstance(urls, dict):
            raise ValueError(f"announce index '{path}': source {source!r} must map to an object")
        derived = channel_files(source, urls.keys())
        entries: dict[str, dict[str, str]] = {}
        for url, entry in urls.items():
            if not isinstance(url, str) or not isinstance(entry, dict):
                raise ValueError(
                    f"announce index '{path}': entry {source!r}/{url!r} must be an object"
                )
            for key in ("file", "sha256", "fetched"):
                if not isinstance(entry.get(key), str):
                    raise ValueError(
                        f"announce index '{path}': entry {source!r}/{url!r} is missing '{key}'"
                    )
            expected = derived[url]
            if entry["file"] != expected:
                raise ValueError(
                    f"announce index '{path}': entry {source!r}/{url!r} file"
                    f" {entry['file']!r} does not match the derived path {expected!r}"
                )
            try:
                text = (repo_root / expected).read_text(encoding="utf-8")
            except FileNotFoundError as exc:
                raise ValueError(
                    f"announce index '{path}': entry {source!r}/{url!r} file"
                    f" '{expected}' is missing"
                ) from exc
            entries[url] = {
                "file": expected,
                "text": unwrap(text),
                "sha256": entry["sha256"],
                "fetched": entry["fetched"],
            }
        snapshot[source] = entries
    return snapshot


def save_snapshot(snapshot: dict[str, dict[str, dict[str, str]]], repo_root: Path) -> None:
    """Write the .md files and index.json, then drop orphaned channel files.

    A channel that left providers.toml no longer appears in the snapshot; its
    .md file is deleted here and the caller stages the deletion with
    ``git add -A -- state/announce``.
    """
    ann_dir = repo_root / ANNOUNCE_DIR
    index: dict[str, dict[str, dict[str, str]]] = {}
    named: set[str] = set()
    for source, urls in snapshot.items():
        derived = channel_files(source, urls.keys())
        for url, entry in urls.items():
            file = derived[url]
            named.add(file)
            _atomic_write(wrap(entry["text"]), repo_root / file)
            index.setdefault(source, {})[url] = {
                "file": file,
                "sha256": entry["sha256"],
                "fetched": entry["fetched"],
            }
    _atomic_write(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", repo_root / ANNOUNCE_INDEX
    )
    for source_dir in list(ann_dir.iterdir()):
        if not source_dir.is_dir():
            continue
        for path in source_dir.glob("*.md"):
            if path.relative_to(repo_root).as_posix() not in named:
                path.unlink()
        if not any(source_dir.iterdir()):
            source_dir.rmdir()


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
    run. Entries for urls no longer configured drop on the next save. A channel
    keeps its stored ``fetched`` while its hash is unchanged and takes today's
    date only when its hash moves, so one real change never re-dates every row.
    """
    changes: list[ChannelChange] = []
    errors: list[str] = []
    fresh: dict[str, dict[str, dict[str, str]]] = {}
    for pcfg in cfg.providers:
        files = channel_files(pcfg.key, pcfg.announce_urls)
        for url in pcfg.announce_urls:
            try:
                prose = extract_prose(url, web.fetch_text(url))
            except (web.FetchError, ValueError) as exc:
                errors.append(f"{pcfg.key} {url}: {type(exc).__name__}: {exc}")
                old = snapshot.get(pcfg.key, {}).get(url)
                if old is not None:
                    fresh.setdefault(pcfg.key, {})[url] = dict(old)
                continue
            sha = _sha256(prose)
            old = snapshot.get(pcfg.key, {}).get(url)
            fetched = old["fetched"] if old is not None and old.get("sha256") == sha else today
            new_entry = {"file": files[url], "text": prose, "sha256": sha, "fetched": fetched}
            fresh.setdefault(pcfg.key, {})[url] = new_entry
            if old is not None and old.get("sha256") != sha:
                changes.append(
                    ChannelChange(
                        pcfg.key,
                        url,
                        old.get("sha256", ""),
                        sha,
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

"""xAI model detection from the docs.x.ai models page.

the page is static mintlify html; models live in an embedded json blob assigned to
``globalThis.__XAI_PUBLIC_MODELS__``. language models are the ``languageModels``
entries carrying ``promptTextTokenPrice`` inside ``clusterConfigs``; image, audio
and video entries have no token pricing and are out of scope.
"""

import json
from functools import cache

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_text

_MARKER = "__XAI_PUBLIC_MODELS__"


def _extract_blob(html: str, url: str) -> dict:
    """pull the json object assigned to the models marker out of the page html."""
    marker_at = html.find(_MARKER)
    if marker_at < 0:
        raise FetchError(f"no {_MARKER} blob found on {url}")
    equals_at = html.find("=", marker_at)
    brace_at = html.find("{", equals_at)
    if brace_at < 0:
        raise FetchError(f"no {_MARKER} value found on {url}")
    depth = 0
    for end_at in range(brace_at, len(html)):
        char = html[end_at]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                break
    else:
        raise FetchError(f"unterminated {_MARKER} blob on {url}")
    try:
        blob = json.loads(html[brace_at : end_at + 1])
    except json.JSONDecodeError as exc:
        raise FetchError(f"invalid {_MARKER} json on {url}: {exc}") from exc
    if not isinstance(blob, dict):
        raise FetchError(f"{_MARKER} blob on {url} is not an object")
    return blob


@cache
def _blob(url: str) -> dict:
    """fetch and parse the models blob; cached per url so the scraper reuses this parse."""
    return _extract_blob(fetch_text(url), url)


def _language_models(blob: dict, url: str) -> list[dict]:
    """every languageModels entry across clusters, cluster order preserved."""
    clusters = blob.get("clusterConfigs")
    if not isinstance(clusters, list):
        raise FetchError(f"{_MARKER} blob on {url} has no clusterConfigs list")
    models: list[dict] = []
    for cluster in clusters:
        if not isinstance(cluster, dict):
            raise FetchError(f"{_MARKER} blob on {url} has a non-object cluster")
        entries = cluster.get("languageModels", [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("name"):
                models.append(entry)
    return models


def detect(cfg: ProviderCfg) -> list[str]:
    """current raw language model ids, page order, deduped across clusters."""
    blob = _blob(cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    for entry in _language_models(blob, cfg.detector_url):
        if "promptTextTokenPrice" not in entry:
            continue
        name = entry["name"]
        if name not in seen:
            seen.add(name)
            ids.append(name)
    if not ids:
        raise FetchError(f"no priced language models found on {cfg.detector_url}")
    return ids

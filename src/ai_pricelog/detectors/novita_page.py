"""detect model ids on the novita pricing page.

reads https://novita.ai/pricing (static server-rendered next.js html). each
priced chat model is an ``<article data-testid="model-section-mobile-card">``
whose name link points at ``/models/model-detail/<slug>?from=pricing``. the
slug is the canonical api id with "/" url-encoded as "-", which hides the
vendor boundary ("meta-llama-llama-3.1-8b-instruct" is meta-llama's llama,
not meta's llama-llama). the page's embedded next.js flight state carries
the canonical ids (``\"id\":\"...\"`` inside the ``__next_f`` script
payloads), so each card slug resolves through it; a slug the flight state
does not name falls back to splitting at the first dash. the embedding and
image cards (testid ``model-api-mobile-card``) have no token rates and are
out of scope. a page with no model cards or no ids is a parse failure
(FetchError).
"""

from __future__ import annotations

import re
from functools import cache

from bs4 import BeautifulSoup, Tag

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup

_CARD_TESTID = "model-section-mobile-card"
_HREF_RE = re.compile(r"^/models/model-detail/([^/?]+)")
_FLIGHT_ID_RE = re.compile(r'\\"id\\":\\"([^"\\]+)\\"')


@cache
def _page(url: str) -> tuple[BeautifulSoup, dict[str, str]]:
    """fetch and parse the page; cached per url so the scraper reuses this parse.

    returns (soup, canonical) where canonical maps each card's dash slug to
    the canonical api id from the embedded flight state.
    """
    soup = fetch_soup(url)
    return soup, _canonical_ids(soup)


def _canonical_ids(soup: BeautifulSoup) -> dict[str, str]:
    """dash slug -> canonical api id, from the __next_f flight state."""
    canonical: dict[str, str] = {}
    for script in soup.find_all("script"):
        text = script.string
        if not text or "__next_f" not in text:
            continue
        for model_id in _FLIGHT_ID_RE.findall(text):
            canonical[model_id.replace("/", "-")] = model_id
    return canonical


def _model_cards(soup: BeautifulSoup, url: str) -> list[Tag]:
    cards = soup.find_all("article", attrs={"data-testid": _CARD_TESTID})
    if not cards:
        raise FetchError(f"no model cards on {url}")
    return cards


def _card_slug(card: Tag) -> str | None:
    """the dash slug from the card's model-detail link, or None without one."""
    for link in card.find_all("a", href=True):
        match = _HREF_RE.search(link["href"])
        if match:
            return match.group(1)
    return None


def _page_id(slug: str, canonical: dict[str, str]) -> str:
    """the canonical api id for a card slug; first-dash split when unknown."""
    return canonical.get(slug, slug.replace("-", "/", 1))


def detect(cfg: ProviderCfg) -> list[str]:
    """current priced-model ids, page order, deduped."""
    soup, canonical = _page(cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    for card in _model_cards(soup, cfg.detector_url):
        slug = _card_slug(card)
        if slug is None:
            continue
        model_id = _page_id(slug, canonical)
        if model_id not in seen:
            seen.add(model_id)
            ids.append(model_id)
    if not ids:
        raise FetchError(f"no model ids on {cfg.detector_url}")
    return ids

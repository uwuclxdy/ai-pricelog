"""detect ai21 model ids from the ai21 pricing page.

https://www.ai21.com/pricing serves the Foundation Models section statically:
one card per model, the name in ``h3.card__title`` and the per-token rates
in ``div.card__footer`` as two lines ("$0.2 / 1M input tokens" / "$0.4 / 1M
output tokens"). ids are the card title lowercased with non-alphanumeric
runs collapsed to single hyphens ("Jamba Mini" -> "jamba-mini"). the page
bot-blocks the default http client's UA and serves a browser UA, so both
fetches send one (measured 2026-09-02). a card without its title or
footer and a title outside the id charset are additive drift: detection
skips them with a warning (plan #22); a page with no cards still raises.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup

log = logging.getLogger(__name__)

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
_SLUG_PATTERN = re.compile(r"[^a-z0-9.]+")

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
}


def _card_parts(soup: BeautifulSoup) -> list[tuple[BeautifulSoup | None, BeautifulSoup | None]]:
    """the Foundation Models cards as (title, footer) tag pairs, page order."""
    cards: list[tuple[BeautifulSoup | None, BeautifulSoup | None]] = []
    for card in soup.select("div.b-cards--type-models div.card"):
        cards.append((card.select_one("h3.card__title"), card.select_one("div.card__footer")))
    return cards


def _slug(title: str, url: str) -> str:
    """the card title as the stored id; an out-of-charset slug is a FetchError."""
    slug = _SLUG_PATTERN.sub("-", title.lower()).strip("-")
    if not _ID_PATTERN.fullmatch(slug):
        raise FetchError(f"model title {title!r} outside the id charset on {url}")
    return slug


def detect(cfg: ProviderCfg) -> list[str]:
    """current model ids, card order; additive drift skips with a warning."""
    soup = fetch_soup(cfg.detector_url, headers=_UA)
    cards = _card_parts(soup)
    ids: list[str] = []
    for title, footer in cards:
        if title is None or footer is None:
            log.warning(
                "detect skip for %s: model card without a title or footer on the ai21 pricing page",
                cfg.key,
            )
            continue
        try:
            model_id = _slug(title.get_text(" ", strip=True), cfg.detector_url)
        except FetchError as exc:
            log.warning("detect skip for %s: %s", cfg.key, exc)
            continue
        ids.append(model_id)
    if not ids:
        raise FetchError(f"no foundation model cards on {cfg.detector_url}")
    return ids

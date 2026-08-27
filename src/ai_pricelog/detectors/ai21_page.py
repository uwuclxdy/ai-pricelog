"""detect ai21 model ids from the ai21 pricing page.

https://www.ai21.com/pricing serves the Foundation Models section statically:
one card per model, the name in ``h3.card__title`` and the per-token rates
in ``div.card__footer`` as two lines ("$0.2 / 1M input tokens" / "$0.4 / 1M
output tokens"). ids are the card title lowercased with non-alphanumeric
runs collapsed to single hyphens ("Jamba Mini" -> "jamba-mini"). a page
with no model cards, or a card without its title/footer, is a parse failure
(FetchError).
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
_SLUG_PATTERN = re.compile(r"[^a-z0-9.]+")


def _model_cards(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """the Foundation Models cards as (title, footer) pairs, page order."""
    cards: list[tuple[str, str]] = []
    for card in soup.select("div.b-cards--type-models div.card"):
        title = card.select_one("h3.card__title")
        footer = card.select_one("div.card__footer")
        if title is None or footer is None:
            raise FetchError("model card without a title or footer on the ai21 pricing page")
        cards.append((title.get_text(" ", strip=True), footer.get_text(" ", strip=True)))
    return cards


def _slug(title: str, url: str) -> str:
    """the card title as the stored id; an out-of-charset slug is a FetchError."""
    slug = _SLUG_PATTERN.sub("-", title.lower()).strip("-")
    if not _ID_PATTERN.fullmatch(slug):
        raise FetchError(f"model title {title!r} outside the id charset on {url}")
    return slug


def detect(cfg: ProviderCfg) -> list[str]:
    """current model ids, card order."""
    soup = fetch_soup(cfg.detector_url)
    cards = _model_cards(soup)
    if not cards:
        raise FetchError(f"no foundation model cards on {cfg.detector_url}")
    return [_slug(title, cfg.detector_url) for title, _ in cards]

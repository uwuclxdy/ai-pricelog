"""mistral model detection from the model-cards index + pricing pages.

the cards page lists every model card; the pricing page carries the priced
set, so both are read (the cards index alone under-seeds). both pages are
static SSR; every model links to ``/models/<slug>``. ids emit as raw page
slugs; the scraper's ``dedup_keys`` maps a slug to the stored spellings
(dashed dated tails compact, the ministral generation segment drops), and
the pipeline settles on whichever spelling has a stored row. deduped,
cards-page order first, then pricing-page rows.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup

SLUG_RE = re.compile(r"^/models/([a-z0-9-]+)$")

# slug tail like -4-0-26-03 or -25-08 (zero to three version segments, then
# yy-mm) compacts to -2603 / -2508, the stored spellings (codestral-2508 etc.).
# slugs without a dated tail stay verbatim.
_DATED_TAIL = re.compile(r"^(.*?)(?:-\d+){0,3}-(\d{2})-(\d{2})$")

# a generation segment between family and size (ministral-3-14b): the store
# holds the spelling without it (ministral-14b-2512)
_GENERATION_SEGMENT = re.compile(r"^(.+)-(\d+)-(\d+b(?:-.*)?)$")


def _compact(slug: str) -> str:
    match = _DATED_TAIL.match(slug)
    if match is None:
        return slug
    return f"{match.group(1)}-{match.group(2)}{match.group(3)}"


def _page_slugs(soup: BeautifulSoup, url: str) -> list[str]:
    """deduped /models/ link slugs on one page, page order."""
    slugs: list[str] = []
    for anchor in soup.find_all("a", href=True):
        match = SLUG_RE.fullmatch(anchor["href"])
        if match is None:
            continue
        slug = match.group(1)
        if slug not in slugs:
            slugs.append(slug)
    if not slugs:
        raise FetchError(f"no model links found on {url}")
    return slugs


def detect(cfg: ProviderCfg) -> list[str]:
    """current model ids as raw page slugs, cards page first, then pricing.

    the pricing page is the priced set; a pricing page without model links
    raises, so a redesign cannot silently shrink the seed.
    """
    ids: list[str] = []
    for soup, url in (
        (fetch_soup(cfg.detector_url), cfg.detector_url),
        (fetch_soup(cfg.scraper_url), cfg.scraper_url),
    ):
        for slug in _page_slugs(soup, url):
            if slug not in ids:
                ids.append(slug)
    return ids


def detect_priced(cfg: ProviderCfg) -> list[str]:
    """page slugs from the pricing page only: the priced set.

    absence keys on this set, so a model still carded but no longer priced
    counts absent while the cards index keeps over-seeding candidates.
    """
    soup = fetch_soup(cfg.scraper_url)
    return _page_slugs(soup, cfg.scraper_url)

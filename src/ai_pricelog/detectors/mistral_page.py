"""mistral model detection from the model-cards index + pricing pages.

the cards page lists every model card; the pricing page carries the priced
set, so both are read (the cards index alone under-seeds). both pages are
static SSR; every model links to ``/models/<slug>``. ids are emitted in the
stored spelling (``stored_spelling``): dashed dated tails compact
(``codestral-25-08`` -> ``codestral-2508``) and the ministral generation
segment drops (``ministral-3-14b-25-12`` -> ``ministral-14b-2512``), so the
first stored spelling names the model. deduped, cards-page order first, then
pricing-page rows.
"""

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


def stored_spelling(slug: str) -> str:
    """The spelling the store holds for a page slug.

    dated tails compact (``codestral-25-08`` -> ``codestral-2508``) and the
    ministral generation segment drops (``ministral-3-14b-25-12`` ->
    ``ministral-14b-2512``). ids the scraper's ``dedup_keys`` maps to nothing
    stay verbatim.
    """
    compacted = _compact(slug)
    match = _GENERATION_SEGMENT.match(compacted)
    if match is not None:
        return f"{match.group(1)}-{match.group(3)}"
    return compacted


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
    """current model ids in the stored spelling, cards page first, then pricing.

    the pricing page is the priced set; a pricing page without model links
    raises, so a redesign cannot silently shrink the seed.
    """
    ids: list[str] = []
    seen: set[str] = set()
    for soup, url in (
        (fetch_soup(cfg.detector_url), cfg.detector_url),
        (fetch_soup(cfg.scraper_url), cfg.scraper_url),
    ):
        for slug in _page_slugs(soup, url):
            stored = stored_spelling(slug)
            if stored not in seen:
                seen.add(stored)
                ids.append(stored)
    return ids

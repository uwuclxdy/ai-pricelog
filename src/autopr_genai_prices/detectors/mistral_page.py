"""mistral model detection from the model-cards index page.

the page is static SSR; every model card links to ``/models/<slug>``. ids are the
slugs verbatim (e.g. ``mistral-medium-3-5-26-04``), deduped, in page order.
"""

import re

from autopr_genai_prices.config import ProviderCfg
from autopr_genai_prices.web import FetchError, fetch_soup

SLUG_RE = re.compile(r"^/models/([a-z0-9-]+)$")


def detect(cfg: ProviderCfg) -> list[str]:
    """current raw model ids (the /models/ link slugs) in page order."""
    soup = fetch_soup(cfg.detector_url)
    ids: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        match = SLUG_RE.fullmatch(anchor["href"])
        if match is None:
            continue
        slug = match.group(1)
        if slug not in seen:
            seen.add(slug)
            ids.append(slug)
    if not ids:
        raise FetchError(f"no model links found on {cfg.detector_url}")
    return ids

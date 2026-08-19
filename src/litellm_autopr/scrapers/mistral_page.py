"""mistral pricing from the inference pricing page.

the page is static; each pricing table sits in a section whose unit line reads
``Prices /M Tokens`` (flagship, third-party-hosted, code sections) or ``Prices as
marked`` (specialized, labs: per-page/per-minute/per-char units, not token-priced).
rows link their model cell to the model-card slug and are matched by exact slug.
cells are USD per 1M tokens in the default static html (the EUR tab is
client-side; the fixture pins the USD variant) -> /1e6. ``Free`` cells and
non-dollar cells (``$4 /1000 Pages``, ``$0.003 /Min``, ``—``) have no token
pricing -> None. the page carries no context window -> max_tokens 0. mode is chat.

note: entry keys use the slug verbatim (``mistral/mistral-medium-3-5-26-04``);
litellm's own newest keys compact the slug (``mistral-medium-2604``) - the human
verifier may rename; no compaction is invented here. the pipeline's in-file
dedup consults ``dedup_keys``, which lists the compacted spellings litellm has
used, so a model already tracked under a compacted key settles without a PR.
"""

import re

from litellm_autopr.config import ProviderCfg
from litellm_autopr.detectors.mistral_page import SLUG_RE
from litellm_autopr.pricing import Pricing
from litellm_autopr.web import FetchError, fetch_soup

_HEADER = ["Model", "Input", "Cached input", "Output"]
_TOKEN_UNIT_LINE = "Prices /M Tokens"
_DOLLAR_CELL = re.compile(r"^\$(\d+(?:\.\d+)?)$")

# slug tail like -4-0-26-03 (one to three version segments, then yy-mm) compacts
# to -2603, the form litellm's keys use for dated models. slugs without a dated
# tail stay verbatim. best-effort: upstream is inconsistent (mistral-medium-3-1-2508
# keeps its version), the raw slug is always checked first.
_DATED_TAIL = re.compile(r"^(.*?)(?:-\d+){1,3}-(\d{2})-(\d{2})$")
_MISTRAL_FAMILIES = (
    "mistral",
    "ministral",
    "pixtral",
    "codestral",
    "devstral",
    "magistral",
    "labs",
)


def _compact(slug: str) -> str:
    match = _DATED_TAIL.match(slug)
    if match is None:
        return slug
    return f"{match.group(1)}-{match.group(2)}{match.group(3)}"


def dedup_keys(namespace: str, model_id: str) -> list[str]:
    """Spellings of this model's key that litellm may already track it under."""
    compacted = _compact(model_id)
    keys = [f"{namespace}/{compacted}"]
    if not compacted.startswith(_MISTRAL_FAMILIES):
        keys.append(f"{namespace}/mistral-{compacted}")
    return keys


def _price(cell: str) -> float | None:
    match = _DOLLAR_CELL.fullmatch(cell)
    if match is None:
        return None
    return float(match.group(1)) / 1e6


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    """Pricing for model_id, or None when the page carries no pricing for it."""
    soup = fetch_soup(cfg.scraper_url)
    found_token_table = False
    for table in soup.find_all("table"):
        if table.find_parent("table") is not None:
            continue
        section = table.find_parent("section")
        if section is None or _TOKEN_UNIT_LINE not in section.get_text(" ", strip=True):
            continue
        rows = table.find_all("tr")
        if not rows:
            continue
        header = [cell.get_text(" ", strip=True) for cell in rows[0].find_all(["th", "td"])]
        if header != _HEADER:
            continue
        found_token_table = True
        for row in rows[1:]:
            cells = row.find_all(["th", "td"])
            if len(cells) < 4:
                continue
            link = cells[0].find("a", href=True)
            if link is None:
                continue
            match = SLUG_RE.fullmatch(link["href"])
            if match is None or match.group(1) != model_id:
                continue
            input_cost = _price(cells[1].get_text(" ", strip=True))
            output_cost = _price(cells[3].get_text(" ", strip=True))
            if input_cost is None or output_cost is None:
                return None
            return Pricing(
                input_cost_per_token=input_cost,
                output_cost_per_token=output_cost,
                mode="chat",
            )
    if not found_token_table:
        raise FetchError(f"no per-token pricing tables found on {cfg.scraper_url}")
    return None

"""detect cohere model ids on the cohere pricing page.

reads https://cohere.com/pricing (static server-rendered html, snapshot
2026-08-24). rate-bearing content comes in two shapes, both parsed:

- the Model Vault table: a css grid whose header row is ``Model |
  Performance Tier | Hourly rate per instance | Monthly rate per
  instance``, one row per model and tier. the id is the slug of
  model+tier joined ("Embed 4" + "Small" -> "embed-4-small"). the rates
  are per instance, never per token, so the rows are detected (new
  models the target's cohere.yml does not track) but scrape to None.
- the legacy-models faq prose: ``<name> pricing is $<input>/1M tokens
  for input and $<output>/1M tokens for output`` sentences ("Command",
  "Command-light", "Command R 03-2024", "Command R+ 04-2024",
  "Command R+ 08-2024").

the slug rule: lowercase, "+" -> "plus" (the target's own spelling of
the R+ family; a bare "+" would fail the entry id charset), then every
non-alphanumeric run (dots kept) collapses to "-", edges trimmed
("Rerank 3.5 Medium" -> "rerank-3.5-medium").

pricing cards without dollar rates (North, Compass, Transcribe,
Command A+, Command R, Command R7B, Embed 4, Rerank 4 Fast/Pro,
North Mini Code) and the Aya research-model faq answer (not a
"pricing is" sentence) are out of scope: an id with no rates would
re-candidate forever without ever scraping.

ids come back in page order: model vault rows first, then faq prose.
dated release spellings of one base id emit newest first (see
_newest_dated_first). a page with neither shape is a parse failure
(FetchError).
"""

import re
from dataclasses import dataclass
from functools import cache

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup

_GRID_MARKER = "grid-template-columns:repeat(4,minmax(150px,1fr))"
_TABLE_HEADER = [
    "Model",
    "Performance Tier",
    "Hourly rate per instance",
    "Monthly rate per instance",
]
_PROSE_RE = re.compile(
    r"^(?P<name>.+?) pricing is \$(?P<input>\d+(?:\.\d+)?)/1M tokens for input"
    r" and \$(?P<output>\d+(?:\.\d+)?)/1M tokens for output$"
)
_AMOUNT_RE = re.compile(r"^\$([\d,]+(?:\.\d+)?)$")
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
_DATED_RELEASE = re.compile(r"^(?P<base>.+)-(?P<month>\d{2})-(?P<year>\d{4})$")


@dataclass(frozen=True)
class _Model:
    """one detected model; rates are per-token dollars, None when the page
    publishes no per-token rate for it (model vault rows)."""

    id: str
    input_cost_per_token: float | None
    output_cost_per_token: float | None


def _slug(name: str) -> str:
    """lowercase-hyphen slug of a page spelling; the new-model entry id."""
    return re.sub(r"[^a-z0-9.]+", "-", name.replace("+", " plus ").lower()).strip("-")


def _grid_cells(div) -> list[str]:
    return [cell.get_text(" ", strip=True) for cell in div.find_all("div", recursive=False)]


def _dollars(text: str) -> float | None:
    match = _AMOUNT_RE.fullmatch(text)
    return float(match.group(1).replace(",", "")) if match else None


def _model_vault_rows(soup, url: str) -> list[_Model]:
    """model vault rows as id-only models; their rates are per instance."""
    grids = [div for div in soup.find_all("div") if _GRID_MARKER in " ".join(div.get("class", []))]
    header_at = next(
        (index for index, div in enumerate(grids) if _grid_cells(div) == _TABLE_HEADER),
        None,
    )
    if header_at is None:
        return []
    rows: list[_Model] = []
    for div in grids[header_at + 1 :]:
        cells = _grid_cells(div)
        if len(cells) != 4:
            raise FetchError(f"malformed model vault row on {url}: {cells!r}")
        if _dollars(cells[2]) is None or _dollars(cells[3]) is None:
            break  # past the rate rows: later 4-column grids are other sections
        model_id = _slug(f"{cells[0]} {cells[1]}")
        if _ID_PATTERN.fullmatch(model_id):
            rows.append(_Model(model_id, None, None))
    return rows


def _prose_models(soup) -> list[_Model]:
    """faq prose rate sentences, per-token dollars, page order."""
    models: list[_Model] = []
    for block in soup.find_all(["li", "p"]):
        if block.find(["li", "p"]) is not None:
            continue  # nested list: only leaf blocks carry one sentence
        match = _PROSE_RE.fullmatch(block.get_text(" ", strip=True))
        if match is None:
            continue
        model_id = _slug(match.group("name"))
        if not _ID_PATTERN.fullmatch(model_id):
            continue
        models.append(
            _Model(
                id=model_id,
                input_cost_per_token=float(match.group("input")) / 1e6,
                output_cost_per_token=float(match.group("output")) / 1e6,
            )
        )
    return models


def _dated_base(model_id: str) -> str | None:
    match = _DATED_RELEASE.match(model_id)
    return match.group("base") if match else None


def _release_date(model: _Model) -> int:
    match = _DATED_RELEASE.match(model.id)
    assert match is not None  # callers pass dated ids only
    return int(match.group("year")) * 100 + int(match.group("month"))


def _newest_dated_first(models: list[_Model]) -> list[_Model]:
    """same-base dated release spellings emit newest first.

    the refresh pass drift-checks the first page id mapping to a tracked
    entry; the target's cohere.yml carries the newest release's rates
    (command-r-plus tracks 2.5/10 = the page's 08-2024 row, measured
    2026-08-24), and an older dated row in the lead would open a false
    drift draft every run.
    """
    ordered: list[_Model] = []
    dated_run: list[_Model] = []
    for model in models:
        base = _dated_base(model.id)
        if dated_run and base != _dated_base(dated_run[0].id):
            ordered.extend(sorted(dated_run, key=_release_date, reverse=True))
            dated_run = []
        if base is None:
            ordered.append(model)
        else:
            dated_run.append(model)
    if dated_run:
        ordered.extend(sorted(dated_run, key=_release_date, reverse=True))
    return ordered


@cache
def _page(url: str) -> tuple[_Model, ...]:
    """fetch and parse both rate shapes; cached per url so the scraper reuses this parse."""
    soup = fetch_soup(url)
    return tuple(_model_vault_rows(soup, url) + _newest_dated_first(_prose_models(soup)))


def detect(cfg: ProviderCfg) -> list[str]:
    """current model ids on the page, model vault rows then faq prose."""
    models = _page(cfg.detector_url)
    if not models:
        raise FetchError(f"no priced models found on {cfg.detector_url}")
    ids: list[str] = []
    seen: set[str] = set()
    for model in models:
        if model.id not in seen:
            seen.add(model.id)
            ids.append(model.id)
    return ids

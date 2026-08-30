"""detect cohere model ids on the cohere pricing page.

reads https://cohere.com/pricing (static server-rendered html, snapshot
2026-08-26). rate-bearing content comes in three shapes, all parsed:

- the model cards: ``pricingGroups`` model entries in the page's
  embedded next.js flight state (``__next_f`` script payloads), one card
  per current model. the card pricings items carry USD per 1M tokens
  ("Input"/"Output" pairs: "Command R" -> command-r at 0.15/0.60,
  "Command R7B" -> command-r7b at 0.0375/0.15; "Embed 4" carries a
  per-token "Cost" plus a per-image "Image cost"). a card seeds when
  both prices are non-negative dollars: free cards (Command A+, North
  Mini Code: API-key/model-download 0/0) seed as zero-rate pairs (free
  is a price). cards without a pricings list (North, Compass,
  Transcribe) and one-sided cards (Rerank 4 Fast/Pro: Cost per 1K
  searches, no output rate) stay excluded.
- the Model Vault table: a css grid whose header row is ``Model |
  Performance Tier | Hourly rate per instance | Monthly rate per
  instance``, one row per model and tier. the id is the slug of
  model+tier joined ("Embed 4" + "Small" -> "embed-4-small"). the rates
  are per instance, never per token, so the rows are detected (new
  models the store does not hold yet) but scrape to None.
- the legacy-models faq prose: ``<name> pricing is $<input>/1M tokens
  for input and $<output>/1M tokens for output`` sentences ("Command",
  "Command-light", "Command R 03-2024", "Command R+ 04-2024",
  "Command R+ 08-2024").

the slug rule: lowercase, "+" -> "plus" (the stored spelling of
the R+ family; a bare "+" would fail the stored id charset), then every
non-alphanumeric run (dots kept) collapses to "-", edges trimmed
("Rerank 3.5 Medium" -> "rerank-3.5-medium").

the Aya research-model faq answer (not a "pricing is" sentence) is out
of scope.

ids come back in page order: model cards, model vault rows, then faq
prose. dated release spellings of one base id emit newest first (see
_newest_dated_first). a page with none of the shapes is a parse failure
(FetchError).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache

from ai_pricelog.config import ProviderCfg
from ai_pricelog.web import FetchError, fetch_soup

_CARD_MARKER = '\\"_type\\":\\"model\\"'
_CARD_NAME_RE = re.compile(r'\\"modelName\\":\\"([^"\\]+)\\"')
_CARD_PRICINGS_RE = re.compile(r'\\"pricings\\":\[([^\]]*)\]')
_CARD_INPUT_RE = re.compile(r'\\"inputLabel\\":\\"([^"\\]*)\\",\\"inputPrice\\":([^,}]+)')
_CARD_OUTPUT_RE = re.compile(r'\\"outputLabel\\":\\"([^"\\]*)\\",\\"outputPrice\\":([^,}]+)')
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


def _card_price(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None  # "null" output on one-sided cards


def _card_model(segment: str, url: str) -> _Model | None:
    """the per-token model for one model-card segment, or None when the card
    carries no usable dollar rates.

    a card seeds when both prices are non-negative dollar amounts; a free
    card (0/0) seeds as a zero-rate pair (free is a price). a card whose
    output rate is not a token rate ("Embed 4"'s "Image cost" is per
    image) prices with output 0, since embedding models bill no output
    tokens (litellm stores cohere/embed-v4.0 as 0.12/1M input, 0 output,
    measured 2026-08-26).
    """
    name_match = _CARD_NAME_RE.search(segment)
    if name_match is None:
        raise FetchError(f"malformed model card on {url}: no modelName")
    model_id = _slug(name_match.group(1))
    if not _ID_PATTERN.fullmatch(model_id):
        return None
    pricings = _CARD_PRICINGS_RE.search(segment)
    if pricings is None:
        return None  # no dollar rates on the card
    input_match = _CARD_INPUT_RE.search(pricings.group(1))
    if input_match is None:
        raise FetchError(f"malformed pricings on model card {model_id} on {url}")
    output_match = _CARD_OUTPUT_RE.search(pricings.group(1))
    if output_match is None:
        # one-sided cards (Rerank 4 Fast/Pro: Cost per 1K searches) carry no output rate
        return None
    input_cost = _card_price(input_match.group(2))
    output_cost = _card_price(output_match.group(2))
    if input_cost is None or output_cost is None or input_cost < 0 or output_cost < 0:
        return None  # negative rates are junk, never a price
    per_token_output = output_cost if output_match.group(1) == "Output" else 0.0
    return _Model(model_id, input_cost / 1e6, per_token_output / 1e6)


def _model_cards(soup, url: str) -> list[_Model]:
    """model cards with per-token rates from the flight state, page order."""
    cards: list[_Model] = []
    for script in soup.find_all("script"):
        text = script.string
        if not text or "__next_f" not in text or _CARD_MARKER not in text:
            continue
        for segment in text.split(_CARD_MARKER)[1:]:
            card = _card_model(segment, url)
            if card is not None:
                cards.append(card)
    return cards


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

    the refresh pass drift-checks the first page id mapping to a stored
    row; the store carries the newest release's rates (command-r-plus
    holds 2.5/10 = the page's 08-2024 row, measured 2026-08-24), and an
    older dated row in the lead would open a false drift row every run.
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
    """fetch and parse all three rate shapes; cached per url so the scraper reuses this parse."""
    soup = fetch_soup(url)
    return tuple(
        _model_cards(soup, url)
        + _model_vault_rows(soup, url)
        + _newest_dated_first(_prose_models(soup))
    )


def detect(cfg: ProviderCfg) -> list[str]:
    """current model ids on the page, model cards then vault rows then faq prose."""
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

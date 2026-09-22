r"""xAI pricing from the docs.x.ai models page blob.

prices live in the same embedded blob the detector reads. the blob price fields are
USD per 1M tokens scaled by 1e4 (20000 -> $2.00/1M, measured 2026-08-19), so a
per-token cost is ``float(field) * 1e-4 / 1e6``. ``cachedPromptTokenPrice``
parses into cache_read_cost_per_token. the long-context tier
(``longContextThreshold`` + the three ``*LongContext`` price fields, measured
2026-09-22 on every language model) rides as one window_rates entry:
``{"min_tokens": threshold, "<axis>_mtok": rate}``, which build_row lands as
a ``when.min_tokens`` override (the openrouter volume-threshold shape).
max_tokens_in comes from ``maxPromptLength``,
the context window (absent -> 0, the entry builder omits it). mode is chat.

the page ids carry dated snapshot spellings (``grok-4.20-0309-non-reasoning``)
for models the store holds under their base id (``grok-4.20``).
``dedup_keys`` normalizes those: strip the ``-\d{4}`` date and the optional
``-(non-)?reasoning`` suffix, check the base. the reasoning strip only applies
after a date strip, so a genuinely new id ending in ``-reasoning`` never
dedups against a base it is not a snapshot of.
"""

from __future__ import annotations

import re

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors.xai_page import _blob, _clusters, _language_models
from ai_pricelog.pricing import Pricing
from ai_pricelog.web import FetchError

_PER_1M_SCALE = 1e-4
_PER_TOKEN = _PER_1M_SCALE / 1e6

_DATED_SNAPSHOT = re.compile(r"^(.*)-\d{4}(?:-(?:non-)?reasoning)?$")


def dedup_keys(model_id: str) -> list[str]:
    """The base id of a dated snapshot spelling, or [] when unchanged."""
    match = _DATED_SNAPSHOT.match(model_id)
    if match is None:
        return []
    base = match.group(1)
    return [] if base == model_id else [base]


def _price(value: object) -> float | None:
    try:
        return float(value) * _PER_TOKEN
    except (TypeError, ValueError):
        return None


def _max_tokens_in(entry: dict) -> int:
    value = entry.get("maxPromptLength")
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


_THRESHOLD_FIELD = "longContextThreshold"
# axis -> the blob's long-context price field; the output field carries no
# "Text", unlike the base field names
_LONG_CONTEXT_FIELDS = {
    "input": "promptTextTokenPriceLongContext",
    "output": "completionTokenPriceLongContext",
    "cache_read": "cachedPromptTokenPriceLongContext",
}


def _mtok(value: object) -> float | None:
    """A blob price field as USD per 1M tokens; every unreadable shape is None."""
    try:
        return round(float(value) * _PER_1M_SCALE, 6)
    except (TypeError, ValueError):
        return None


def _long_context_override(entry: dict, model_id: str) -> dict[str, object] | None:
    """The entry's long-context tier as a window_rates entry, or None.

    Any of the tier's fields present requires the threshold plus the input
    and output rates; a missing cache-read rate inherits the base rate (the
    override semantics). An unreadable tier on the chosen entry raises
    (plan #22): silently dropping it would omit a rate the page carries and
    re-fire a duplicate row against every review-corrected stored row.
    """
    values = {axis: entry.get(field) for axis, field in _LONG_CONTEXT_FIELDS.items()}
    threshold = entry.get(_THRESHOLD_FIELD)
    if threshold is None and all(value is None for value in values.values()):
        return None
    try:
        min_tokens = int(threshold)
    except (TypeError, ValueError) as exc:
        raise FetchError(
            f"model {model_id!r}: unreadable {_THRESHOLD_FIELD} {threshold!r}"
        ) from exc
    if min_tokens <= 0:
        raise FetchError(f"model {model_id!r}: {_THRESHOLD_FIELD} must be > 0, got {min_tokens}")
    rates: dict[str, float] = {}
    for axis in ("input", "output"):
        mtok = _mtok(values[axis])
        if mtok is None:
            raise FetchError(
                f"model {model_id!r}: long-context tier without a readable {axis} rate"
                f" ({values[axis]!r})"
            )
        rates[f"{axis}_mtok"] = mtok
    if values["cache_read"] is not None:
        cache_mtok = _mtok(values["cache_read"])
        if cache_mtok is None:
            raise FetchError(
                f"model {model_id!r}: unreadable long-context cache_read rate"
                f" ({values['cache_read']!r})"
            )
        rates["cache_read_mtok"] = cache_mtok
    return {"min_tokens": min_tokens, **rates}


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    """Pricing for model_id, or None when the page carries no pricing for it."""
    blob = _blob(cfg.scraper_url)
    for cluster in _clusters(blob, cfg.scraper_url):
        try:
            entries = _language_models(cluster, cfg.scraper_url)
        except FetchError:
            continue  # additive drift; detect already reported the cluster
        for entry in entries:
            if entry["name"] != model_id:
                continue
            if "promptTextTokenPrice" not in entry or "completionTextTokenPrice" not in entry:
                return None
            input_cost = _price(entry["promptTextTokenPrice"])
            output_cost = _price(entry["completionTextTokenPrice"])
            if input_cost is None or output_cost is None:
                return None
            override = _long_context_override(entry, model_id)
            return Pricing(
                input_cost_per_token=input_cost,
                output_cost_per_token=output_cost,
                mode="chat",
                max_tokens_in=_max_tokens_in(entry),
                cache_read_cost_per_token=_price(entry.get("cachedPromptTokenPrice")),
                window_rates=(override,) if override is not None else (),
            )
    return None

"""Entry sanity checks that run before yml emission.

Only what our own emission could corrupt before the clone ever sees it: the
model id charset (it lands verbatim in yml ids and match clauses, and inside
rebuilt regex patterns), the price values, and the context window. The target
clone's `make build` is the authority for everything else (schema, unit
registry, match overlap, sort order, generated data); an entry that passes
here and fails there skips the candidate and retries next run.
"""

import math
import re

from autopr_genai_prices.pricing import Pricing

_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,99}$")


class ValidationError(ValueError):
    """an entry failed validation; the message names the field, bad value, fix."""


def validate_entry(model_id: str, pricing: Pricing) -> None:
    if not _ID_PATTERN.fullmatch(model_id):
        raise ValidationError(
            f"model id {model_id!r}: must be 1-100 chars of [a-zA-Z0-9._:/-] "
            "starting alphanumeric (it lands verbatim in yml ids and match "
            "clauses); fix: check the detector output"
        )
    for field in ("input_cost_per_token", "output_cost_per_token"):
        value = getattr(pricing, field)
        if (
            isinstance(value, bool)
            or not isinstance(value, float)
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValidationError(
                f"pricing field '{field}' has bad value {value!r}; fix: use a finite float > 0"
            )
    for field in (
        "cache_read_cost_per_token",
        "peak_input_cost_per_token",
        "peak_output_cost_per_token",
    ):
        value = getattr(pricing, field)
        if value is None:
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, float)
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValidationError(
                f"pricing field '{field}' has bad value {value!r}; fix: use a finite float > 0"
            )
    if pricing.max_tokens:
        value = pricing.max_tokens
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValidationError(
                f"pricing field 'max_tokens' has bad value {value!r}; fix: use an int > 0"
            )

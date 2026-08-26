from dataclasses import dataclass


@dataclass(frozen=True)
class Pricing:
    input_cost_per_token: float
    output_cost_per_token: float
    mode: str
    max_tokens: int = 0
    cache_read_cost_per_token: float | None = None
    peak_input_cost_per_token: float | None = None
    peak_output_cost_per_token: float | None = None
    peak_windows: tuple[tuple[str, str], ...] = ()
    peak_cache_read_cost_per_token: float | None = None


def to_mtok(per_token: float) -> float:
    """Per-token dollars -> per-megatoken dollars, rounded to 6 decimals."""
    return round(per_token * 1_000_000, 6)

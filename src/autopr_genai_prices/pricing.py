from dataclasses import dataclass


@dataclass(frozen=True)
class Pricing:
    input_cost_per_token: float
    output_cost_per_token: float
    mode: str
    max_tokens: int = 0
    peak_input_cost_per_token: float | None = None
    peak_output_cost_per_token: float | None = None
    peak_windows: tuple[tuple[str, str], ...] = ()

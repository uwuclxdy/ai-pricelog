"""scrape doubao pricing from the volcengine model plaza page.

dormant: volcengine is disabled in providers.toml while pricing exists only
as CNY on the CN plaza (2026-08-19); re-enable when a USD source appears and
drop the pinned-rate conversion then.

one card per model; the card text carries "输入价格 6 元/百万 tokens" and
"输出价格 30 元/百万 tokens" (CNY per 1M tokens). reasoning cards
(doubao-seed-2-0-lite/mini) carry "推理输入" / "推理输出" instead and quote
ranges: the reasoning labels stand in for input/output and the LOW bound of
the range is used. CNY is converted to USD at the pinned rate CNY_PER_USD
(update the constant when the rate drifts; litellm's own volcengine entries
carry no costs, so the conversion policy lives in this module only).
max_tokens comes from the card's 最大输出 label, falling back to 上下文窗口
(values like "256k" / "128k", K * 1024); cards without either label yield 0.

None = the model id is not on the page or its card carries no parseable
price (skip-and-retry). FetchError = the fetch failed, or the page text
carries no doubao-seed id at all (page redesigned).
"""

import re

from litellm_autopr.config import ProviderCfg
from litellm_autopr.detectors.volcengine_page import _page
from litellm_autopr.pricing import Pricing
from litellm_autopr.web import FetchError

CNY_PER_USD = 7.2
_WINDOW_CHARS = 400

_ID_RE = re.compile(r"doubao-seed(?!ream|ance)[a-z0-9.-]+")
_INPUT_LABELS = ("输入价格", "推理输入")
_OUTPUT_LABELS = ("输出价格", "推理输出")
_PRICE_LABELS = _INPUT_LABELS + _OUTPUT_LABELS
_WINDOW_LABELS = ("最大输出", "上下文窗口")
_ALL_LABELS = _PRICE_LABELS + _WINDOW_LABELS
_VALUE_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)(?:\s*-\s*[0-9]+(?:\.[0-9]+)?)?\s*元\s*/\s*百万")
_K_RE = re.compile(r"(\d+(?:\.\d+)?)\s*k\b", re.IGNORECASE)


def scrape(cfg: ProviderCfg, model_id: str) -> Pricing | None:
    text = _page(cfg.scraper_url)
    matches = list(_ID_RE.finditer(text))
    if not matches:
        raise FetchError(f"no doubao-seed model ids found on {cfg.scraper_url}")
    start = next((match.end() for match in matches if match.group() == model_id), None)
    if start is None:
        return None
    window = text[start : _window_end(text, start, matches)]
    input_price = _price_after(window, _INPUT_LABELS)
    output_price = _price_after(window, _OUTPUT_LABELS)
    if input_price is None or output_price is None:
        return None
    return Pricing(
        input_cost_per_token=input_price / 1e6 / CNY_PER_USD,
        output_cost_per_token=output_price / 1e6 / CNY_PER_USD,
        mode="chat",
        max_tokens=_max_tokens(window),
    )


def _window_end(text: str, start: int, matches: list[re.Match]) -> int:
    """bound the card window at the next card's start: the next id match, or
    the copy button after the id's own one (covers the last doubao card,
    whose neighbor ids don't match the detection regex), capped at
    _WINDOW_CHARS."""
    end = start + _WINDOW_CHARS
    for match in matches:
        if match.start() > start:
            end = min(end, match.start())
            break
    own_copy = text.find("复制", start, end)
    if own_copy != -1:
        next_copy = text.find("复制", own_copy + 2, end)
        if next_copy != -1:
            end = min(end, next_copy)
    return end


def _price_after(window: str, labels: tuple[str, ...]) -> float | None:
    """the value right after the first label occurrence in the window, or
    None. the value search stops at the next label, so a card with a
    missing value cannot pick up the following label's value."""
    found = []
    for label in labels:
        pos = window.find(label)
        if pos != -1:
            found.append((pos, label))
    if not found:
        return None
    pos, label = min(found)
    span_start = pos + len(label)
    next_label = [window.find(other, span_start) for other in _ALL_LABELS]
    next_label = [pos for pos in next_label if pos != -1]
    span_end = min(next_label) if next_label else len(window)
    match = _VALUE_RE.search(window[span_start:span_end])
    return float(match.group(1)) if match else None


def _max_tokens(window: str) -> int:
    """the K value after the card's 最大输出 label, falling back to
    上下文窗口; 0 when neither carries a parseable K value. the value
    search stops at the next label so a missing value cannot pick up the
    following label's value."""
    for label in _WINDOW_LABELS:
        pos = window.find(label)
        if pos == -1:
            continue
        span_start = pos + len(label)
        next_label = [window.find(other, span_start) for other in _ALL_LABELS]
        next_label = [pos for pos in next_label if pos != -1]
        span_end = min(next_label) if next_label else len(window)
        match = _K_RE.search(window[span_start:span_end])
        if match:
            return int(float(match.group(1))) * 1024
    return 0

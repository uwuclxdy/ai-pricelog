"""anthropic pricing pair tests, pinned against the saved live page."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import anthropic_page as detector
from ai_pricelog.scrapers import anthropic_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://platform.claude.com/docs/en/about-claude/pricing.md"
FIXTURE = Path(__file__).parent / "fixtures" / "anthropic_page" / "pricing.md"

EXPECTED_IDS = [
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-opus-4-5",
    "claude-opus-4-1",
    "claude-opus-4",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5",
    "claude-sonnet-4",
    "claude-haiku-4-5",
    "claude-haiku-3-5",
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="anthropic",
        provider="Anthropic",
        detector="anthropic_page",
        detector_url=PAGE_URL,
        scraper="anthropic_page",
        scraper_url=PAGE_URL,
    )


def feed(monkeypatch: pytest.MonkeyPatch, text: str | None = None) -> None:
    monkeypatch.setattr(detector, "fetch_text", lambda url: text or FIXTURE.read_text())
    monkeypatch.setattr(scraper, "fetch_text", lambda url: text or FIXTURE.read_text())


def test_detect_ids(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch)
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_scrape_opus_5(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch)
    pricing = scraper.scrape(cfg(), "claude-opus-5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(5 / 1e6)
    assert pricing.cache_write_cost_per_token == pytest.approx(6.25 / 1e6)
    assert pricing.cache_write_1h_cost_per_token == pytest.approx(10 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.5 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(25 / 1e6)
    assert pricing.mode == "chat"


def test_scrape_haiku_3_5(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch)
    pricing = scraper.scrape(cfg(), "claude-haiku-3-5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.80 / 1e6)
    assert pricing.cache_write_cost_per_token == pytest.approx(1 / 1e6)
    assert pricing.cache_write_1h_cost_per_token == pytest.approx(1.60 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.08 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(4 / 1e6)


def test_scrape_unknown_model_returns_none(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch)
    assert scraper.scrape(cfg(), "claude-opus-3") is None


_TABLE = (
    "| Model | Base Input Tokens | 5m Cache Writes | 1h Cache Writes"
    " | Cache Hits & Refreshes | Output Tokens |\n"
    "| --- | --- | --- | --- | --- | --- |\n"
    "| Claude Opus 5 (Fast) | $5 / MTok | $6.25 / MTok | $10 / MTok"
    " | $0.50 / MTok | $25 / MTok |\n"
    "| Claude Sonnet 5 ([intro through 2026-08-31](https://x)) | $2 / MTok"
    " | $2.50 / MTok | $4 / MTok | $0.20 / MTok | $10 / MTok |\n"
)


def test_paren_without_link_is_part_of_the_name(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch, _TABLE)
    assert detector.detect(cfg()) == ["claude-opus-5-fast", "claude-sonnet-5"]
    pricing = scraper.scrape(cfg(), "claude-opus-5-fast")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(5 / 1e6)


def test_detect_row_outside_shape_raises(monkeypatch: pytest.MonkeyPatch):
    short_row_table = _TABLE + "| Claude Opus 4 | $3 / MTok |\n"
    feed(monkeypatch, short_row_table)
    with pytest.raises(FetchError, match="outside the pricing shape"):
        detector.detect(cfg())


def test_detect_annotation_only_name_raises(monkeypatch: pytest.MonkeyPatch):
    # a cell that is only a link annotation strips to no id; emitting an
    # empty id is worse than failing the run
    annotation_only = (
        "| Model | Base Input Tokens | 5m Cache Writes | 1h Cache Writes"
        " | Cache Hits & Refreshes | Output Tokens |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| ([retired](https://x)) | $1 / MTok | $1 / MTok | $1 / MTok"
        " | $1 / MTok | $1 / MTok |\n"
    )
    feed(monkeypatch, annotation_only)
    with pytest.raises(FetchError, match="unreadable model name"):
        detector.detect(cfg())


def test_detect_missing_model_table_raises(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch, "| Concept | Details |\n| --- | --- |\n| a | b |\n")
    with pytest.raises(FetchError, match="model pricing table"):
        detector.detect(cfg())


def test_scrape_missing_model_table_raises(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch, "no tables at all here")
    with pytest.raises(FetchError, match="model pricing table"):
        scraper.scrape(cfg(), "claude-opus-5")


def test_scrape_unreadable_rate_raises(monkeypatch: pytest.MonkeyPatch):
    broken = _TABLE.replace("$6.25 / MTok", "included", 1)
    feed(monkeypatch, broken)
    with pytest.raises(FetchError, match="unreadable rate"):
        scraper.scrape(cfg(), "claude-opus-5-fast")

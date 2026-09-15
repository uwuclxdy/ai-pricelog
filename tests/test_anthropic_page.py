"""anthropic pricing pair tests, pinned against the saved live page."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import anthropic_page as detector
from ai_pricelog.pricing import Pricing
from ai_pricelog.scrapers import anthropic_page as scraper
from ai_pricelog.store import build_row
from ai_pricelog.web import FetchError

PAGE_URL = "https://platform.claude.com/docs/en/about-claude/pricing.md"
FIXTURE = Path(__file__).parent / "fixtures" / "anthropic_page" / "pricing.md"

EXPECTED_IDS = [
    "claude-fable-5-1",
    "claude-mythos-5-1",
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


def test_scrape_fable_5_1(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch)
    pricing = scraper.scrape(cfg(), "claude-fable-5-1")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(10 / 1e6)
    assert pricing.cache_write_cost_per_token == pytest.approx(12.5 / 1e6)
    assert pricing.cache_write_1h_cost_per_token == pytest.approx(20 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.25 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(50 / 1e6)


def test_header_wording_drift_still_matches(monkeypatch: pytest.MonkeyPatch):
    drifted = (
        "| Model | base input tokens | 5M CACHE WRITES | 1h cache writes"
        " | cache hits and refreshes | output tokens |\n"
    )
    feed(monkeypatch, drifted + "\n".join(_TABLE.splitlines()[1:]))
    assert detector.detect(cfg()) == ["claude-opus-5-fast", "claude-sonnet-5"]


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


def test_detect_row_outside_shape_skips(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    short_row_table = _TABLE + "| Claude Opus 4 | $3 / MTok |\n"
    feed(monkeypatch, short_row_table)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["claude-opus-5-fast", "claude-sonnet-5"]
    assert "detect skip for anthropic" in caplog.text


def test_detect_annotation_only_name_skips(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # a cell that is only a link annotation strips to no id: additive
    # drift, skipped with a warning; with no readable rows left the
    # detector raises the structural error
    annotation_only = (
        "| Model | Base Input Tokens | 5m Cache Writes | 1h Cache Writes"
        " | Cache Hits & Refreshes | Output Tokens |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| ([retired](https://x)) | $1 / MTok | $1 / MTok | $1 / MTok"
        " | $1 / MTok | $1 / MTok |\n"
    )
    feed(monkeypatch, annotation_only)
    with caplog.at_level(logging.WARNING), pytest.raises(FetchError, match="no model rows"):
        detector.detect(cfg())
    assert "unreadable model name" in caplog.text


def test_detect_annotation_only_name_skips_that_row(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    annotation_row = (
        "| ([retired](https://x)) | $1 / MTok | $1 / MTok | $1 / MTok | $1 / MTok | $1 / MTok |\n"
    )
    feed(monkeypatch, _TABLE + annotation_row)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["claude-opus-5-fast", "claude-sonnet-5"]
    assert "unreadable model name" in caplog.text


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


# the fast-mode table as the page carries it: header, separator, the one
# row whose cell joins the two covered names
_FAST_TABLE = (
    "| Model                           | Input      | Output     |\n"
    "| ------------------------------- | ---------- | ---------- |\n"
    "| Claude Opus 5 / Claude Opus 4.8 | $10 / MTok | $50 / MTok |\n"
)


@pytest.mark.parametrize("model_id", ["claude-opus-5", "claude-opus-4-8"])
def test_scrape_attaches_fast_mode_entry(monkeypatch: pytest.MonkeyPatch, model_id: str):
    feed(monkeypatch)
    pricing = scraper.scrape(cfg(), model_id)
    assert pricing is not None
    assert pricing.window_rates == ({"mode": "fast", "input_mtok": 10.0, "output_mtok": 50.0},)


def test_scrape_other_model_carries_no_fast_entry(monkeypatch: pytest.MonkeyPatch):
    # fast mode covers the two opus models only; the others keep the bare row
    feed(monkeypatch)
    pricing = scraper.scrape(cfg(), "claude-sonnet-5")
    assert pricing is not None
    assert pricing.window_rates == ()


def test_fast_table_absent_is_additive_drift(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    fixture = FIXTURE.read_text()
    stripped = fixture.replace(_FAST_TABLE, "")
    assert stripped != fixture, "the fixture's fast table changed shape"
    feed(monkeypatch, stripped)
    with caplog.at_level(logging.WARNING):
        pricing = scraper.scrape(cfg(), "claude-opus-5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(5 / 1e6)
    assert pricing.window_rates == ()
    assert "fast-mode pricing table absent" in caplog.text


def test_fast_table_unreadable_rate_raises(monkeypatch: pytest.MonkeyPatch):
    broken = _FAST_TABLE.replace("$10 / MTok", "premium", 1)
    fixture = FIXTURE.read_text().replace(_FAST_TABLE, broken)
    feed(monkeypatch, fixture)
    with pytest.raises(FetchError, match="unreadable rate"):
        scraper.scrape(cfg(), "claude-opus-5")


def test_fast_table_row_outside_shape_raises(monkeypatch: pytest.MonkeyPatch):
    broken = _FAST_TABLE + "| Claude Opus 4.6 | $1 |\n"
    fixture = FIXTURE.read_text().replace(_FAST_TABLE, broken)
    feed(monkeypatch, fixture)
    with pytest.raises(FetchError, match="fast-mode shape"):
        scraper.scrape(cfg(), "claude-opus-5")


def test_fast_table_row_with_one_unknown_name_still_applies(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # the row covers both names it joins, so one match applies it even when
    # the other name sits in no model-table row
    drifted = _FAST_TABLE.replace(
        "Claude Opus 5 / Claude Opus 4.8", "Claude Opus 5 / Claude Cybertruck"
    )
    fixture = FIXTURE.read_text().replace(_FAST_TABLE, drifted)
    feed(monkeypatch, fixture)
    with caplog.at_level(logging.WARNING):
        pricing = scraper.scrape(cfg(), "claude-opus-5")
    assert pricing is not None
    assert pricing.window_rates == ({"mode": "fast", "input_mtok": 10.0, "output_mtok": 50.0},)
    assert "names no model" not in caplog.text


def test_fast_table_row_naming_no_known_model_skips(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # a row whose every name sits in no model-table row is drift: the
    # requested model still prices at its base rates, with no entry
    drifted = _FAST_TABLE.replace(
        "Claude Opus 5 / Claude Opus 4.8", "Claude Cybertruck / Claude Semi"
    )
    fixture = FIXTURE.read_text().replace(_FAST_TABLE, drifted)
    feed(monkeypatch, fixture)
    with caplog.at_level(logging.WARNING):
        pricing = scraper.scrape(cfg(), "claude-opus-5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(5 / 1e6)
    assert pricing.window_rates == ()
    assert "names no model in the pricing table" in caplog.text


def test_build_row_copies_the_mode_into_the_overrides_when():
    """The full-row contract: the fast entry lands as one override whose
    `when` keys on the request mode and whose rates carry the page's amounts.

    Lands the build_row expectation: store.build_row copies the entry's
    `mode` into the override's `when` beside the days/window keys. until that
    copy line exists the entry builds condition-less (or not at all), and
    this test reds.
    """
    pricing = Pricing(
        input_cost_per_token=5 / 1e6,
        output_cost_per_token=25 / 1e6,
        mode="chat",
        cache_read_cost_per_token=0.5 / 1e6,
        cache_write_cost_per_token=6.25 / 1e6,
        cache_write_1h_cost_per_token=10 / 1e6,
        window_rates=({"mode": "fast", "input_mtok": 10.0, "output_mtok": 50.0},),
    )
    row = build_row(
        source="anthropic",
        model_id="claude-opus-5",
        pricing=pricing,
        observed_at="2026-09-14",
        url=PAGE_URL,
        schema_version=4,
    )
    assert row["overrides"] == [
        {"when": {"mode": "fast"}, "rates": {"input": 10.0, "output": 50.0}}
    ]

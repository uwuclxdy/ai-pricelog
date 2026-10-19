"""anthropic pricing pair tests, pinned against the saved live page.

the fixture is the 2026-10-14 capture of the pricing markdown twin: Claude
Haiku 5.5 prices by prompt length in two model-table rows ("(for prompts up
to 100,000 tokens)" / "(for prompts over 100,000 tokens)"), and the fast-mode
table covers Claude Opus 5.5 on its own row.
"""

from __future__ import annotations

import contextlib
import logging
import time
import traceback
from pathlib import Path

import pytest

from ai_pricelog import health
from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import anthropic_page as detector
from ai_pricelog.pricing import Pricing
from ai_pricelog.scrapers import anthropic_page as scraper
from ai_pricelog.store import build_row
from ai_pricelog.web import FetchError

PAGE_URL = "https://platform.claude.com/docs/en/about-claude/pricing.md"
FIXTURE = Path(__file__).parent / "fixtures" / "anthropic_page" / "pricing.md"

# the model table's rows in page order; the two Haiku 5.5 prompt-length
# rows are one model, so its id appears once, where its first row sits
EXPECTED_IDS = [
    "claude-fable-5-1",
    "claude-mythos-5-1",
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-opus-4-5",
    "claude-opus-4-1",
    "claude-opus-4",
    "claude-sonnet-5-5",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5",
    "claude-sonnet-4",
    "claude-haiku-5-5",
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


# Haiku 5.5's prompt-length pair as the 2026-10-14 page carries it: one model
# billed at the second row's prices once a request's prompt passes the
# threshold (the page's "Long context pricing" section)
_HAIKU_TIER_ROWS = (
    "| Claude Haiku 5.5 (for prompts up to 100,000 tokens) | $0.10 / MTok | $0.125 / MTok"
    " | $0.20 / MTok | $0.01 / MTok | $0.50 / MTok |\n"
    "| Claude Haiku 5.5 (for prompts over 100,000 tokens) | $0.50 / MTok | $0.625 / MTok"
    " | $1 / MTok | $0.05 / MTok | $2.50 / MTok |\n"
)

# the over-threshold row as a window_rates entry: build_row lands it as one
# `when.min_tokens` override, the shape openrouter's own
# anthropic/claude-haiku-5.5 row carries (min_prompt_tokens 100000)
_HAIKU_TIER_ENTRY = {
    "min_tokens": 100000,
    "input_mtok": 0.5,
    "output_mtok": 2.5,
    "cache_read_mtok": 0.05,
    "cache_write_mtok": 0.625,
    "cache_write_1h_mtok": 1.0,
}


def test_detect_folds_the_prompt_length_rows_into_one_id(monkeypatch: pytest.MonkeyPatch):
    # PR 460 stored each tier row as its own model
    # (claude-haiku-5-5-for-prompts-up-to-100-000-tokens and its "over" twin);
    # the qualifier names a price tier of one model, never a model
    feed(monkeypatch)
    ids = detector.detect(cfg())
    assert ids.count("claude-haiku-5-5") == 1
    assert [model_id for model_id in ids if "for-prompts" in model_id] == []


def test_scrape_haiku_5_5_prices_the_prompt_length_tier(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch)
    pricing = scraper.scrape(cfg(), "claude-haiku-5-5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.10 / 1e6)
    assert pricing.cache_write_cost_per_token == pytest.approx(0.125 / 1e6)
    assert pricing.cache_write_1h_cost_per_token == pytest.approx(0.20 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.01 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.50 / 1e6)
    assert pricing.window_rates == (_HAIKU_TIER_ENTRY,)


def test_scrape_untiered_model_carries_no_tier_entry(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch)
    pricing = scraper.scrape(cfg(), "claude-haiku-4-5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1 / 1e6)
    assert pricing.window_rates == ()


def test_scrape_tier_order_on_the_page_does_not_matter(monkeypatch: pytest.MonkeyPatch):
    # the base rates are the "up to" row's wherever it sits; reading the
    # first matching row would price every request at the long-prompt tier
    up_to, over = _HAIKU_TIER_ROWS.splitlines(keepends=True)
    feed(monkeypatch, _TABLE + over + up_to)
    pricing = scraper.scrape(cfg(), "claude-haiku-5-5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.10 / 1e6)
    assert pricing.window_rates == (_HAIKU_TIER_ENTRY,)


@pytest.mark.parametrize(
    "rows",
    [
        # the "over" partner is gone: the tier's prices would silently drop
        _HAIKU_TIER_ROWS.splitlines(keepends=True)[0],
        # the "up to" partner is gone: no base rates to read
        _HAIKU_TIER_ROWS.splitlines(keepends=True)[1],
        # the two rows disagree on the threshold
        _HAIKU_TIER_ROWS.replace("over 100,000", "over 200,000"),
    ],
    ids=["no-over-row", "no-up-to-row", "mismatched-threshold"],
)
def test_scrape_incomplete_prompt_length_pair_raises(monkeypatch: pytest.MonkeyPatch, rows: str):
    feed(monkeypatch, _TABLE + rows)
    with pytest.raises(FetchError, match="prompt-length tier rows"):
        scraper.scrape(cfg(), "claude-haiku-5-5")


def test_scrape_link_annotated_tier_rows_still_pair(monkeypatch: pytest.MonkeyPatch):
    # a trailing link annotation after the tier qualifier (the page's
    # retirement note) must not stop the two rows from pairing
    note = " ([retired, except on Google Cloud](https://x))"
    up_to = (
        "| Claude Mythos 6 (for prompts up to 100,000 tokens)"
        + note
        + " | $0.10 / MTok | $0.125 / MTok | $0.20 / MTok | $0.01 / MTok | $0.50 / MTok |\n"
    )
    over = (
        "| Claude Mythos 6 (for prompts over 100,000 tokens)"
        + note
        + " | $0.50 / MTok | $0.625 / MTok | $1 / MTok | $0.05 / MTok | $2.50 / MTok |\n"
    )
    feed(monkeypatch, _TABLE + up_to + over)
    assert detector.detect(cfg()).count("claude-mythos-6") == 1
    pricing = scraper.scrape(cfg(), "claude-mythos-6")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.10 / 1e6)
    assert pricing.window_rates == (_HAIKU_TIER_ENTRY,)


def test_scrape_link_before_tier_still_folds(monkeypatch: pytest.MonkeyPatch):
    # a link annotation placed BEFORE the tier qualifier must not leak into
    # the id: the qualifier drops first, then the annotation, so the pair
    # still folds into one id with the tier
    note = " ([limited availability](https://x))"
    up_to = (
        "| Claude Haiku 5.5" + note + " (for prompts up to 100,000 tokens)"
        " | $0.10 / MTok | $0.125 / MTok | $0.20 / MTok | $0.01 / MTok | $0.50 / MTok |\n"
    )
    over = (
        "| Claude Haiku 5.5" + note + " (for prompts over 100,000 tokens)"
        " | $0.50 / MTok | $0.625 / MTok | $1 / MTok | $0.05 / MTok | $2.50 / MTok |\n"
    )
    feed(monkeypatch, _TABLE + up_to + over)
    ids = detector.detect(cfg())
    assert ids.count("claude-haiku-5-5") == 1
    assert [model_id for model_id in ids if "limited-availability" in model_id] == []
    pricing = scraper.scrape(cfg(), "claude-haiku-5-5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.10 / 1e6)
    assert pricing.window_rates == (_HAIKU_TIER_ENTRY,)


def test_scrape_more_than_one_untiered_row_raises(monkeypatch: pytest.MonkeyPatch):
    # two untiered rows folding into one id are an ambiguous page
    noted = (
        "| Claude Haiku 5.5 ([note](https://x)) | $0.10 / MTok | $0.125 / MTok"
        " | $0.20 / MTok | $0.01 / MTok | $0.50 / MTok |\n"
    )
    plain = (
        "| Claude Haiku 5.5 | $0.50 / MTok | $0.625 / MTok | $1 / MTok"
        " | $0.05 / MTok | $2.50 / MTok |\n"
    )
    feed(monkeypatch, _TABLE + noted + plain)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-haiku-5-5")
    assert str(exc.value) == (
        f"more than one untiered row for 'claude-haiku-5-5' on {PAGE_URL}: "
        "['Claude Haiku 5.5 ([note](https://x))', 'Claude Haiku 5.5']; "
        "fix: teach the anthropic scraper which row prices the model"
    )


def test_drifted_tier_wording_still_folds(monkeypatch: pytest.MonkeyPatch):
    # case, NBSP, a K suffix and "input tokens" all keep the tier readable
    up_to = (
        "| Claude Haiku 5.5 (For prompts up to 100K tokens) | $0.10 / MTok | $0.125 / MTok"
        " | $0.20 / MTok | $0.01 / MTok | $0.50 / MTok |\n"
    )
    over = (
        "| Claude Haiku 5.5 (for prompts over 100K\xa0input tokens) | $0.50 / MTok"
        " | $0.625 / MTok | $1 / MTok | $0.05 / MTok | $2.50 / MTok |\n"
    )
    feed(monkeypatch, _TABLE + up_to + over)
    ids = detector.detect(cfg())
    assert ids.count("claude-haiku-5-5") == 1
    assert [model_id for model_id in ids if "for-prompts" in model_id] == []
    pricing = scraper.scrape(cfg(), "claude-haiku-5-5")
    assert pricing is not None
    assert pricing.window_rates == (_HAIKU_TIER_ENTRY,)


def test_detect_unreadable_sibling_qualifier_skips(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # a link-less paren other than "(Fast)" is a qualifier the name parse
    # does not read, so neither row may slug into an id (PR 460's fake-id
    # shape): each row skips on its own and its model's scrape fails loudly
    standard = (
        "| Claude Mythos 6 (standard) | $1 / MTok | $1.25 / MTok | $2 / MTok"
        " | $0.10 / MTok | $5 / MTok |\n"
    )
    premium = (
        "| Claude Mythos 6 (premium) | $2 / MTok | $2.50 / MTok | $4 / MTok"
        " | $0.20 / MTok | $10 / MTok |\n"
    )
    feed(monkeypatch, _TABLE + standard + premium)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["claude-opus-5-fast", "claude-sonnet-5"]
    assert caplog.messages == [
        f"detect skip for anthropic: {_name_error('Claude Mythos 6 (standard)')}",
        f"detect skip for anthropic: {_name_error('Claude Mythos 6 (premium)')}",
    ]
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-mythos-6")
    assert str(exc.value) == _name_error("Claude Mythos 6 (standard)")


def test_detect_fast_sku_beside_base_emits_both(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    fixture = FIXTURE.read_text()
    fast_row = (
        "| Claude Opus 5 (Fast) | $10 / MTok | $12.50 / MTok | $20 / MTok"
        " | $1 / MTok | $50 / MTok |\n"
    )
    with_fast = fixture.replace("| Claude Opus 5 ", fast_row + "| Claude Opus 5 ", 1)
    assert with_fast != fixture
    feed(monkeypatch, with_fast)
    with caplog.at_level(logging.WARNING):
        ids = detector.detect(cfg())
    assert "claude-opus-5" in ids
    assert "claude-opus-5-fast" in ids


def test_scrape_tier_beside_untiered_row_raises(monkeypatch: pytest.MonkeyPatch):
    # a full pair beside an untiered row for the id is an ambiguous page
    untiered = (
        "| Claude Haiku 5.5 | $0.10 / MTok | $0.125 / MTok | $0.20 / MTok"
        " | $0.01 / MTok | $0.50 / MTok |\n"
    )
    feed(monkeypatch, _TABLE + _HAIKU_TIER_ROWS + untiered)
    with pytest.raises(FetchError, match="prompt-length tier rows"):
        scraper.scrape(cfg(), "claude-haiku-5-5")


def test_scrape_duplicate_tier_row_raises(monkeypatch: pytest.MonkeyPatch):
    up_to, over = _HAIKU_TIER_ROWS.splitlines(keepends=True)
    feed(monkeypatch, _TABLE + up_to + up_to + over)
    with pytest.raises(FetchError, match="prompt-length tier rows"):
        scraper.scrape(cfg(), "claude-haiku-5-5")


def test_scrape_duplicate_over_row_raises(monkeypatch: pytest.MonkeyPatch):
    # a duplicate "over" row beside the real one is an ambiguous tier set
    up_to, over = _HAIKU_TIER_ROWS.splitlines(keepends=True)
    duplicate = over.replace("$0.50 / MTok | $0.625 / MTok", "$0.70 / MTok | $0.875 / MTok")
    feed(monkeypatch, _TABLE + up_to + duplicate + over)
    with pytest.raises(FetchError, match="prompt-length tier rows"):
        scraper.scrape(cfg(), "claude-haiku-5-5")


def test_scrape_comma_only_threshold_raises(monkeypatch: pytest.MonkeyPatch):
    comma = (
        "| Claude Haiku 5.5 (for prompts over , tokens) | $0.50 / MTok | $0.625 / MTok"
        " | $1 / MTok | $0.05 / MTok | $2.50 / MTok |\n"
    )
    feed(monkeypatch, _TABLE + comma)
    with pytest.raises(FetchError, match="unreadable prompt-length tier threshold"):
        scraper.scrape(cfg(), "claude-haiku-5-5")


@pytest.mark.parametrize("token", ["100,000²", "1,00", "0.1M", "１００,０００"])
def test_scrape_unreadable_threshold_spelling_raises(monkeypatch: pytest.MonkeyPatch, token: str):
    # the threshold takes ASCII digits in proper thousands grouping only;
    # a superscript digit, a broken grouping, or a decimal-with-suffix must
    # raise FetchError (never ValueError), naming the token and the fix
    up_to = _HAIKU_TIER_ROWS.splitlines(keepends=True)[0]
    over = _HAIKU_TIER_ROWS.splitlines(keepends=True)[1].replace("over 100,000", f"over {token}", 1)
    feed(monkeypatch, _TABLE + up_to + over)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-haiku-5-5")
    assert str(exc.value) == (
        f"unreadable prompt-length tier threshold {token!r} in "
        f"'Claude Haiku 5.5 (for prompts over {token} tokens)'; "
        "fix: teach the anthropic tier parse this spelling"
    )


def test_scrape_odd_row_does_not_blind_other_models(monkeypatch: pytest.MonkeyPatch):
    # a broken tier threshold on one model and a short row on another must
    # not fail an unrelated model's scrape; the broken row's own model raises
    fixture = FIXTURE.read_text()
    broken = fixture.replace(
        "Claude Haiku 5.5 (for prompts over 100,000 tokens)",
        "Claude Haiku 5.5 (for prompts over 100,000² tokens)",
        1,
    )
    broken = broken.replace(
        "| Claude Haiku 3.5 ",
        "| Claude Haiku 3.5 | $0.80 / MTok |\n| Claude Haiku 3.5 ",
        1,
    )
    assert broken != fixture
    feed(monkeypatch, broken)
    pricing = scraper.scrape(cfg(), "claude-opus-5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(5 / 1e6)
    with pytest.raises(FetchError, match="unreadable prompt-length tier threshold"):
        scraper.scrape(cfg(), "claude-haiku-5-5")


def test_scrape_inconsistent_tier_error_names_rows_count_and_fix(monkeypatch: pytest.MonkeyPatch):
    mismatched = _HAIKU_TIER_ROWS.replace("over 100,000", "over 200,000")
    feed(monkeypatch, _TABLE + mismatched)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-haiku-5-5")
    assert str(exc.value) == (
        f"prompt-length tier rows for 'claude-haiku-5-5' on {PAGE_URL} are not one "
        "'up to N' + 'over N' pair: found "
        "['Claude Haiku 5.5 (for prompts up to 100,000 tokens)', "
        "'Claude Haiku 5.5 (for prompts over 200,000 tokens)'] beside 0 "
        "untiered row(s); fix: teach the anthropic scraper the page's tier layout"
    )


def test_build_row_lands_the_tier_as_a_min_tokens_override(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch)
    pricing = scraper.scrape(cfg(), "claude-haiku-5-5")
    assert pricing is not None
    row = build_row(
        source="anthropic",
        model_id="claude-haiku-5-5",
        pricing=pricing,
        observed_at="2026-10-07",
        url=PAGE_URL,
        schema_version=4,
    )
    assert row["rates"] == {
        "input": 0.1,
        "output": 0.5,
        "cache_read": 0.01,
        "cache_write": 0.125,
        "cache_write_1h": 0.2,
    }
    assert row["overrides"] == [
        {
            "when": {"min_tokens": 100000},
            "rates": {
                "input": 0.5,
                "output": 2.5,
                "cache_read": 0.05,
                "cache_write": 0.625,
                "cache_write_1h": 1.0,
            },
        }
    ]


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


def _fast_name_warning(name: str) -> str:
    """the scrape-time line a fast-table name naming no model logs."""
    return (
        f"fast-mode name {name!r} names no model in the pricing table for anthropic on {PAGE_URL}"
    )


# the fast-mode table as the page carries it: header, separator, the Opus
# 5.5 row, then the one row whose cell joins two covered names
_FAST_TABLE = (
    "| Model                           | Input      | Output     |\n"
    "| ------------------------------- | ---------- | ---------- |\n"
    "| Claude Opus 5.5                 | $8 / MTok  | $40 / MTok |\n"
    "| Claude Opus 5 / Claude Opus 4.8 | $10 / MTok | $50 / MTok |\n"
)


@pytest.mark.parametrize(
    ("model_id", "input_mtok", "output_mtok"),
    [
        ("claude-opus-5-5", 8.0, 40.0),
        ("claude-opus-5", 10.0, 50.0),
        ("claude-opus-4-8", 10.0, 50.0),
    ],
)
def test_scrape_attaches_fast_mode_entry(
    monkeypatch: pytest.MonkeyPatch, model_id: str, input_mtok: float, output_mtok: float
):
    feed(monkeypatch)
    pricing = scraper.scrape(cfg(), model_id)
    assert pricing is not None
    assert pricing.window_rates == (
        {"mode": "fast", "input_mtok": input_mtok, "output_mtok": output_mtok},
    )


def test_scrape_other_model_carries_no_fast_entry(monkeypatch: pytest.MonkeyPatch):
    # fast mode covers the opus models only; the others keep the bare row
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


def test_fast_table_row_outside_shape_blames_its_own_model(monkeypatch: pytest.MonkeyPatch):
    # a short fast-table row whose name is readable fails only its own
    # model's scrape; every other model keeps its fast entry
    broken = _FAST_TABLE + "| Claude Opus 4.6 | $1 |\n"
    fixture = FIXTURE.read_text().replace(_FAST_TABLE, broken)
    feed(monkeypatch, fixture)
    pricing = scraper.scrape(cfg(), "claude-opus-5")
    assert pricing is not None
    assert pricing.window_rates == ({"mode": "fast", "input_mtok": 10.0, "output_mtok": 50.0},)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-opus-4-6")
    assert (
        str(exc.value)
        == f"row outside the fast-mode shape on {PAGE_URL}: ['Claude Opus 4.6', '$1']"
    )


def _nameless_fast_row_error(row: list[str]) -> str:
    return (
        f"fast-mode row {row!r} on {PAGE_URL} names no model, so it fails every"
        " model's scrape; fix: give the row a model name or teach the anthropic"
        " scraper this fast-table layout"
    )


@pytest.mark.parametrize(
    "name", ["", "—", "([note](https://x))"], ids=["empty", "dash", "annotation-only"]
)
def test_fast_table_row_with_no_name_raises_for_every_model(
    monkeypatch: pytest.MonkeyPatch, name: str
):
    # a fast-table row whose name yields no model id cannot be told apart from
    # the requested model's own row, so every scrape raises, saying why
    broken = _FAST_TABLE + f"| {name} | $1 / MTok | $2 / MTok |\n"
    fixture = FIXTURE.read_text().replace(_FAST_TABLE, broken)
    feed(monkeypatch, fixture)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-sonnet-5")
    assert str(exc.value) == _nameless_fast_row_error([name, "$1 / MTok", "$2 / MTok"])


def test_fast_table_row_with_one_unknown_name_still_applies(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # the row covers both names it joins, so one match applies it even when
    # the other name sits in no model-table row; that name still warns, once
    # (cloudy, 2026-10-19: every unknown fast name warns)
    drifted = _FAST_TABLE.replace(
        "Claude Opus 5 / Claude Opus 4.8", "Claude Opus 5 / Claude Cybertruck"
    )
    fixture = FIXTURE.read_text().replace(_FAST_TABLE, drifted)
    feed(monkeypatch, fixture)
    with caplog.at_level(logging.WARNING):
        pricing = scraper.scrape(cfg(), "claude-opus-5")
    assert pricing is not None
    assert pricing.window_rates == ({"mode": "fast", "input_mtok": 10.0, "output_mtok": 50.0},)
    assert caplog.messages == [_fast_name_warning("Claude Cybertruck")]


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


def _wording_error(paren: str, name: str) -> str:
    return (
        f"unreadable prompt-length tier wording {paren!r} in {name!r}; "
        "fix: teach the anthropic tier parse this spelling"
    )


_UP_TO_NAME = "Claude Haiku 5.5 (for prompts up to 100,000 tokens)"
_OVER_NAME = "Claude Haiku 5.5 (for prompts over 100,000 tokens)"


@pytest.mark.parametrize(
    ("old", "paren"),
    [
        (_OVER_NAME, "(for prompts above 100,000 tokens)"),
        (_OVER_NAME, "(for prompts more than 100,000 tokens)"),
        (_OVER_NAME, "(for prompts exceeding 100,000 tokens)"),
        (_UP_TO_NAME, "(for prompts under 100,000 tokens)"),
        (_OVER_NAME, "(for prompts over 100 000 tokens)"),
        (_OVER_NAME, "(for prompts over 100 K tokens)"),
    ],
    ids=["above", "more-than", "exceeding", "under", "thin-space", "spaced-k"],
)
def test_one_twin_tier_wording_drift_skips_and_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, old: str, paren: str
):
    # PR 460's class: a tier paren the parse cannot read must never slug into
    # a model id; the row skips with a warning and its own model's scrape
    # raises, while the other twin keeps the id and other models price
    new = "Claude Haiku 5.5 " + paren
    fixture = FIXTURE.read_text()
    drifted = fixture.replace(old, new, 1)
    assert drifted != fixture
    feed(monkeypatch, drifted)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == EXPECTED_IDS
    assert f"detect skip for anthropic: {_wording_error(paren, new)}" in caplog.messages
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-haiku-5-5")
    assert str(exc.value) == _wording_error(paren, new)
    pricing = scraper.scrape(cfg(), "claude-opus-5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(5 / 1e6)


def test_plain_row_beside_a_drifted_tier_row_raises(monkeypatch: pytest.MonkeyPatch):
    # a plain row must not hide its twin's unreadable tier: the tier would
    # drop silently and the drifted row would mint a fake id
    plain = (
        "| Claude Haiku 5.5 | $0.10 / MTok | $0.125 / MTok | $0.20 / MTok"
        " | $0.01 / MTok | $0.50 / MTok |\n"
    )
    drifted_name = "Claude Haiku 5.5 (for prompts above 100,000 tokens)"
    drifted = _HAIKU_TIER_ROWS.splitlines(keepends=True)[1].replace(_OVER_NAME, drifted_name)
    feed(monkeypatch, _TABLE + plain + drifted)
    assert detector.detect(cfg()) == ["claude-opus-5-fast", "claude-sonnet-5", "claude-haiku-5-5"]
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-haiku-5-5")
    assert str(exc.value) == _wording_error("(for prompts above 100,000 tokens)", drifted_name)


def test_short_sibling_row_blames_its_own_model(monkeypatch: pytest.MonkeyPatch):
    # a link-less paren is part of the name, so a short "(Fast)" row is
    # claude-opus-5-fast's row: only that model's scrape raises
    fixture = FIXTURE.read_text()
    short = "| Claude Opus 5 (Fast) | $10 / MTok |\n"
    broken = fixture.replace("| Claude Opus 5 ", short + "| Claude Opus 5 ", 1)
    assert broken != fixture
    feed(monkeypatch, broken)
    pricing = scraper.scrape(cfg(), "claude-opus-5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(5 / 1e6)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-opus-5-fast")
    assert str(exc.value) == (
        f"row outside the pricing shape on {PAGE_URL}: ['Claude Opus 5 (Fast)', '$10 / MTok']"
    )


def test_fast_table_unreadable_threshold_blames_its_own_model(monkeypatch: pytest.MonkeyPatch):
    broken = (
        _FAST_TABLE + "| Claude Opus 4.6 (for prompts over 1,00 tokens) | $1 / MTok | $2 / MTok |\n"
    )
    fixture = FIXTURE.read_text().replace(_FAST_TABLE, broken)
    feed(monkeypatch, fixture)
    sonnet = scraper.scrape(cfg(), "claude-sonnet-5")
    assert sonnet is not None
    assert sonnet.window_rates == ()
    opus = scraper.scrape(cfg(), "claude-opus-5")
    assert opus is not None
    assert opus.window_rates == ({"mode": "fast", "input_mtok": 10.0, "output_mtok": 50.0},)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-opus-4-6")
    assert str(exc.value) == (
        "unreadable prompt-length tier threshold '1,00' in "
        "'Claude Opus 4.6 (for prompts over 1,00 tokens)'; "
        "fix: teach the anthropic tier parse this spelling"
    )


def test_fast_table_tier_rows_raise_for_their_model(monkeypatch: pytest.MonkeyPatch):
    # fast mode has no prompt-length tiers in the row schema: two tier rows
    # would land as two contradictory fast overrides under one `when`
    tiered = (
        _FAST_TABLE
        + f"| {_UP_TO_NAME} | $0.20 / MTok | $1 / MTok |\n"
        + f"| {_OVER_NAME} | $1 / MTok | $5 / MTok |\n"
    )
    fixture = FIXTURE.read_text().replace(_FAST_TABLE, tiered)
    feed(monkeypatch, fixture)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-haiku-5-5")
    assert str(exc.value) == (
        f"fast-mode row {_UP_TO_NAME!r} carries a prompt-length tier on {PAGE_URL}; "
        "fix: teach the anthropic scraper fast-mode tiers"
    )
    opus = scraper.scrape(cfg(), "claude-opus-5")
    assert opus is not None
    assert opus.window_rates == ({"mode": "fast", "input_mtok": 10.0, "output_mtok": 50.0},)


def test_fast_table_duplicate_rows_for_one_model_raise(monkeypatch: pytest.MonkeyPatch):
    duplicated = _FAST_TABLE + "| Claude Opus 5.5 | $9 / MTok | $45 / MTok |\n"
    fixture = FIXTURE.read_text().replace(_FAST_TABLE, duplicated)
    feed(monkeypatch, fixture)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-opus-5-5")
    assert str(exc.value) == (
        f"more than one fast-mode row for 'claude-opus-5-5' on {PAGE_URL}: "
        "['Claude Opus 5.5', 'Claude Opus 5.5']; "
        "fix: teach the anthropic scraper which fast row prices the model"
    )


def test_two_link_notes_before_the_tier_fold(monkeypatch: pytest.MonkeyPatch):
    noted = _HAIKU_TIER_ROWS.replace(
        "Claude Haiku 5.5 (", "Claude Haiku 5.5 ([a](https://x)) ([b](https://y)) ("
    )
    assert noted.count("([a](https://x))") == 2
    feed(monkeypatch, _TABLE + noted)
    assert detector.detect(cfg()) == ["claude-opus-5-fast", "claude-sonnet-5", "claude-haiku-5-5"]
    pricing = scraper.scrape(cfg(), "claude-haiku-5-5")
    assert pricing is not None
    assert pricing.window_rates == (_HAIKU_TIER_ENTRY,)


def test_link_note_before_a_qualifier_drops(monkeypatch: pytest.MonkeyPatch):
    noted = _TABLE.replace(
        "Claude Opus 5 (Fast)", "Claude Opus 5 ([limited availability](https://x)) (Fast)"
    )
    assert noted != _TABLE
    feed(monkeypatch, noted)
    assert detector.detect(cfg()) == ["claude-opus-5-fast", "claude-sonnet-5"]


@pytest.mark.parametrize(
    "note",
    ["([intro (beta)](https://x))", "([intro](https://x.example/Foo_(bar)))"],
    ids=["paren-in-text", "paren-in-url"],
)
def test_link_note_with_nested_parens_drops(monkeypatch: pytest.MonkeyPatch, note: str):
    noted = _TABLE.replace("([intro through 2026-08-31](https://x))", note)
    assert noted != _TABLE
    feed(monkeypatch, noted)
    assert detector.detect(cfg()) == ["claude-opus-5-fast", "claude-sonnet-5"]


def test_footnote_markup_on_a_model_name_drops(monkeypatch: pytest.MonkeyPatch):
    # the page glues <sup>n</sup> footnote markers to rate cells today; on a
    # name they would slug into the id
    footnoted = _TABLE.replace(
        "Claude Sonnet 5 ([intro through 2026-08-31](https://x))", "Claude Sonnet 5<sup>3</sup>"
    )
    tier = _HAIKU_TIER_ROWS.replace(_OVER_NAME, _OVER_NAME + "<sup>4</sup>")
    assert footnoted != _TABLE and tier != _HAIKU_TIER_ROWS
    feed(monkeypatch, footnoted + tier)
    assert detector.detect(cfg()) == ["claude-opus-5-fast", "claude-sonnet-5", "claude-haiku-5-5"]
    pricing = scraper.scrape(cfg(), "claude-haiku-5-5")
    assert pricing is not None
    assert pricing.window_rates == (_HAIKU_TIER_ENTRY,)


@pytest.mark.parametrize("cell", ["$1,50 / MTok", "$0,10 / MTok", "$, / MTok"])
def test_rate_cell_with_a_misplaced_comma_raises(monkeypatch: pytest.MonkeyPatch, cell: str):
    # a decimal comma must never read as a 100x rate
    broken = _TABLE.replace(
        "| Claude Opus 5 (Fast) | $5 / MTok |", f"| Claude Opus 5 (Fast) | {cell} |"
    )
    assert broken != _TABLE
    feed(monkeypatch, broken)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-opus-5-fast")
    assert str(exc.value) == f"unreadable rate {cell!r} for claude-opus-5-fast on {PAGE_URL}"


@pytest.mark.parametrize(
    ("cell", "rate"),
    [("$1,000 / MTok", 1000.0), ("$0.25 / MTok<sup>1</sup>", 0.25), ("$0.125 / MTok", 0.125)],
)
def test_rate_cell_reads_grouped_and_footnoted_amounts(
    monkeypatch: pytest.MonkeyPatch, cell: str, rate: float
):
    readable = _TABLE.replace(
        "| Claude Opus 5 (Fast) | $5 / MTok |", f"| Claude Opus 5 (Fast) | {cell} |"
    )
    assert readable != _TABLE
    feed(monkeypatch, readable)
    pricing = scraper.scrape(cfg(), "claude-opus-5-fast")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(rate / 1e6)


def _odd_rows_fixture() -> str:
    fixture = FIXTURE.read_text()
    broken = fixture.replace(_OVER_NAME, "Claude Haiku 5.5 (for prompts over 100,000² tokens)", 1)
    broken = broken.replace(
        "| Claude Haiku 3.5 ", "| Claude Haiku 3.5 | $0.80 / MTok |\n| Claude Haiku 3.5 ", 1
    )
    assert broken.count("$0.80 / MTok |\n") == 1
    return broken


def test_odd_rows_blind_no_other_model(monkeypatch: pytest.MonkeyPatch):
    # every model other than the two broken rows' own prices: a fixed list
    # of spot checks would let an odd row blind the models it skips
    feed(monkeypatch, _odd_rows_fixture())
    broken_models = {"claude-haiku-5-5", "claude-haiku-3-5"}
    ids = detector.detect(cfg())
    assert ids == EXPECTED_IDS
    for model_id in ids:
        if model_id not in broken_models:
            assert scraper.scrape(cfg(), model_id) is not None, model_id


def test_own_short_row_raises_beside_its_good_row(monkeypatch: pytest.MonkeyPatch):
    # a model's malformed duplicate row must not resolve silently to its good row
    feed(monkeypatch, _odd_rows_fixture())
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-haiku-3-5")
    assert str(exc.value) == (
        f"row outside the pricing shape on {PAGE_URL}: ['Claude Haiku 3.5', '$0.80 / MTok']"
    )


def _name_error(name: str) -> str:
    return (
        f"unreadable model name {name!r} on {PAGE_URL}; "
        "fix: teach the anthropic name parse this spelling"
    )


def _skip_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [line for line in caplog.messages if line.startswith("detect skip for anthropic: ")]


def _without(model_id: str) -> list[str]:
    return [expected for expected in EXPECTED_IDS if expected != model_id]


_OPUS_4_NAME = (
    "Claude Opus 4 ([retired, except on Google Cloud]"
    "(https://platform.claude.com/docs/en/about-claude/model-deprecations))"
)


@pytest.mark.parametrize(
    "name",
    [
        "Claude Opus 4 (retired, see [notice](https://x))",
        "Claude Opus 4 ([retired](https://x), except on Google Cloud)",
        "Claude Opus 4 ( [retired, except on Google Cloud](https://x) )",
        "Claude Opus 4 ([retired \\] except on Google Cloud](https://x))",
    ],
    ids=["text-before-link", "text-after-link", "spaced-link", "escaped-bracket"],
)
def test_link_note_with_text_outside_the_link_drops(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, name: str
):
    # a trailing paren group carrying a link is an annotation, whatever text
    # sits around the link inside it
    fixture = FIXTURE.read_text()
    noted = fixture.replace(_OPUS_4_NAME, name, 1)
    assert noted != fixture
    feed(monkeypatch, noted)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == EXPECTED_IDS
    assert _skip_lines(caplog) == []
    pricing = scraper.scrape(cfg(), "claude-opus-4")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(15 / 1e6)


def test_fast_name_link_note_with_text_outside_the_link_drops(monkeypatch: pytest.MonkeyPatch):
    noted = _FAST_TABLE.replace(
        "Claude Opus 5 / Claude Opus 4.8",
        "Claude Opus 5 (see [note](https://x)) / Claude Opus 4.8",
    )
    fixture = FIXTURE.read_text()
    assert noted != _FAST_TABLE and _FAST_TABLE in fixture
    feed(monkeypatch, fixture.replace(_FAST_TABLE, noted))
    pricing = scraper.scrape(cfg(), "claude-opus-5")
    assert pricing is not None
    assert pricing.window_rates == ({"mode": "fast", "input_mtok": 10.0, "output_mtok": 50.0},)


@pytest.mark.parametrize(
    "glyph",
    ["†", "[^4]"],
    ids=["dagger", "footnote-ref"],
)
def test_glyph_after_both_tier_rows_skips_and_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, glyph: str
):
    # PR 460's exact ids: a glyph after the tier paren hides it from the tier
    # read, so neither row may slug into an id, and the model's own scrape
    # fails loudly instead of reading as off the page
    up_to, over = _UP_TO_NAME + glyph, _OVER_NAME + glyph
    fixture = FIXTURE.read_text()
    glyphed = fixture.replace(_UP_TO_NAME, up_to, 1).replace(_OVER_NAME, over, 1)
    assert glyphed != fixture
    feed(monkeypatch, glyphed)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == _without("claude-haiku-5-5")
    assert _skip_lines(caplog) == [
        f"detect skip for anthropic: {_name_error(up_to)}",
        f"detect skip for anthropic: {_name_error(over)}",
    ]
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-haiku-5-5")
    assert str(exc.value) == _name_error(up_to)
    pricing = scraper.scrape(cfg(), "claude-opus-5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(5 / 1e6)


@pytest.mark.parametrize(
    "name",
    [
        "Claude Sonnet 5<SUP>3</SUP>",
        'Claude Sonnet 5<sup class="fn">3</sup>',
        "Claude Sonnet 5[^3]",
        "Claude Sonnet 5 [intro](https://x)",
        "Claude Sonnet 5 (2)",
    ],
    ids=["uppercase-sup", "sup-with-attribute", "footnote-ref", "bare-link", "digit-in-paren"],
)
def test_unread_markup_on_a_model_name_skips_and_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, name: str
):
    fixture = FIXTURE.read_text()
    marked = fixture.replace("| Claude Sonnet 5 ", f"| {name} ", 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == _without("claude-sonnet-5")
    assert _skip_lines(caplog) == [f"detect skip for anthropic: {_name_error(name)}"]
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-sonnet-5")
    assert str(exc.value) == _name_error(name)


@pytest.mark.parametrize(
    ("old", "name", "model_id", "ids"),
    [
        (_OVER_NAME, "Claude Haiku 5.5 (over 100K)", "claude-haiku-5-5", EXPECTED_IDS),
        (
            "Claude Opus 4.8 ",
            "Claude Opus 4.8 (legacy) ",
            "claude-opus-4-8",
            _without("claude-opus-4-8"),
        ),
    ],
    ids=["tier-without-trigger-words", "unknown-qualifier"],
)
def test_unread_qualifier_skips_and_raises_its_own_model(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    old: str,
    name: str,
    model_id: str,
    ids: list[str],
):
    fixture = FIXTURE.read_text()
    edited = fixture.replace(f"| {old}", f"| {name}", 1)
    assert edited != fixture
    feed(monkeypatch, edited)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ids
    assert _skip_lines(caplog) == [f"detect skip for anthropic: {_name_error(name.strip())}"]
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), model_id)
    assert str(exc.value) == _name_error(name.strip())


def test_plain_row_beside_an_unread_qualifier_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # beside a plain row, an unread qualifier row must neither mint an id
    # nor let the plain row price the model without it
    plain = (
        "| Claude Haiku 5.5 | $0.10 / MTok | $0.125 / MTok | $0.20 / MTok"
        " | $0.01 / MTok | $0.50 / MTok |\n"
    )
    long_context = (
        "| Claude Haiku 5.5 (long context) | $0.50 / MTok | $0.625 / MTok | $1 / MTok"
        " | $0.05 / MTok | $2.50 / MTok |\n"
    )
    feed(monkeypatch, _TABLE + plain + long_context)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == [
            "claude-opus-5-fast",
            "claude-sonnet-5",
            "claude-haiku-5-5",
        ]
    name = "Claude Haiku 5.5 (long context)"
    assert _skip_lines(caplog) == [f"detect skip for anthropic: {_name_error(name)}"]
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-haiku-5-5")
    assert str(exc.value) == _name_error(name)


@pytest.mark.parametrize(
    ("name", "model_id"),
    [("Claude Sonata 6", "claude-sonata-6"), ("Claude Opus Max 6.1", "claude-opus-max-6-1")],
    ids=["new-family", "two-word-family"],
)
def test_new_model_family_is_detected(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, name: str, model_id: str
):
    # the name parse reads a name's shape, never a family list: a release
    # under a new family name lands as a new id
    row = f"| {name} | $1 / MTok | $1.25 / MTok | $2 / MTok | $0.10 / MTok | $5 / MTok |\n"
    feed(monkeypatch, _TABLE + row)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["claude-opus-5-fast", "claude-sonnet-5", model_id]
    assert _skip_lines(caplog) == []
    pricing = scraper.scrape(cfg(), model_id)
    assert pricing is not None
    assert pricing.output_cost_per_token == pytest.approx(5 / 1e6)


@pytest.mark.parametrize("cell", ["$5,0 / MTok ($4.50 / MTok batch)", "$5, $10 / MTok"])
def test_rate_cell_reads_its_first_amount_only(monkeypatch: pytest.MonkeyPatch, cell: str):
    # a malformed first amount raises; a later amount in the cell never
    # stands in for it
    broken = _TABLE.replace(
        "| Claude Opus 5 (Fast) | $5 / MTok |", f"| Claude Opus 5 (Fast) | {cell} |"
    )
    assert broken != _TABLE
    feed(monkeypatch, broken)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-opus-5-fast")
    assert str(exc.value) == f"unreadable rate {cell!r} for claude-opus-5-fast on {PAGE_URL}"


@pytest.mark.parametrize(
    "cell",
    ["$1,0 / MTok ($10 / MTok)", "$.10 / MTok (was $10 / MTok)"],
    ids=["comma-glued", "dot-first-amount"],
)
def test_fast_rate_cell_reads_its_first_amount_only(monkeypatch: pytest.MonkeyPatch, cell: str):
    broken = _FAST_TABLE.replace("| $10 / MTok | $50 / MTok |", f"| {cell} | $50 / MTok |")
    fixture = FIXTURE.read_text()
    assert broken != _FAST_TABLE and _FAST_TABLE in fixture
    feed(monkeypatch, fixture.replace(_FAST_TABLE, broken))
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-opus-5")
    assert str(exc.value) == f"unreadable rate {cell!r} for claude-opus-5 on {PAGE_URL}"


def test_rate_cell_with_fullwidth_digits_raises(monkeypatch: pytest.MonkeyPatch):
    cell = "$５ / MTok"
    broken = _TABLE.replace(
        "| Claude Opus 5 (Fast) | $5 / MTok |", f"| Claude Opus 5 (Fast) | {cell} |"
    )
    assert broken != _TABLE
    feed(monkeypatch, broken)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-opus-5-fast")
    assert str(exc.value) == f"unreadable rate {cell!r} for claude-opus-5-fast on {PAGE_URL}"


def test_model_table_row_with_no_name_raises_for_every_model(monkeypatch: pytest.MonkeyPatch):
    # a row with an empty name cannot be told apart from the requested
    # model's own row (a rowspan rendering of a tier reads so), so every
    # scrape raises, as in the fast-mode table
    plain = (
        "| Claude Haiku 5.5 | $0.10 / MTok | $0.125 / MTok | $0.20 / MTok"
        " | $0.01 / MTok | $0.50 / MTok |\n"
    )
    nameless = "|  | $0.50 / MTok | $0.625 / MTok | $1 / MTok | $0.05 / MTok | $2.50 / MTok |\n"
    feed(monkeypatch, _TABLE + plain + nameless)
    for model_id in ("claude-haiku-5-5", "claude-sonnet-5"):
        with pytest.raises(FetchError) as exc:
            scraper.scrape(cfg(), model_id)
        assert str(exc.value) == (
            f"row outside the pricing shape on {PAGE_URL}: "
            "['', '$0.50 / MTok', '$0.625 / MTok', '$1 / MTok', '$0.05 / MTok', '$2.50 / MTok']"
        )


@pytest.mark.parametrize(
    "paren",
    ["(for prompts over 100K)", "(over 100,000 tokens)"],
    ids=["prompts-only", "tokens-only"],
)
def test_tier_wording_naming_one_trigger_word_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, paren: str
):
    # either trigger word alone marks a tier paren the tier parse must read
    new = "Claude Haiku 5.5 " + paren
    fixture = FIXTURE.read_text()
    drifted = fixture.replace(_OVER_NAME, new, 1)
    assert drifted != fixture
    feed(monkeypatch, drifted)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == EXPECTED_IDS
    assert _skip_lines(caplog) == [f"detect skip for anthropic: {_wording_error(paren, new)}"]
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-haiku-5-5")
    assert str(exc.value) == _wording_error(paren, new)


def test_fast_joint_row_with_a_tier_on_its_second_name_raises_for_both(
    monkeypatch: pytest.MonkeyPatch,
):
    joint = "Claude Opus 5 / " + _OVER_NAME
    tiered = _FAST_TABLE.replace("Claude Opus 5 / Claude Opus 4.8", joint)
    fixture = FIXTURE.read_text()
    assert tiered != _FAST_TABLE and _FAST_TABLE in fixture
    feed(monkeypatch, fixture.replace(_FAST_TABLE, tiered))
    for model_id in ("claude-opus-5", "claude-haiku-5-5"):
        with pytest.raises(FetchError) as exc:
            scraper.scrape(cfg(), model_id)
        assert str(exc.value) == (
            f"fast-mode row {joint!r} carries a prompt-length tier on {PAGE_URL}; "
            "fix: teach the anthropic scraper fast-mode tiers"
        )


@pytest.mark.parametrize(
    "note",
    ["([n](https://x.example/Foo_(bar)))", "([retired [GA]](https://x))"],
    ids=["paren-in-url", "bracket-in-text"],
)
def test_mid_name_link_note_with_nesting_drops(monkeypatch: pytest.MonkeyPatch, note: str):
    # before the tier paren only the balanced scan can drop the note: a
    # leftover would keep the over row from folding
    noted = _HAIKU_TIER_ROWS.replace(
        _OVER_NAME, f"Claude Haiku 5.5 {note} (for prompts over 100,000 tokens)"
    )
    assert noted != _HAIKU_TIER_ROWS
    feed(monkeypatch, _TABLE + noted)
    assert detector.detect(cfg()) == ["claude-opus-5-fast", "claude-sonnet-5", "claude-haiku-5-5"]
    pricing = scraper.scrape(cfg(), "claude-haiku-5-5")
    assert pricing is not None
    assert pricing.window_rates == (_HAIKU_TIER_ENTRY,)


def test_two_sup_markers_on_one_name_drop(monkeypatch: pytest.MonkeyPatch):
    footnoted = _TABLE.replace(
        "Claude Sonnet 5 ([intro through 2026-08-31](https://x))",
        "Claude<sup>1</sup> Sonnet 5<sup>3</sup>",
    )
    assert footnoted != _TABLE
    feed(monkeypatch, footnoted)
    assert detector.detect(cfg()) == ["claude-opus-5-fast", "claude-sonnet-5"]


def test_two_trailing_link_carrying_groups_drop(monkeypatch: pytest.MonkeyPatch):
    # R5-A: a trailing paren group carrying a link drops repeatedly, so the
    # second such group the first drop leaves trailing also drops
    noted = _TABLE.replace(
        "Claude Sonnet 5 ([intro through 2026-08-31](https://x))",
        "Claude Sonnet 5 (a [x](https://x)) (b [y](https://y))",
    )
    assert noted != _TABLE
    feed(monkeypatch, noted)
    assert detector.detect(cfg()) == ["claude-opus-5-fast", "claude-sonnet-5"]


def test_short_fast_row_naming_no_model_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # a short fast row naming no model-table model is drift: the requested
    # model still prices, with the same warning a full-shape one carries
    drifted = _FAST_TABLE + "| Claude Opus 9 | $1 / MTok |\n"
    fixture = FIXTURE.read_text()
    assert _FAST_TABLE in fixture
    feed(monkeypatch, fixture.replace(_FAST_TABLE, drifted))
    with caplog.at_level(logging.WARNING):
        pricing = scraper.scrape(cfg(), "claude-opus-5")
    assert pricing is not None
    assert pricing.window_rates == ({"mode": "fast", "input_mtok": 10.0, "output_mtok": 50.0},)
    assert caplog.messages == [_fast_name_warning("Claude Opus 9")]


def test_name_without_a_leading_shape_fails_no_scrape(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # a model-table row whose name has no leading shape names no model, so
    # detection skips it and no scrape raises for it
    row = "| Cybertruck | $1 / MTok | $1.25 / MTok | $2 / MTok | $0.10 / MTok | $5 / MTok |\n"
    feed(monkeypatch, _TABLE + row)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["claude-opus-5-fast", "claude-sonnet-5"]
    assert _skip_lines(caplog) == [f"detect skip for anthropic: {_name_error('Cybertruck')}"]
    assert scraper.scrape(cfg(), "cybertruck") is None
    pricing = scraper.scrape(cfg(), "claude-opus-5-fast")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(5 / 1e6)


_ZWSP = chr(0x200B)
_BOM = chr(0xFEFF)
_FAST_ENTRY = {"mode": "fast", "input_mtok": 10.0, "output_mtok": 50.0}


@pytest.mark.parametrize(
    "prefix", ["([new](https://x)) ", "<sup>1</sup> "], ids=["link-note", "footnote-sup"]
)
def test_leading_note_or_footnote_keeps_the_model(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, prefix: str
):
    # a note dropped from the front of a name must leave the name readable
    fixture = FIXTURE.read_text()
    noted = fixture.replace("| Claude Opus 5 ", f"| {prefix}Claude Opus 5 ", 1)
    noted = noted.replace(_UP_TO_NAME, prefix + _UP_TO_NAME, 1)
    noted = noted.replace(_OVER_NAME, prefix + _OVER_NAME, 1)
    assert noted != fixture
    feed(monkeypatch, noted)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == EXPECTED_IDS
    assert _skip_lines(caplog) == []
    opus = scraper.scrape(cfg(), "claude-opus-5")
    assert opus is not None
    assert opus.input_cost_per_token == pytest.approx(5 / 1e6)
    assert opus.window_rates == (_FAST_ENTRY,)
    haiku = scraper.scrape(cfg(), "claude-haiku-5-5")
    assert haiku is not None
    assert haiku.window_rates == (_HAIKU_TIER_ENTRY,)


@pytest.mark.parametrize(
    "name",
    [
        "**Claude Opus 5**",
        "*Claude Opus 5*",
        "`Claude Opus 5`",
        "Claude **Opus** 5",
        _ZWSP + "Claude Opus 5",
        _BOM + "Claude Opus 5",
        "Claude Opus 5*",
        "_Claude Opus 5_",
        "Claude _Opus_ 5",
        chr(0x200C) + "Claude Opus 5",
        chr(0x200D) + "Claude Opus 5",
        chr(0x2060) + "Claude Opus 5",
    ],
    ids=[
        "bold",
        "italic",
        "code",
        "bold-word",
        "zwsp-before",
        "bom-before",
        "asterisk-after",
        "underscore-italic",
        "underscore-word",
        "zwnj-before",
        "zwj-before",
        "wj-before",
    ],
)
def test_markdown_emphasis_or_invisible_mark_on_a_name_reads(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, name: str
):
    # markdown emphasis and invisible format marks carry no part of a model's
    # name: the name reads as if they were absent
    fixture = FIXTURE.read_text()
    marked = fixture.replace("| Claude Opus 5 ", f"| {name} ", 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == EXPECTED_IDS
    assert _skip_lines(caplog) == []
    pricing = scraper.scrape(cfg(), "claude-opus-5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(5 / 1e6)


@pytest.mark.parametrize("glyph", ["*", _ZWSP], ids=["asterisk", "zero-width-space"])
def test_emphasis_or_invisible_mark_after_both_tier_rows_folds(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, glyph: str
):
    fixture = FIXTURE.read_text()
    marked = fixture.replace(_UP_TO_NAME, _UP_TO_NAME + glyph, 1)
    marked = marked.replace(_OVER_NAME, _OVER_NAME + glyph, 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == EXPECTED_IDS
    assert _skip_lines(caplog) == []
    pricing = scraper.scrape(cfg(), "claude-haiku-5-5")
    assert pricing is not None
    assert pricing.window_rates == (_HAIKU_TIER_ENTRY,)


@pytest.mark.parametrize(
    "joint",
    [
        "Claude Opus 5! / Claude Opus 4.8",
        f"Claude{_ZWSP}Opus 5 / Claude Opus 4.8",
        f"Claude Opus 5 / Claude{_ZWSP}Opus 4.8",
        "Claude Opus 5 / Claude Opus 4_8",
    ],
    ids=[
        "bang-on-first",
        "zwsp-for-space-on-first",
        "zwsp-for-space-on-second",
        "underscore-in-version",
    ],
)
def test_fast_names_match_as_their_slug_reads(monkeypatch: pytest.MonkeyPatch, joint: str):
    # a fast-table name matches a model-table id through its slug, never the
    # model-table name guard: "Claude Opus 5!" fails that guard, yet its slug
    # still names claude-opus-5
    noted = _FAST_TABLE.replace("Claude Opus 5 / Claude Opus 4.8", joint)
    fixture = FIXTURE.read_text()
    assert noted != _FAST_TABLE and _FAST_TABLE in fixture
    feed(monkeypatch, fixture.replace(_FAST_TABLE, noted))
    for model_id in ("claude-opus-5", "claude-opus-4-8"):
        pricing = scraper.scrape(cfg(), model_id)
        assert pricing is not None, model_id
        assert pricing.window_rates == (_FAST_ENTRY,), model_id


@pytest.mark.parametrize(
    "name",
    ["Claude Opuſ 5", "Claude Opus ５", "Claude Opus 5 (Faſt)", "Claude Opus 5 (FAſT)"],
    ids=["long-s", "fullwidth", "long-s-in-fast", "long-s-in-upper-fast"],
)
def test_non_ascii_name_skips_without_a_fake_id(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, name: str
):
    # case folding maps some non-ASCII letters onto ASCII ones and the slug
    # drops the rest, so a non-ASCII name would mint a wrong id
    fixture = FIXTURE.read_text()
    marked = fixture.replace("| Claude Opus 5 ", f"| {name} ", 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == _without("claude-opus-5")
    assert _skip_lines(caplog) == [f"detect skip for anthropic: {_name_error(name)}"]


@pytest.mark.parametrize(
    "cell",
    [
        "~~$5 / MTok~~ $2.50 / MTok",
        "(was $10 / MTok) $5 / MTok",
        "$5 / MTok ($4.50 / MTok batch)",
        "$.50 / MTok (was $5 / MTok)",
        "$ 2.50 / MTok (list $5 / MTok)",
        "$,50 / MTok (was $5 / MTok)",
    ],
    ids=[
        "struck-list-price",
        "was-price",
        "batch-in-parens",
        "dot-first-amount",
        "space-after-dollar",
        "comma-first-amount",
    ],
)
def test_rate_cell_with_two_amounts_raises(monkeypatch: pytest.MonkeyPatch, cell: str):
    # a cell carrying two amounts names no single rate in force: loud, never
    # a guess
    broken = _TABLE.replace(
        "| Claude Opus 5 (Fast) | $5 / MTok |", f"| Claude Opus 5 (Fast) | {cell} |"
    )
    assert broken != _TABLE
    feed(monkeypatch, broken)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-opus-5-fast")
    assert str(exc.value) == f"unreadable rate {cell!r} for claude-opus-5-fast on {PAGE_URL}"


@pytest.mark.parametrize(
    "cell",
    [
        "$5 / MTok (was ＄10 / MTok)",
        "&#36;10 / MTok $5 / MTok",
        "$5 / MTok (was 10$)",
        "$1-2 / MTok",
        "$5 / MTok (was &dollar;10 / MTok)",
        "$5 / MTok (was 10 $)",
        "$5 - 10 / MTok",
        "$5-$10 / MTok",
    ],
    ids=[
        "fullwidth-dollar",
        "entity-dollar",
        "trailing-dollar",
        "hyphen-range",
        "named-entity-dollar",
        "spaced-trailing-dollar",
        "spaced-range",
        "re-dollared-range",
    ],
)
def test_rate_cell_with_a_second_amount_in_another_spelling_raises(
    monkeypatch: pytest.MonkeyPatch, cell: str
):
    # a second amount written with a fullwidth, entity or trailing dollar
    # sign, or a hyphen range, names no single rate in force either
    broken = _TABLE.replace(
        "| Claude Opus 5 (Fast) | $5 / MTok |", f"| Claude Opus 5 (Fast) | {cell} |"
    )
    assert broken != _TABLE
    feed(monkeypatch, broken)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-opus-5-fast")
    assert str(exc.value) == f"unreadable rate {cell!r} for claude-opus-5-fast on {PAGE_URL}"


@pytest.mark.parametrize(
    "name",
    [
        "—",
        "&nbsp;",
        _ZWSP,
        "(for prompts over 100,000 tokens)",
        "— (for prompts over 100,000 tokens)",
        "↳ (for prompts over 100,000 tokens)",
    ],
    ids=[
        "em-dash",
        "nbsp-entity",
        "zwsp-only",
        "tier-text-only",
        "dash-then-tier-text",
        "arrow-then-tier-text",
    ],
)
def test_model_table_row_with_a_letterless_name_raises_for_every_model(
    monkeypatch: pytest.MonkeyPatch, name: str
):
    # a placeholder name (a rowspan rendering of a tier reads so) names no
    # model any more than an empty cell does
    plain = (
        "| Claude Haiku 5.5 | $0.10 / MTok | $0.125 / MTok | $0.20 / MTok"
        " | $0.01 / MTok | $0.50 / MTok |\n"
    )
    rates = ["$0.50 / MTok", "$0.625 / MTok", "$1 / MTok", "$0.05 / MTok", "$2.50 / MTok"]
    placeholder = "| " + " | ".join([name, *rates]) + " |\n"
    feed(monkeypatch, _TABLE + plain + placeholder)
    for model_id in ("claude-haiku-5-5", "claude-sonnet-5"):
        with pytest.raises(FetchError) as exc:
            scraper.scrape(cfg(), model_id)
        assert str(exc.value) == f"row outside the pricing shape on {PAGE_URL}: {[name, *rates]!r}"


def test_rate_cell_with_bad_grouping_raises(monkeypatch: pytest.MonkeyPatch):
    # "$1,5000" reads as 1500 only once the no-digit lookahead is dropped:
    # the strict amount never falls through to a partial grouping
    cell = "$1,5000 / MTok"
    broken = _TABLE.replace(
        "| Claude Opus 5 (Fast) | $5 / MTok |", f"| Claude Opus 5 (Fast) | {cell} |"
    )
    assert broken != _TABLE
    feed(monkeypatch, broken)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-opus-5-fast")
    assert str(exc.value) == f"unreadable rate {cell!r} for claude-opus-5-fast on {PAGE_URL}"


def test_rate_cell_with_double_dot_raises(monkeypatch: pytest.MonkeyPatch):
    # "$5.0.0" reads as 5 only once the no-dot lookahead is dropped: the
    # second decimal point is never part of the amount
    cell = "$5.0.0 / MTok"
    broken = _TABLE.replace(
        "| Claude Opus 5 (Fast) | $5 / MTok |", f"| Claude Opus 5 (Fast) | {cell} |"
    )
    assert broken != _TABLE
    feed(monkeypatch, broken)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-opus-5-fast")
    assert str(exc.value) == f"unreadable rate {cell!r} for claude-opus-5-fast on {PAGE_URL}"


def test_tier_trigger_words_in_uppercase_raise(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # the prompt/token trigger is case-insensitive, so an uppercase tier
    # still reads as a tier whose wording is drifted, never as part of the
    # name
    name = "Claude Haiku 5.5 (FOR PROMPTS ABOVE 100,000 TOKENS)"
    paren = "(FOR PROMPTS ABOVE 100,000 TOKENS)"
    fixture = FIXTURE.read_text()
    drifted = fixture.replace(_OVER_NAME, name, 1)
    assert drifted != fixture
    feed(monkeypatch, drifted)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == EXPECTED_IDS
    assert _skip_lines(caplog) == [f"detect skip for anthropic: {_wording_error(paren, name)}"]
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-haiku-5-5")
    assert str(exc.value) == _wording_error(paren, name)


def test_tier_escaped_parens_raise(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # backslash-escaped parens are a glyph the name-shape guard rejects: the
    # leftover backslash keeps the name from matching, so the row skips and
    # its model's scrape raises (never a fake id)
    name = r"Claude Haiku 5.5 \(for prompts over 100,000 tokens\)"
    fixture = FIXTURE.read_text()
    drifted = fixture.replace(_OVER_NAME, name, 1)
    assert drifted != fixture
    feed(monkeypatch, drifted)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == EXPECTED_IDS
    assert _skip_lines(caplog) == [f"detect skip for anthropic: {_name_error(name)}"]
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-haiku-5-5")
    assert str(exc.value) == _name_error(name)


@pytest.mark.parametrize(
    "name",
    ["Anthropic Opus 5", "xClaude Opus 5", "Claude (beta) Opus 5", "Claude Opus5 5"],
    ids=["any-first-word", "prefix-claude", "paren-word", "digit-in-word"],
)
def test_fake_word_shapes_skip_without_minting(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, name: str
):
    # a name whose first word is not "Claude", or whose words are not ASCII
    # letters, names no model: it skips with the shape message and mints
    # nothing
    fixture = FIXTURE.read_text()
    marked = fixture.replace("| Claude Opus 5 ", f"| {name} ", 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == _without("claude-opus-5")
    assert _skip_lines(caplog) == [f"detect skip for anthropic: {_name_error(name)}"]
    assert scraper.scrape(cfg(), "claude-opus-5") is None


def test_lowercase_fast_qualifier_reads(monkeypatch: pytest.MonkeyPatch):
    # the shape check is case-insensitive, so "(fast)" reads the same
    # claude-opus-5-fast id as "(Fast)"
    noted = _TABLE.replace("Claude Opus 5 (Fast)", "Claude Opus 5 (fast)")
    assert noted != _TABLE
    feed(monkeypatch, noted)
    assert detector.detect(cfg()) == ["claude-opus-5-fast", "claude-sonnet-5"]


def test_uppercase_name_reads(monkeypatch: pytest.MonkeyPatch):
    # case does not matter to the shape, so an uppercase name still names
    # the same model
    fixture = FIXTURE.read_text()
    marked = fixture.replace("| Claude Opus 5 ", "| CLAUDE OPUS 5 ", 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    assert detector.detect(cfg()) == EXPECTED_IDS
    pricing = scraper.scrape(cfg(), "claude-opus-5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(5 / 1e6)


def test_nbsp_between_words_reads(monkeypatch: pytest.MonkeyPatch):
    # a non-breaking space is one space between words, so the name still
    # names claude-opus-5
    fixture = FIXTURE.read_text()
    marked = fixture.replace("| Claude Opus 5 ", "| Claude" + chr(0xA0) + "Opus 5 ", 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    assert detector.detect(cfg()) == EXPECTED_IDS
    pricing = scraper.scrape(cfg(), "claude-opus-5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(5 / 1e6)


@pytest.mark.parametrize(
    ("name", "model_id"),
    [("Claude Opus 4.5.1", "claude-opus-4-5-1"), ("Claude Opus 4.10", "claude-opus-4-10")],
    ids=["two-dot-version", "two-digit-minor"],
)
def test_multipart_version_is_a_new_candidate(
    monkeypatch: pytest.MonkeyPatch, name: str, model_id: str
):
    # the version takes any number of dot groups, each with any digit
    # count, so a new multi-part version lands as a new candidate
    fixture = FIXTURE.read_text()
    marked = fixture.replace("| Claude Opus 5 ", f"| {name} ", 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    ids = detector.detect(cfg())
    assert model_id in ids
    assert "claude-opus-5" not in ids
    assert len(ids) == len(EXPECTED_IDS)
    pricing = scraper.scrape(cfg(), model_id)
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(5 / 1e6)


@pytest.mark.parametrize(
    "cell",
    ["[US$ pricing](https://x) $5 / MTok", "$5 / MTok<sup>$</sup>"],
    ids=["dollar-in-link-text", "dollar-in-footnote"],
)
def test_dollar_sign_with_no_amount_beside_the_rate_reads(
    monkeypatch: pytest.MonkeyPatch, cell: str
):
    # a "$" no digit follows is no amount, so the cell still carries one rate
    noted = _TABLE.replace(
        "| Claude Opus 5 (Fast) | $5 / MTok |", f"| Claude Opus 5 (Fast) | {cell} |"
    )
    assert noted != _TABLE
    feed(monkeypatch, noted)
    pricing = scraper.scrape(cfg(), "claude-opus-5-fast")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(5 / 1e6)


@pytest.mark.parametrize(
    "name",
    [
        "Claude Opus 4_5",
        "Claude Opus 4*5",
        "Claude Opus 4`5",
        "Claude Opus 4,5",
        "Claude Opus 4." + chr(0x200B) + "5",
        "Claude Opus 4.*5*",
        "Claude Opus 4..5",
        "Claude Opus 4. 5",
        "Claude Opus 4 , 5",
    ],
    ids=[
        "underscore",
        "asterisk",
        "backtick",
        "decimal-comma",
        "zwsp-after-dot",
        "emphasis-on-minor",
        "double-dot",
        "space-after-dot",
        "spaced-comma",
    ],
)
def test_version_split_by_a_mark_or_comma_names_no_model(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, name: str
):
    # a mark or a comma between two digit groups never joins them into another
    # version, and the shorter version is a different real model, so the row
    # names none: one skip, no fake id, and the shorter model still scrapes
    fixture = FIXTURE.read_text()
    marked = fixture.replace("| Claude Opus 4.5 ", f"| {name} ", 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == _without("claude-opus-4-5")
    assert _skip_lines(caplog) == [f"detect skip for anthropic: {_name_error(name)}"]
    assert scraper.scrape(cfg(), "claude-opus-4") is not None


def test_tier_text_only_twin_blames_its_paired_model_only(monkeypatch: pytest.MonkeyPatch):
    # a rowspan rendering keeps the model's name on its first tier row only:
    # the nameless twin pairs with that one model, so only its scrape fails
    over_only = _HAIKU_TIER_ROWS.replace(_OVER_NAME, "(for prompts over 100,000 tokens)")
    assert over_only != _HAIKU_TIER_ROWS
    feed(monkeypatch, _TABLE + over_only)
    with pytest.raises(FetchError, match="prompt-length tier rows"):
        scraper.scrape(cfg(), "claude-haiku-5-5")
    for model_id in ("claude-opus-5-fast", "claude-sonnet-5"):
        assert scraper.scrape(cfg(), model_id) is not None, model_id


_SONNET_UP_ROW = (
    "| Claude Sonnet 5 (for prompts up to 100,000 tokens) | $2 / MTok | $2.50 / MTok"
    " | $4 / MTok | $0.20 / MTok | $10 / MTok |\n"
)
_OVER_RATES = ["$0.50 / MTok", "$0.625 / MTok", "$1 / MTok", "$0.05 / MTok", "$2.50 / MTok"]


@pytest.mark.parametrize(
    ("rows", "nameless"),
    [
        (
            _HAIKU_TIER_ROWS
            + _SONNET_UP_ROW
            + "| (for prompts over 100,000 tokens) | "
            + " | ".join(_OVER_RATES)
            + " |\n",
            ["(for prompts over 100,000 tokens)", *_OVER_RATES],
        ),
        (
            _HAIKU_TIER_ROWS.replace(_OVER_NAME, "(for prompts over 200,000 tokens)"),
            ["(for prompts over 200,000 tokens)", *_OVER_RATES],
        ),
        (
            _HAIKU_TIER_ROWS.split("\n")[0]
            + "\n| (for prompts over 100,000 tokens) | $0.50 / MTok | $2.50 / MTok |\n",
            ["(for prompts over 100,000 tokens)", "$0.50 / MTok", "$2.50 / MTok"],
        ),
    ],
    ids=["two-candidate-twins", "other-threshold", "short-row"],
)
def test_unpaired_tier_text_row_raises_for_every_model(
    monkeypatch: pytest.MonkeyPatch, rows: str, nameless: list[str]
):
    # a nameless tier row pairs with a model only when exactly one full-width
    # row of that model carries the twin tier at the same threshold; any other
    # nameless row names no model, so every scrape fails loudly
    feed(monkeypatch, _TABLE + rows)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-opus-5-fast")
    assert str(exc.value) == f"row outside the pricing shape on {PAGE_URL}: {nameless!r}"


def test_tier_wording_error_prints_the_paren_as_the_page_writes_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # marks inside a drifted tier paren read as spaces for the parse, while
    # the error quotes the page's own bytes
    name = "Claude Haiku 5.5 (for prompts *above* 100,000 tokens)"
    paren = "(for prompts *above* 100,000 tokens)"
    fixture = FIXTURE.read_text()
    drifted = fixture.replace(_OVER_NAME, name, 1)
    assert drifted != fixture
    feed(monkeypatch, drifted)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == EXPECTED_IDS
    assert _skip_lines(caplog) == [f"detect skip for anthropic: {_wording_error(paren, name)}"]
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-haiku-5-5")
    assert str(exc.value) == _wording_error(paren, name)


_SONNET_4_5_ROW = "| Claude Sonnet 4.5 "


def _qualifier_error(paren: str, name: str) -> str:
    return (
        f"unread model qualifier {paren!r} in {name!r}: the paren names a model"
        " variant, not a prompt-length tier; fix: teach the anthropic detector the"
        " model this qualifier names"
    )


@pytest.mark.parametrize("paren", ["(1M token context)", "(prompt caching)"])
def test_model_qualifier_paren_names_itself_a_model_qualifier(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, paren: str
):
    # a qualifier naming a model variant is no tier wording, and
    # its fix is to teach the detector the model, never the tier parse
    name = f"Claude Sonnet 4.5 {paren}"
    fixture = FIXTURE.read_text()
    marked = fixture.replace(_SONNET_4_5_ROW, f"| {name} ", 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == _without("claude-sonnet-4-5")
    assert _skip_lines(caplog) == [f"detect skip for anthropic: {_qualifier_error(paren, name)}"]
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-sonnet-4-5")
    assert str(exc.value) == _qualifier_error(paren, name)


def test_link_annotation_drop_is_linear():
    # "([" x 8000 took 6.0 s per parse when the scan was quadratic
    name = "([" * 8000
    start = time.perf_counter()
    with pytest.raises(FetchError):
        detector.split_name(name, PAGE_URL)
    assert time.perf_counter() - start < 1.0


@pytest.mark.parametrize(
    ("page_name", "model_id"),
    [
        ("Claude Op*us 5", "claude-opus-5"),
        ("Claude Son_net 4.5", "claude-sonnet-4-5"),
        ("Claude Hai`ku 4.5", "claude-haiku-4-5"),
    ],
    ids=["asterisk-in-word", "underscore-in-word", "backtick-in-word"],
)
def test_mark_between_two_letters_joins_them(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, page_name: str, model_id: str
):
    # a mark inside a word used to split it and mint a fake id
    # ("claude-op-us-5") while the real model's absence counter ran
    plain = page_name.replace("*", "").replace("_", "").replace("`", "")
    fixture = FIXTURE.read_text()
    marked = fixture.replace(f"| {plain} ", f"| {page_name} ", 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == EXPECTED_IDS
    assert _skip_lines(caplog) == []
    assert scraper.scrape(cfg(), model_id) is not None


def _fast_scrapes(monkeypatch: pytest.MonkeyPatch, joint: str) -> None:
    noted = _FAST_TABLE.replace("Claude Opus 5 / Claude Opus 4.8", joint)
    fixture = FIXTURE.read_text()
    assert noted != _FAST_TABLE and _FAST_TABLE in fixture
    feed(monkeypatch, fixture.replace(_FAST_TABLE, noted))


def _fast_entries(model_id: str) -> tuple[dict[str, object], ...]:
    pricing = scraper.scrape(cfg(), model_id)
    assert pricing is not None, model_id
    return pricing.window_rates


def _run_log(caplog: pytest.LogCaptureFixture) -> list[str]:
    # the lines `ai-pricelog 2>&1 | tee /tmp/run.log` writes and the health
    # step reads back with splitlines(): basicConfig's format, each
    # exception record followed by its traceback
    formatter = logging.Formatter(logging.BASIC_FORMAT)
    return "\n".join(formatter.format(record) for record in caplog.records).splitlines()


def _names_no_model_warned(caplog: pytest.LogCaptureFixture, name: str) -> bool:
    return _fast_name_warning(name) in caplog.messages


def test_fast_name_joined_by_an_underscore_names_no_model(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # a mark between two letters joins them in the fast table too (cloudy,
    # 2026-10-19): "Claude_Opus" is one word, so that name names no model and warns
    _fast_scrapes(monkeypatch, "Claude_Opus 5 / Claude Opus 4.8")
    with caplog.at_level(logging.WARNING):
        assert _fast_entries("claude-opus-5") == ()
        assert _fast_entries("claude-opus-4-8") == (_FAST_ENTRY,)
    assert _names_no_model_warned(caplog, "Claude_Opus 5")


@pytest.mark.parametrize(
    ("joint", "odd_name"),
    [
        ("Claude Opus 5 / Claude Opus 4.８", "Claude Opus 4.８"),
        ("Claude Opus 5 / Claude Opus 4.8†", "Claude Opus 4.8†"),
    ],
    ids=["fullwidth-digit", "dagger"],
)
def test_fast_name_with_a_non_ascii_character_names_no_model(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, joint: str, odd_name: str
):
    # "4.８" slugged onto claude-opus-4 and stole a fast price;
    # any non-ASCII non-space character in a fast name's stem names no model
    # (cloudy, 2026-10-19), so the dagger spelling warns too
    _fast_scrapes(monkeypatch, joint)
    with caplog.at_level(logging.WARNING):
        assert _fast_entries("claude-opus-5") == (_FAST_ENTRY,)
        assert _fast_entries("claude-opus-4-8") == ()
        assert _fast_entries("claude-opus-4") == ()
    assert _names_no_model_warned(caplog, odd_name)


def test_fast_row_warns_for_each_name_that_matches_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # one matching name used to silence the warning for the other
    _fast_scrapes(monkeypatch, "Claude Opus 5 / Claude Opus 4.8 (legacy)")
    with caplog.at_level(logging.WARNING):
        assert _fast_entries("claude-opus-5") == (_FAST_ENTRY,)
    assert _names_no_model_warned(caplog, "Claude Opus 4.8 (legacy)")


def test_fast_mode_drop_line_reaches_a_health_annotation(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # the scrape-time "names no model" line matched no health rule,
    # so the dropped fast entry reached no ::warning:: and no issue body
    _fast_scrapes(monkeypatch, "Claude Cybertruck / Claude Semi")
    with caplog.at_level(logging.WARNING):
        assert _fast_entries("claude-opus-5") == ()
    lines = [line for line in _run_log(caplog) if "names no model" in line]
    assert lines
    assert health.parse_log(lines) == {"anthropic": {"hard": [], "soft": lines}}


def test_tier_wording_error_quotes_the_page_paren_past_a_trailing_mark(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # a mark after the paren used to print the mapped paren
    paren = "(for prompts *above* 100,000 tokens)"
    name = f"Claude Haiku 5.5 {paren}*"
    fixture = FIXTURE.read_text()
    drifted = fixture.replace(_OVER_NAME, name, 1)
    assert drifted != fixture
    feed(monkeypatch, drifted)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == EXPECTED_IDS
    assert _skip_lines(caplog) == [f"detect skip for anthropic: {_wording_error(paren, name)}"]
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-haiku-5-5")
    assert str(exc.value) == _wording_error(paren, name)


def test_nameless_tier_row_beside_a_complete_pair_raises_the_pair_error(
    monkeypatch: pytest.MonkeyPatch,
):
    # a nameless over-row beside Haiku 5.5's complete named
    # pair was skipped, so one of two conflicting over-tier rate sets priced
    # the model silently
    nameless = "(for prompts over 100,000 tokens)"
    extra = (
        f"| {nameless} | $0.60 / MTok | $0.75 / MTok | $1.20 / MTok | $0.06 / MTok | $3 / MTok |\n"
    )
    fixture = FIXTURE.read_text()
    over_line = next(line for line in fixture.splitlines() if line.startswith(f"| {_OVER_NAME}"))
    marked = fixture.replace(over_line + "\n", over_line + "\n" + extra, 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-haiku-5-5")
    assert str(exc.value) == (
        f"prompt-length tier rows for 'claude-haiku-5-5' on {PAGE_URL} are not one "
        f"'up to N' + 'over N' pair: found {[_UP_TO_NAME, _OVER_NAME, nameless]!r} beside 0 "
        "untiered row(s); fix: teach the anthropic scraper the page's tier layout"
    )
    assert scraper.scrape(cfg(), "claude-opus-5") is not None


@pytest.mark.parametrize(
    "char",
    ["‎", "‏", "­", "⁡", "⁦", "‪", "͏", "؜", "᠎"],
    ids=["lrm", "rlm", "shy", "fa", "lri", "lre", "cgj", "alm", "mvs"],
)
def test_format_character_before_a_name_keeps_the_model(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, char: str
):
    # these used to drop the model out of detection
    fixture = FIXTURE.read_text()
    marked = fixture.replace("| Claude Opus 5 ", f"| {char}Claude Opus 5 ", 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == EXPECTED_IDS
    assert _skip_lines(caplog) == []


def test_soft_hyphen_inside_a_word_joins_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    fixture = FIXTURE.read_text()
    marked = fixture.replace(_SONNET_4_5_ROW, "| Claude Son­net 4.5 ", 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == EXPECTED_IDS
    assert _skip_lines(caplog) == []


def test_zero_width_space_between_words_stays_a_space(monkeypatch: pytest.MonkeyPatch):
    # the five invisible characters keep reading as a space (one may stand in
    # for the space between words)
    fixture = FIXTURE.read_text()
    marked = fixture.replace("| Claude Opus 5 ", f"| Claude{_ZWSP}Opus 5 ", 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_soft_hyphen_between_version_digits_mints_no_glued_version(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # "Claude Opus 4_5" once minted claude-opus-45
    name = "Claude Opus 4­5"
    fixture = FIXTURE.read_text()
    marked = fixture.replace("| Claude Opus 4.5 ", f"| {name} ", 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    with caplog.at_level(logging.WARNING):
        ids = detector.detect(cfg())
    assert "claude-opus-45" not in ids
    assert ids == _without("claude-opus-4-5")
    assert len(_skip_lines(caplog)) == 1


def test_tier_error_prints_its_message_once_in_a_traceback(monkeypatch: pytest.MonkeyPatch):
    # the chained FetchError printed the same message twice
    name = "Claude Haiku 5.5 (for prompts beyond 100,000 tokens)"
    fixture = FIXTURE.read_text()
    drifted = fixture.replace(_OVER_NAME, name, 1)
    assert drifted != fixture
    feed(monkeypatch, drifted)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-haiku-5-5")
    message = str(exc.value)
    assert "".join(traceback.format_exception(exc.value)).count(message) == 1


@pytest.mark.parametrize(
    ("page_name", "plain", "model_id"),
    [
        ("Claude Op­­us 5", "Claude Opus 5", "claude-opus-5"),
        ("Claude Op*­us 5", "Claude Opus 5", "claude-opus-5"),
        ("Claude Op­͏us 5", "Claude Opus 5", "claude-opus-5"),
        ("Claude Op‎‎us 5", "Claude Opus 5", "claude-opus-5"),
        ("Claude Op**us 5", "Claude Opus 5", "claude-opus-5"),
        ("Claude Son__net 4.5", "Claude Sonnet 4.5", "claude-sonnet-4-5"),
        ("Claude Son``net 4.5", "Claude Sonnet 4.5", "claude-sonnet-4-5"),
        ("Claude Op**us** 5", "Claude Opus 5", "claude-opus-5"),
    ],
    ids=[
        "two-soft-hyphens",
        "asterisk-then-soft-hyphen",
        "soft-hyphen-then-cgj",
        "two-lrm",
        "double-asterisk",
        "double-underscore",
        "double-backtick",
        "bold-tail-of-a-word",
    ],
)
def test_run_of_marks_between_two_letters_joins_them(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    page_name: str,
    plain: str,
    model_id: str,
):
    # a run of two or more marks inside a word split it into
    # a fake id (claude-op-us-5) with no warning; the run joins like one mark
    fixture = FIXTURE.read_text()
    marked = fixture.replace(f"| {plain} ", f"| {page_name} ", 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == EXPECTED_IDS
    assert _skip_lines(caplog) == []
    assert scraper.scrape(cfg(), model_id) is not None


@pytest.mark.parametrize(
    ("paren", "qualifier"),
    [
        ("(1M tokens context)", True),
        ("(1M context tokens)", True),
        ("(prompts cached)", True),
        ("(for prompt over 200K token)", False),
        ("(prompt over 100k)", False),
    ],
    ids=["tokens-context", "context-tokens", "prompts-cached", "singular-over", "prompt-over"],
)
def test_comparison_word_tells_a_tier_wording_from_a_model_qualifier(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, paren: str, qualifier: bool
):
    # a paren holding a comparison (up to, over, above, under, below, beyond,
    # more/less than, exceed, < > ≤ ≥) is a drifted tier wording; any other
    # prompt/token paren is a model qualifier (cloudy, 2026-10-19)
    name = f"Claude Sonnet 4.5 {paren}"
    expected = _qualifier_error(paren, name) if qualifier else _wording_error(paren, name)
    fixture = FIXTURE.read_text()
    marked = fixture.replace(_SONNET_4_5_ROW, f"| {name} ", 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == _without("claude-sonnet-4-5")
    assert _skip_lines(caplog) == [f"detect skip for anthropic: {expected}"]
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-sonnet-4-5")
    assert str(exc.value) == expected


@pytest.mark.parametrize(
    "tail",
    # a bare trailing raw NBSP never reaches the parse (the markdown table
    # reader strips cell whitespace), so the raw NBSP sits before a mark
    [" *", " ([n](https://x))", "&nbsp;", "&#42;", " *"],
    ids=[
        "space-then-mark",
        "trailing-annotation",
        "nbsp-entity",
        "mark-entity",
        "raw-nbsp-then-mark",
    ],
)
def test_tier_wording_error_quotes_the_page_paren_whatever_follows(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tail: str
):
    # whitespace, an entity or an annotation after the paren
    # still made the message print the mapped paren
    paren = "(for prompts *above* 100,000 tokens)"
    name = f"Claude Haiku 5.5 {paren}{tail}"
    fixture = FIXTURE.read_text()
    drifted = fixture.replace(_OVER_NAME, name, 1)
    assert drifted != fixture
    feed(monkeypatch, drifted)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-haiku-5-5")
    assert str(exc.value) == _wording_error(paren, name)


def test_unshaped_unknown_fast_name_beside_a_known_one_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # "Opus 4.8" (no "Claude") dropped opus-4-8's fast price
    # with no warning
    _fast_scrapes(monkeypatch, "Claude Opus 5 / Opus 4.8")
    with caplog.at_level(logging.WARNING):
        assert _fast_entries("claude-opus-5") == (_FAST_ENTRY,)
        assert _fast_entries("claude-opus-4-8") == ()
    assert _names_no_model_warned(caplog, "Opus 4.8")


def test_short_fast_row_warns_per_unknown_name_beside_a_known_one(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # a short row warned only when no name matched, with a
    # keyless line no health rule classed
    drifted = _FAST_TABLE + "| Claude Sonnet 5 / Claude Opus 4.８ | $1 / MTok |\n"
    fixture = FIXTURE.read_text()
    feed(monkeypatch, fixture.replace(_FAST_TABLE, drifted))
    with caplog.at_level(logging.WARNING):
        assert _fast_entries("claude-opus-5") == (_FAST_ENTRY,)
    assert _names_no_model_warned(caplog, "Claude Opus 4.８")
    lines = [line for line in _run_log(caplog) if "names no model" in line]
    assert health.parse_log(lines) == {"anthropic": {"hard": [], "soft": lines}}


def test_soft_hyphen_between_fast_version_digits_reads_like_an_underscore(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # invisible characters follow the join/space rule first, so "4­8" reads
    # as "4 8", like the ruled "4_8" (cloudy, 2026-10-19)
    _fast_scrapes(monkeypatch, "Claude Opus 5 / Claude Opus 4­8")
    with caplog.at_level(logging.WARNING):
        assert _fast_entries("claude-opus-4-8") == (_FAST_ENTRY,)
    assert caplog.messages == []


@pytest.mark.parametrize(
    ("row_name", "paren", "qualifier"),
    [
        (_OVER_NAME, "(for prompts *above* 100,000 tokens)", False),
        (_SONNET_4_5_ROW, "(1M token context)", True),
    ],
    ids=["tier-wording", "qualifier"],
)
def test_thick_space_entity_after_a_paren_fails_only_its_row(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    row_name: str,
    paren: str,
    qualifier: bool,
):
    # "&ThickSpace;" decodes to two characters and crashed every
    # anthropic detect and scrape with a TypeError
    base = "Claude Haiku 5.5" if row_name == _OVER_NAME else "Claude Sonnet 4.5"
    name = f"{base} {paren}&ThickSpace;"
    fixture = FIXTURE.read_text()
    old = row_name if row_name == _OVER_NAME else row_name.removeprefix("| ").rstrip()
    marked = fixture.replace(old, name, 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    expected = _qualifier_error(paren, name) if qualifier else _wording_error(paren, name)
    with caplog.at_level(logging.WARNING):
        ids = detector.detect(cfg())
    assert _skip_lines(caplog) == [f"detect skip for anthropic: {expected}"]
    assert "claude-opus-5" in ids
    assert scraper.scrape(cfg(), "claude-opus-5") is not None


@pytest.mark.parametrize(
    "paren",
    [
        "(for prompts &gt; 100,000 tokens)",
        "(for prompts &#62; 100,000 tokens)",
        "(for prompts &ge; 100,000 tokens)",
        "(for prompts &lt;= 100,000 tokens)",
        "(for prompts ab*ove 100,000 tokens)",
        "(for prompts ab**ove 100,000 tokens)",
        "(for prompts un*der 100,000 tokens)",
        "(for prompts *more* than 100,000 tokens)",
        "(for prompts more *than* 100,000 tokens)",
        "(for prompts up&nbsp;to 100,000 tokens total)",
        "(for prompts up​to 100,000 tokens total)",
        "(for prompts > 100,000 tokens)",
        "(for prompts ≥ 100,000 tokens)",
        "(for prompts below 100,000 tokens)",
        "(for prompts less than 100,000 tokens)",
    ],
)
def test_comparison_read_after_entities_and_marks_is_a_tier_wording(
    monkeypatch: pytest.MonkeyPatch, paren: str
):
    # the comparison test ran on the page bytes, so an entity
    # or a mark inside the comparison word gave the qualifier message
    name = f"Claude Haiku 5.5 {paren}"
    fixture = FIXTURE.read_text()
    drifted = fixture.replace(_OVER_NAME, name, 1)
    assert drifted != fixture
    feed(monkeypatch, drifted)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-haiku-5-5")
    assert str(exc.value) == _wording_error(paren, name)


@pytest.mark.parametrize("paren", ["(1M token <em>context</em>)", "(prompt caching<br>)"])
def test_markup_angle_brackets_are_no_comparison(monkeypatch: pytest.MonkeyPatch, paren: str):
    # a tag's "<" or ">" is markup, not a
    # comparison, so the paren stays a model qualifier
    name = f"Claude Sonnet 4.5 {paren}"
    fixture = FIXTURE.read_text()
    marked = fixture.replace(_SONNET_4_5_ROW, f"| {name} ", 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-sonnet-4-5")
    assert str(exc.value) == _qualifier_error(paren, name)


def test_trailing_entity_strip_is_linear():
    # a quadratic strip took 2.1 s per parse at 16000 trailing entities; 64000
    # keeps it red on a runner several times faster (27.7 s quadratic vs
    # 0.16 s linear)
    name = "Claude Haiku 5.5 (for prompts above 100,000 tokens)" + "&#42;" * 64000
    start = time.perf_counter()
    with pytest.raises(FetchError):
        detector.split_name(name, PAGE_URL)
    assert time.perf_counter() - start < 1.0


@pytest.mark.parametrize(
    "paren",
    [
        "(for prompts *above* 100,000 tokens&#41;",
        "(for prompts (*above*) 100,000 tokens&#41;",
    ],
    ids=["entity-close", "inner-paren-before-entity-close"],
)
def test_tier_wording_error_quotes_a_paren_closed_by_an_entity(
    monkeypatch: pytest.MonkeyPatch, paren: str
):
    # a close paren spelled "&#41;" printed the mapped paren;
    # the quote runs from the outer "(", past an inner pair
    name = f"Claude Haiku 5.5 {paren}"
    fixture = FIXTURE.read_text()
    drifted = fixture.replace(_OVER_NAME, name, 1)
    assert drifted != fixture
    feed(monkeypatch, drifted)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-haiku-5-5")
    assert str(exc.value) == _wording_error(paren, name)


@pytest.mark.parametrize(
    "second_name",
    [
        "Claude Opus 9 names no model in the pricing table for openai",
        "Claude Opus 9 names no model in the pricing table for openai on x",
    ],
    ids=["phrase", "phrase-with-url-tail"],
)
def test_fast_name_holding_the_health_phrase_keeps_the_anthropic_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, second_name: str
):
    # the page-controlled name sits before "for <key>", so a name holding the
    # phrase picked the health key; with an "on <url>" tail the key must still
    # be the line's own last "for <key> on <url>"
    _fast_scrapes(monkeypatch, f"Claude Opus 5 / {second_name}")
    with caplog.at_level(logging.WARNING):
        assert _fast_entries("claude-opus-5") == (_FAST_ENTRY,)
    lines = [line for line in _run_log(caplog) if "names no model" in line]
    assert lines
    assert health.parse_log(lines) == {"anthropic": {"hard": [], "soft": lines}}


def test_one_of_the_five_splits_a_run_of_marks(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # the five keep reading as a space and split a run, so
    # "Claude*" + ZWSP + "Opus" reads as two words
    fixture = FIXTURE.read_text()
    marked = fixture.replace("| Claude Opus 5 ", f"| Claude*{_ZWSP}Opus 5 ", 1)
    assert marked != fixture
    feed(monkeypatch, marked)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == EXPECTED_IDS
    assert _skip_lines(caplog) == []


_PIPELINE_LOG = logging.getLogger("ai_pricelog.pipeline")

# the prefix `gh run view --log` puts before every line of a previous run's
# log (measured on autopr run 39241446184): job, step, timestamp
_GH_PREFIX = "run\trun watchdog\t2026-10-19T11:04:14.0922384Z "


def _pipeline_pass() -> None:
    # the lines pipeline.run logs for anthropic: a raising detect, a raising
    # scrape of a detected id, a raising refresh scrape of a stored id
    try:
        ids = detector.detect(cfg())
    except Exception:
        _PIPELINE_LOG.exception("detector for %s failed", "anthropic")
        return
    for model_id in EXPECTED_IDS:
        try:
            scraper.scrape(cfg(), model_id)
        except Exception:
            if model_id in ids:
                _PIPELINE_LOG.exception("scraper %s failed for %s", "anthropic", model_id)
            else:
                _PIPELINE_LOG.exception("refresh scrape failed for %s (%s)", model_id, "anthropic")


_FORGED_PHRASES = [
    "names no model in the pricing table for openai on x",
    "detector for openai failed",
    "scraper openai failed for x",
    "parse skip for openai: x",
    "detect skip for openai: x",
    "entry x failed validation for openai: y",
]


@pytest.mark.parametrize("prefix", ["", _GH_PREFIX], ids=["run-log", "gh-log"])
@pytest.mark.parametrize("phrase", _FORGED_PHRASES)
def test_page_text_in_a_model_row_never_names_the_health_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, phrase: str, prefix: str
):
    # a health rule matched anywhere in a line, so page text in a detect-skip
    # line or a traceback line picked another provider's key; an extra cell
    # puts the row outside the model-table shape, so the phrase rides both
    fixture = FIXTURE.read_text()
    row = next(line for line in fixture.splitlines() if line.startswith("| Claude Opus 5 "))
    feed(monkeypatch, fixture.replace(row, row + f" {phrase} |", 1))
    with caplog.at_level(logging.WARNING):
        _pipeline_pass()
    run_log = _run_log(caplog)
    assert any(
        line.startswith("WARNING:") and "detect skip for anthropic:" in line and phrase in line
        for line in run_log
    )
    issues = health.parse_log([prefix + line for line in run_log])
    assert set(issues) == {"anthropic"}


@pytest.mark.parametrize("prefix", ["", _GH_PREFIX], ids=["run-log", "gh-log"])
@pytest.mark.parametrize("phrase", _FORGED_PHRASES)
def test_page_text_in_a_fast_name_never_names_the_health_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, phrase: str, prefix: str
):
    # the page-written name sits before the fast-name rule's
    # phrase, so an earlier rule's phrase inside it won the first match
    _fast_scrapes(monkeypatch, f"Claude Opus 5 / Claude {phrase}")
    with caplog.at_level(logging.WARNING):
        _pipeline_pass()
    issues = health.parse_log([prefix + line for line in _run_log(caplog)])
    assert set(issues) == {"anthropic"}


@pytest.mark.parametrize("prefix", ["", _GH_PREFIX], ids=["run-log", "gh-log"])
def test_page_text_never_forges_the_checked_or_hold_line(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, prefix: str
):
    # page text read as the run's own line reaches beyond _RULES too: the
    # checked-set and hold markers were
    # found anywhere in a line, so a page-written name could stand in for the
    # run's own checked line (closing the wrong issues) or fake a hold
    _fast_scrapes(
        monkeypatch,
        f"Claude Opus 5 / Claude {health.CHECKED_PROVIDERS} openai"
        f" / Claude {health.HOLD_PENDING_SCAN} / Claude {health.HOLD_SEED_PR}",
    )
    with caplog.at_level(logging.WARNING):
        _pipeline_pass()
        _PIPELINE_LOG.warning("%s anthropic deepseek", health.CHECKED_PROVIDERS)
    lines = [prefix + line for line in _run_log(caplog)]
    assert health.checked_providers(lines) == frozenset({"anthropic", "deepseek"})
    assert health.hold_reason(lines) is None


_HUGE_DECIMAL_REF = "&#" + "9" * 5000 + ";"


_ZERO_PADDED_REF = "&#" + "0" * 5000 + "65;"
_HUGE_THRESHOLD_NAME = "Claude Haiku 5.5 (for prompts over " + "1" * 5000 + " tokens)"


@pytest.mark.parametrize(
    ("old", "new", "model_id", "error"),
    [
        (
            "| Claude Opus 5 ",
            f"| Claude Opus 5 {_HUGE_DECIMAL_REF} ",
            "claude-opus-5",
            _name_error(f"Claude Opus 5 {_HUGE_DECIMAL_REF}"),
        ),
        (
            "| Claude Opus 5 ",
            f"| Claude Opus 5 {_ZERO_PADDED_REF} ",
            "claude-opus-5",
            _name_error(f"Claude Opus 5 {_ZERO_PADDED_REF}"),
        ),
        (
            _OVER_NAME,
            _HUGE_THRESHOLD_NAME,
            "claude-haiku-5-5",
            "unreadable prompt-length tier threshold '" + "1" * 5000,
        ),
    ],
    ids=["decimal-ref", "zero-padded-decimal-ref", "tier-threshold"],
)
def test_huge_number_in_a_model_name_fails_only_its_row(
    monkeypatch: pytest.MonkeyPatch, old: str, new: str, model_id: str, error: str
):
    # past 4,300 digits int() raises ValueError, which no FetchError handler
    # catches, so the provider dropped for the run; the row reads like any
    # out-of-range number instead: its own model fails loud, every other prices
    fixture = FIXTURE.read_text()
    drifted = fixture.replace(old, new, 1)
    assert drifted != fixture
    feed(monkeypatch, drifted)
    ids = detector.detect(cfg())
    assert "claude-sonnet-4-5" in ids
    # an unreadable name leaves detection; a bad tier threshold fails the scrape only
    assert (model_id in ids) is (new == _HUGE_THRESHOLD_NAME)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), model_id)
    assert str(exc.value).startswith(error)
    _scrape_every_model()
    assert scraper.scrape(cfg(), "claude-sonnet-4-5") is not None


def test_rate_past_a_sane_length_fails_the_scrape(monkeypatch: pytest.MonkeyPatch):
    # a rate of 33 or more characters is no price the page means: a 40-digit
    # amount would price at 1e34 per token
    fixture = FIXTURE.read_text()
    row = next(line for line in fixture.splitlines() if line.startswith("| Claude Opus 5 "))
    huge = "$" + "9" * 40 + " / MTok"
    drifted = fixture.replace(row, row.replace("$25 / MTok", huge), 1)
    assert drifted != fixture
    feed(monkeypatch, drifted)
    with pytest.raises(FetchError) as exc:
        scraper.scrape(cfg(), "claude-opus-5")
    assert str(exc.value).startswith(f"unreadable rate {huge!r} for claude-opus-5 on {PAGE_URL}")


def _scrape_every_model() -> None:
    # a scrape may fail loud (FetchError); any other exception fails the test
    for model_id in EXPECTED_IDS:
        with contextlib.suppress(FetchError):
            scraper.scrape(cfg(), model_id)


@pytest.mark.parametrize(
    "joint",
    [
        f"Claude Opus 5 / Claude Opus 4.8 {_HUGE_DECIMAL_REF}",
        "Claude Opus 5 (for prompts over " + "1" * 5000 + " tokens) / Claude Opus 4.8",
    ],
    ids=["decimal-ref", "tier-threshold"],
)
def test_huge_number_in_a_fast_name_never_crashes_a_scrape(
    monkeypatch: pytest.MonkeyPatch, joint: str
):
    # the fast cell is read by every scrape, so its ValueError
    # crashed every model's scrape, not only the named models'
    _fast_scrapes(monkeypatch, joint)
    _scrape_every_model()
    assert scraper.scrape(cfg(), "claude-sonnet-4-5") is not None

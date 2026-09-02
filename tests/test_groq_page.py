"""groq pricing pair tests, pinned against the saved live models page."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import groq_page as detector
from ai_pricelog.scrapers import groq_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://console.groq.com/docs/models.md"
FIXTURE = Path(__file__).parent / "fixtures" / "groq_page" / "models.md"

# every fixture row that carries a per-token rate, page order; ContactSales,
# per-hour (whisper), per-character (orpheus), and unpriced rows are skipped
EXPECTED_IDS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "meta-llama/llama-prompt-guard-2-22m",
    "meta-llama/llama-prompt-guard-2-86m",
    "openai/gpt-oss-safeguard-20b",
    "qwen/qwen3.6-27b",
    "qwen/qwen3.8-27b",
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="groq",
        provider="Groq",
        detector="groq_page",
        detector_url=PAGE_URL,
        scraper="groq_page",
        scraper_url=PAGE_URL,
    )


def feed(monkeypatch: pytest.MonkeyPatch, text: str | None = None) -> None:
    monkeypatch.setattr(detector, "fetch_text", lambda url: text or FIXTURE.read_text())
    monkeypatch.setattr(scraper, "fetch_text", lambda url: text or FIXTURE.read_text())


_TABLE_HEADER = (
    "| MODEL ID | SPEED (T/SEC) | PRICE PER 1M TOKENS | RATE LIMITS (DEVELOPER PLAN)"
    " | CONTEXT WINDOW (TOKENS) | MAX COMPLETION TOKENS | MAX FILE SIZE |\n"
    "| --- | --- | --- | --- | --- | --- | --- |\n"
)


def table(*rows: str) -> str:
    return _TABLE_HEADER + "".join(rows)


def row(model_cell: str, price: str, context: str = "131,072") -> str:
    return f"| {model_cell} | 500 | {price} | 250K TPM | {context} | 65,536 | - |\n"


def test_detect_ids(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch)
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_detect_skips_unpriced_rows(monkeypatch: pytest.MonkeyPatch):
    # ContactSales, per-hour, per-character, and unpriced rows carry no
    # per-token rate and are skipped, not emitted
    text = table(
        row(
            "[Sales](/docs/model/llama-3.1-8b-instant)Enterprisellama-3.1-8b-instant",
            "ContactSales",
        ),
        row("[Whisper](/docs/model/whisper-large-v3)whisper-large-v3", "$0.111 per hour"),
        row(
            "[Orpheus](/docs/model/canopylabs/orpheus-v1-english)canopylabs/orpheus-v1-english",
            "$22.00 per 1M characters",
        ),
        row("[Compound](/docs/compound/systems/compound)groq/compound", "-"),
        row(
            "[GPT OSS 120B](/docs/model/openai/gpt-oss-120b)openai/gpt-oss-120b",
            "$0.15 input$0.60 output",
        ),
    )
    feed(monkeypatch, text)
    assert detector.detect(cfg()) == ["openai/gpt-oss-120b"]


def test_detect_badge_row_parses_clean_id(monkeypatch: pytest.MonkeyPatch):
    # the Enterprise badge glues onto the api id in the fixture; a priced
    # badge row must emit the clean id
    text = table(
        row(
            "[Llama 3.1 8B](/docs/model/llama-3.1-8b-instant)Enterprisellama-3.1-8b-instant",
            "$0.10 input$0.20 output",
        )
    )
    feed(monkeypatch, text)
    assert detector.detect(cfg()) == ["llama-3.1-8b-instant"]


def test_detect_unpriced_row_without_link_is_skipped(monkeypatch: pytest.MonkeyPatch):
    # unpriced rows are never id-parsed, so a linkless ContactSales row
    # cannot break the run
    text = table(
        row("llama-solo", "ContactSales"),
        row(
            "[GPT OSS 120B](/docs/model/openai/gpt-oss-120b)openai/gpt-oss-120b",
            "$0.15 input$0.60 output",
        ),
    )
    feed(monkeypatch, text)
    assert detector.detect(cfg()) == ["openai/gpt-oss-120b"]


def test_detect_priced_row_without_link_skips_with_warning(monkeypatch: pytest.MonkeyPatch, caplog):
    # a priced row whose model cell carries no link is additive drift: the
    # run skips it with a warning and keeps the well-shaped rows
    text = table(
        row("openai/gpt-oss-120b", "$0.15 input$0.60 output"),
        row(
            "[GPT OSS 20B](/docs/model/openai/gpt-oss-20b)openai/gpt-oss-20b",
            "$0.075 input$0.30 output",
        ),
    )
    feed(monkeypatch, text)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["openai/gpt-oss-20b"]
    assert "detect skip for groq" in caplog.text
    assert "model cell without a model link" in caplog.text


def test_detect_odd_row_shape_skips_with_warning(monkeypatch: pytest.MonkeyPatch, caplog):
    # a row outside the seven-cell shape is additive drift: the run skips
    # it with a warning and keeps the well-shaped rows
    text = table(
        "| [Odd](/docs/model/x)x | 500 | $0.15 input$0.60 output |\n",
        row(
            "[GPT OSS 20B](/docs/model/openai/gpt-oss-20b)openai/gpt-oss-20b",
            "$0.075 input$0.30 output",
        ),
    )
    feed(monkeypatch, text)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["openai/gpt-oss-20b"]
    assert "detect skip for groq" in caplog.text
    assert "outside the pricing shape" in caplog.text


def test_detect_header_wording_drift_still_locates_table(monkeypatch: pytest.MonkeyPatch):
    # the header pin folds case, whitespace, and &/and: casing drift on the
    # live page must not read as a missing table
    text = _TABLE_HEADER.lower() + "".join(
        row(
            "[GPT OSS 20B](/docs/model/openai/gpt-oss-20b)openai/gpt-oss-20b",
            "$0.075 input$0.30 output",
        )
    )
    feed(monkeypatch, text)
    assert detector.detect(cfg()) == ["openai/gpt-oss-20b"]


def test_detect_missing_table_raises(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch, "| Concept | Details |\n| --- | --- |\n| a | b |\n")
    with pytest.raises(FetchError, match="no per-token pricing table"):
        detector.detect(cfg())


def test_detect_no_priced_rows_raises(monkeypatch: pytest.MonkeyPatch):
    text = table(
        row("[Llama 3.1 8B](/docs/model/llama-3.1-8b-instant)llama-3.1-8b-instant", "ContactSales")
    )
    feed(monkeypatch, text)
    with pytest.raises(FetchError, match="no per-token model rows"):
        detector.detect(cfg())


def test_detect_unknown_price_cell_skips_with_warning(monkeypatch: pytest.MonkeyPatch, caplog):
    # a drifted price-cell shape is additive drift: the row skips with a
    # warning naming the cell, and the well-shaped rows still emit
    text = table(
        row(
            "[GPT OSS 120B](/docs/model/openai/gpt-oss-120b)openai/gpt-oss-120b",
            "$0.15 per 1M input",
        ),
        row(
            "[GPT OSS 20B](/docs/model/openai/gpt-oss-20b)openai/gpt-oss-20b",
            "$0.075 input$0.30 output",
        ),
    )
    feed(monkeypatch, text)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["openai/gpt-oss-20b"]
    assert "detect skip for groq" in caplog.text
    assert "unreadable price cell" in caplog.text


def test_detect_zero_rate_rows_emitted(monkeypatch: pytest.MonkeyPatch):
    # zero-rate rows are still emitted: a stored model whose row turns free
    # must stay mapped, or absence would count it and open a phantom
    # delisting (the F1 hazard again); the scraper decides instead
    text = table(
        row("[Free](/docs/model/llama-3.1-8b-instant)llama-3.1-8b-instant", "$0 input$0 output"),
        row(
            "[Half](/docs/model/llama-3.3-70b-versatile)llama-3.3-70b-versatile",
            "$0 input$0.30 output",
        ),
        row(
            "[GPT OSS 120B](/docs/model/openai/gpt-oss-120b)openai/gpt-oss-120b",
            "$0.15 input$0.60 output",
        ),
    )
    feed(monkeypatch, text)
    assert detector.detect(cfg()) == [
        "llama-3.1-8b-instant",
        "llama-3.3-70b-versatile",
        "openai/gpt-oss-120b",
    ]


def test_detect_lowercase_badge_row_parses_clean_id(monkeypatch: pytest.MonkeyPatch):
    # a lowercase glued badge must strip like an uppercase one, never emit
    # as an invented id
    text = table(
        row(
            "[X](/docs/model/llama-3.1-8b-instant)betallama-3.1-8b-instant",
            "$0.10 input$0.20 output",
        )
    )
    feed(monkeypatch, text)
    assert detector.detect(cfg()) == ["llama-3.1-8b-instant"]


def test_parse_id_strips_badge():
    cell = "[Llama 3.1 8B](/docs/model/llama-3.1-8b-instant)Enterprisellama-3.1-8b-instant"
    assert detector.parse_id(cell, PAGE_URL) == "llama-3.1-8b-instant"


def test_parse_id_strips_lowercase_badge():
    cell = "[X](/docs/model/llama-3.1-8b-instant)betallama-3.1-8b-instant"
    assert detector.parse_id(cell, PAGE_URL) == "llama-3.1-8b-instant"


def test_parse_id_keeps_namespaced_tail():
    cell = "[GPT OSS 120B](/docs/model/openai/gpt-oss-120b)openai/gpt-oss-120b"
    assert detector.parse_id(cell, PAGE_URL) == "openai/gpt-oss-120b"


def test_parse_id_without_link_raises():
    with pytest.raises(FetchError, match="model cell without a model link"):
        detector.parse_id("llama-3.1-8b-instant", PAGE_URL)


def test_scrape_gpt_oss_120b(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch)
    pricing = scraper.scrape(cfg(), "openai/gpt-oss-120b")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.15 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.60 / 1e6)
    assert pricing.mode == "chat"
    assert pricing.max_tokens_in == 131072
    assert pricing.max_tokens_out == 65536
    assert pricing.cache_read_cost_per_token is None
    assert pricing.cache_write_cost_per_token is None
    assert pricing.cache_write_1h_cost_per_token is None
    assert pricing.url == PAGE_URL


def test_scrape_gpt_oss_20b(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch)
    pricing = scraper.scrape(cfg(), "openai/gpt-oss-20b")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.075 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.30 / 1e6)
    assert pricing.max_tokens_in == 131072
    assert pricing.max_tokens_out == 65536


def test_scrape_qwen3_6_27b(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch)
    pricing = scraper.scrape(cfg(), "qwen/qwen3.6-27b")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.60 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(3.00 / 1e6)
    assert pricing.max_tokens_in == 131072
    assert pricing.max_tokens_out == 16384


def test_scrape_badge_row_uses_clean_id(monkeypatch: pytest.MonkeyPatch):
    text = table(
        row(
            "[Llama 3.1 8B](/docs/model/llama-3.1-8b-instant)Enterprisellama-3.1-8b-instant",
            "$0.10 input$0.20 output",
        )
    )
    feed(monkeypatch, text)
    pricing = scraper.scrape(cfg(), "llama-3.1-8b-instant")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.10 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.20 / 1e6)


def test_scrape_contact_sales_model_returns_none(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch)
    assert scraper.scrape(cfg(), "llama-3.1-8b-instant") is None


def test_scrape_both_zero_rates_price_zero(monkeypatch: pytest.MonkeyPatch):
    # free is a price: a fully free row scrapes as a 0.0/0.0 pair, never None
    text = table(
        row("[Free](/docs/model/llama-3.1-8b-instant)llama-3.1-8b-instant", "$0 input$0 output")
    )
    feed(monkeypatch, text)
    pricing = scraper.scrape(cfg(), "llama-3.1-8b-instant")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.0
    assert pricing.output_cost_per_token == 0.0


def test_scrape_partial_zero_returns_pricing(monkeypatch: pytest.MonkeyPatch):
    # a zero input beside a priced output scrapes normally (the google
    # embeddings convention)
    text = table(
        row(
            "[Half](/docs/model/llama-3.3-70b-versatile)llama-3.3-70b-versatile",
            "$0 input$0.30 output",
        )
    )
    feed(monkeypatch, text)
    pricing = scraper.scrape(cfg(), "llama-3.3-70b-versatile")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.0
    assert pricing.output_cost_per_token == pytest.approx(0.30 / 1e6)


def test_scrape_unknown_model_returns_none(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch)
    assert scraper.scrape(cfg(), "llama-3.3-70b-instruct") is None


def test_scrape_unreadable_token_count_raises(monkeypatch: pytest.MonkeyPatch):
    text = table(
        row(
            "[GPT OSS 120B](/docs/model/openai/gpt-oss-120b)openai/gpt-oss-120b",
            "$0.15 input$0.60 output",
            "lots",
        )
    )
    feed(monkeypatch, text)
    with pytest.raises(FetchError, match="unreadable token count 'lots'"):
        scraper.scrape(cfg(), "openai/gpt-oss-120b")


def test_scrape_matched_row_drifted_price_raises(monkeypatch: pytest.MonkeyPatch):
    # the matched row's price cell is strict: a drifted shape raises, it
    # must not read as the model missing
    text = table(
        row(
            "[GPT OSS 120B](/docs/model/openai/gpt-oss-120b)openai/gpt-oss-120b",
            "$0.15 per 1M input",
        )
    )
    feed(monkeypatch, text)
    with pytest.raises(FetchError, match="unreadable price cell"):
        scraper.scrape(cfg(), "openai/gpt-oss-120b")


def test_scrape_unrelated_linkless_row_tolerated(monkeypatch: pytest.MonkeyPatch):
    # a malformed model cell for another model is additive drift detection
    # already reported; the match scan passes it over instead of raising
    text = table(
        row("openai/gpt-oss-120b", "$0.15 input$0.60 output"),
        row(
            "[GPT OSS 20B](/docs/model/openai/gpt-oss-20b)openai/gpt-oss-20b",
            "$0.075 input$0.30 output",
        ),
    )
    feed(monkeypatch, text)
    pricing = scraper.scrape(cfg(), "openai/gpt-oss-20b")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.075 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.30 / 1e6)


def test_scrape_missing_table_raises(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch, "no tables at all here")
    with pytest.raises(FetchError, match="no per-token pricing table"):
        scraper.scrape(cfg(), "openai/gpt-oss-120b")

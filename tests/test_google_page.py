"""the google scraper's surface contract over the AI Studio markdown twin.

the watched surface is https://aistudio.google.com/docs/pricing.md (the old
ai.google.dev page 302s into an OAuth auto-signin chain). this file pins the
scraper's rate and error paths against the live-page fixture, plus the
detector's lead-in link guard; the live-page detector id list lives in
test_google_md_page.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import google_page as detector
from ai_pricelog.pricing import Pricing
from ai_pricelog.scrapers import google_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://aistudio.google.com/docs/pricing.md"
FIXTURE = Path(__file__).parent / "fixtures" / "google_page" / "pricing.md"


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="google",
        provider="Google",
        detector="google_page",
        detector_url=PAGE_URL,
        scraper="google_page",
        scraper_url=PAGE_URL,
    )


@pytest.fixture
def live_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve the fixture bytes through the scraper's text fetcher."""
    monkeypatch.setattr(scraper, "fetch_text", lambda url: FIXTURE.read_text(encoding="utf-8"))


def synthetic_page(section_body: str) -> str:
    return f'# Gemini Developer API pricing\n\n## Model  {{% id="gemini-x" %}}\n\n{section_body}\n'


def price_table(rows: list[str]) -> str:
    body = "\n\n---\n\n".join(rows)
    return (
        "{% table %}\n"
        "* Feature\n"
        "* Free Tier\n"
        "* Paid Tier, per 1M tokens in USD\n"
        "\n"
        "---\n"
        f"\n{body}\n"
        "{% /table %}"
    )


def row(label: str, cell: str) -> str:
    return f"* {label}\n* Not available\n* {cell}"


def test_scrape_gemini_4_argon_reads_the_standard_tab_two_step_rates(live_page):
    # the Standard tab carries the two-step cells (Batch prices 1.00/5.00 and
    # must not leak in); the first amount of each cell is the in-force rate
    pricing = scraper.scrape(cfg(), "gemini-4-argon")
    assert pricing is not None
    assert pricing.input_cost_per_token == 2.0 / 1e6
    assert pricing.output_cost_per_token == 10.0 / 1e6
    assert pricing.cache_read_cost_per_token == 0.10 / 1e6
    assert pricing.mode == "chat"
    assert pricing.max_tokens_in == 0
    assert pricing.window_rates == ()


def test_scrape_prefers_the_standard_tab_over_an_earlier_tab(monkeypatch):
    # Standard is the first tab in every live section, so the fixture alone
    # cannot tell a Standard rule from a first-table rule
    body = (
        "{% tabs %}\n"
        '  {% tab title="Batch" %}\n'
        + price_table([row("Input price", "$9.99")])
        + "\n  {% /tab %}\n"
        '  {% tab title="Standard" %}\n'
        + price_table([row("Input price", "$0.10")])
        + "\n  {% /tab %}\n"
        "{% /tabs %}"
    )
    monkeypatch.setattr(scraper, "fetch_text", lambda url: synthetic_page(body))
    pricing = scraper.scrape(cfg(), "gemini-x")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.10 / 1e6


def test_scrape_gemini_2_5_pro_long_context_override(live_page):
    # the "> 200k tokens" tier is the second amount in every cell; it emits
    # one min_tokens override at 200k carrying the long-tier per-1M rates
    pricing = scraper.scrape(cfg(), "gemini-2.5-pro")
    assert pricing is not None
    assert pricing.input_cost_per_token == 1.25 / 1e6  # base unchanged
    assert pricing.output_cost_per_token == 10 / 1e6
    assert pricing.cache_read_cost_per_token == 0.125 / 1e6
    assert pricing.window_rates == (
        {
            "min_tokens": 200_000,
            "input_mtok": 2.50,
            "output_mtok": 15.00,
            "cache_read_mtok": 0.25,
        },
    )


def test_scrape_customtools_second_slug_same_section(live_page):
    # the 3.1 Pro Preview section spells two ids; both resolve to the
    # section's Standard rates
    base = scraper.scrape(cfg(), "gemini-3.1-pro-preview")
    customtools = scraper.scrape(cfg(), "gemini-3.1-pro-preview-customtools")
    assert base == customtools
    assert base is not None
    assert base.input_cost_per_token == 2 / 1e6
    assert base.output_cost_per_token == 12 / 1e6
    assert base.cache_read_cost_per_token == 0.20 / 1e6
    assert base.window_rates == (
        {
            "min_tokens": 200_000,
            "input_mtok": 4.00,
            "output_mtok": 18.00,
            "cache_read_mtok": 0.40,
        },
    )


def test_scrape_image_model_output_takes_the_first_amount(live_page):
    # the image models' output cell leads with the text rate; the image and
    # per-image amounts that follow are not the output rate
    pricing = scraper.scrape(cfg(), "gemini-nano-banana-2.1")
    assert pricing is not None
    assert pricing.input_cost_per_token == 1.50 / 1e6
    assert pricing.output_cost_per_token == 7.50 / 1e6


def test_scrape_embedding_sections_price_input_only(live_page):
    # embeddings bill input tokens only: output rate 0 (litellm convention);
    # the embedding-2 input rate is the Text row, never the Image/Audio/Video
    # per-unit rows
    pricing = scraper.scrape(cfg(), "gemini-embedding-2")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.20 / 1e6
    assert pricing.output_cost_per_token == 0.0
    pricing = scraper.scrape(cfg(), "gemini-embedding-001")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.15 / 1e6
    assert pricing.output_cost_per_token == 0.0


def test_scrape_matches_link_text_not_heading_anchor(live_page):
    # the native-audio section's link text spells the api id; its heading
    # anchor is the shorter page slug and resolves nothing
    assert scraper.scrape(cfg(), "gemini-2.5-flash-native-audio") is None
    pricing = scraper.scrape(cfg(), "gemini-2.5-flash-native-audio-preview-12-2025")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.50 / 1e6
    assert pricing.output_cost_per_token == 2.0 / 1e6


def test_scrape_per_image_output_returns_none(live_page):
    # the 2.5 Flash Image output cell reads "$0.039 per image*": a per-image
    # unit, not a per-token output rate
    assert scraper.scrape(cfg(), "gemini-2.5-flash-image") is None


def test_scrape_no_caching_row_leaves_cache_read_unset(live_page):
    # the transcribe/live/tts/image sections carry no caching row; the
    # carried None path (the old file's test_scrape_cache_not_available_is_omitted)
    pricing = scraper.scrape(cfg(), "gemini-3.5-transcribe")
    assert pricing is not None
    assert pricing.input_cost_per_token == 2.0 / 1e6
    assert pricing.output_cost_per_token == 12.0 / 1e6
    assert pricing.cache_read_cost_per_token is None


def test_scrape_free_tier_returns_none(live_page):
    # gemma-4 carries no paid rates on the page
    assert scraper.scrape(cfg(), "gemma-4") is None


def test_scrape_unknown_model_returns_none(live_page):
    assert scraper.scrape(cfg(), "gemini-1.5-pro") is None


def test_scrape_context_window_comes_from_section_prose(live_page):
    # the 2.5-flash section description names a 1M token context window; no
    # other section names one
    pricing = scraper.scrape(cfg(), "gemini-2.5-flash")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.30 / 1e6
    assert pricing.output_cost_per_token == 2.50 / 1e6
    assert pricing.cache_read_cost_per_token == 0.03 / 1e6
    assert pricing.max_tokens_in == 1_000_000
    argon = scraper.scrape(cfg(), "gemini-4-argon")
    assert argon is not None
    assert argon.max_tokens_in == 0


def test_scrape_equals_pricing_shape(live_page):
    # the Pricing dataclass is the pipeline's contract: field-by-field
    assert scraper.scrape(cfg(), "gemini-3.5-flash-lite") == Pricing(
        input_cost_per_token=0.30 / 1e6,
        output_cost_per_token=2.50 / 1e6,
        mode="chat",
        max_tokens_in=0,
        cache_read_cost_per_token=0.03 / 1e6,
    )


def test_scrape_no_standard_tier_raises(monkeypatch):
    body = (
        "{% tabs %}\n"
        '  {% tab title="Batch" %}\n'
        + price_table([row("Input price", "$1.00")])
        + "\n  {% /tab %}\n"
        "{% /tabs %}"
    )
    monkeypatch.setattr(scraper, "fetch_text", lambda url: synthetic_page(body))
    with pytest.raises(FetchError, match="no Standard tier"):
        scraper.scrape(cfg(), "gemini-x")


def test_scrape_missing_paid_column_raises(monkeypatch):
    body = (
        "{% table %}\n"
        "* Feature\n"
        "* Free Tier\n"
        "\n"
        "---\n"
        "\n"
        "* Input price\n"
        "* Free of charge\n"
        "{% /table %}"
    )
    monkeypatch.setattr(scraper, "fetch_text", lambda url: synthetic_page(body))
    with pytest.raises(FetchError, match="no Paid Tier column"):
        scraper.scrape(cfg(), "gemini-x")


def test_scrape_malformed_amount_raises(monkeypatch):
    # a comma-decimal reads no amount and flags malformed (plan #22): a
    # silent skip would drop a rate the page carries
    monkeypatch.setattr(
        scraper,
        "fetch_text",
        lambda url: synthetic_page(price_table([row("Input price", "$0,14")])),
    )
    with pytest.raises(FetchError, match="unreadable rate"):
        scraper.scrape(cfg(), "gemini-x")


def test_scrape_second_long_tier_raises(monkeypatch):
    # an unmodeled multi-tier cell (two "> N" markers) raises instead of
    # silently dropping a rate
    body = price_table(
        [
            row(
                "Input price",
                "$1.00, prompts <= 200k tokens $2.00, prompts > 200k tokens"
                " $4.00, prompts > 1M tokens",
            )
        ]
    )
    monkeypatch.setattr(scraper, "fetch_text", lambda url: synthetic_page(body))
    with pytest.raises(FetchError, match="second long tier"):
        scraper.scrape(cfg(), "gemini-x")


def test_scrape_disagreeing_long_tier_thresholds_raise(monkeypatch):
    # one override carries one min_tokens: cells describing different tiers
    # (input > 200k, output > 1M) raise instead of merging
    body = price_table(
        [
            row("Input price", "$1.00, prompts <= 200k tokens $2.00, prompts > 200k tokens"),
            row("Output price", "$5.00, prompts <= 200k tokens $9.00, prompts > 1M tokens"),
        ]
    )
    monkeypatch.setattr(scraper, "fetch_text", lambda url: synthetic_page(body))
    with pytest.raises(FetchError, match="disagree on threshold"):
        scraper.scrape(cfg(), "gemini-x")


def test_detect_ignores_a_code_span_cross_link_after_the_table(monkeypatch):
    # the id scan stops at the section's first table block: a trailing
    # "pair with" code-span link must not emit the cross-linked model, whose
    # scrape would otherwise resolve to the host section's rates
    body = (
        price_table([row("Input price", "$0.10")])
        + "\nPair with [`gemini-other`](/docs/models/gemini-other) for the cheaper tier."
    )
    monkeypatch.setattr(detector, "fetch_text", lambda url: synthetic_page(body))
    assert detector.detect(cfg()) == ["gemini-x"]


def test_scrape_stray_dollar_before_the_amount_returns_none(monkeypatch):
    # `index("$" + amount)` pins the amount's own "$", so a stray "$" earlier
    # in the cell cannot shift where the amount ends and read a per-image
    # rate as a per-token one
    monkeypatch.setattr(
        scraper,
        "fetch_text",
        lambda url: synthetic_page(
            price_table(
                [
                    row("Input price", "$0.10"),
                    row("Output price", "$ (promo) $0.039 per image"),
                ]
            )
        ),
    )
    assert scraper.scrape(cfg(), "gemini-x") is None


def test_dedup_keys_ga_image_spellings():
    # the page dropped the -preview suffix at GA; the store holds the
    # preview spelling
    assert scraper.dedup_keys("gemini-3.1-flash-image") == ["gemini-3.1-flash-image-preview"]
    assert scraper.dedup_keys("gemini-3-pro-image") == ["gemini-3-pro-image-preview"]


def test_dedup_keys_dated_preview_spellings():
    assert scraper.dedup_keys("gemini-2.5-flash-native-audio-preview-12-2025") == [
        "gemini-live-2.5-flash"
    ]
    assert scraper.dedup_keys("gemini-2.5-flash-lite-preview-09-2025") == ["gemini-2.5-flash-lite"]


def test_dedup_keys_plain_ids_return_nothing():
    for page_id in ("gemini-4-argon", "gemini-2.5-flash-image", "gemini-embedding-001"):
        assert scraper.dedup_keys(page_id) == [], page_id

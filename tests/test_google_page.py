from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import google_page as detector
from ai_pricelog.pricing import Pricing
from ai_pricelog.scrapers import google_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://ai.google.dev/gemini-api/docs/pricing"
FIXTURE = Path(__file__).parent / "fixtures" / "google_page" / "pricing.html"

EXPECTED_IDS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-live-translate-preview",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-omni-flash-preview",
    "gemini-3.1-pro-preview",
    "gemini-3.1-pro-preview-customtools",
    "gemini-3.1-flash-live-preview",
    "gemini-3.1-flash-image",
    "gemini-3.1-flash-lite-image",
    "gemini-3.1-flash-tts-preview",
    "gemini-3-flash-preview",
    "gemini-3-pro-image",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash-lite-preview-09-2025",
    "gemini-2.5-flash-native-audio-preview-12-2025",
    "gemini-2.5-flash-image",
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-embedding-2",
    "gemini-embedding-001",
    "gemini-robotics-er-2-preview",
    "gemini-robotics-er-2-streaming-preview",
    "gemini-robotics-er-1.6-preview",
    "gemini-2.5-computer-use-preview-10-2025",
    "gemma-4",
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="google",
        provider="Google",
        detector="google_page",
        detector_url=PAGE_URL,
        scraper="google_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


@pytest.fixture
def live_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())


def synthetic_soup(body: str) -> BeautifulSoup:
    return BeautifulSoup(f"<article>{body}</article>", "html.parser")


def test_detect_lists_token_priced_models_in_page_order(live_page):
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_detect_excludes_non_token_sections(live_page):
    ids = detector.detect(cfg())
    # per-image/per-second/per-request sections and the tools/agents tables
    # are not token-priced and must not leak into detection
    for leaked in (
        "imagen-4.0-generate-001",
        "imagen-4.0-ultra-generate-001",
        "imagen-4.0-fast-generate-001",
        "veo-3.1-generate-preview",
        "veo-3.0-generate-001",
        "lyria-3-clip-preview",
    ):
        assert leaked not in ids


def test_detect_no_token_tables_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: synthetic_soup(
            "<table class='pricing-table'><tr><th></th><th>Free Tier</th>"
            "<th>Paid Tier, per second in USD</th></tr>"
            "<tr><td>Video price</td><td>Not available</td><td>$0.35</td></tr></table>"
        ),
    )
    with pytest.raises(FetchError, match="no token pricing tables"):
        detector.detect(cfg())


def test_detect_no_ids_raises(monkeypatch):
    # a token-shaped table under a heading with no id and no slug em yields
    # no ids: a parse failure, not a silent empty detection
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: synthetic_soup(
            "<h2>Model</h2><table class='pricing-table'>"
            "<tr><th></th><th>Free Tier</th><th>Paid Tier, per 1M tokens in USD</th></tr>"
            "<tr><td>Input price</td><td>Free of charge</td><td>$1</td></tr></table>"
        ),
    )
    with pytest.raises(FetchError, match="no model ids"):
        detector.detect(cfg())


def test_fetch_error_propagates(monkeypatch):
    def boom(url):
        raise FetchError(f"fetch failed for {url}")

    monkeypatch.setattr(detector, "fetch_soup", boom)
    with pytest.raises(FetchError, match=PAGE_URL):
        detector.detect(cfg())


def test_scrape_gemini_3_7_flash_exact(live_page):
    # promo cells list the current rate first; the first amount is the base rate
    pricing = scraper.scrape(cfg(), "gemini-3.7-flash")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.75 / 1e6
    assert pricing.output_cost_per_token == 3.75 / 1e6
    assert pricing.cache_read_cost_per_token == 0.075 / 1e6
    assert pricing.mode == "chat"
    assert pricing.max_tokens_in == pricing.max_tokens_out == 0


def test_scrape_gemini_2_5_flash_exact(live_page):
    # the section description carries a "1M token context window" mention
    pricing = scraper.scrape(cfg(), "gemini-2.5-flash")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.30 / 1e6
    assert pricing.output_cost_per_token == 2.50 / 1e6
    assert pricing.cache_read_cost_per_token == 0.03 / 1e6
    assert pricing.mode == "chat"
    assert pricing.max_tokens_in == 1_000_000


def test_scrape_gemini_2_5_pro_takes_base_input_tier(live_page):
    # the >200k tier is the later amount in the cell; the first is the base
    pricing = scraper.scrape(cfg(), "gemini-2.5-pro")
    assert pricing is not None
    assert pricing.input_cost_per_token == 1.25 / 1e6
    assert pricing.output_cost_per_token == 10 / 1e6
    assert pricing.cache_read_cost_per_token == 0.125 / 1e6


def test_scrape_customtools_second_slug_same_section(live_page):
    # the 3.1 Pro Preview section carries two slugs in one heading; both
    # resolve to the section's Standard rates
    pricing = scraper.scrape(cfg(), "gemini-3.1-pro-preview-customtools")
    assert pricing is not None
    assert pricing.input_cost_per_token == 2 / 1e6
    assert pricing.output_cost_per_token == 12 / 1e6


def test_scrape_matches_em_slug_not_h2_id(live_page):
    # the flash-lite-preview h2 anchors as gemini-2.5-flash-lite-preview but
    # its model slug is the dated one
    assert scraper.scrape(cfg(), "gemini-2.5-flash-lite-preview") is None
    pricing = scraper.scrape(cfg(), "gemini-2.5-flash-lite-preview-09-2025")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.10 / 1e6
    assert pricing.output_cost_per_token == 0.40 / 1e6


def test_scrape_cache_not_available_is_omitted(live_page):
    pricing = scraper.scrape(cfg(), "gemini-2.0-flash-lite")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.075 / 1e6
    assert pricing.output_cost_per_token == 0.30 / 1e6
    assert pricing.cache_read_cost_per_token is None


def test_scrape_embedding_sections_price_input_only(live_page):
    # embeddings bill input tokens only: output rate 0 (litellm convention)
    pricing = scraper.scrape(cfg(), "gemini-embedding-001")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.15 / 1e6)
    assert pricing.output_cost_per_token == 0.0
    assert pricing.cache_read_cost_per_token is None
    pricing = scraper.scrape(cfg(), "gemini-embedding-2")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.20 / 1e6)
    assert pricing.output_cost_per_token == 0.0


def test_scrape_free_tier_returns_none(live_page):
    # gemma-4 carries no paid rates on the page
    assert scraper.scrape(cfg(), "gemma-4") is None


def test_scrape_per_image_output_returns_none(live_page):
    # the 2.5 Flash Image output cell reads "$0.039 per image*": a per-image
    # unit, not a per-token output rate
    assert scraper.scrape(cfg(), "gemini-2.5-flash-image") is None


def test_scrape_unknown_model_returns_none(live_page):
    assert scraper.scrape(cfg(), "gemini-1.5-pro") is None


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
    for page_id in ("gemini-3.7-flash", "gemini-2.5-flash-image", "gemini-embedding-001"):
        assert scraper.dedup_keys(page_id) == [], page_id


def test_scrape_no_standard_tier_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: synthetic_soup(
            "<h2 id='gemini-x'><em><code>gemini-x</code></em></h2>"
            "<devsite-selector><section><h3>Batch</h3>"
            "<table class='pricing-table'>"
            "<tr><th></th><th>Free Tier</th><th>Paid Tier, per 1M tokens in USD</th></tr>"
            "<tr><td>Input price</td><td>Free of charge</td><td>$1</td></tr></table>"
            "</section></devsite-selector>"
        ),
    )
    with pytest.raises(FetchError, match="no Standard tier"):
        scraper.scrape(cfg(), "gemini-x")


def test_scrape_missing_paid_column_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: synthetic_soup(
            "<h2 id='gemini-x'><em><code>gemini-x</code></em></h2>"
            "<table class='pricing-table'>"
            "<tr><th></th><th>Free Tier</th></tr>"
            "<tr><td>Input price</td><td>Free of charge</td></tr></table>"
        ),
    )
    with pytest.raises(FetchError, match="no Paid Tier column"):
        scraper.scrape(cfg(), "gemini-x")


def test_scrape_equals_pricing_shape(live_page):
    # the Pricing dataclass is the pipeline's contract: field-by-field
    assert scraper.scrape(cfg(), "gemini-3.5-flash") == Pricing(
        input_cost_per_token=1.5 / 1e6,
        output_cost_per_token=9 / 1e6,
        mode="chat",
        max_tokens_in=0,
        cache_read_cost_per_token=0.15 / 1e6,
    )

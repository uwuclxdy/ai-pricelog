from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import novita_page as detector
from ai_pricelog.scrapers import novita_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://novita.ai/pricing"
FIXTURE = Path(__file__).parent / "fixtures" / "novita_page" / "pricing.html"

# the pinned pricing.html snapshot (2026-08-24) in page order. dash-vendor
# slugs resolve through the page's embedded flight state: zai-org/* and
# meta-llama/* must not split at the first dash, Sao10K keeps its page case.
EXPECTED_IDS = [
    "deepseek/deepseek-v4-pro-0813",
    "deepseek/deepseek-v4-flash-0731",
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-v4-pro",
    "deepseek/deepseek-v3.2",
    "deepseek/deepseek-ocr-2",
    "deepseek/deepseek-v3.2-exp",
    "deepseek/deepseek-v3.1-terminus",
    "deepseek/deepseek-v3.1",
    "deepseek/deepseek-v3-0324",
    "deepseek/deepseek-r1-0528",
    "deepseek/deepseek-r1-distill-llama-70b",
    "deepseek/deepseek-v3-turbo",
    "deepseek/deepseek-r1-turbo",
    "qwen/qwen3.8-max",
    "qwen/qwen3.7-max",
    "qwen/qwen3.6-27b",
    "qwen/qwen3.5-27b",
    "qwen/qwen3.5-122b-a10b",
    "qwen/qwen3.5-35b-a3b",
    "qwen/qwen3.5-397b-a17b",
    "qwen/qwen3-coder-next",
    "qwen/qwen3-vl-235b-a22b-thinking",
    "qwen/qwen3.6-35b-a3b",
    "qwen/qwen3-next-80b-a3b-instruct",
    "qwen/qwen3-vl-235b-a22b-instruct",
    "qwen/qwen3-max",
    "qwen/qwen3-coder-480b-a35b-instruct",
    "qwen/qwen3-coder-30b-a3b-instruct",
    "qwen/qwen3-235b-a22b-thinking-2507",
    "qwen/qwen3-235b-a22b-instruct-2507",
    "qwen/qwen-2.5-72b-instruct",
    "qwen/qwen3-235b-a22b-fp8",
    "qwen/qwen3-vl-30b-a3b-instruct",
    "qwen/qwen3-omni-30b-a3b-thinking",
    "qwen/qwen3-omni-30b-a3b-instruct",
    "qwen/qwen-mt-plus",
    "baidu/cobuddy",
    "baidu/ernie-4.5-vl-424b-a47b",
    "baidu/ernie-4.5-21B-a3b",
    "zai-org/glm-5.2",
    "zai-org/glm-5.1",
    "zai-org/glm-5",
    "zai-org/glm-4.7-flash",
    "zai-org/glm-4.7",
    "zai-org/autoglm-phone-9b-multilingual",
    "zai-org/glm-4.6v",
    "zai-org/glm-4.6",
    "zai-org/glm-4.5v",
    "zai-org/glm-4.5-air",
    "sao10k/l3-8b-lunaris",
    "Sao10K/L3-8B-Stheno-v3.2",
    "sao10k/l31-70b-euryale-v2.2",
    "moonshotai/kimi-k3",
    "moonshotai/kimi-k2.7-code",
    "moonshotai/kimi-k2.6",
    "moonshotai/kimi-k2.5",
    "moonshotai/kimi-k2-thinking",
    "moonshotai/kimi-k2-0905",
    "moonshotai/kimi-k2-instruct",
    "tencent/hy3",
    "mindai/macaron-v1-venti",
    "mindai/macaron-v1-tall",
    "minimax/minimax-m3",
    "minimax/minimax-m2.7",
    "minimax/minimax-m2.5-highspeed",
    "minimax/minimax-m2.5",
    "minimax/minimax-m2.1",
    "minimax/minimax-m2",
    "minimaxai/minimax-m1-80k",
    "inclusionai/ling-3.0-flash-fast",
    "inclusionai/ling-3.0-flash",
    "stepfun/step-3.7-flash",
    "nvidia/nemotron-3-nano-30b-a3b",
    "google/gemma-4-26b-a4b-it",
    "google/gemma-4-31b-it",
    "google/gemma-3-27b-it",
    "kwaipilot/kat-coder-pro",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "meta-llama/llama-3.1-8b-instruct",
    "meta-llama/llama-3.3-70b-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct-fp8",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "mistralai/mistral-nemo",
    "xiaomimimo/mimo-v2.5",
    "xiaomimimo/mimo-v2.5-pro",
    "microsoft/wizardlm-2-8x22b",
]


def make_cfg(url: str = PAGE_URL) -> ProviderCfg:
    return ProviderCfg(
        key="novita",
        provider="Novita",
        detector="novita_page",
        detector_url=url,
        scraper="novita_page",
        scraper_url=url,
    )


@pytest.fixture(autouse=True)
def fresh_page_cache():
    # _page caches (soup, canonical) per url for the pipeline's
    # detect-then-scrape pass; each test serves its own page, so the cache
    # must not leak across tests.
    detector._page.cache_clear()
    yield
    detector._page.cache_clear()


@pytest.fixture
def live_page(monkeypatch: pytest.MonkeyPatch) -> None:
    # the single fetch seam is the detector module's fetch_soup: the scraper
    # shares the detector's cached _page.
    def feed(url: str) -> BeautifulSoup:
        return BeautifulSoup(FIXTURE.read_text(), "html.parser")

    monkeypatch.setattr(detector, "fetch_soup", feed)


def card_html(
    slug: str,
    *,
    context: str | None = "1048576",
    input_amount: str | None = "1.00",
    cache_amount: str | None = None,
    output_amount: str | None = "2.00",
) -> str:
    rows = []
    if context is not None:
        rows.append(f"<dt>Context</dt><dd><span title='{context}'>1M</span></dd>")
    if input_amount is not None:
        spans = f"<span title='{input_amount}'>${input_amount} /Mt</span>"
        if cache_amount is not None:
            spans = (
                f"<span data-pricing-key='cache-read'>{spans}"
                f"<span>·</span> Cache Read <span title='{cache_amount}'>"
                f"${cache_amount} /Mt</span></span>"
            )
        rows.append(f"<dt>Input</dt><dd>{spans}</dd>")
    if output_amount is not None:
        rows.append(
            f"<dt>Output</dt><dd><span title='{output_amount}'>${output_amount} /Mt</span></dd>"
        )
    return (
        f"<article data-testid='model-section-mobile-card'>"
        f"<h4><a href='/models/model-detail/{slug}?from=pricing'>Model</a></h4>"
        f"<dl>{''.join(rows)}</dl></article>"
    )


def synthetic_page(*cards: str, flight: str = "") -> BeautifulSoup:
    return BeautifulSoup(f"<html><body>{''.join(cards)}{flight}</body></html>", "html.parser")


def test_detect_lists_priced_models_in_page_order(live_page):
    assert detector.detect(make_cfg()) == EXPECTED_IDS


def test_detect_resolves_dash_vendors_from_flight_state(live_page):
    # the href slug is the canonical id with "/" url-encoded as "-"; the
    # vendor boundary comes from the embedded flight state, so meta-llama
    # and zai-org must not split at the first dash, and Sao10K keeps its case
    ids = detector.detect(make_cfg())
    assert "meta-llama/llama-3.1-8b-instruct" in ids
    assert "zai-org/glm-5.2" in ids
    assert "Sao10K/L3-8B-Stheno-v3.2" in ids
    assert "meta/llama-llama-3.1-8b-instruct" not in ids
    assert "zai/org-glm-5.2" not in ids


def test_detect_falls_back_to_first_dash_without_flight_state(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: synthetic_page(card_html("foo-bar-baz")),
    )
    assert detector.detect(make_cfg()) == ["foo/bar-baz"]


def test_detect_uses_flight_id_over_first_dash(monkeypatch):
    flight = r'<script>self.__next_f.push([1,"{\"id\":\"vendor-x/model-y\"}"])</script>'
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: synthetic_page(card_html("vendor-x-model-y"), flight=flight),
    )
    assert detector.detect(make_cfg()) == ["vendor-x/model-y"]


def test_detect_dedupes_repeated_cards(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: synthetic_page(card_html("foo-bar"), card_html("foo-bar")),
    )
    assert detector.detect(make_cfg()) == ["foo/bar"]


def test_detect_no_model_cards_raises(monkeypatch):
    monkeypatch.setattr(
        detector, "fetch_soup", lambda url: BeautifulSoup("<html></html>", "html.parser")
    )
    with pytest.raises(FetchError, match="no model cards"):
        detector.detect(make_cfg())


def test_detect_cards_without_model_links_raise(monkeypatch):
    page = (
        "<html><body><article data-testid='model-section-mobile-card'>"
        "<h4>no link</h4></article></body></html>"
    )
    monkeypatch.setattr(detector, "fetch_soup", lambda url: BeautifulSoup(page, "html.parser"))
    with pytest.raises(FetchError, match="no model ids"):
        detector.detect(make_cfg())


def test_detect_propagates_fetch_error(monkeypatch):
    def boom(url: str) -> BeautifulSoup:
        raise FetchError(f"fetch failed for {url}")

    monkeypatch.setattr(detector, "fetch_soup", boom)
    with pytest.raises(FetchError, match=PAGE_URL):
        detector.detect(make_cfg())


def test_scrape_cache_read_model_exact(live_page):
    pricing = scraper.scrape(make_cfg(), "deepseek/deepseek-v4-pro-0813")
    assert pricing is not None
    assert pricing.input_cost_per_token == 1.32 / 1e6
    assert pricing.cache_read_cost_per_token == 0.132 / 1e6
    assert pricing.output_cost_per_token == 3.96 / 1e6
    assert pricing.max_tokens == 1048576
    assert pricing.mode == "chat"
    assert pricing.peak_input_cost_per_token is None


def test_scrape_model_without_cache_read(live_page):
    pricing = scraper.scrape(make_cfg(), "deepseek/deepseek-v3.2-exp")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.27 / 1e6
    assert pricing.cache_read_cost_per_token is None
    assert pricing.output_cost_per_token == 0.41 / 1e6
    assert pricing.max_tokens == 163840
    assert pricing.mode == "chat"


def test_scrape_resolves_dash_vendor_ids(live_page):
    # scrape keys cards by the resolved canonical id; the naive first-dash
    # spelling matches nothing
    cfg = make_cfg()
    llama = scraper.scrape(cfg, "meta-llama/llama-3.1-8b-instruct")
    assert llama is not None
    assert llama.input_cost_per_token == 0.02 / 1e6
    assert llama.output_cost_per_token == 0.05 / 1e6
    assert llama.max_tokens == 16384
    glm = scraper.scrape(cfg, "zai-org/glm-5.2")
    assert glm is not None
    assert glm.input_cost_per_token == 1.4 / 1e6
    assert glm.cache_read_cost_per_token == 0.26 / 1e6
    assert glm.output_cost_per_token == 4.4 / 1e6
    assert scraper.scrape(cfg, "meta/llama-llama-3.1-8b-instruct") is None


def test_scrape_tiered_and_omnimodal_cards_return_none(live_page):
    cfg = make_cfg()
    assert scraper.scrape(cfg, "qwen/qwen3-max") is None
    assert scraper.scrape(cfg, "minimax/minimax-m3") is None
    assert scraper.scrape(cfg, "qwen/qwen3-omni-30b-a3b-instruct") is None


def test_scrape_unknown_model_returns_none(live_page):
    assert scraper.scrape(make_cfg(), "deepseek/deepseek-v9") is None


def test_scrape_zero_rate_returns_none(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: synthetic_page(card_html("free-model", input_amount="0")),
    )
    assert scraper.scrape(make_cfg(), "free/model") is None


def test_scrape_card_without_context_omits_max_tokens(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: synthetic_page(card_html("no-ctx-model", context=None)),
    )
    pricing = scraper.scrape(make_cfg(), "no/ctx-model")
    assert pricing is not None
    assert pricing.input_cost_per_token == 1.00 / 1e6
    assert pricing.output_cost_per_token == 2.00 / 1e6
    assert pricing.max_tokens == 0


def test_scrape_no_model_cards_raises(monkeypatch):
    monkeypatch.setattr(
        detector, "fetch_soup", lambda url: BeautifulSoup("<html></html>", "html.parser")
    )
    with pytest.raises(FetchError, match="no model cards"):
        scraper.scrape(make_cfg(), "deepseek/deepseek-v4-pro-0813")


def test_dedup_keys_dated_snapshots():
    # the page spells deepseek's dated snapshots; the store holds the base
    # ids (deepseek/deepseek-r1, and deepseek_v3 with an underscore),
    # measured 2026-08-24
    assert scraper.dedup_keys("deepseek/deepseek-r1-0528") == ("deepseek/deepseek-r1",)
    assert scraper.dedup_keys("deepseek/deepseek-v3-0324") == ("deepseek/deepseek_v3",)


def test_dedup_keys_other_ids_return_nothing():
    for model_id in (
        "deepseek/deepseek-v4-pro-0813",
        "qwen/qwen-2.5-72b-instruct",
        "deepseek/deepseek-r1-turbo",
    ):
        assert scraper.dedup_keys(model_id) == (), model_id

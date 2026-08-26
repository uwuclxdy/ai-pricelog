from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import together_page as detector
from ai_pricelog.scrapers import together_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://www.together.ai/pricing"
FIXTURE = Path(__file__).parent / "fixtures" / "together_page" / "pricing.html"

EXPECTED_IDS = [
    "minimax-m3",
    "glm-5.2",
    "kimi-k3",
    "deepseek-v4-flash-0731",
    "qwen3.8-2.4t-a95b",
    "muse-glimmer-30b",
    "deepseek-v4-pro-0813",
    "gemma-4-31b",
    "deepseek-v4-pro",
    "nvidia-nemotron-3-ultra",
    "kimi-k2.7-code",
    "qwen3.7-plus",
    "ternary-bonsai-27b",
    "inkling",
    "lfm2.5-8b-a1b",
    "inkling-small",
    "qwen3.7-max",
    "gpt-oss-120b",
    "qwen3.5-397b-a17b",
    "qwen3.5-9b",
    "gemma-4-31b-it-pearl",
    "cogito-v2.1-671b",
    "rnj-1-instruct",
    "llama-3.3-70b",
    "gemma-3n-e4b-instruct",
    "gpt-oss-20b",
    "minimax-m2.7",
    "qwen3.6-plus",
    "qwen2.5-7b-instruct-turbo",
    "llama-3-8b-instruct-lite",
    "qwen3-235b-a22b-instruct-2507-fp8-throughput",
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="together",
        provider="Together AI",
        detector="together_page",
        detector_url=PAGE_URL,
        scraper="together_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


def synthetic_soup(*rows: tuple[str, str, str]) -> BeautifulSoup:
    header = "<table><thead><th>Model</th><th>Input</th><th>output</th></thead>"
    body = "".join(
        f"<tr><td>{name}</td><td>{input_price}</td><td>{output_price}</td></tr>"
        for name, input_price, output_price in rows
    )
    return BeautifulSoup(f"{header}{body}</table>", "html.parser")


def test_detect_lists_models_in_page_order(monkeypatch):
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_detect_vision_table_does_not_duplicate(monkeypatch):
    # the vision tab table re-lists 13 of the chat rows at identical rates;
    # detection merges both tables by slug, so each id appears once
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    ids = detector.detect(cfg())
    assert ids == EXPECTED_IDS
    assert len(ids) == len(set(ids)) == 31


def test_detect_excludes_non_token_tables(monkeypatch):
    # embeddings, moderation, image and video tables have Model | Price(ish)
    # headers and must not leak into detection
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    ids = detector.detect(cfg())
    for leaked in (
        "multilingual-e5-large-instruct",
        "llama-guard-4-12b",
        "bytedance-seedance-2.5",
        "qwen-image-2.0",
    ):
        assert leaked not in ids


def test_detect_skips_unusable_model_cells(monkeypatch):
    # an empty name cell is not a model; a name slugging outside the id
    # charset is skipped rather than emitted as a junk id
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: synthetic_soup(
            ("MiniMax M3", "$1", "$1"), ("", "$1", "$1"), ("FLUX.2 [pro]", "$1", "$1")
        ),
    )
    assert detector.detect(cfg()) == ["minimax-m3"]


def test_detect_no_ids_raises(monkeypatch):
    # a per-token table whose model cells all fail the id pattern is a parse
    # failure, not a silent empty detection
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: synthetic_soup(("FLUX.2 [pro]", "$1", "$1")),
    )
    with pytest.raises(FetchError, match="no model ids"):
        detector.detect(cfg())


def test_detect_no_token_table_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><thead><th>Model</th><th>Price</th></thead>"
            "<tr><td>Multilingual e5 large instruct</td><td>$0.02</td></tr></table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="no per-token model table"):
        detector.detect(cfg())


def test_fetch_error_propagates(monkeypatch):
    def boom(url):
        raise FetchError(f"fetch failed for {url}")

    monkeypatch.setattr(detector, "fetch_soup", boom)
    with pytest.raises(FetchError, match=PAGE_URL):
        detector.detect(cfg())


def test_scrape_model_with_cached_rate(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "minimax-m3")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.30 / 1e6
    assert pricing.output_cost_per_token == 1.20 / 1e6
    assert pricing.cache_read_cost_per_token == 0.06 / 1e6
    assert pricing.mode == "chat"
    assert pricing.max_tokens == 0


def test_scrape_model_without_cached_rate(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "gemma-4-31b")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.39 / 1e6
    assert pricing.output_cost_per_token == 0.97 / 1e6
    assert pricing.cache_read_cost_per_token is None


def test_scrape_chat_row_wins_over_vision_row(monkeypatch):
    # Kimi K3 sits in both per-token tables: the chat row carries the cached
    # rate, the vision row does not. the first table in document order wins,
    # so the cached rate must survive.
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == 3.00 / 1e6
    assert pricing.output_cost_per_token == 15.00 / 1e6
    assert pricing.cache_read_cost_per_token == 0.30 / 1e6


def test_scrape_free_model_returns_none(monkeypatch):
    # Ternary Bonsai 27B lists $0.00/$0.00: no usable rates, never a candidate
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "ternary-bonsai-27b") is None


def test_scrape_unknown_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "nonexistent-model") is None


def test_scrape_matches_page_spelling(monkeypatch):
    # the page spells the id "MiniMax M3"; the normalized id must match too
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "MiniMax M3")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.30 / 1e6
    assert pricing.output_cost_per_token == 1.20 / 1e6


def test_scrape_unpriced_row_returns_none(monkeypatch):
    # a model whose input cell carries no dollar amount is not priced yet
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: synthetic_soup(("MiniMax M3", "$0.30", "$1.20"), ("Kimi K3", "-", "$15.00")),
    )
    assert scraper.scrape(cfg(), "kimi-k3") is None


def test_scrape_zero_prices_return_none(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: synthetic_soup(("Free Model", "$0.00", "$0.00")),
    )
    assert scraper.scrape(cfg(), "free-model") is None


def test_scrape_malformed_row_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><thead><th>Model</th><th>Input</th><th>output</th></thead>"
            "<tr><td>MiniMax M3</td><td>$0.30</td></tr></table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="malformed pricing row"):
        scraper.scrape(cfg(), "minimax-m3")


def test_scrape_no_token_table_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><thead><th>Model</th><th>Price</th></thead>"
            "<tr><td>e5</td><td>$0.02</td></tr></table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="no per-token model table"):
        scraper.scrape(cfg(), "e5")


def test_scrape_thousands_separator(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: synthetic_soup(("Model", "$1,000", "$2,000.5")),
    )
    pricing = scraper.scrape(cfg(), "model")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1000.0 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(2000.5 / 1e6)


def test_dedup_keys_tracked_llama_endpoints():
    # page spellings map to the HF-style ids the store holds
    # (measured against that yml, 2026-08-24)
    assert scraper.dedup_keys("llama-3.3-70b") == ("meta-llama/Llama-3.3-70B-Instruct-Turbo",)
    assert scraper.dedup_keys("llama-3-8b-instruct-lite") == (
        "meta-llama/Meta-Llama-3-8B-Instruct-Lite",
    )


def test_dedup_keys_page_spelling_matches_too():
    assert scraper.dedup_keys("Llama 3.3 70B") == ("meta-llama/Llama-3.3-70B-Instruct-Turbo",)


def test_dedup_keys_plain_ids_return_nothing():
    for page_id in ("deepseek-v4-pro-0813", "deepseek-v4-pro", "minimax-m3", "kimi-k3"):
        assert scraper.dedup_keys(page_id) == (), page_id

from pathlib import Path

import pytest

from autopr_genai_prices.config import ProviderCfg
from autopr_genai_prices.detectors import minimax_page as minimax_detect
from autopr_genai_prices.scrapers import minimax_page as minimax_scrape
from autopr_genai_prices.web import FetchError

FIXTURES = Path(__file__).parent / "fixtures" / "minimax_page"


@pytest.fixture
def minimax_cfg() -> ProviderCfg:
    return ProviderCfg(
        key="minimax",
        yml="minimax.yml",
        or_prefix="minimax",
        detector="minimax_page",
        detector_url="https://platform.minimax.io/docs/guides/models-intro.md",
        scraper="minimax_page",
        scraper_url="https://platform.minimax.io/docs/guides/pricing-paygo.md",
    )


@pytest.fixture
def feed_fixtures(monkeypatch: pytest.MonkeyPatch) -> None:
    def feed(url: str) -> str:
        if url.endswith("models-intro.md"):
            return (FIXTURES / "models-intro.md").read_text()
        if url.endswith("pricing-paygo.md"):
            return (FIXTURES / "pricing-paygo.md").read_text()
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(minimax_detect, "fetch_text", feed)
    monkeypatch.setattr(minimax_scrape, "fetch_text", feed)


def test_detect_returns_language_models_in_page_order(minimax_cfg, feed_fixtures):
    assert minimax_detect.detect(minimax_cfg) == [
        "MiniMax-M3",
        "MiniMax-M2.7",
        "MiniMax-M2.7-highspeed",
        "MiniMax-M2.5",
        "MiniMax-M2.5-highspeed",
        "MiniMax-M2.1",
        "MiniMax-M2.1-highspeed",
        "MiniMax-M2",
    ]


def test_scrape_m3_takes_first_standard_row(minimax_cfg, feed_fixtures):
    pricing = minimax_scrape.scrape(minimax_cfg, "MiniMax-M3")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.3 / 1e6
    assert pricing.output_cost_per_token == 1.2 / 1e6
    assert pricing.mode == "chat"
    assert pricing.max_tokens == 0


def test_scrape_m27_prices_exact(minimax_cfg, feed_fixtures):
    pricing = minimax_scrape.scrape(minimax_cfg, "MiniMax-M2.7")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.3 / 1e6
    assert pricing.output_cost_per_token == 1.2 / 1e6


def test_scrape_m27_highspeed_prices_exact(minimax_cfg, feed_fixtures):
    pricing = minimax_scrape.scrape(minimax_cfg, "MiniMax-M2.7-highspeed")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.6 / 1e6
    assert pricing.output_cost_per_token == 2.4 / 1e6


def test_scrape_video_model_has_no_token_pricing(minimax_cfg, feed_fixtures):
    assert minimax_scrape.scrape(minimax_cfg, "MiniMax-H3") is None


def test_scrape_audio_model_has_no_token_pricing(minimax_cfg, feed_fixtures):
    assert minimax_scrape.scrape(minimax_cfg, "speech-2.8-turbo") is None


def test_detect_malformed_page_raises_fetch_error(minimax_cfg, monkeypatch):
    monkeypatch.setattr(minimax_detect, "fetch_text", lambda url: "no tables here")
    with pytest.raises(FetchError):
        minimax_detect.detect(minimax_cfg)


def test_detect_tables_without_model_ids_raise_fetch_error(minimax_cfg, monkeypatch):
    monkeypatch.setattr(
        minimax_detect, "fetch_text", lambda url: "| Name | Type |\n|---|---|\n| Hailuo | video |\n"
    )
    with pytest.raises(FetchError, match="model ids"):
        minimax_detect.detect(minimax_cfg)


def test_scrape_malformed_page_raises_fetch_error(minimax_cfg, monkeypatch):
    monkeypatch.setattr(minimax_scrape, "fetch_text", lambda url: "no tables here")
    with pytest.raises(FetchError):
        minimax_scrape.scrape(minimax_cfg, "MiniMax-M3")

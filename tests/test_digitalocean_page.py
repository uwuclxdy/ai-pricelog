from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import digitalocean_page as detector
from ai_pricelog.scrapers import digitalocean_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://docs.digitalocean.com/products/inference/details/pricing/"
FIXTURE = Path(__file__).parent / "fixtures" / "digitalocean_page" / "pricing.html"

EXPECTED_IDS = [
    "claude-fable-5",
    "claude-haiku-4.5",
    "claude-opus-5",
    "claude-opus-5-fast-mode",
    "claude-opus-4.8",
    "claude-opus-4.7",
    "claude-opus-4.6",
    "claude-opus-4.5",
    "claude-sonnet-5",
    "claude-sonnet-4.6",
    "claude-sonnet-4.5",
    "trinity-large",
    "gpt-oss-120b",
    "gpt-oss-20b",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.4-pro",
    "gpt-5.3-codex",
    "gpt-5.2",
    "gpt-5.2-pro",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4.1",
    "gpt-4o",
    "gpt-4o-mini",
    "o1",
    "o3",
    "o3-mini",
    "qwen3.8-max",
    "qwen-3.5-397b-a17b",
    "deepseek-v4-pro-0813",
    "deepseek-v4-flash-0731",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "deepseek-v3.2",
    "gemma-4",
    "minimax-m2.5",
    "kimi-k3",
    "kimi-k2.6",
    "kimi-k2.5",
    "llama-4-maverick-17b-128e-instruct",
    "ministral-3-14b-instruct",
    "nemotron-3-ultra",
    "nemotron-3-super-120b",
    "nemotron-nano-3-omni",
    "nemotron-nano-12b-v2-vl",
    "mimo-v2.5-pro",
    "glm-5.2",
    "glm-5.1",
    "glm-5",
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="digitalocean",
        provider="DigitalOcean",
        detector="digitalocean_page",
        detector_url=PAGE_URL,
        scraper="digitalocean_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


def test_detect_serverless_models(monkeypatch):
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_scrape_claude_opus_5(monkeypatch):
    # $5.00 / $25.00 per 1M, cache read $0.50; the two cache-creation
    # lines are write rates and must not leak into cache_read
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "claude-opus-5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(5.00 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(25.00 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.50 / 1e6)
    assert pricing.mode == "chat"


def test_scrape_deepseek_v4_pro_0813(monkeypatch):
    # digitalocean-hosted spelling: "$1.32 per 1M tokens" then "$3.96 per
    # 1M tokens", input first; the Prompt caching group holds the read rate
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "deepseek-v4-pro-0813")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1.32 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(3.96 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.044 / 1e6)


def test_scrape_long_context_first_group_standard(monkeypatch):
    # Claude Sonnet 4.5 prices a ≤200K and a >200K group; the first group
    # is the standard rate
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "claude-sonnet-4.5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.00 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(15.00 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.30 / 1e6)


def test_scrape_link_name_with_cell_suffix(monkeypatch):
    # "MiniMax M2.5 (Public Preview)" keys by the link text "MiniMax M2.5"
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "minimax-m2.5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.30 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(1.20 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.06 / 1e6)


def test_scrape_no_caching_group(monkeypatch):
    # Nemotron 3 Ultra carries no Prompt caching group
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "nemotron-3-ultra")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.90 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(1.70 / 1e6)
    assert pricing.cache_read_cost_per_token is None


def test_scrape_unknown_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "claude-opus-6") is None


def test_scrape_image_model_out_of_scope(monkeypatch):
    # gpt-image-1 sits in the OpenAI table but is an image model: detected
    # ids exclude it and scrape reads it as absent
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "gpt-image-1") is None


def test_malformed_grid_no_base_rates_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><thead><tr><th>Model</th><th>Serverless Inference</th></tr>"
            "</thead><tbody><tr><td><a>Kimi K3</a></td>"
            '<td><span class="gen-ai-pricing-grid"><span>Prompt caching</span>'
            "<span>$0.10 per 1M cache read input tokens</span></span></td>"
            "</tr></tbody></table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="no per-1M input/output rates"):
        scraper.scrape(cfg(), "kimi-k3")


def test_malformed_grid_odd_spans_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><thead><tr><th>Model</th><th>Serverless Inference</th></tr>"
            "</thead><tbody><tr><td><a>Kimi K3</a></td>"
            '<td><span class="gen-ai-pricing-grid"><span>Input/output tokens</span>'
            "<span>$3.00 per 1M input tokens</span><span>stray</span></span></td>"
            "</tr></tbody></table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="3 spans"):
        scraper.scrape(cfg(), "kimi-k3")


def test_detect_missing_table_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>GPU</th><th>Price</th></tr></table>", "html.parser"
        ),
    )
    with pytest.raises(FetchError, match="no per-model serverless pricing table"):
        detector.detect(cfg())


def test_detect_table_without_priced_rows_raises(monkeypatch):
    # a serverless table whose rows carry no pricing grid prices nothing;
    # empty detection is a parse failure, never a quiet empty run
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><thead><tr><th>Model</th><th>Serverless Inference</th></tr>"
            "</thead><tbody><tr><td>Flux Schnell</td>"
            "<td>$0.0030 per megapixel</td></tr></tbody></table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="no model ids"):
        detector.detect(cfg())


def test_unparseable_caching_group_raises(monkeypatch):
    # a caching group with two cache-creation lines and no read line is a
    # shape break, never a silent cache-rate drop
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><thead><tr><th>Model</th><th>Serverless Inference</th></tr>"
            "</thead><tbody><tr><td><a>Claude Opus 5</a></td>"
            '<td><span class="gen-ai-pricing-grid"><span>Input/output tokens</span>'
            "<span>$5.00 per 1M input tokens $25.00 per 1M output tokens</span>"
            "<span>Prompt caching</span>"
            "<span>$6.25 per 1M cache creation 5m input tokens "
            "$10.00 per 1M cache creation 1h input tokens</span></span></td>"
            "</tr></tbody></table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="unparseable caching group"):
        scraper.scrape(cfg(), "claude-opus-5")

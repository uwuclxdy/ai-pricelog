from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import cloudflare_page as detector
from ai_pricelog.scrapers import cloudflare_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://developers.cloudflare.com/workers-ai/platform/pricing/"
FIXTURE = Path(__file__).parent / "fixtures" / "cloudflare_page" / "pricing.html"

EXPECTED_IDS = [
    "@cf/meta/llama-3.2-1b-instruct",
    "@cf/meta/llama-3.2-3b-instruct",
    "@cf/meta/llama-3.1-8b-instruct-fp8-fast",
    "@cf/meta/llama-3.2-11b-vision-instruct",
    "@cf/meta/llama-3.1-70b-instruct-fp8-fast",
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b",
    "@cf/deepseek-ai/deepseek-v4-flash-0731",
    "@cf/deepseek-ai/deepseek-v4-pro-0813",
    "@cf/mistral/mistral-7b-instruct-v0.1",
    "@cf/mistralai/mistral-small-3.1-24b-instruct",
    "@cf/meta/llama-3.1-8b-instruct",
    "@cf/meta/llama-3.1-8b-instruct-fp8",
    "@cf/meta/llama-3.1-8b-instruct-awq",
    "@cf/meta/llama-3-8b-instruct",
    "@cf/meta/llama-3-8b-instruct-awq",
    "@cf/meta/llama-2-7b-chat-fp16",
    "@cf/meta/llama-guard-3-8b",
    "@cf/meta/llama-4-scout-17b-16e-instruct",
    "@cf/google/gemma-3-12b-it",
    "@cf/qwen/qwq-32b",
    "@cf/qwen/qwen2.5-coder-32b-instruct",
    "@cf/qwen/qwen3-30b-a3b-fp8",
    "@cf/qwen/qwen3.8-27b",
    "@cf/openai/gpt-oss-120b",
    "@cf/openai/gpt-oss-20b",
    "@cf/aisingapore/gemma-sea-lion-v4-27b-it",
    "@cf/ibm-granite/granite-4.0-h-micro",
    "@cf/zai-org/glm-4.7-flash",
    "@cf/zai-org/glm-5.2",
    "@cf/zai-org/glm-5.3-flash",
    "@cf/nvidia/nemotron-3-120b-a12b",
    "@cf/moonshotai/kimi-k2.5",
    "@cf/moonshotai/kimi-k2.6",
    "@cf/moonshotai/kimi-k2.7-code",
    "@cf/google/gemma-4-26b-a4b-it",
    "@cf/meta/m2m100-1.2b",
    "@cf/ai4bharat/indictrans2-en-indic-1b",
    "@cf/moondream/moondream3.1-9b-a2b",
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="cloudflare",
        provider="Cloudflare",
        detector="cloudflare_page",
        detector_url=PAGE_URL,
        scraper="cloudflare_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


def test_detect_llm_models(monkeypatch):
    # five tables share the Model | Price in Tokens | Price in Neurons
    # header; the LLM section is taken whole, and the other section
    # contributes only rows with a clean input+output pair. embeddings,
    # image, and audio ids never enter detect
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_scrape_llama_3_2_1b(monkeypatch):
    # rates as published on the first-party pricing page (fixture snapshot
    # 2026-08-27): $0.027 / 1M input, $0.201 / 1M output, no cached rate
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "@cf/meta/llama-3.2-1b-instruct")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.027 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.201 / 1e6)
    assert pricing.cache_read_cost_per_token is None
    assert pricing.mode == "chat"


def test_scrape_cached_input_rate(monkeypatch):
    # deepseek-v4-flash-0731 publishes a cached-input line between input and
    # output: $0.440 / $0.014 cached / $1.320 per 1M, first-party page
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "@cf/deepseek-ai/deepseek-v4-flash-0731")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.440 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(1.320 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.014 / 1e6)


def test_scrape_other_section_model(monkeypatch):
    # the other section's translation rows price per input+output token:
    # $0.342 / 1M input, $0.342 / 1M output, no cached rate
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "@cf/meta/m2m100-1.2b")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.342 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.342 / 1e6)
    assert pricing.cache_read_cost_per_token is None


def test_scrape_unknown_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "@cf/meta/llama-9.9") is None


def test_scrape_out_of_scope_id_returns_none(monkeypatch):
    # embeddings ids sit in a section the pair does not serve
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "@cf/baai/bge-m3") is None


def test_scrape_malformed_cell_raises(monkeypatch):
    # a rate line the parser does not know is a page-shape break, never a
    # silent drop
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            '<h2 id="llm-model-pricing">LLM model pricing</h2>'
            "<table><thead><tr><th>Model</th><th>Price in Tokens</th>"
            "<th>Price in Neurons</th></tr></thead><tbody><tr>"
            "<td>@cf/meta/llama-3.2-1b-instruct</td>"
            "<td>$0.027 per M input tokens<br>$0.201 per M image tokens</td>"
            "<td>2457 neurons</td></tr></tbody></table>"
            '<h2 id="other-model-pricing">Other model pricing</h2>'
            "<table><thead><tr><th>Model</th><th>Price in Tokens</th>"
            "<th>Price in Neurons</th></tr></thead><tbody><tr>"
            "<td>@cf/meta/m2m100-1.2b</td>"
            "<td>$0.342 per M input tokens $0.342 per M output tokens</td>"
            "<td>0 neurons</td></tr></tbody></table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match=r"per M image tokens"):
        scraper.scrape(cfg(), "@cf/meta/llama-3.2-1b-instruct")


def test_scrape_input_only_cell_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            '<h2 id="llm-model-pricing">LLM model pricing</h2>'
            "<table><thead><tr><th>Model</th><th>Price in Tokens</th>"
            "<th>Price in Neurons</th></tr></thead><tbody><tr>"
            "<td>@cf/meta/llama-3.2-1b-instruct</td>"
            "<td>$0.027 per M input tokens</td>"
            "<td>2457 neurons</td></tr></tbody></table>"
            '<h2 id="other-model-pricing">Other model pricing</h2>'
            "<table><thead><tr><th>Model</th><th>Price in Tokens</th>"
            "<th>Price in Neurons</th></tr></thead><tbody><tr>"
            "<td>@cf/meta/m2m100-1.2b</td>"
            "<td>$0.342 per M input tokens $0.342 per M output tokens</td>"
            "<td>0 neurons</td></tr></tbody></table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="missing input or output rate"):
        scraper.scrape(cfg(), "@cf/meta/llama-3.2-1b-instruct")


def test_detect_missing_section_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><thead><tr><th>Model</th><th>Price in Tokens</th>"
            "<th>Price in Neurons</th></tr></thead></table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="no llm-model-pricing pricing section"):
        detector.detect(cfg())


def test_detect_missing_table_raises(monkeypatch):
    # the walk is bounded by the next h2, so an embeddings table after
    # h2#embeddings-model-pricing is not read as the LLM table
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            '<h2 id="llm-model-pricing">LLM model pricing</h2>'
            '<h2 id="embeddings-model-pricing">Embeddings model pricing</h2>'
            "<table><thead><tr><th>Model</th><th>Price in Tokens</th>"
            "<th>Price in Neurons</th></tr></thead></table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="no llm-model-pricing pricing table"):
        detector.detect(cfg())


def test_detect_other_section_skips_input_only_rows(monkeypatch):
    # the other section mixes input-only classifiers and per-image rows;
    # only rows with a clean input+output pair are token-priced
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            '<h2 id="llm-model-pricing">LLM model pricing</h2>'
            "<table><thead><tr><th>Model</th><th>Price in Tokens</th>"
            "<th>Price in Neurons</th></tr></thead><tbody><tr>"
            "<td>@cf/meta/llama-3.2-1b-instruct</td>"
            "<td>$0.027 per M input tokens<br>$0.201 per M output tokens</td>"
            "<td>2457 neurons</td></tr></tbody></table>"
            '<h2 id="other-model-pricing">Other model pricing</h2>'
            "<table><thead><tr><th>Model</th><th>Price in Tokens</th>"
            "<th>Price in Neurons</th></tr></thead><tbody><tr>"
            "<td>@cf/huggingface/distilbert-sst-2-int8</td>"
            "<td>$0.026 per M input tokens</td>"
            "<td>0 neurons</td></tr><tr>"
            "<td>@cf/microsoft/resnet-50</td>"
            "<td>$2.51 per M images</td>"
            "<td>0 neurons</td></tr><tr>"
            "<td>@cf/meta/m2m100-1.2b</td>"
            "<td>$0.342 per M input tokens<br>$0.342 per M output tokens</td>"
            "<td>0 neurons</td></tr></tbody></table>",
            "html.parser",
        ),
    )
    assert detector.detect(cfg()) == [
        "@cf/meta/llama-3.2-1b-instruct",
        "@cf/meta/m2m100-1.2b",
    ]

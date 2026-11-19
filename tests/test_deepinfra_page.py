"""deepinfra pricing pair tests, pinned against the saved live page."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import deepinfra_page as detector
from ai_pricelog.scrapers import deepinfra_page as scraper
from ai_pricelog.web import FetchError
from conftest import move_last_row_to_second_tbody

PAGE_URL = "https://deepinfra.com/pricing"
FIXTURE = Path(__file__).parent / "fixtures" / "deepinfra_page" / "pricing.html"
FIXTURE_2026_11_18 = (
    Path(__file__).parent / "fixtures" / "deepinfra_page" / "pricing-2026-11-18.html"
)

EXPECTED_IDS = [
    "deepseek-v4-flash-0731",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "deepseek-v3.2",
    "deepseek-v3.1",
    "deepseek-v3-0324",
    "deepseek-v3",
    "deepseek-r1-0528",
    "kimi-k3",
    "kimi-k2.7-code",
    "kimi-k2.6",
    "kimi-k2.5",
    "qwen3.6-27b",
    "qwen3.6-35b-a3b",
    "qwen3.5-397b-a17b",
    "qwen3.5-122b-a10b",
    "qwen3.5-35b-a3b",
    "qwen3.5-27b",
    "qwen3.5-9b",
    "qwen3.8-max",
    "qwen3.7-max",
    "qwen3-vl-30b-a3b-instruct",
    "qwen3-vl-235b-a22b-instruct",
    "qwen3-max-thinking",
    "qwen3-max",
    "qwen3-next-80b-a3b-instruct",
    "qwen3-coder-480b-a35b-instruct-turbo",
    "qwen3-235b-a22b-instruct-2507",
    "qwen3-32b",
    "qwen3-30b-a3b",
    "qwen3-14b",
    "qwen2.5-72b-instruct",
    "llama-4-scout-17b-16e-instruct",
    "llama-4-maverick-17b-128e-instruct-fp8",
    "llama-guard-4-12b",
    "llama-3.3-70b-instruct-turbo",
    "meta-llama-3.1-70b-instruct-turbo",
    "meta-llama-3.1-8b-instruct-turbo",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.1-pro",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemma-4-e4b-it",
    "gemma-4-31b-it-ultra",
    "gemma-4-31b-it-turbo",
    "gemma-4-31b-it",
    "gemma-4-26b-a4b-it",
    "gemma-3-27b-it",
    "gemma-3-12b-it",
    "gemma-3-4b-it",
    "nvidia-nemotron-3.5-lightning",
    "nemotron-content-safety-3.5",
    "nvidia-nemotron-3-ultra-550b-a55b",
    "nvidia-nemotron-3-super-120b-a12b",
    "nemotron-3-nano-30b-a3b",
    "claude-opus-5",
    "claude-fable-5",
    "claude-sonnet-5",
    "claude-haiku-4-5",
    "claude-sonnet-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "phi-4",
    "mistral-small-3.2-24b-instruct-2506",
    "mistral-small-24b-instruct-2501",
    "mistral-nemo-instruct-2407",
    "mythomax-l2-13b",
]

# the page captured 2026-11-18: 7 of these rows badge a limited-time discount
EXPECTED_IDS_2026_11_18 = [
    "deepseek-v4.1-flash-1017",
    "deepseek-v4.1-flash",
    "deepseek-v4-pro-0813",
    "deepseek-v4-flash-0731",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "deepseek-v4-flash-vision-exp",
    "deepseek-v3.2",
    "deepseek-v3.1",
    "deepseek-v3",
    "deepseek-r1-0528",
    "kimi-k3.1-pro",
    "kimi-k3",
    "kimi-k2.6",
    "glm-5.3",
    "glm-5.3-flash",
    "glm-5.2",
    "glm-4.7",
    "glm-4.6",
    "qwen4-max",
    "qwen3.8-flash",
    "qwen3.8-27b",
    "qwen3.6-27b",
    "qwen3.6-35b-a3b",
    "qwen3.5-397b-a17b",
    "qwen3.5-35b-a3b",
    "qwen3.5-27b",
    "qwen3.5-9b",
    "qwen3.8-max",
    "qwen3.7-max",
    "qwen3-vl-30b-a3b-instruct",
    "qwen3-vl-235b-a22b-instruct",
    "qwen3-next-80b-a3b-instruct",
    "qwen3-coder-480b-a35b-instruct-turbo",
    "qwen3-235b-a22b-instruct-2507",
    "qwen3-32b",
    "qwen3-30b-a3b",
    "qwen3-14b",
    "qwen2.5-72b-instruct",
    "llama-4-scout-17b-16e-instruct",
    "llama-guard-4-12b",
    "llama-3.3-70b-instruct-turbo",
    "meta-llama-3.1-8b-instruct-turbo",
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.1-pro",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemma-4-31b-it-ultra",
    "gemma-4-31b-it-turbo",
    "gemma-4-31b-it",
    "gemma-4-26b-a4b-it",
    "gemma-3-27b-it",
    "gemma-3-12b-it",
    "gemma-3-4b-it",
    "nvidia-nemotron-3.5-lightning",
    "nvidia-nemotron-3.5-super-vl",
    "nemotron-content-safety-3.5",
    "nvidia-nemotron-3-ultra-550b-a55b",
    "nvidia-nemotron-3-super-120b-a12b",
    "claude-sonnet-5-5",
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-fable-5",
    "claude-sonnet-5",
    "claude-haiku-4-5",
    "claude-sonnet-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "phi-4",
    "mistral-small-3.2-24b-instruct-2506",
    "mistral-small-24b-instruct-2501",
    "mistral-nemo-instruct-2407",
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="deepinfra",
        provider="DeepInfra",
        detector="deepinfra_page",
        detector_url=PAGE_URL,
        scraper="deepinfra_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


def load_soup_2026_11_18() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE_2026_11_18.read_text(), "html.parser")


def token_table_soup(*rows: str) -> BeautifulSoup:
    return BeautifulSoup(
        "<table><thead><tr>"
        "<th>Model</th><th>Context</th><th>$ per 1M input tokens</th>"
        "<th>$ per 1M output tokens</th><th>Actions</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>",
        "html.parser",
    )


def model_row(model: str, href: str, context: str, input_cell: str, output_cell: str) -> str:
    return (
        f"<tr><td><a href='{href}'>{model}</a></td>"
        f"<td>{context}</td><td>{input_cell}</td><td>{output_cell}</td>"
        "<td><a>View more</a></td></tr>"
    )


def test_detect_ids(monkeypatch):
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_scrape_deepseek_v4_flash_0731(monkeypatch):
    # the fixture is the saved live pricing page; the input cell carries
    # base then cached, read in that order
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "deepseek-v4-flash-0731")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.08 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.016 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.18 / 1e6)
    assert pricing.max_tokens_in == 1024 * 1024
    assert pricing.mode == "chat"


def test_scrape_kimi_k3(monkeypatch):
    # cross-checked against moonshot's first-party k3 rates (cache miss
    # $3.00 / cache hit $0.30 / output $15.00): deepinfra lists 95% of each,
    # its standard 5% discount
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(2.85 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.285 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(14.25 / 1e6)
    assert pricing.max_tokens_in == 1024 * 1024


def test_scrape_single_amount_input(monkeypatch):
    # models without cache-read billing carry one input amount, no cached
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "qwen3.6-27b")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.32 / 1e6)
    assert pricing.cache_read_cost_per_token is None
    assert pricing.output_cost_per_token == pytest.approx(3.20 / 1e6)
    assert pricing.max_tokens_in == 256 * 1024


def test_scrape_discounted_cell_records_the_charged_rate(monkeypatch):
    # the 2026-11-18 page badges a discounted model and prints its list and
    # charged amounts in both cells; the charged pair is what bills today
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup_2026_11_18())
    pricing = scraper.scrape(cfg(), "deepseek-v4.1-flash")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.14 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.0042 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.42 / 1e6)
    assert pricing.max_tokens_in == 1024 * 1024
    assert pricing.mode == "chat"


def test_scrape_discounted_cell_records_the_charged_cached_rate(monkeypatch):
    # a 5%-off row: the charged cached amount moves with the charged base
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup_2026_11_18())
    pricing = scraper.scrape(cfg(), "kimi-k3.1-pro")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1.90 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.19 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(9.50 / 1e6)
    assert pricing.max_tokens_in == 1024 * 1024


# each captured id's tuple is frozen from the page's printed cells, so a read
# drift on any of the 74 fails here, not only on the discounted rows
FROZEN_2026_11_18_ROWS = {
    "deepseek-v4.1-flash-1017": (0.098 / 1e6, 0.0029 / 1e6, 0.294 / 1e6, 1048576),
    "deepseek-v4.1-flash": (0.14 / 1e6, 0.0042 / 1e6, 0.42 / 1e6, 1048576),
    "deepseek-v4-pro-0813": (1.3 / 1e6, 0.1 / 1e6, 2.6 / 1e6, 1048576),
    "deepseek-v4-flash-0731": (0.06 / 1e6, 0.015 / 1e6, 0.18 / 1e6, 1048576),
    "deepseek-v4-pro": (1.3 / 1e6, 0.1 / 1e6, 2.6 / 1e6, 1048576),
    "deepseek-v4-flash": (0.09 / 1e6, 0.018 / 1e6, 0.18 / 1e6, 1048576),
    "deepseek-v4-flash-vision-exp": (0.2156 / 1e6, 0.0069 / 1e6, 0.6468 / 1e6, 1048576),
    "deepseek-v3.2": (0.26 / 1e6, 0.13 / 1e6, 0.38 / 1e6, 163840),
    "deepseek-v3.1": (0.25 / 1e6, 0.13 / 1e6, 0.95 / 1e6, 163840),
    "deepseek-v3": (0.32 / 1e6, None, 0.89 / 1e6, 163840),
    "deepseek-r1-0528": (0.5 / 1e6, 0.35 / 1e6, 2.15 / 1e6, 163840),
    "kimi-k3.1-pro": (1.9 / 1e6, 0.19 / 1e6, 9.5 / 1e6, 1048576),
    "kimi-k3": (2.85 / 1e6, 0.285 / 1e6, 14.25 / 1e6, 1048576),
    "kimi-k2.6": (0.75 / 1e6, 0.15 / 1e6, 3.5 / 1e6, 262144),
    "glm-5.3": (0.5625 / 1e6, 0.125 / 1e6, 2.5 / 1e6, 1048576),
    "glm-5.3-flash": (0.15 / 1e6, 0.03 / 1e6, 0.5 / 1e6, 1048576),
    "glm-5.2": (0.5625 / 1e6, 0.105 / 1e6, 1.8 / 1e6, 1048576),
    "glm-4.7": (0.4 / 1e6, 0.08 / 1e6, 1.75 / 1e6, 202752),
    "glm-4.6": (0.5 / 1e6, 0.1 / 1e6, 2.0 / 1e6, 202752),
    "qwen4-max": (1.413 / 1e6, 0.071 / 1e6, 4.24 / 1e6, 999424),
    "qwen3.8-flash": (0.113 / 1e6, 0.0141 / 1e6, 0.382 / 1e6, 999424),
    "qwen3.8-27b": (0.15 / 1e6, 0.0375 / 1e6, 1.875 / 1e6, 262144),
    "qwen3.6-27b": (0.32 / 1e6, None, 3.2 / 1e6, 262144),
    "qwen3.6-35b-a3b": (0.1 / 1e6, 0.1 / 1e6, 0.95 / 1e6, 262144),
    "qwen3.5-397b-a17b": (0.45 / 1e6, 0.22 / 1e6, 3.0 / 1e6, 262144),
    "qwen3.5-35b-a3b": (0.14 / 1e6, 0.05 / 1e6, 1.0 / 1e6, 262144),
    "qwen3.5-27b": (0.26 / 1e6, None, 2.6 / 1e6, 262144),
    "qwen3.5-9b": (0.1 / 1e6, None, 0.15 / 1e6, 262144),
    "qwen3.8-max": (1.65 / 1e6, 0.206 / 1e6, 4.951 / 1e6, 256000),
    "qwen3.7-max": (2.5 / 1e6, 0.5 / 1e6, 7.5 / 1e6, 256000),
    "qwen3-vl-30b-a3b-instruct": (0.15 / 1e6, None, 0.6 / 1e6, 262144),
    "qwen3-vl-235b-a22b-instruct": (0.2 / 1e6, 0.11 / 1e6, 0.88 / 1e6, 262144),
    "qwen3-next-80b-a3b-instruct": (0.09 / 1e6, None, 1.1 / 1e6, 262144),
    "qwen3-coder-480b-a35b-instruct-turbo": (0.3 / 1e6, 0.1 / 1e6, 1.0 / 1e6, 262144),
    "qwen3-235b-a22b-instruct-2507": (0.09 / 1e6, None, 0.55 / 1e6, 262144),
    "qwen3-32b": (0.08 / 1e6, None, 0.28 / 1e6, 40960),
    "qwen3-30b-a3b": (0.12 / 1e6, None, 0.5 / 1e6, 40960),
    "qwen3-14b": (0.12 / 1e6, None, 0.24 / 1e6, 40960),
    "qwen2.5-72b-instruct": (0.36 / 1e6, None, 0.4 / 1e6, 32768),
    "llama-4-scout-17b-16e-instruct": (0.1 / 1e6, None, 0.3 / 1e6, 327680),
    "llama-guard-4-12b": (0.18 / 1e6, None, 0.18 / 1e6, 163840),
    "llama-3.3-70b-instruct-turbo": (0.1 / 1e6, None, 0.32 / 1e6, 131072),
    "meta-llama-3.1-8b-instruct-turbo": (0.02 / 1e6, None, 0.04 / 1e6, 131072),
    "gemini-3.7-flash": (0.75 / 1e6, None, 3.75 / 1e6, 999424),
    "gemini-3.5-flash": (1.5 / 1e6, None, 9.0 / 1e6, 999424),
    "gemini-3.1-flash-lite": (0.25 / 1e6, None, 1.5 / 1e6, 999424),
    "gemini-3.1-pro": (2.0 / 1e6, None, 12.0 / 1e6, 999424),
    "gemini-2.5-pro": (1.25 / 1e6, None, 10.0 / 1e6, 999424),
    "gemini-2.5-flash": (0.3 / 1e6, None, 2.5 / 1e6, 999424),
    "gemma-4-31b-it-ultra": (0.27 / 1e6, None, 0.76 / 1e6, 131072),
    "gemma-4-31b-it-turbo": (0.09 / 1e6, 0.05 / 1e6, 0.34 / 1e6, 262144),
    "gemma-4-31b-it": (0.2 / 1e6, None, 0.4 / 1e6, 262144),
    "gemma-4-26b-a4b-it": (0.07 / 1e6, None, 0.34 / 1e6, 262144),
    "gemma-3-27b-it": (0.08 / 1e6, None, 0.16 / 1e6, 131072),
    "gemma-3-12b-it": (0.05 / 1e6, None, 0.15 / 1e6, 131072),
    "gemma-3-4b-it": (0.05 / 1e6, None, 0.1 / 1e6, 131072),
    "nvidia-nemotron-3.5-lightning": (0.06 / 1e6, 0.03 / 1e6, 0.16 / 1e6, 262144),
    "nvidia-nemotron-3.5-super-vl": (0.15 / 1e6, 0.02 / 1e6, 0.5 / 1e6, 262144),
    "nemotron-content-safety-3.5": (0.2 / 1e6, None, 0.2 / 1e6, 131072),
    "nvidia-nemotron-3-ultra-550b-a55b": (0.5 / 1e6, 0.1 / 1e6, 2.2 / 1e6, 262144),
    "nvidia-nemotron-3-super-120b-a12b": (0.075 / 1e6, None, 0.4 / 1e6, 262144),
    "claude-sonnet-5-5": (2.0 / 1e6, None, 10.0 / 1e6, 999424),
    "claude-opus-5-5": (4.0 / 1e6, 0.2 / 1e6, 20.0 / 1e6, 999424),
    "claude-opus-5": (5.0 / 1e6, None, 25.0 / 1e6, 999424),
    "claude-fable-5": (10.0 / 1e6, None, 50.0 / 1e6, 999424),
    "claude-sonnet-5": (3.0 / 1e6, None, 15.0 / 1e6, 999424),
    "claude-haiku-4-5": (1.0 / 1e6, None, 5.0 / 1e6, 199680),
    "claude-sonnet-4-6": (3.0 / 1e6, None, 15.0 / 1e6, 999424),
    "claude-opus-4-7": (5.0 / 1e6, None, 25.0 / 1e6, 999424),
    "claude-opus-4-8": (5.0 / 1e6, None, 25.0 / 1e6, 999424),
    "phi-4": (0.07 / 1e6, None, 0.14 / 1e6, 16384),
    "mistral-small-3.2-24b-instruct-2506": (0.075 / 1e6, None, 0.2 / 1e6, 128000),
    "mistral-small-24b-instruct-2501": (0.05 / 1e6, None, 0.08 / 1e6, 32768),
    "mistral-nemo-instruct-2407": (0.029 / 1e6, None, 0.03 / 1e6, 131072),
}


def test_scrape_every_id_of_the_2026_11_18_page(monkeypatch):
    # every id on the captured page prices, the 7 discounted rows included
    soup = load_soup_2026_11_18()
    monkeypatch.setattr(detector, "fetch_soup", lambda url: soup)
    assert detector.detect(cfg()) == EXPECTED_IDS_2026_11_18
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: soup)
    priced = {}
    for model_id in EXPECTED_IDS_2026_11_18:
        pricing = scraper.scrape(cfg(), model_id)
        assert pricing is not None, model_id
        priced[model_id] = (
            pricing.input_cost_per_token,
            pricing.cache_read_cost_per_token,
            pricing.output_cost_per_token,
            pricing.max_tokens_in,
        )
    assert priced == FROZEN_2026_11_18_ROWS


def discounted_soup(input_cell: str, output_cell: str) -> BeautifulSoup:
    # the promo row's two price cells, one model row around them
    return token_table_soup(
        model_row(
            "DeepSeek V4.1 Flash",
            "/deepseek-ai/DeepSeek-V4.1-Flash",
            "1024k",
            input_cell,
            output_cell,
        )
    )


PROMO_INPUT = (
    '<span><span aria-label="List price">$0.20 / $0.006 cached</span>'
    "<span>$0.14 / $0.0042 cached</span></span>"
)
PROMO_OUTPUT = '<span><span aria-label="List price">$0.60</span><span>$0.42</span></span>'


def test_scrape_a_charged_span_first_raises(monkeypatch):
    # the page prints the list run first; any other order is a page shape no
    # capture shows, so it raises instead of reading a side
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup(
            "<span><span>$0.14 / $0.0042 cached</span>"
            '<span aria-label="List price">$0.20 / $0.006 cached</span></span>',
            '<span><span>$0.42</span><span aria-label="List price">$0.60</span></span>',
        ),
    )
    with pytest.raises(FetchError, match="malformed discounted cell"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_a_pair_directly_in_the_cell_raises(monkeypatch):
    # the page holds both runs in one wrapper span; without the wrapper the
    # split of the cell's amounts is not the page's
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup(
            '<span aria-label="List price">$0.20 / $0.006 cached</span>'
            "<span>$0.14 / $0.0042 cached</span>",
            PROMO_OUTPUT,
        ),
    )
    with pytest.raises(FetchError, match="malformed discounted cell"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_discounted_amounts_without_the_list_price_raise(monkeypatch):
    # two amounts in a cell with no list-price label are not a pair the
    # grammar reads; the pair shape comes from the page's own label
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: token_table_soup(
            model_row(
                "DeepSeek V4.1 Flash",
                "/deepseek-ai/DeepSeek-V4.1-Flash",
                "1024k",
                "$0.20 / $0.006 cached $0.14 / $0.0042 cached",
                "$0.60 $0.42",
            )
        ),
    )
    with pytest.raises(FetchError, match="4 amounts, want 1 or 2"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_two_list_price_spans_raise(monkeypatch):
    # two list amounts leave no captured shape saying which one is charged
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup(
            '<span><span aria-label="List price">$0.20 / $0.006 cached</span>'
            '<span aria-label="List price">$0.14 / $0.0042 cached</span></span>',
            PROMO_OUTPUT,
        ),
    )
    with pytest.raises(FetchError, match="malformed discounted cell"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_a_second_list_label_on_the_charged_span_raises(monkeypatch):
    # the charged span carries no list label; a second one leaves which amount
    # the page charges unknown, whatever its case
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup(
            '<span><span aria-label="List price">$0.20 / $0.006 cached</span>'
            '<span aria-label="list price">$0.14 / $0.0042 cached</span></span>',
            PROMO_OUTPUT,
        ),
    )
    with pytest.raises(FetchError, match="malformed discounted cell"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_a_list_price_span_alone_raises(monkeypatch):
    # the label alone does not say what the page charges: no charged span
    # beside it leaves the rate unread
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup(
            '<span><span aria-label="List price">$0.20 / $0.006 cached</span></span>',
            PROMO_OUTPUT,
        ),
    )
    with pytest.raises(FetchError, match="malformed discounted cell"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_a_list_span_without_a_dollar_amount_raises(monkeypatch):
    # the list span must hold the cell's first amounts; an unreadable one
    # leaves the split unknown
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup(
            '<span><span aria-label="List price">0.20</span>'
            "<span>$0.14 / $0.0042 cached</span></span>",
            PROMO_OUTPUT,
        ),
    )
    with pytest.raises(FetchError, match="malformed discounted cell"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_a_wrapper_with_a_third_child_raises(monkeypatch):
    # the page's wrapper holds exactly the list span and the charged span; a
    # third child leaves which runs are the pair unknown
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup(
            '<span><span aria-label="List price">$0.20 / $0.006 cached</span>'
            "<span>$0.14 / $0.0042 cached</span><span>cached</span></span>",
            PROMO_OUTPUT,
        ),
    )
    with pytest.raises(FetchError, match="malformed discounted cell"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_a_div_wrapper_raises(monkeypatch):
    # both runs sit in one wrapper span; another element wrapping them is a
    # page shape no capture shows
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup(
            '<div><span aria-label="List price">$0.20 / $0.006 cached</span>'
            "<span>$0.14 / $0.0042 cached</span></div>",
            PROMO_OUTPUT,
        ),
    )
    with pytest.raises(FetchError, match="malformed discounted cell"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_text_between_the_runs_raises(monkeypatch):
    # the wrapper holds exactly two child spans as the page prints; text
    # between them is a shape no capture shows
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup(
            '<span><span aria-label="List price">$0.20 / $0.006 cached</span>'
            " now <span>$0.14 / $0.0042 cached</span></span>",
            PROMO_OUTPUT,
        ),
    )
    with pytest.raises(FetchError, match="malformed discounted cell"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_a_struck_amount_inside_the_charged_span_raises(monkeypatch):
    # each run is one span of plain text as the page prints it; a nested tag
    # puts an amount in the run that its markup strikes, so the shape raises
    # instead of reading the struck amount as charged
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup(
            '<span><span aria-label="List price">$0.20 / $0.006 cached</span>'
            "<span><s>$0.60</s> $0.42</span></span>",
            PROMO_OUTPUT,
        ),
    )
    with pytest.raises(FetchError, match="malformed discounted cell"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_a_charged_child_outside_a_span_raises(monkeypatch):
    # both runs sit in spans; another element beside the label is a page
    # shape no capture shows
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup(
            '<span><span aria-label="List price">$0.20 / $0.006 cached</span>'
            "<div>$0.14 / $0.0042 cached</div></span>",
            PROMO_OUTPUT,
        ),
    )
    with pytest.raises(FetchError, match="malformed discounted cell"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_an_amount_outside_the_wrapper_raises(monkeypatch):
    # an amount the cell prints beside the wrapper is no part of either run;
    # reading the spans alone would drop it silently
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup("$9.99 " + PROMO_INPUT, PROMO_OUTPUT),
    )
    with pytest.raises(FetchError, match="malformed discounted cell"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_a_broken_amount_beside_a_discounted_pair_raises(monkeypatch):
    # a discounted cell's unreadable amount is a page-shape break on the
    # strict path too, not only on the ordinary one
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: token_table_soup(
            model_row(
                "DeepSeek V4.1 Flash",
                "/deepseek-ai/DeepSeek-V4.1-Flash",
                "1024k",
                '<span><span aria-label="List price">$0.20 / $0.006 cached</span>'
                "<span>$0.14 / $0.0042 cached</span></span>$1,2.3.4",
                '<span aria-label="List price">$0.60</span><span>$0.42</span>',
            )
        ),
    )
    with pytest.raises(FetchError, match="unreadable rate"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_a_discounted_pair_on_one_cell_only_raises(monkeypatch):
    # a discounted row prints the pair in both cells; the pair in one cell
    # alone leaves the other's single amount in a shape no capture shows
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup(PROMO_INPUT, "$0.42"),
    )
    with pytest.raises(FetchError, match="malformed discounted cell"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_a_discounted_pair_without_a_cached_rate_raises(monkeypatch):
    # the page prints two amounts in each input promo run; one per input run
    # is a shape no capture shows
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup(
            '<span><span aria-label="List price">$0.20</span><span>$0.14</span></span>',
            PROMO_OUTPUT,
        ),
    )
    with pytest.raises(FetchError, match="malformed discounted cell"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


@pytest.mark.parametrize(
    "input_cell",
    [
        "List price $0.20 / $0.006 cached",
        '<span aria-label="list price">$0.20 / $0.006 cached</span>',
        '<span><span aria-label="List-price">$0.20 / $0.006 cached</span>'
        "<span>$0.14 / $0.0042 cached</span></span>",
        "Listprice $0.20 / $0.006 cached",
        '<span><span aria-label="List  price">$0.20 / $0.006 cached</span>'
        "<span>$0.14 / $0.0042 cached</span></span>",
        '<div aria-label="list price">$0.20 / $0.006 cached</div>',
    ],
    ids=["text", "other-case", "hyphen", "glued", "whitespace-run", "div"],
)
def test_scrape_a_list_price_outside_the_labelled_span_raises(monkeypatch, input_cell):
    # a cell naming a list price any other way would otherwise record the list
    # amount as charged; a promo cell's one list mention is the label's own
    # attribute
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup(input_cell, "$0.60"),
    )
    with pytest.raises(FetchError, match="a list price outside the labelled span"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_a_list_price_mention_in_the_output_cell_alone_raises(monkeypatch):
    # the guard reads both price cells, not the input one alone
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup("$2.85", "Listprice $14.25"),
    )
    with pytest.raises(FetchError, match="a list price outside the labelled span"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_a_list_mention_beside_the_wrapper_raises(monkeypatch):
    # the label's own attribute is the one list mention a promo cell carries;
    # a second mention beside the wrapper is a page shape no capture shows
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup(
            PROMO_INPUT + "<span>List price ends Dec 1</span>", PROMO_OUTPUT
        ),
    )
    with pytest.raises(FetchError, match="malformed discounted cell"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_a_span_beside_the_wrapper_raises(monkeypatch):
    # the cell holds the wrapper alone, the capture's one arrangement; an
    # element beside it is a page shape no capture shows
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup(PROMO_INPUT + "<span>30% off</span>", PROMO_OUTPUT),
    )
    with pytest.raises(FetchError, match="malformed discounted cell"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_a_discounted_output_run_of_two_raises(monkeypatch):
    # the output cell's promo run holds exactly one amount per span; a second
    # amount in the charged span is a page shape no capture shows
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup(
            PROMO_INPUT,
            '<span><span aria-label="List price">$0.60</span><span>$0.42 $0.30</span></span>',
        ),
    )
    with pytest.raises(FetchError, match="malformed discounted cell"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


@pytest.mark.parametrize(
    "input_cell",
    [
        '<span><span aria-label="List price">$0.20</span>'
        "<span>$0.006 cached $0.14 / $0.0042 cached</span></span>",
        '<span><span aria-label="List price">$0.20 / $0.006 cached $0.14</span>'
        "<span>$0.0042 cached</span></span>",
    ],
    ids=["one-then-three", "three-then-one"],
)
def test_scrape_an_uneven_split_across_the_runs_raises(monkeypatch, input_cell):
    # the amount count alone does not say the runs line up; an uneven split
    # takes the cell's last amounts whichever span holds them
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: discounted_soup(input_cell, PROMO_OUTPUT),
    )
    with pytest.raises(FetchError, match="malformed discounted cell"):
        scraper.scrape(cfg(), "deepseek-v4.1-flash")


def test_scrape_an_input_cell_without_an_amount_raises(monkeypatch):
    # a non-discounted cell that prints no dollar amount names its cell
    # instead of reaching the amount list
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: token_table_soup(
            model_row("Kimi K3", "/moonshotai/Kimi-K3", "1024k", "n/a", "$14.25")
        ),
    )
    with pytest.raises(FetchError, match="0 amounts, want 1 or 2"):
        scraper.scrape(cfg(), "kimi-k3")


def test_scrape_an_output_cell_without_an_amount_raises(monkeypatch):
    # the same for the output side
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: token_table_soup(
            model_row("Kimi K3", "/moonshotai/Kimi-K3", "1024k", "$2.85", "n/a")
        ),
    )
    with pytest.raises(FetchError, match="0 amounts, want 1"):
        scraper.scrape(cfg(), "kimi-k3")


def test_scrape_three_output_amounts_raise(monkeypatch):
    # the output cell holds exactly one amount outside a discounted row
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: token_table_soup(
            model_row("Kimi K3", "/moonshotai/Kimi-K3", "1024k", "$2.85", "$14.25 $9.00 $7.00")
        ),
    )
    with pytest.raises(FetchError, match="3 amounts, want 1"):
        scraper.scrape(cfg(), "kimi-k3")


def test_scrape_llama_href_id(monkeypatch):
    # the display name abbreviates the model; the link slug is the id, and
    # the display spelling alone is not on the page
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "llama-4-scout-17b-16e-instruct")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.10 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.30 / 1e6)
    assert pricing.max_tokens_in == 320 * 1024
    assert scraper.scrape(cfg(), "llama-4-scout-17b-16e") is None


def test_scrape_unknown_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "kimi-k9") is None


def test_scrape_malformed_input_cell_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: token_table_soup(
            model_row(
                "Kimi K3", "/moonshotai/Kimi-K3", "1024k", "$2.85 / $0.285 / $0.10 cached", "$14.25"
            )
        ),
    )
    with pytest.raises(FetchError, match="3 amounts, want 1 or 2"):
        scraper.scrape(cfg(), "kimi-k3")


def test_scrape_malformed_output_cell_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: token_table_soup(
            model_row(
                "Kimi K3",
                "/moonshotai/Kimi-K3",
                "1024k",
                "$2.85 / $0.285 cached",
                "$14.25 / $1.43 cached",
            )
        ),
    )
    with pytest.raises(FetchError, match="2 amounts, want 1"):
        scraper.scrape(cfg(), "kimi-k3")


def test_scrape_unreadable_context_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: token_table_soup(
            model_row("Kimi K3", "/moonshotai/Kimi-K3", "1024", "$2.85", "$14.25")
        ),
    )
    with pytest.raises(FetchError, match="unreadable context '1024'"):
        scraper.scrape(cfg(), "kimi-k3")


def test_scrape_dashed_context_leaves_context_unset(monkeypatch):
    # the page now renders "-" where a model lists no context window; the
    # rates still read, so the row prices without a context limit
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: token_table_soup(
            model_row(
                "DeepSeek V3.2", "/deepseek-ai/DeepSeek-V3.2", "-", "$0.26 / $0.13 cached", "$0.38"
            )
        ),
    )
    pricing = scraper.scrape(cfg(), "deepseek-v3.2")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.26 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.13 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.38 / 1e6)
    assert pricing.max_tokens_in is None


def test_scrape_missing_table_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>Model</th><th>$ per image</th><th>Actions</th></tr></table>",
            "html.parser",
        ),
    )
    with pytest.raises(FetchError, match="no per-token model table"):
        scraper.scrape(cfg(), "kimi-k3")


def test_detect_missing_table_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><th>GPU</th><th>Memory</th><th>Price</th></tr></table>", "html.parser"
        ),
    )
    with pytest.raises(FetchError, match="no per-token model table"):
        detector.detect(cfg())


def test_detect_model_cell_without_link_skips(monkeypatch, caplog):
    # a link-less model cell is additive drift: skipped with a warning,
    # later rows still seed
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: token_table_soup(
            (
                "<tr><td>Kimi K9</td><td>1024k</td><td>$2.85</td><td>$14.25</td>"
                "<td>View more</td></tr>"
            ),
            model_row("Kimi K3", "/moonshotai/Kimi-K3", "1024k", "$2.85", "$14.25"),
        ),
    )
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["kimi-k3"]
    assert "detect skip for deepinfra" in caplog.text
    assert "model cell without a model link" in caplog.text


def test_detect_all_cells_without_links_raises(monkeypatch, caplog):
    # every row skipped leaves no ids: the structural raise stays
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: token_table_soup(
            "<tr><td>Kimi K3</td><td>1024k</td><td>$2.85</td><td>$14.25</td><td>View more</td></tr>"
        ),
    )
    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(FetchError, match="no model ids"),
    ):
        detector.detect(cfg())
    assert "detect skip for deepinfra" in caplog.text


def test_detect_folded_header_matches(monkeypatch):
    # header wording drift (case) still matches after folding
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><thead><tr>"
            "<th>model</th><th>CONTEXT</th><th>$ per 1M input tokens</th>"
            "<th>$ per 1m output tokens</th><th>actions</th>"
            "</tr></thead><tbody>"
            + model_row("Kimi K3", "/moonshotai/Kimi-K3", "1024k", "$2.85", "$14.25")
            + "</tbody></table>",
            "html.parser",
        ),
    )
    assert detector.detect(cfg()) == ["kimi-k3"]


def test_scrape_model_cell_without_link_does_not_block(monkeypatch):
    # a link-less cell the scan passes over is additive drift detect
    # reported; the chosen model still scrapes, the link-less one is absent
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: token_table_soup(
            (
                "<tr><td>Kimi K9</td><td>1024k</td><td>$2.85</td><td>$14.25</td>"
                "<td>View more</td></tr>"
            ),
            model_row("Kimi K3", "/moonshotai/Kimi-K3", "1024k", "$2.85 / $0.285 cached", "$14.25"),
        ),
    )
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(2.85 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.285 / 1e6)
    assert scraper.scrape(cfg(), "kimi-k9") is None


def test_detect_and_scrape_read_a_second_tbody(monkeypatch):
    # a row moved out of a table's first tbody into a second one must still
    # detect and scrape: the reader owns every tbody, never just the first
    soup = load_soup()
    assert move_last_row_to_second_tbody(soup) > 0
    monkeypatch.setattr(detector, "fetch_soup", lambda url: soup)
    assert detector.detect(cfg()) == EXPECTED_IDS
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: soup)
    for model_id in EXPECTED_IDS:
        assert scraper.scrape(cfg(), model_id) is not None


def test_a_model_row_in_the_thead_raises(monkeypatch):
    # a model row swallowed into the header vanishes from detect, so the model
    # would delist after two absent runs: the reader raises instead
    soup = token_table_soup(model_row("Kimi K3", "/moonshotai/Kimi-K3", "256K", "$3", "$15"))
    body_row = soup.find("tbody").find("tr")
    body_row.extract()
    soup.find("thead").append(body_row)
    monkeypatch.setattr(detector, "fetch_soup", lambda url: soup)
    with pytest.raises(FetchError, match="header holds 2 rows"):
        detector.detect(cfg())


def test_a_huge_context_cell_raises_a_fetch_error(monkeypatch):
    # a 4300+ digit context reaches int() and raises ValueError, which is no
    # FetchError: the reader must bound the run and name the cell
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: token_table_soup(
            model_row("Kimi K3", "/moonshotai/Kimi-K3", "9" * 5000 + "k", "$2.85", "$14.25")
        ),
    )
    with pytest.raises(FetchError, match="unreadable context"):
        scraper.scrape(cfg(), "kimi-k3")

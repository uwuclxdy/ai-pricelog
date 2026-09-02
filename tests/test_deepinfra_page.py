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

PAGE_URL = "https://deepinfra.com/pricing"
FIXTURE = Path(__file__).parent / "fixtures" / "deepinfra_page" / "pricing.html"

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

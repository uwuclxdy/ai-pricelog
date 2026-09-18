from __future__ import annotations

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
    "claude-fable-5.1",
    "claude-fable-5",
    "claude-haiku-4.5",
    "claude-opus-5",
    "claude-opus-5-fast-mode",
    "claude-opus-4.8",
    "claude-opus-4.8-fast-mode",
    "claude-opus-4.7",
    "claude-opus-4.6",
    "claude-opus-4.5",
    "claude-sonnet-5",
    "claude-sonnet-4.6",
    "claude-sonnet-4.5",
    "trinity-large",
    "gpt-oss-120b",
    "gpt-oss-20b",
    "gpt-6-astra",
    "gpt-6-astra-fast-mode",
    "gpt-6-astra-flex-mode",
    "gpt-5.6-sol",
    "gpt-5.6-sol-fast-mode",
    "gpt-5.6-sol-flex-mode",
    "gpt-5.6-terra",
    "gpt-5.6-terra-fast-mode",
    "gpt-5.6-terra-flex-mode",
    "gpt-5.6-luna",
    "gpt-5.6-luna-fast-mode",
    "gpt-5.6-luna-flex-mode",
    "gpt-5.5",
    "gpt-5.5-fast-mode",
    "gpt-5.5-flex-mode",
    "gpt-5.4",
    "gpt-5.4-fast-mode",
    "gpt-5.4-flex-mode",
    "gpt-5.4-mini",
    "gpt-5.4-mini-fast-mode",
    "gpt-5.4-mini-flex-mode",
    "gpt-5.4-nano",
    "gpt-5.4-nano-flex-mode",
    "gpt-5.4-pro",
    "gpt-5.4-pro-flex-mode",
    "gpt-5.3-codex",
    "gpt-5.3-codex-fast-mode",
    "gpt-5.2",
    "gpt-5.2-fast-mode",
    "gpt-5.2-flex-mode",
    "gpt-5.2-pro",
    "gpt-5",
    "gpt-5-fast-mode",
    "gpt-5-flex-mode",
    "gpt-5-mini",
    "gpt-5-mini-fast-mode",
    "gpt-5-mini-flex-mode",
    "gpt-5-nano",
    "gpt-5-nano-flex-mode",
    "gpt-4.1",
    "gpt-4.1-fast-mode",
    "gpt-4o",
    "gpt-4o-fast-mode",
    "gpt-4o-mini",
    "gpt-4o-mini-fast-mode",
    "o1",
    "o3",
    "o3-fast-mode",
    "o3-flex-mode",
    "o3-mini",
    "qwen3.8-max",
    "qwen-3.5-397b-a17b",
    "deepseek-v4.1-flash",
    "deepseek-v4-pro-0813",
    "deepseek-v4-flash-0731",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "deepseek-v3.2",
    "gemma-4",
    "minimax-m2.5",
    "kimi-k3",
    "kimi-k2.6",
    "llama-4-maverick-17b-128e-instruct",
    "ministral-3-14b-instruct",
    "nemotron-3-ultra",
    "nemotron-nano-3-omni",
    "nemotron-nano-12b-v2-vl",
    "mimo-v2.5-pro",
    "glm-5.3",
    "glm-5.3-flash",
    "glm-5.2",
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


def matrix_page(
    header: str = "Serverless Inference",
    body: str = "",
    name: str = "Kimi K3",
) -> BeautifulSoup:
    """a minimal one-row page: the table, the pricing matrix, one data row.

    the default data row prices Standard $3.00/$15.00 with $0.30 cache read;
    `body` replaces the matrix's inner markup for the malformed-shape tests.
    """
    if not body:
        body = (
            '<span class="gen-ai-pricing-matrix-row gen-ai-pricing-matrix-header" role="row">'
            '<span role="columnheader">Processing mode</span>'
            '<span role="columnheader">Prompt length</span>'
            '<span role="columnheader">Input</span>'
            '<span role="columnheader">Output</span>'
            '<span role="columnheader">Cache read</span></span>'
            '<span class="gen-ai-pricing-matrix-row" role="row">'
            '<span role="rowheader">Standard</span>'
            '<span role="rowheader">All prompts</span>'
            '<span role="cell">$3.00</span>'
            '<span role="cell">$15.00</span>'
            '<span role="cell">$0.30</span></span>'
        )
    return BeautifulSoup(
        "<table><thead><tr><th>Model</th>"
        f"<th>{header}</th></tr></thead><tbody><tr><td><a>{name}</a></td>"
        '<td><span class="gen-ai-pricing-matrix-wrap">'
        f'<span class="gen-ai-pricing-matrix" role="table">{body}</span>'
        "</span></td></tr></tbody></table>",
        "html.parser",
    )


def test_detect_serverless_models(monkeypatch):
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_scrape_claude_opus_5(monkeypatch):
    # the Standard row: $5.00/$25.00 with $0.50 cache read; the Fast Mode
    # row prices the -fast-mode id, never the base
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "claude-opus-5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(5.00 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(25.00 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.50 / 1e6)
    assert pricing.mode == "chat"


def test_scrape_claude_opus_5_fast_mode(monkeypatch):
    # the -fast-mode id reads the matrix's Fast Mode row: $10/$50/$1.00
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "claude-opus-5-fast-mode")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(10.00 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(50.00 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(1.00 / 1e6)


def test_scrape_mode_row_absent_returns_none(monkeypatch):
    # claude-opus-4.7's matrix carries no Fast Mode row: the -fast-mode id
    # is not among the in-scope rows
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "claude-opus-4.7-fast-mode") is None


def test_scrape_long_context_first_group_standard(monkeypatch):
    # Claude Sonnet 4.5 prices a <= 200K and a > 200K Standard row; the
    # first Standard row is the standard rate, the long-context tier drops
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "claude-sonnet-4.5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.00 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(15.00 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.30 / 1e6)


def test_scrape_deepseek_v4_pro_0813(monkeypatch):
    # the provider-hosted table (Provider | Model | Serverless Inference)
    # prices this DeepSeek row $1.32/$3.96/$0.044
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "deepseek-v4-pro-0813")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1.32 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(3.96 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.044 / 1e6)


def test_scrape_flex_mode_row(monkeypatch):
    # gpt-5.4-mini's Flex Mode row prices the -flex-mode id: $0.375/$2.25
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "gpt-5.4-mini-flex-mode")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.375 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(2.25 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.0375 / 1e6)


def test_scrape_no_cache_read_column(monkeypatch):
    # GPT-5.4 pro's matrix has no Cache read column
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "gpt-5.4-pro")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(30.00 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(180.00 / 1e6)
    assert pricing.cache_read_cost_per_token is None


def test_scrape_link_name_with_cell_suffix(monkeypatch):
    # "MiniMax M2.5 (Public Preview)" keys by the link text "MiniMax M2.5"
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "minimax-m2.5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.30 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(1.20 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.06 / 1e6)


def test_scrape_unknown_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "claude-opus-6") is None


def test_scrape_image_model_out_of_scope(monkeypatch):
    # GPT-image-1 carries a matrix but is an image model: detected ids
    # exclude it and scrape reads it as absent
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "gpt-image-1") is None


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
    # a serverless table whose rows carry no pricing matrix prices nothing;
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


def test_detect_header_wording_drift_still_matches(monkeypatch):
    # the pinned table headers match by folded-cell prefix: the live page
    # appends "USD per 1M tokens unless noted" to the Serverless Inference
    # header since 2026-09-15, and the fold absorbs internal whitespace
    # runs and &/and — all three still locate the serverless tables
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: matrix_page(header="Serverless  Inference & USD per 1M tokens unless noted"),
    )
    assert detector.detect(cfg()) == ["kimi-k3"]


def test_malformed_matrix_no_standard_rates_raises(monkeypatch):
    # a matrix whose Standard row carries no input/output amounts is a
    # shape break, never a silent unpriced read
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: matrix_page(
            body='<span class="gen-ai-pricing-matrix-row gen-ai-pricing-matrix-header" role="row">'
            '<span role="columnheader">Processing mode</span>'
            '<span role="columnheader">Prompt length</span>'
            '<span role="columnheader">Input</span>'
            '<span role="columnheader">Output</span></span>'
            '<span class="gen-ai-pricing-matrix-row" role="row">'
            '<span role="rowheader">Standard</span>'
            '<span role="rowheader">All prompts</span>'
            '<span role="cell">N/A</span>'
            '<span role="cell">N/A</span></span>'
        ),
    )
    with pytest.raises(FetchError, match="no per-1M input/output rates"):
        scraper.scrape(cfg(), "kimi-k3")


def test_malformed_rate_cell_raises(monkeypatch):
    # a rate cell whose text is not a plain dollar amount is a shape break
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: matrix_page(
            body='<span class="gen-ai-pricing-matrix-row gen-ai-pricing-matrix-header" role="row">'
            '<span role="columnheader">Processing mode</span>'
            '<span role="columnheader">Prompt length</span>'
            '<span role="columnheader">Input</span>'
            '<span role="columnheader">Output</span></span>'
            '<span class="gen-ai-pricing-matrix-row" role="row">'
            '<span role="rowheader">Standard</span>'
            '<span role="rowheader">All prompts</span>'
            '<span role="cell">$3.00 per 1M</span>'
            '<span role="cell">$15.00</span></span>'
        ),
    )
    with pytest.raises(FetchError, match="unparseable rate cell"):
        scraper.scrape(cfg(), "kimi-k3")


def test_malformed_matrix_row_cell_count_raises(monkeypatch):
    # a data row with a different cell count than the header is a shape break
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: matrix_page(
            body='<span class="gen-ai-pricing-matrix-row gen-ai-pricing-matrix-header" role="row">'
            '<span role="columnheader">Processing mode</span>'
            '<span role="columnheader">Prompt length</span>'
            '<span role="columnheader">Input</span>'
            '<span role="columnheader">Output</span></span>'
            '<span class="gen-ai-pricing-matrix-row" role="row">'
            '<span role="rowheader">Standard</span>'
            '<span role="cell">$3.00</span>'
            '<span role="cell">$15.00</span></span>'
        ),
    )
    with pytest.raises(FetchError, match="3 cells against 4 columns"):
        scraper.scrape(cfg(), "kimi-k3")


def test_missing_processing_mode_column_raises(monkeypatch):
    # the mode split is load-bearing: a matrix without the Processing mode
    # column is a shape break
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: matrix_page(
            body='<span class="gen-ai-pricing-matrix-row gen-ai-pricing-matrix-header" role="row">'
            '<span role="columnheader">Prompt length</span>'
            '<span role="columnheader">Input</span>'
            '<span role="columnheader">Output</span></span>'
            '<span class="gen-ai-pricing-matrix-row" role="row">'
            '<span role="rowheader">All prompts</span>'
            '<span role="cell">$3.00</span>'
            '<span role="cell">$15.00</span></span>'
        ),
    )
    with pytest.raises(FetchError, match="processing mode"):
        detector.detect(cfg())

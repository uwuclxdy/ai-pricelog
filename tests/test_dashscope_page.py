from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import dashscope_page as dashscope_detect
from ai_pricelog.scrapers import dashscope_page as dashscope_scrape
from ai_pricelog.web import FetchError

FIXTURES = Path(__file__).parent / "fixtures" / "dashscope_page"


@pytest.fixture
def dashscope_cfg() -> ProviderCfg:
    return ProviderCfg(
        key="dashscope",
        yml="dashscope.yml",
        or_prefix="dashscope",
        detector="dashscope_page",
        detector_url="https://help.aliyun.com/zh/model-studio/text-generation-model/",
        scraper="dashscope_page",
        scraper_url="https://www.alibabacloud.com/help/en/model-studio/model-pricing",
    )


@pytest.fixture
def feed_fixtures(monkeypatch: pytest.MonkeyPatch) -> None:
    def feed(url: str) -> str:
        if url.endswith("text-generation-model/"):
            return (FIXTURES / "textgen-cn.html").read_text()
        if url.endswith("model-pricing"):
            return (FIXTURES / "model-pricing-intl.html").read_text()
        raise AssertionError(f"unexpected url: {url}")

    def soup(url: str) -> BeautifulSoup:
        return BeautifulSoup(feed(url), "html.parser")

    monkeypatch.setattr(dashscope_detect, "fetch_soup", soup)
    monkeypatch.setattr(dashscope_scrape, "fetch_soup", soup)


def test_detect_returns_all_fixture_models_in_page_order(dashscope_cfg, feed_fixtures):
    assert dashscope_detect.detect(dashscope_cfg) == [
        "qwen3.8-max",
        "qwen3.7-plus",
        "qwen3.7-plus-2026-05-26",
        "qwen3.7-flash",
        "qwen3.7-flash-2026-07-15",
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "glm-5.2",
        "kimi-k2.7-code",
        "MiniMax-M3",
        "mimo-v2.5-pro",
        "qwen3.7-max",
        "qwen3.7-max-preview",
        "qwen3.7-max-2026-06-08",
        "qwen3.7-max-2026-05-20",
        "qwen3.7-max-2026-05-17",
        "glm-5.1",
        "glm-5",
        "glm-4.7",
        "glm-4.5",
        "glm-4.5-air",
        "MiniMax-M2.7",
        "MiniMax-M2.5",
        "MiniMax-M2.1",
        "kimi-k2.5",
        "kimi-k2-thinking",
        "Moonshot-Kimi-K2-Instruct",
        "deepseek-v3.2",
        "deepseek-v3.2-exp",
        "deepseek-v3.1",
        "deepseek-v3",
        "deepseek-r1",
        "deepseek-r1-0528",
        "deepseek-r1-distill-llama-70b",
        "deepseek-r1-distill-qwen-32b",
        "deepseek-r1-distill-qwen-14b",
        "deepseek-r1-distill-qwen-7b",
        "deepseek-r1-distill-qwen-1.5b",
        "deepseek-r1-distill-llama-8b",
    ]


def test_scrape_qwen37_plus_takes_first_dollar_amount(dashscope_cfg, feed_fixtures):
    pricing = dashscope_scrape.scrape(dashscope_cfg, "qwen3.7-plus")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.4 / 1e6
    assert pricing.output_cost_per_token == 1.6 / 1e6
    assert pricing.mode == "chat"
    assert pricing.max_tokens == 0


def test_scrape_snapshot_version_matches_its_row(dashscope_cfg, feed_fixtures):
    pricing = dashscope_scrape.scrape(dashscope_cfg, "qwen3.7-plus-2026-05-26")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.4 / 1e6
    assert pricing.output_cost_per_token == 1.6 / 1e6


def test_scrape_single_output_column_table(dashscope_cfg, feed_fixtures):
    pricing = dashscope_scrape.scrape(dashscope_cfg, "glm-5.2")
    assert pricing is not None
    assert pricing.input_cost_per_token == 1.4 / 1e6
    assert pricing.output_cost_per_token == 4.4 / 1e6


def test_scrape_global_only_scope_returns_none(dashscope_cfg, feed_fixtures):
    assert dashscope_scrape.scrape(dashscope_cfg, "qwen3.7-max") is None


def test_scrape_model_absent_from_pricing_page_returns_none(dashscope_cfg, feed_fixtures):
    assert dashscope_scrape.scrape(dashscope_cfg, "qwen3.8-max") is None


def test_detect_malformed_page_raises_fetch_error(dashscope_cfg, monkeypatch):
    monkeypatch.setattr(
        dashscope_detect, "fetch_soup", lambda url: BeautifulSoup("<html></html>", "html.parser")
    )
    with pytest.raises(FetchError):
        dashscope_detect.detect(dashscope_cfg)


def test_detect_tables_without_ids_raise_fetch_error(dashscope_cfg, monkeypatch):
    monkeypatch.setattr(
        dashscope_detect,
        "fetch_soup",
        lambda url: BeautifulSoup(
            "<table><tr><td>模型 ID</td></tr><tr><td>!!</td></tr></table>", "html.parser"
        ),
    )
    with pytest.raises(FetchError, match="model ids"):
        dashscope_detect.detect(dashscope_cfg)


def test_scrape_short_row_falls_through_to_later_tables(dashscope_cfg, monkeypatch):
    header = (
        "<td>Input price (per 1 million tokens)</td><td>Output price (per 1 million tokens)</td>"
    )
    html = (
        "<table><tr><td>Model ID</td><td>Deployment scope</td>"
        f"{header}</tr>"
        "<tr><td>qwen-x</td><td>International</td></tr></table>"
        "<table><tr><td>Model ID</td><td>Deployment scope</td>"
        f"{header}</tr>"
        "<tr><td>qwen-x</td><td>International</td><td>$0.1</td><td>$0.5</td></tr></table>"
    )
    monkeypatch.setattr(
        dashscope_scrape, "fetch_soup", lambda url: BeautifulSoup(html, "html.parser")
    )
    pricing = dashscope_scrape.scrape(dashscope_cfg, "qwen-x")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.1 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.5 / 1e6)
    assert pricing.max_tokens == 0


def test_scrape_unpriced_row_falls_through_to_later_tables(dashscope_cfg, monkeypatch):
    header = (
        "<td>Input price (per 1 million tokens)</td><td>Output price (per 1 million tokens)</td>"
    )
    html = (
        "<table><tr><td>Model ID</td><td>Deployment scope</td>"
        f"{header}</tr>"
        "<tr><td>qwen-x</td><td>International</td><td>List price --</td><td>--</td></tr></table>"
        "<table><tr><td>Model ID</td><td>Deployment scope</td>"
        f"{header}</tr>"
        "<tr><td>qwen-x</td><td>International</td><td>$0.1</td><td>$0.5</td></tr></table>"
    )
    monkeypatch.setattr(
        dashscope_scrape, "fetch_soup", lambda url: BeautifulSoup(html, "html.parser")
    )
    pricing = dashscope_scrape.scrape(dashscope_cfg, "qwen-x")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.1 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.5 / 1e6)


def test_scrape_page_without_pricing_tables_raises_fetch_error(dashscope_cfg, monkeypatch):
    monkeypatch.setattr(
        dashscope_scrape,
        "fetch_soup",
        lambda url: BeautifulSoup("<table><tr><td>unrelated</td></tr></table>", "html.parser"),
    )
    with pytest.raises(FetchError):
        dashscope_scrape.scrape(dashscope_cfg, "qwen3.7-plus")

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import dashscope_page as dashscope_detect
from ai_pricelog.pricing import to_mtok
from ai_pricelog.scrapers import dashscope_page as dashscope_scrape
from ai_pricelog.web import FetchError

FIXTURES = Path(__file__).parent / "fixtures" / "dashscope_page"
CN_URL = "https://help.aliyun.com/zh/model-studio/text-generation-model/"
EN_URL = "https://www.alibabacloud.com/help/en/model-studio/model-pricing"
# the 2026-08-19 capture: `Input price` / `Output price` headers, every cell
# in its grid position
OLD_EN_FIXTURE = "model-pricing-intl-2026-08-19.html"

# the 14 ids PR #839 proposed as delisted, at their removal-snapshot rates
# (their last priced rows on c9a9e682, USD per 1M tokens)
FALSE_REMOVALS = {
    "glm-5.2-fast-preview": (2.8, 8.8),
    "qwen3-coder-flash-2025-07-28": (0.3, 1.5),
    "qwen3.5-flash-2026-02-23": (0.1, 0.4),
    "qwen3.5-plus-2026-02-15": (0.4, 2.4),
    "qwen3.6-27b": (0.6, 3.6),
    "qwen3.6-flash-2026-04-16": (0.25, 1.5),
    "qwen3.6-plus-2026-04-02": (0.5, 3.0),
    "qwen3.7-flash-2026-07-15": (0.03, 0.13),
    "qwen3.7-max-2026-05-17": (2.5, 7.5),
    "qwen3.7-max-2026-05-20": (2.5, 7.5),
    "qwen3.7-max-2026-06-08": (2.5, 7.5),
    "qwen3.7-max-preview": (2.5, 7.5),
    "qwen3.7-plus-2026-05-26": (0.4, 1.6),
    "qwen3.8-max-0902": (2.0, 6.0),
}

# every dashscope id whose latest row on c9a9e682 is not removed, at that
# row's rates (USD per 1M tokens)
LIVE_STORED = {
    "deepseek-v4.1-flash-1017": (0.3, 1.2),
    "glm-5.2-fast-preview": (2.8, 8.8),
    "glm-5.3": (1.4, 4.4),
    "kimi-k3": (3.0, 15.0),
    "kimi-k3.1-pro": (2.0, 10.0),
    "qwen-flash": (0.05, 0.4),
    "qwen-flash-character": (0.05, 0.4),
    "qwen-max": (1.6, 6.4),
    "qwen-mt-flash": (0.16, 0.49),
    "qwen-mt-lite": (0.12, 0.36),
    "qwen-mt-plus": (2.46, 7.37),
    "qwen-plus": (0.4, 1.2),
    "qwen-plus-character": (0.5, 1.4),
    "qwen-plus-character-ja": (0.5, 1.4),
    "qwen3-coder-flash": (0.3, 1.5),
    "qwen3-coder-flash-2025-07-28": (0.3, 1.5),
    "qwen3.5-122b-a10b": (0.4, 3.2),
    "qwen3.5-27b": (0.3, 2.4),
    "qwen3.5-35b-a3b": (0.25, 2.0),
    "qwen3.5-397b-a17b": (0.6, 3.6),
    "qwen3.5-flash": (0.1, 0.4),
    "qwen3.5-flash-2026-02-23": (0.1, 0.4),
    "qwen3.5-plus": (0.4, 2.4),
    "qwen3.5-plus-2026-02-15": (0.4, 2.4),
    "qwen3.6-27b": (0.6, 3.6),
    "qwen3.6-35b-a3b": (0.375, 2.25),
    "qwen3.6-flash": (0.25, 1.5),
    "qwen3.6-flash-2026-04-16": (0.25, 1.5),
    "qwen3.6-plus": (0.5, 3.0),
    "qwen3.6-plus-2026-04-02": (0.5, 3.0),
    "qwen3.7-flash": (0.03, 0.13),
    "qwen3.7-flash-2026-07-15": (0.03, 0.13),
    "qwen3.7-max": (2.5, 7.5),
    "qwen3.7-max-2026-05-17": (2.5, 7.5),
    "qwen3.7-max-2026-05-20": (2.5, 7.5),
    "qwen3.7-max-2026-06-08": (2.5, 7.5),
    "qwen3.7-max-preview": (2.5, 7.5),
    "qwen3.7-plus": (0.4, 1.6),
    "qwen3.7-plus-2026-05-26": (0.4, 1.6),
    "qwen3.8-flash": (0.15, 0.47),
    "qwen3.8-max": (2.0, 6.0),
    "qwen3.8-max-0902": (2.0, 6.0),
    "qwen4-max": (1.5, 4.5),
}

# the 2026-11-18 CN text-generation page, in page order
CN_IDS = [
    "qwen4-max",
    "qwen3.8-flash",
    "qwen3.7-plus",
    "deepseek-v4.1-flash-1017",
    "glm-5.3",
    "kimi-k3.1-pro",
    "kimi-k3",
    "MiniMax-M3.1-Flash",
    "mimo-v2.6-pro-ultraspeed",
    "step-5-preview",
    "qwen3.8-max",
    "qwen3.7-max",
    "qwen3.7-flash",
    "qwen3.6-plus",
    "qwen3.6-flash",
    "qwen3.6-35b-a3b",
    "qwen3.5-plus",
    "qwen3.5-flash",
    "qwen3.5-397b-a17b",
    "qwen3.5-122b-a10b",
    "qwen3.5-27b",
    "qwen3.5-35b-a3b",
    "qwen3-coder-flash",
    "qwen-mt-plus",
    "qwen-mt-flash",
    "qwen-mt-lite",
    "qwen-long",
    "qwen-plus-character",
    "qwen-plus-character-ja",
    "qwen-flash-character",
    "qwen-plus",
    "qwen-max",
    "qwen-flash",
    "deepseek-r1-distill-llama-70b",
    "deepseek-r1-distill-qwen-1.5b",
]

# the ids the 2026-11-18 EN fixture prices on an International row, page order
EN_PRICED_IDS = [
    "qwen4-max",
    "qwen3.8-max",
    "qwen3.8-max-0902",
    "qwen3.7-max",
    "qwen3.7-max-2026-06-08",
    "qwen3.7-max-2026-05-20",
    "qwen3.7-max-preview",
    "qwen3.7-max-2026-05-17",
    "qwen-max",
    "qwen3.7-plus",
    "qwen3.7-plus-2026-05-26",
    "qwen3.6-plus",
    "qwen3.6-plus-2026-04-02",
    "qwen3.5-plus",
    "qwen3.5-plus-2026-04-20",
    "qwen3.5-plus-2026-02-15",
    "qwen-plus",
    "qwen-plus-latest",
    "qwen-plus-2025-12-01",
    "qwen-plus-2025-07-14",
    "qwen-plus-2025-04-28",
    "qwen-plus-2025-01-25",
    "qwen3.8-flash",
    "qwen3.7-flash",
    "qwen3.7-flash-2026-07-15",
    "qwen3.6-flash",
    "qwen3.6-flash-2026-04-16",
    "qwen3.5-flash",
    "qwen3.5-flash-2026-02-23",
    "qwen-flash",
    "qwen-flash-2025-07-28",
    "qwen3-coder-flash",
    "qwen3-coder-flash-2025-07-28",
    "qwen-mt-plus",
    "qwen-mt-flash",
    "qwen-mt-lite",
    "qwen3.6-35b-a3b",
    "qwen3.6-27b",
    "qwen3.5-397b-a17b",
    "qwen3.5-122b-a10b",
    "qwen3.5-27b",
    "qwen3.5-35b-a3b",
    "deepseek-v4.1-flash-1017",
    "deepseek-v4.1-flash",
    "deepseek-v4-pro-0813",
    "deepseek-v4-flash-0731",
    "kimi-k3",
    "kimi-k3.1-pro",
    "glm-5.3",
    "glm-5.2-fast-preview",
    "glm-5.3-prime",
    "qwen-image-3.0-pro",
    "qwen-image-3.0",
    "qwen-plus-character",
    "qwen-flash-character",
    "qwen-plus-character-ja",
]


@pytest.fixture
def dashscope_cfg() -> ProviderCfg:
    return ProviderCfg(
        key="dashscope",
        provider="DashScope",
        detector="dashscope_page",
        detector_url=CN_URL,
        scraper="dashscope_page",
        scraper_url=EN_URL,
    )


def serve_pages(monkeypatch: pytest.MonkeyPatch, en: str = "model-pricing-intl.html") -> list[str]:
    """serve the CN fixture and the named EN fixture, parsed once; returns the
    fetched urls in order."""
    soups = {
        CN_URL: BeautifulSoup((FIXTURES / "textgen-cn.html").read_text(), "html.parser"),
        EN_URL: BeautifulSoup((FIXTURES / en).read_text(), "html.parser"),
    }
    fetched: list[str] = []

    def soup(url: str) -> BeautifulSoup:
        fetched.append(url)
        if url not in soups:
            raise AssertionError(f"unexpected url: {url}")
        return soups[url]

    monkeypatch.setattr(dashscope_detect, "fetch_soup", soup)
    monkeypatch.setattr(dashscope_scrape, "fetch_soup", soup)
    return fetched


def serve_html(monkeypatch: pytest.MonkeyPatch, html: str) -> None:
    soup = BeautifulSoup(html, "html.parser")
    monkeypatch.setattr(dashscope_detect, "fetch_soup", lambda url: soup)
    monkeypatch.setattr(dashscope_scrape, "fetch_soup", lambda url: soup)


def rates(cfg: ProviderCfg, model_id: str) -> tuple[float, float] | None:
    """the scraped rates per 1M tokens, rounded as the store rounds."""
    pricing = dashscope_scrape.scrape(cfg, model_id)
    if pricing is None:
        return None
    return (to_mtok(pricing.input_cost_per_token), to_mtok(pricing.output_cost_per_token))


def pricing_table(rows: str, *, pattern: bool = False, scope: bool = True) -> str:
    header = "<td>Model ID</td>"
    if scope:
        header += "<td>Service Deployment Scope</td>"
    if pattern:
        header += "<td>Pattern</td>"
    header += (
        "<td>Input token range per request</td>"
        "<td>Input unit price (per million tokens)</td>"
        "<td>Output unit price (per million tokens)</td>"
        "<td>Free quota</td>"
    )
    return f"<table><tr>{header}</tr>{rows}</table>"


# --- the 2026-11-18 page ---------------------------------------------------


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [("qwen4-max", (1.5, 4.5))] + [(model_id, rate) for model_id, rate in FALSE_REMOVALS.items()],
)
def test_scrape_prices_the_unit_price_page(dashscope_cfg, monkeypatch, model_id, expected):
    serve_pages(monkeypatch)
    assert rates(dashscope_cfg, model_id) == expected


def test_scrape_reads_rows_that_omit_a_grid_cell(dashscope_cfg, monkeypatch):
    # the International flash rows omit the `Pattern` cell and pad an empty
    # cell at the end, so positional indexing reads `1 million Tokens` as
    # the output rate; the token-range cell anchors the row instead
    serve_pages(monkeypatch)
    assert rates(dashscope_cfg, "qwen3.5-flash-2026-02-23") == (0.1, 0.4)
    assert rates(dashscope_cfg, "qwen3.6-flash-2026-04-16") == (0.25, 1.5)
    # the same table's rows that carry the `Pattern` cell keep their positions
    assert rates(dashscope_cfg, "qwen3.7-flash-2026-07-15") == (0.03, 0.13)
    assert rates(dashscope_cfg, "qwen3.8-flash") == (0.15, 0.47)


def test_scrape_omitted_cell_row_aligns_on_its_token_range(dashscope_cfg, monkeypatch):
    rows = (
        "<tr><td>qwen-full</td><td>International</td><td>Thinking mode</td>"
        "<td>0&lt;Token≤1M</td><td>$0.3</td><td>$0.9</td><td>None</td></tr>"
        "<tr><td>qwen-short</td><td>International</td>"
        "<td>0&lt;Token≤1M</td><td>$0.1</td><td>$0.4</td><td>1 million Tokens</td><td></td></tr>"
    )
    serve_html(monkeypatch, pricing_table(rows, pattern=True))
    assert rates(dashscope_cfg, "qwen-full") == (0.3, 0.9)
    assert rates(dashscope_cfg, "qwen-short") == (0.1, 0.4)


def test_scrape_never_aligns_a_price_onto_the_scope_cell(dashscope_cfg, monkeypatch):
    # a token-range cell sitting where the scope belongs would shift the
    # price columns onto the id and scope cells; such a row is skipped. the
    # scope cell carries an amount, so dropping the guard prices the row
    # from that cell and reds this test
    rows = (
        "<tr><td>qwen-x</td><td>International $0.99</td><td>$0.1</td><td>$0.4</td>"
        "<td>x</td><td>0&lt;Token≤1M</td><td></td></tr>"
    )
    html = (
        "<table><tr><td>Model ID</td><td>Service Deployment Scope</td>"
        "<td>Input unit price</td><td>Output unit price</td><td>Pattern</td>"
        "<td>Free quota</td><td>Input token range per request</td></tr>"
        f"{rows}</table>"
    )
    serve_html(monkeypatch, html)
    assert dashscope_scrape.scrape(dashscope_cfg, "qwen-x") is None


def test_scrape_takes_the_row_id_from_the_first_token_only(dashscope_cfg, monkeypatch):
    # the alias row's note names the dated id; the dated id prices from its
    # own row, never from the alias row's promo cells
    serve_pages(monkeypatch)
    assert rates(dashscope_cfg, "qwen3.7-plus-2026-05-26") == (0.4, 1.6)


# --- promo cells: the rate in force -----------------------------------------


def test_scrape_promo_list_amount_records_the_discounted_rate(dashscope_cfg, monkeypatch):
    # `Original$0.4 (20% off for a limited time)`: 0.4 x 80 / 100
    serve_pages(monkeypatch)
    assert rates(dashscope_cfg, "qwen3.7-plus") == (0.32, 1.28)


def test_scrape_old_list_price_promo_records_the_discounted_rate(dashscope_cfg, monkeypatch):
    # `List price $0.4 Limited-time 20% off`, the 2026-08-19 spelling
    serve_pages(monkeypatch, en=OLD_EN_FIXTURE)
    assert rates(dashscope_cfg, "qwen3.7-plus") == (0.32, 1.28)


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("Original$0.4 (20% off for a limited time)", 0.32),
        ("List price $1.65 Limited-time 15% off", 1.4025),
        ("Original$0.4 (20%off)", 0.32),
        ("Original$0.4 $0.3 (20% off for a limited time)", 0.3),
        ("$0.3 Original$0.4 (20% off for a limited time)", 0.3),
        ("Original $1,234.5 $1,000.5 (20% off for a limited time)", 1000.5),
        ("List price $1,234.5 Limited-time 20% off", 987.6),
        ("original$0.4 $0.3 (20% off for a limited time)", 0.3),
        ("Original$0.4 (100% off for a limited time)", 0.0),
        ("$0.4", 0.4),
        ("$0.4 cached $0.04", 0.4),
        # the live audio rows' currency suffix form
        ("0.15 USD/million tokens", 0.15),
        # both currency forms in one plain cell: the first amount still wins
        ("$0.4 0.3 USD/million tokens", 0.4),
        ("$0.15 0.15 USD/million tokens", 0.15),
        # a complete amount right before the percent is no split token
        ("Original$0.4 20% off for a limited time", 0.32),
        ("Original $1,234.5 20% off", 987.6),
        # the list label also attaches to a suffix-form amount
        ("Original 0.4 USD/million tokens (20% off for a limited time)", 0.32),
        ("List price 0.4 USD/million tokens (20% off for a limited time)", 0.32),
    ],
)
def test_scrape_rate_in_force_per_cell_form(dashscope_cfg, monkeypatch, cell, expected):
    rows = (
        f"<tr><td>qwen-x</td><td>International</td><td>0&lt;Token≤1M</td>"
        f"<td>{cell}</td><td>$1</td><td>None</td></tr>"
    )
    serve_html(monkeypatch, pricing_table(rows))
    assert rates(dashscope_cfg, "qwen-x") == (expected, 1.0)


@pytest.mark.parametrize(
    "cell",
    [
        # two discounts: a peak and an off-peak rate, no single rate in force
        "Original$0.276 (limited-time 60% off for off-peak usage) 20% off during peak hours",
        # a discount marker beside one unlabelled amount: list or charged is unknown
        "$0.4 (20% off for a limited time)",
        # three amounts beside a discount marker
        "Original$0.4 $0.35 $0.32 (20% off for a limited time)",
        "Original$0.4 (120% off for a limited time)",
        # a list label says the amount is not what the page charges, and no
        # marker gives the discount: the cell names no charged rate
        "Original$0.4 (limited time)",
        "List price $0.4",
        # two amounts both labelled as the list: no single charged rate
        "Original$0.4 Original$0.3 (20% off for a limited time)",
        "Original$0.4 Original$0.4 (20% off for a limited time)",
        "Original$0.4 (20% off) Original$0.4",
        # the label names no amount, so which amount is the list is unknown
        "Original price $0.4 $0.3 (20% off for a limited time)",
        # a marked cell carrying a second amount on another priced axis
        "Original$2 (20% off for a limited time) Cache hit input: $0.2",
        "$2 Cache hit input: $0.2 (20% off for a limited time)",
        "Peak $0.3 Off-peak $0.15 (limited-time 50% off)",
        # a marked cell whose second amount is unlabelled: list or charged is
        # unknown
        "$0.3 $0.4 (20% off for a limited time)",
        # the percent runs to the whole token; past 100 there is no rate
        "Original$0.4 (1000% off for a limited time)",
        "Original$0.4 (1,000% off for a limited time)",
        # a percent token split by whitespace is never its trailing fragment
        "Original$0.4 (1 000% off for a limited time)",
        "Original$0.4 (10 00% off for a limited time)",
        "Original$0.4 (1, 000% off for a limited time)",
        "Original$0.4 (1. 000% off for a limited time)",
        # a split percent behind a dollar-led fragment
        "Original$0.4 ($1 000% off for a limited time)",
        "Original$0.4 $12 000% off",
        # a percent token glued to the end of the amount reads the amount as
        # the percent
        "Original$0.420% off for a limited time",
        # a suffix-form amount beside a dollar amount is read too: the first
        # two hit the axis guard, the last two the equal-list guard
        "Original$2 (20% off for a limited time) Cache hit input: 0.2 USD/million tokens",
        "Original$0.3 Peak 0.15 USD/million tokens (50% off for a limited time)",
        "Original$2 (20% off for a limited time) Cache hit input: 2 USD/million tokens",
        "Original$0.4 0.4 USD/million tokens (20% off for a limited time)",
        # the page's `cached` spelling names another priced axis too
        "Original$0.4 $0.3 cached (20% off for a limited time)",
        "Original$0.4 $0.3 Cached (20% off for a limited time)",
        # an amount-shaped suffix token the grammar cannot read beside a
        # readable dollar amount
        "$0.4 1.2.3 USD",
    ],
)
def test_scrape_unreadable_promo_cell_raises(dashscope_cfg, monkeypatch, cell):
    rows = (
        f"<tr><td>qwen-x</td><td>International</td><td>0&lt;Token≤1M</td>"
        f"<td>{cell}</td><td>$1</td><td>None</td></tr>"
    )
    serve_html(monkeypatch, pricing_table(rows))
    with pytest.raises(FetchError, match="qwen-x"):
        dashscope_scrape.scrape(dashscope_cfg, "qwen-x")


# --- the 2026-08-19 page (the `Input price` headers) ------------------------


def test_old_header_fixture_prices_as_before(dashscope_cfg, monkeypatch):
    # the pre-change scraper's output on this fixture; qwen3.7-plus alone
    # moves, its `List price ... 20% off` cells now record the rate in force
    serve_pages(monkeypatch, en=OLD_EN_FIXTURE)
    expected = {
        "glm-5.1": (1.4, 4.4),
        "glm-5.2": (1.4, 4.4),
        "glm-5.2-fast-preview": (2.8, 8.8),
        "qwen-plus": (0.4, 1.2),
        "qwen-plus-2025-01-25": (0.4, 1.2),
        "qwen-plus-2025-04-28": (0.4, 1.2),
        "qwen-plus-2025-07-14": (0.4, 1.2),
        "qwen-plus-2025-07-28": (0.4, 1.2),
        "qwen-plus-2025-09-11": (0.4, 1.2),
        "qwen-plus-2025-12-01": (0.4, 1.2),
        "qwen-plus-latest": (0.4, 1.2),
        "qwen3-max": None,
        "qwen3-max-2026-01-23": None,
        "qwen3.5-plus": (0.4, 2.4),
        "qwen3.5-plus-2026-02-15": (0.4, 2.4),
        "qwen3.5-plus-2026-04-20": (0.4, 2.4),
        "qwen3.6-plus": (0.5, 3.0),
        "qwen3.6-plus-2026-04-02": (0.5, 3.0),
        "qwen3.7-max": None,
        "qwen3.7-max-2026-05-20": None,
        "qwen3.7-max-2026-06-08": None,
        "qwen3.7-plus": (0.32, 1.28),
        "qwen3.7-plus-2026-05-26": (0.4, 1.6),
    }
    assert {model_id: rates(dashscope_cfg, model_id) for model_id in expected} == expected


def test_scrape_old_fixture_model_absent_returns_none(dashscope_cfg, monkeypatch):
    serve_pages(monkeypatch, en=OLD_EN_FIXTURE)
    assert dashscope_scrape.scrape(dashscope_cfg, "qwen3.8-max") is None


def test_scrape_omni_split_columns_take_first_sub_column(dashscope_cfg, monkeypatch):
    # the omni tables split the input span into text/audio/image and the
    # output span into three modes; the row cells follow the expanded grid,
    # so the first input position is the text rate and the first output
    # position the text-output rate (the base rates)
    html = (
        "<table><tr>"
        "<th>Model ID</th><th>Deployment scope</th>"
        "<th colspan='3'>Input price (per 1 million tokens)</th>"
        "<th colspan='3'>Output price (per 1 million tokens)</th>"
        "<th>Free quota</th></tr>"
        "<tr><th>Text</th><th>Audio</th><th>Image/video</th>"
        "<th>Text Text-only input</th><th>Text Multimodal input</th>"
        "<th>Text + audio Audio only billed</th></tr>"
        "<tr><td>qwen2.5-omni-7b</td><td>International</td>"
        "<td>$0.10</td><td>$6.76</td><td>$0.28</td>"
        "<td>$0.40</td><td>$0.84</td><td>$13.51</td>"
        "<td>1 million tokens</td></tr>"
        "</table>"
    )
    serve_html(monkeypatch, html)
    pricing = dashscope_scrape.scrape(dashscope_cfg, "qwen2.5-omni-7b")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.10 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.40 / 1e6)


def test_scrape_reads_only_the_tables_own_header_cells(dashscope_cfg, monkeypatch):
    # a nested table inside a header cell must not widen the column grid, which
    # would shift every rate column and leave the row short of its indexes
    html = (
        "<table><tr><td>Model ID</td><td>Deployment scope"
        "<table><tr><td>nested</td></tr></table></td>"
        "<td>Input price (per 1 million tokens)</td>"
        "<td>Output price (per 1 million tokens)</td></tr>"
        "<tr><td>qwen-x</td><td>International</td><td>$0.1</td><td>$0.5</td></tr></table>"
    )
    serve_html(monkeypatch, html)
    pricing = dashscope_scrape.scrape(dashscope_cfg, "qwen-x")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.1 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.5 / 1e6)


def test_scrape_global_only_scope_returns_none(dashscope_cfg, monkeypatch):
    serve_pages(monkeypatch, en=OLD_EN_FIXTURE)
    assert dashscope_scrape.scrape(dashscope_cfg, "qwen3.7-max") is None


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
    serve_html(monkeypatch, html)
    pricing = dashscope_scrape.scrape(dashscope_cfg, "qwen-x")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.1 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.5 / 1e6)
    assert pricing.max_tokens_in == pricing.max_tokens_out == 0


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
    serve_html(monkeypatch, html)
    pricing = dashscope_scrape.scrape(dashscope_cfg, "qwen-x")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.1 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.5 / 1e6)


def test_scrape_page_without_pricing_tables_raises_fetch_error(dashscope_cfg, monkeypatch):
    serve_html(monkeypatch, "<table><tr><td>unrelated</td></tr></table>")
    with pytest.raises(FetchError):
        dashscope_scrape.scrape(dashscope_cfg, "qwen3.7-plus")


# --- detection --------------------------------------------------------------


def test_detect_reads_only_the_cn_text_generation_page(dashscope_cfg, monkeypatch):
    # candidates stay on the text-generation page, so a priced image or video
    # model of the pricing page never becomes a chat candidate
    fetched = serve_pages(monkeypatch)
    detected = dashscope_detect.detect(dashscope_cfg)
    assert detected == CN_IDS
    assert fetched == [CN_URL]
    assert "qwen-image-3.0" not in detected


def test_detect_takes_every_id_token_of_a_multi_id_first_cell(dashscope_cfg, monkeypatch):
    html = (
        "<table><tr><td>模型 ID</td><td>上下文</td></tr>"
        "<tr><td>qwen3.7-max 查看快照版本 qwen3.7-max-2026-06-08 qwen3.7-max-preview</td>"
        "<td>1M</td></tr></table>"
    )
    serve_html(monkeypatch, html)
    assert dashscope_detect.detect(dashscope_cfg) == [
        "qwen3.7-max",
        "qwen3.7-max-2026-06-08",
        "qwen3.7-max-preview",
    ]


def test_detect_excludes_resold_first_party_ids(dashscope_cfg, monkeypatch):
    rows = "".join(f"<tr><td>{model_id}</td></tr>" for model_id in ("qwen-x", "glm-5.2"))
    serve_html(monkeypatch, f"<table><tr><td>模型 ID</td></tr>{rows}</table>")
    assert dashscope_detect.detect(dashscope_cfg) == ["qwen-x"]


def test_detect_malformed_page_raises_fetch_error(dashscope_cfg, monkeypatch):
    serve_html(monkeypatch, "<html></html>")
    with pytest.raises(FetchError):
        dashscope_detect.detect(dashscope_cfg)


def test_detect_tables_without_ids_raise_fetch_error(dashscope_cfg, monkeypatch):
    serve_html(monkeypatch, "<table><tr><td>模型 ID</td></tr><tr><td>!!</td></tr></table>")
    with pytest.raises(FetchError, match="model ids"):
        dashscope_detect.detect(dashscope_cfg)


def test_detect_priced_lists_every_international_priced_id(dashscope_cfg, monkeypatch):
    fetched = serve_pages(monkeypatch)
    priced = dashscope_detect.detect_priced(dashscope_cfg)
    assert fetched == [EN_URL]
    assert priced == EN_PRICED_IDS
    assert set(FALSE_REMOVALS) <= set(priced)
    assert set(LIVE_STORED) <= set(priced)
    # first-cell notes (`Current capabilities are equivalent to ...`, `Cache
    # unit price`, `Context cache enjoys a discount`) and tier labels never
    # read as ids
    assert {"Cache", "unit", "price", "2K", "Current", "Context", "cache"}.isdisjoint(priced)


def test_detect_priced_reads_the_old_header_page_too(dashscope_cfg, monkeypatch):
    serve_pages(monkeypatch, en=OLD_EN_FIXTURE)
    priced = dashscope_detect.detect_priced(dashscope_cfg)
    assert "qwen3.7-plus-2026-05-26" in priced
    assert "glm-5.2-fast-preview" in priced
    # Global-only and Hong Kong rows are not the International price
    assert "qwen3.7-max" not in priced
    assert "qwen3-max" not in priced
    # resold first-party ids stay out, as in detect
    assert "glm-5.2" not in priced
    assert "glm-5.1" not in priced


def test_detect_priced_skips_rows_without_both_amounts(dashscope_cfg, monkeypatch):
    rows = (
        "<tr><td>qwen-priced</td><td>International</td><td>0&lt;Token≤1M</td>"
        "<td>$0.1</td><td>$0.4</td><td>None</td></tr>"
        "<tr><td>qwen-free</td><td>International</td><td>0&lt;Token≤1M</td>"
        "<td>Limited Time Free</td><td>$0.4</td><td>None</td></tr>"
        "<tr><td>qwen-global</td><td>Global</td><td>0&lt;Token≤1M</td>"
        "<td>$0.1</td><td>$0.4</td><td>None</td></tr>"
        "<tr><td>qwen-split</td><td>International</td><td>0&lt;Token≤1M</td>"
        "<td>Original$0.2 (60% off off-peak) 20% off peak</td><td>$0.4</td><td>None</td></tr>"
        "<tr><td>qwen-comma</td><td>International</td><td>0&lt;Token≤1M</td>"
        "<td>$0,30</td><td>$0.4</td><td>None</td></tr>"
    )
    serve_html(monkeypatch, pricing_table(rows))
    # an amount the scraper cannot read still lists the model: the scraper
    # raises on its cell, absence must not count it delisted
    assert dashscope_detect.detect_priced(dashscope_cfg) == [
        "qwen-priced",
        "qwen-split",
        "qwen-comma",
    ]


def test_detect_priced_reads_the_usd_suffix_amount_form(dashscope_cfg, monkeypatch):
    # the live audio rows price in the suffix form; either currency form
    # lists the row as priced, and the scraper reads its amount
    rows = (
        "<tr><td>qwen-usd</td><td>International</td><td>0&lt;Token≤1M</td>"
        "<td>0.15 USD/million tokens</td><td>0.4 USD/million tokens</td><td>None</td></tr>"
        "<tr><td>qwen-half</td><td>International</td><td>0&lt;Token≤1M</td>"
        "<td>0.15 USD/million tokens</td><td>Limited Time Free</td><td>None</td></tr>"
    )
    serve_html(monkeypatch, pricing_table(rows))
    assert dashscope_detect.detect_priced(dashscope_cfg) == ["qwen-usd"]
    assert rates(dashscope_cfg, "qwen-usd") == (0.15, 0.4)


def test_detect_priced_raises_when_the_page_prices_no_id(dashscope_cfg, monkeypatch):
    # a header reword the table walk cannot read must not empty the priced
    # set, or every stored id would count absent
    html = (
        "<table><tr><td>Model ID</td><td>Service Deployment Scope</td>"
        "<td>Input cost</td><td>Output cost</td></tr>"
        "<tr><td>qwen-x</td><td>International</td><td>$0.1</td><td>$0.4</td></tr></table>"
    )
    serve_html(monkeypatch, html)
    with pytest.raises(FetchError, match="no priced International rows"):
        dashscope_detect.detect_priced(dashscope_cfg)


def test_detect_priced_raises_without_pricing_tables(dashscope_cfg, monkeypatch):
    serve_html(monkeypatch, "<table><tr><td>unrelated</td></tr></table>")
    with pytest.raises(FetchError, match="no pricing tables"):
        dashscope_detect.detect_priced(dashscope_cfg)


# --- fixtures ---------------------------------------------------------------


def test_fixtures_carry_the_2026_11_18_page_shapes():
    en = (FIXTURES / "model-pricing-intl.html").read_text()
    cn = (FIXTURES / "textgen-cn.html").read_text()
    old = (FIXTURES / OLD_EN_FIXTURE).read_text()
    assert en.startswith(f"<!-- captured 2026-11-18 from {EN_URL} ;")
    assert cn.startswith(f"<!-- captured 2026-11-18 from {CN_URL} ;")
    assert "Input unit price" in en
    assert "Input price" not in en
    assert "Input price" in old
    # the CN page lists official versions only: no snapshot collapsible
    assert "查看快照版本" not in cn

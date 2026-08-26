from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import volcengine_page as detector
from ai_pricelog.pricing import Pricing
from ai_pricelog.scrapers import volcengine_page as scraper
from ai_pricelog.web import FetchError

FIXTURES = Path(__file__).parent / "fixtures" / "volcengine_page"
PAGE_URL = "https://ai.volcengine.com/model"

ALL_MODELS = [
    "doubao-seed-evolving-latest-version",
    "doubao-seed-2-1-pro-260628",
    "doubao-seed-2-1-turbo-260628",
    "doubao-seed-2-0-lite-260428",
    "doubao-seed-2-0-mini-260428",
]


def _cfg() -> ProviderCfg:
    return ProviderCfg(
        key="volcengine",
        provider="Volcengine",
        detector="volcengine_page",
        detector_url=PAGE_URL,
        scraper="volcengine_page",
        scraper_url=PAGE_URL,
    )


def _load(name: str = "model.html") -> BeautifulSoup:
    return BeautifulSoup((FIXTURES / name).read_text(), "html.parser")


@pytest.fixture(autouse=True)
def fresh_page_cache() -> None:
    # _page is cached per url for the pipeline's detect-then-scrape pass; each
    # test serves its own page content, so the cache must not leak across tests.
    detector._page.cache_clear()
    yield
    detector._page.cache_clear()


def _patch_soup(monkeypatch: pytest.MonkeyPatch, soup: BeautifulSoup) -> None:
    # the single fetch seam is the detector module's fetch_soup; the scraper
    # reads the detector's cached _page
    monkeypatch.setattr(detector, "fetch_soup", lambda url: soup)


def test_detect_returns_all_models_in_page_order(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_soup(monkeypatch, _load())
    assert detector.detect(_cfg()) == ALL_MODELS


def test_detect_excludes_video_and_image_cards(monkeypatch: pytest.MonkeyPatch) -> None:
    soup = _load()
    text = soup.get_text(" ", strip=True)
    # fixture really carries the excluded families, so the exclusion is exercised
    assert "doubao-seedance-2-0-260128" in text
    assert "doubao-seedream-5-0-pro-260628" in text
    _patch_soup(monkeypatch, soup)
    ids = detector.detect(_cfg())
    assert ids == ALL_MODELS
    assert not any("seedance" in model or "seedream" in model for model in ids)


def test_detect_deduplicates_preserving_order(monkeypatch: pytest.MonkeyPatch) -> None:
    html = (
        "<html><body><div>doubao-seed-2-1-pro-260628</div>"
        "<div>doubao-seed-2-1-turbo-260628</div>"
        "<div>doubao-seed-2-1-pro-260628</div></body></html>"
    )
    _patch_soup(monkeypatch, BeautifulSoup(html, "html.parser"))
    assert detector.detect(_cfg()) == ["doubao-seed-2-1-pro-260628", "doubao-seed-2-1-turbo-260628"]


def test_detect_raises_fetch_error_when_page_has_no_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    soup = BeautifulSoup("<html><body>redesigned</body></html>", "html.parser")
    _patch_soup(monkeypatch, soup)
    with pytest.raises(FetchError, match=PAGE_URL):
        detector.detect(_cfg())


@pytest.mark.parametrize(
    ("model_id", "input_cost", "output_cost", "max_tokens_out", "max_tokens_in"),
    [
        # CNY per 1M tokens / 1e6 / CNY_PER_USD, exact per-token floats;
        # out = 最大输出, in = 上下文窗口, K * 1024
        (
            "doubao-seed-evolving-latest-version",
            8.333333333333333e-07,
            4.166666666666667e-06,
            262_144,
            262_144,
        ),
        (
            "doubao-seed-2-1-pro-260628",
            8.333333333333333e-07,
            4.166666666666667e-06,
            262_144,
            262_144,
        ),
        (
            "doubao-seed-2-1-turbo-260628",
            4.1666666666666667e-07,
            2.0833333333333334e-06,
            262_144,
            262_144,
        ),
        # reasoning cards quote ranges: low bound wins
        ("doubao-seed-2-0-lite-260428", 8.333333333333333e-08, 5e-07, 131_072, 262_144),
        (
            "doubao-seed-2-0-mini-260428",
            2.777777777777778e-08,
            2.7777777777777776e-07,
            131_072,
            262_144,
        ),
    ],
    ids=["evolving", "pro", "turbo", "lite", "mini"],
)
def test_scrape_converts_cny_prices_exactly(
    monkeypatch: pytest.MonkeyPatch,
    model_id: str,
    input_cost: float,
    output_cost: float,
    max_tokens_out: int,
    max_tokens_in: int,
) -> None:
    _patch_soup(monkeypatch, _load())
    assert scraper.scrape(_cfg(), model_id) == Pricing(
        input_cost_per_token=input_cost,
        output_cost_per_token=output_cost,
        mode="chat",
        max_tokens_out=max_tokens_out,
        max_tokens_in=max_tokens_in,
    )


def test_scrape_returns_none_for_model_not_on_page(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_soup(monkeypatch, _load())
    assert scraper.scrape(_cfg(), "doubao-seed-2-0-max-260428") is None


def test_scrape_returns_none_when_card_has_no_price(monkeypatch: pytest.MonkeyPatch) -> None:
    html = (
        "<html><body><div>doubao-seed-2-1-pro-260628 复制 Doubao-Seed-2.1-pro 尚未定价</div>"
        "<div>doubao-seed-2-1-turbo-260628 复制 Doubao-Seed-2.1-turbo"
        "输入价格 3 元/百万 tokens 输出价格 15 元/百万 tokens</div></body></html>"
    )
    _patch_soup(monkeypatch, BeautifulSoup(html, "html.parser"))
    assert scraper.scrape(_cfg(), "doubao-seed-2-1-pro-260628") is None


def test_scrape_raises_fetch_error_when_page_has_no_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    soup = BeautifulSoup("<html><body>redesigned</body></html>", "html.parser")
    _patch_soup(monkeypatch, soup)
    with pytest.raises(FetchError, match=PAGE_URL):
        scraper.scrape(_cfg(), "doubao-seed-2-1-pro-260628")


def test_scrape_missing_window_labels_yields_zero_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = (
        "<html><body><div>doubao-seed-2-1-turbo-260628 复制 Doubao-Seed-2.1-turbo"
        "输入价格 3 元/百万 tokens 输出价格 15 元/百万 tokens</div></body></html>"
    )
    _patch_soup(monkeypatch, BeautifulSoup(html, "html.parser"))
    pricing = scraper.scrape(_cfg(), "doubao-seed-2-1-turbo-260628")
    assert pricing is not None
    assert pricing.max_tokens_out == 0
    assert pricing.max_tokens_in == 0


def test_page_fetched_once_per_url(monkeypatch: pytest.MonkeyPatch) -> None:
    fetches = {"count": 0}
    soup = _load()

    def counting(url: str) -> BeautifulSoup:
        fetches["count"] += 1
        return soup

    monkeypatch.setattr(detector, "fetch_soup", counting)
    cfg = _cfg()
    assert detector.detect(cfg) == ALL_MODELS
    assert scraper.scrape(cfg, "doubao-seed-2-1-pro-260628") is not None
    assert detector.detect(cfg) == ALL_MODELS
    assert fetches["count"] == 1

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import baseten_page as detector
from ai_pricelog.scrapers import baseten_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://www.baseten.co/pricing"
FIXTURE = Path(__file__).parent / "fixtures" / "baseten_page" / "pricing.html"

EXPECTED_IDS = [
    "glm-53-flash",
    "glm-52",
    "glm-52-fast",
    "glm-4-7",
    "deepseek-v4-pro-0813",
    "deepseek-v4",
    "deepseek-v4-flash-0731",
    "kimi-k3",
    "kimi-k26",
    "kimi-k27-code",
    "inkling-small",
    "inkling",
    "nvidia-nemotron-ultra",
    "gpt-oss-120b",
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="baseten",
        provider="Baseten",
        detector="baseten_page",
        detector_url=PAGE_URL,
        scraper="baseten_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


def test_detect_models(monkeypatch):
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_scrape_glm_53_flash(monkeypatch):
    # column order Model | Input | Cache Input | Output from the page's own
    # server-rendered header; checked against the first-party GLM-5.3-Flash
    # list rates on docs.z.ai (input 0.15 / output 0.50 per 1M tokens)
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "glm-53-flash")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.15 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.50 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.03 / 1e6)
    assert pricing.mode == "chat"


def test_scrape_nvidia_nemotron_3_ultra(monkeypatch):
    # first-party: NVIDIA quotes Nemotron 3 Ultra at 0.60 in / 2.40 out per 1M
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "nvidia-nemotron-ultra")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.60 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(2.40 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.12 / 1e6)


def test_scrape_kimi_k3(monkeypatch):
    # matches the kimi-k3 rate pinned in the fireworks tests against the
    # first-party source (3.0 / 0.3 / 15.0 per 1M)
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.00 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(15.00 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.30 / 1e6)


def test_scrape_model_without_cache_rate(monkeypatch):
    # gpt-oss-120b renders "-" in the Cache Input column: no cache rate
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "gpt-oss-120b")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.10 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.50 / 1e6)
    assert pricing.cache_read_cost_per_token is None


def test_scrape_unknown_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "glm-99") is None


_ROW_HTML = (
    "<div>"
    '<div class="grid">'
    "<div>Model</div><div>Input</div><div>Cache Input</div><div>Output</div>"
    "</div>"
    '<div class="grid">'
    '<div><div class="hidden md:flex"><a href="/library/glm-53-flash/">'
    "GLM-5.3-Flash</a></div></div>"
    '<div><div class="hidden md:flex">{input_text}</div></div>'
    '<div><div class="hidden md:flex">$0.03</div></div>'
    '<div><div class="hidden md:flex">$0.50</div></div>'
    "</div>"
    "</div>"
)


def test_scrape_malformed_input_cell_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(_ROW_HTML.format(input_text="free"), "html.parser"),
    )
    with pytest.raises(FetchError, match="0 amounts, want 1"):
        scraper.scrape(cfg(), "glm-53-flash")


def test_scrape_malformed_row_raises(monkeypatch):
    html = (
        "<div>"
        '<div class="grid">'
        "<div>Model</div><div>Input</div><div>Cache Input</div><div>Output</div>"
        "</div>"
        '<div class="grid">'
        '<div><div class="hidden md:flex"><a href="/library/glm-53-flash/">'
        "GLM-5.3-Flash</a></div></div>"
        '<div><div class="hidden md:flex">$0.15</div></div>'
        '<div><div class="hidden md:flex">$0.50</div></div>'
        "</div>"
        "</div>"
    )
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(html, "html.parser"),
    )
    with pytest.raises(FetchError, match="3 cells, want 4"):
        scraper.scrape(cfg(), "glm-53-flash")


def test_scrape_missing_table_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup("<div><div>Model</div><div>Price</div></div>", "html.parser"),
    )
    with pytest.raises(FetchError, match="no Model APIs pricing table"):
        scraper.scrape(cfg(), "glm-53-flash")


def test_detect_missing_table_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup("<div><div>Model</div><div>Price</div></div>", "html.parser"),
    )
    with pytest.raises(FetchError, match="no Model APIs pricing table"):
        detector.detect(cfg())


def test_detect_row_without_library_link_skips(monkeypatch, caplog):
    # an odd model link is additive drift: the row is skipped with a
    # warning, later rows still seed
    html = (
        "<div>"
        '<div class="grid">'
        "<div>Model</div><div>Input</div><div>Cache Input</div><div>Output</div>"
        "</div>"
        '<div class="grid">'
        '<div><div class="hidden md:flex"><a href="/something/else/">'
        "GLM-5.3-Flash</a></div></div>"
        '<div><div class="hidden md:flex">$0.15</div></div>'
        '<div><div class="hidden md:flex">$0.03</div></div>'
        '<div><div class="hidden md:flex">$0.50</div></div>'
        "</div>"
        '<div class="grid">'
        '<div><div class="hidden md:flex"><a href="/library/glm-53-flash/">'
        "GLM-5.3-Flash</a></div></div>"
        '<div><div class="hidden md:flex">$0.15</div></div>'
        '<div><div class="hidden md:flex">$0.03</div></div>'
        '<div><div class="hidden md:flex">$0.50</div></div>'
        "</div>"
        "</div>"
    )
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(html, "html.parser"),
    )
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["glm-53-flash"]
    assert "detect skip for baseten" in caplog.text
    assert "unexpected model link" in caplog.text


def test_detect_all_rows_malformed_raises(monkeypatch, caplog):
    # every row skipped leaves no ids: the structural raise stays
    html = (
        "<div>"
        '<div class="grid">'
        "<div>Model</div><div>Input</div><div>Cache Input</div><div>Output</div>"
        "</div>"
        '<div class="grid">'
        '<div><div class="hidden md:flex"><a href="/something/else/">'
        "GLM-5.3-Flash</a></div></div>"
        '<div><div class="hidden md:flex">$0.15</div></div>'
        '<div><div class="hidden md:flex">$0.03</div></div>'
        '<div><div class="hidden md:flex">$0.50</div></div>'
        "</div>"
        "</div>"
    )
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(html, "html.parser"),
    )
    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(FetchError, match="no model ids"),
    ):
        detector.detect(cfg())
    assert "detect skip for baseten" in caplog.text


def test_detect_folded_header_matches(monkeypatch):
    # header wording drift (case) still matches after folding
    html = (
        "<div>"
        '<div class="grid">'
        "<div>model</div><div>INPUT</div><div>cache input</div><div>Output</div>"
        "</div>"
        '<div class="grid">'
        '<div><div class="hidden md:flex"><a href="/library/glm-53-flash/">'
        "GLM-5.3-Flash</a></div></div>"
        '<div><div class="hidden md:flex">$0.15</div></div>'
        '<div><div class="hidden md:flex">$0.03</div></div>'
        '<div><div class="hidden md:flex">$0.50</div></div>'
        "</div>"
        "</div>"
    )
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: BeautifulSoup(html, "html.parser"),
    )
    assert detector.detect(cfg()) == ["glm-53-flash"]


_HEADER_ROW = (
    '<div class="grid"><div>Model</div><div>Input</div>'
    "<div>Cache Input</div><div>Output</div></div>"
)
_BUTTON = '<a href="https://app.baseten.co/model-apis/create"><span>Try Model API</span></a>'


def _row(model_id: str, input_cell: str, cache_cell: str, output_cell: str) -> str:
    return (
        '<div class="grid">'
        f'<div><div class="hidden md:flex"><a href="/library/{model_id}/">'
        f"{model_id}</a></div></div>"
        f'<div><div class="hidden md:flex">{input_cell}</div></div>'
        f'<div><div class="hidden md:flex">{cache_cell}</div></div>'
        f'<div><div class="hidden md:flex">{output_cell}</div></div>'
        "</div>"
    )


def _page(*rows: str) -> BeautifulSoup:
    return BeautifulSoup(f"<div>{_HEADER_ROW}{''.join(rows)}</div>", "html.parser")


def test_scrape_all_dash_row_is_unpriced(monkeypatch):
    # live page 2026-10-22: elephant-1 and mammoth-1 render "-" in Input,
    # Cache Input and Output while sixteen rows price normally; every run
    # read the row as a page-shape break and the provider went dark
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: _page(
            _row(
                "glm-53-flash",
                "<span>$0.15</span>",
                "<span>$0.03</span>",
                f"<span>$0.50</span>{_BUTTON}",
            ),
            _row("elephant-1", "<span>-</span>", "<span>-</span>", f"<span>-</span>{_BUTTON}"),
        ),
    )
    assert scraper.scrape(cfg(), "elephant-1") is None
    pricing = scraper.scrape(cfg(), "glm-53-flash")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.15 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.03 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.50 / 1e6)


def test_scrape_all_dash_page_raises(monkeypatch):
    # a page that prices nothing at all is the structural break plan #22
    # keeps loud; only a dash row beside priced ones reads as unpriced
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: _page(
            _row("elephant-1", "<span>-</span>", "<span>-</span>", f"<span>-</span>{_BUTTON}"),
            _row("mammoth-1", "<span>-</span>", "<span>-</span>", f"<span>-</span>{_BUTTON}"),
        ),
    )
    with pytest.raises(FetchError, match="no priced model rows"):
        scraper.scrape(cfg(), "elephant-1")
    # the guard is a page property, so an off-page id raises too
    with pytest.raises(FetchError, match="no priced model rows"):
        scraper.scrape(cfg(), "not-listed-99")


def test_scrape_reads_the_rate_not_the_button_label(monkeypatch):
    # the output cell carries the Try Model API button, so an amount in its
    # label must not join the rate scan
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: _page(
            _row(
                "glm-53-flash",
                "<span>$0.15</span>",
                "<span>$0.03</span>",
                "<span>$0.50</span>"
                '<a href="https://app.baseten.co/model-apis/create"><span>Try for $5</span></a>',
            ),
        ),
    )
    pricing = scraper.scrape(cfg(), "glm-53-flash")
    assert pricing is not None
    assert pricing.output_cost_per_token == pytest.approx(0.50 / 1e6)


def test_scrape_partially_unpriced_row_raises(monkeypatch):
    # only the all-dash form is unpriced; a row with one "-" column stays a
    # page-shape break
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: _page(
            _row(
                "glm-53-flash",
                "<span>$0.15</span>",
                "<span>$0.03</span>",
                "<span>$0.50</span>",
            ),
            _row("half-priced", "<span>-</span>", "<span>$0.03</span>", "<span>$0.50</span>"),
        ),
    )
    with pytest.raises(FetchError, match="0 amounts, want 1"):
        scraper.scrape(cfg(), "half-priced")


@pytest.mark.parametrize(
    "cells",
    [
        ("<span>$0.15</span>", "<span>-</span>", "<span>-</span>"),
        ("<span>-</span>", "<span>$0.03</span>", "<span>-</span>"),
        ("<span>-</span>", "<span>-</span>", "<span>$0.50</span>"),
    ],
)
def test_scrape_guard_reads_an_amount_in_every_price_column(monkeypatch, cells):
    # the page-level guard must see an amount in any of the three price
    # columns; the matched row then raises its own column error, never the
    # page-level "no priced model rows"
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: _page(_row("half-priced", *cells)),
    )
    with pytest.raises(FetchError, match="0 amounts, want 1"):
        scraper.scrape(cfg(), "half-priced")


def test_scrape_guard_reads_a_malformed_amount_as_priced(monkeypatch):
    # an unreadable amount-shaped token still marks the page as priced, so
    # the matched row raises the unreadable-rate error, not the page-level
    # structural message
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: _page(
            _row("half-priced", "<span>$1-2</span>", "<span>-</span>", "<span>-</span>")
        ),
    )
    with pytest.raises(FetchError, match="unreadable rate"):
        scraper.scrape(cfg(), "half-priced")


def test_scrape_skips_unrelated_malformed_row(monkeypatch):
    # an unrelated row with an odd link is additive drift detect reported;
    # the chosen model still scrapes
    html = (
        "<div>"
        '<div class="grid">'
        "<div>Model</div><div>Input</div><div>Cache Input</div><div>Output</div>"
        "</div>"
        '<div class="grid">'
        '<div><div class="hidden md:flex"><a href="/something/else/">'
        "GLM-5.3-Flash</a></div></div>"
        '<div><div class="hidden md:flex">$0.15</div></div>'
        '<div><div class="hidden md:flex">$0.03</div></div>'
        '<div><div class="hidden md:flex">$0.50</div></div>'
        "</div>"
        '<div class="grid">'
        '<div><div class="hidden md:flex"><a href="/library/glm-53-flash/">'
        "GLM-5.3-Flash</a></div></div>"
        '<div><div class="hidden md:flex">$0.15</div></div>'
        '<div><div class="hidden md:flex">$0.03</div></div>'
        '<div><div class="hidden md:flex">$0.50</div></div>'
        "</div>"
        "</div>"
    )
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: BeautifulSoup(html, "html.parser"),
    )
    pricing = scraper.scrape(cfg(), "glm-53-flash")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.15 / 1e6)

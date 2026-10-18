"""comma-decimal amounts across the scrapers that shared the old `[\\d,]+` grammar.

"$0,14" once read as 14.0: commas were stripped wherever they sat. a comma
outside a proper three-digit group now makes the amount unreadable, which
fails the row loud in a scrape (FetchError naming the model and the cell)
and skips it with the counter-freezing detect-skip warning in a detector;
a real thousands group still reads.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import cohere_page as cohere_detector
from ai_pricelog.detectors import publicai_page as publicai_detector
from ai_pricelog.detectors import watsonx_page as watsonx_detector
from ai_pricelog.scrapers import (
    avian_page,
    baseten_page,
    google_page,
    moonshot_page,
    perplexity_page,
    publicai_page,
    sambanova_page,
    together_page,
    watsonx_page,
)
from ai_pricelog.web import FetchError

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://example.com/pricing"


@dataclass(frozen=True)
class Case:
    key: str
    module: ModuleType
    fixture: str
    model_id: str
    anchor: str  # unique in the fixture; holds `amount` once
    amount: str
    comma_decimal: str
    thousands: str
    axis: str
    thousands_value: float


SCRAPE_CASES = [
    Case(
        "together",
        together_page,
        "together_page/pricing.html",
        "deepseek-v4-flash-0731",
        '$0.14</p><div class="body-m text-weight-medium"><span>$0.03</span>',
        "$0.14",
        "$0,14",
        "$1,000.14",
        "input_cost_per_token",
        1000.14,
    ),
    Case(
        "google",
        google_page,
        "google_page/pricing.html",
        "gemini-2.5-flash",
        "$0.30 (text / image / video)",
        "$0.30",
        "$0,30",
        "$1,000.30",
        "input_cost_per_token",
        1000.30,
    ),
    Case(
        "baseten",
        baseten_page,
        "baseten_page/pricing.html",
        "glm-53-flash",
        '!text-r-ps-reg">$0.15</span>',
        "$0.15",
        "$0,15",
        "$1,000.15",
        "input_cost_per_token",
        1000.15,
    ),
    Case(
        "avian",
        avian_page,
        "avian_page/pricing.html",
        "mimo-v2.5-small",
        "$0.05",
        "$0.05",
        "$0,05",
        "$1,000.05",
        "cache_read_cost_per_token",
        1000.05,
    ),
    Case(
        "perplexity",
        perplexity_page,
        "perplexity_page/models.html",
        "sonar",
        'perplexity/sonar</code></td><td data-numeric="true">0.25</td>',
        ">0.25<",
        ">0,25<",
        ">1,000.25<",
        "input_cost_per_token",
        1000.25,
    ),
    Case(
        "sambanova",
        sambanova_page,
        "sambanova_page/pricing.html",
        "minimax-m2.7",
        '>0.06 USD</td><td class="first-of-type:text-start bg-inherit first-of-type:border-r'
        " first-of-type:border-border first-of-type:text-foreground first-of-type:md:sticky"
        " first-of-type:top-0 first-of-type:left-0 border-b border-border text-center text-sm"
        ' font-normal px-4 py-3 break-keep transition-colors whitespace-nowrap">0.60 USD</td>',
        ">0.60 USD",
        ">0,60 USD",
        ">1,000.60 USD",
        "input_cost_per_token",
        1000.60,
    ),
    Case(
        "watsonx",
        watsonx_page,
        "watsonx_page/pricing.html",
        "granite-4h-small",
        "USD 0.0636",
        "USD 0.0636",
        "USD 0,0636",
        "USD 1,000.0636",
        "input_cost_per_token",
        1000.0636,
    ),
    Case(
        "publicai",
        publicai_page,
        "publicai_page/pricing.html",
        "swiss-ai/apertus-v1.5-8b",
        'apertus-v1.5-8b</a></td><td class="py-3 px-2 text-sm text-muted-foreground'
        ' whitespace-nowrap">262K</td><td class="py-3 px-2 text-sm text-muted-foreground'
        ' whitespace-nowrap">$0.10 / $0.20',
        "$0.20",
        "$0,20",
        "$1,000.20",
        "output_cost_per_token",
        1000.20,
    ),
]

DETECT_CASES = [case for case in SCRAPE_CASES if case.key in ("watsonx", "publicai")]
DETECTORS = {"watsonx": watsonx_detector, "publicai": publicai_detector}


def make_cfg(key: str) -> ProviderCfg:
    return ProviderCfg(
        key=key,
        provider=key.title(),
        detector=f"{key}_page",
        detector_url=URL,
        scraper=f"{key}_page",
        scraper_url=URL,
    )


def page_with(case: Case, amount: str) -> BeautifulSoup:
    text = (FIXTURES / case.fixture).read_text(encoding="utf-8")
    assert text.count(case.anchor) == 1, f"{case.key}: anchor not unique in {case.fixture}"
    assert case.anchor.count(case.amount) == 1, f"{case.key}: amount not unique in anchor"
    page = text.replace(case.anchor, case.anchor.replace(case.amount, amount))
    return BeautifulSoup(page, "html.parser")


def serve(monkeypatch: pytest.MonkeyPatch, module: ModuleType, soup: BeautifulSoup) -> None:
    monkeypatch.setattr(module, "fetch_soup", lambda url, *args, **kwargs: soup)


@pytest.mark.parametrize("case", SCRAPE_CASES, ids=lambda case: case.key)
def test_scrape_rejects_a_comma_decimal_amount(monkeypatch, case):
    serve(monkeypatch, case.module, page_with(case, case.comma_decimal))
    comma_digits = case.comma_decimal.strip("$<> USD")
    with pytest.raises(FetchError) as excinfo:
        case.module.scrape(make_cfg(case.key), case.model_id)
    message = str(excinfo.value)
    assert case.model_id in message
    assert comma_digits in message


@pytest.mark.parametrize("case", SCRAPE_CASES, ids=lambda case: case.key)
def test_scrape_reads_a_thousands_group(monkeypatch, case):
    serve(monkeypatch, case.module, page_with(case, case.thousands))
    pricing = case.module.scrape(make_cfg(case.key), case.model_id)
    assert pricing is not None
    assert getattr(pricing, case.axis) == pytest.approx(case.thousands_value / 1e6)


@pytest.mark.parametrize("case", DETECT_CASES, ids=lambda case: case.key)
def test_detect_skips_a_comma_decimal_row_with_a_warning(monkeypatch, caplog, case):
    detector = DETECTORS[case.key]
    serve(monkeypatch, detector, page_with(case, case.comma_decimal))
    caplog.set_level(logging.WARNING)
    ids = detector.detect(make_cfg(case.key))
    assert case.model_id not in ids
    assert ids, "the other rows still detect"
    skips = [r.getMessage() for r in caplog.records if r.getMessage().startswith("detect skip for")]
    assert any(case.key in line and case.comma_decimal.strip("$ USD") in line for line in skips)


MOONSHOT_INDEX = "https://platform.kimi.ai/docs/llms.txt"
MOONSHOT_CHAT = "https://platform.kimi.ai/docs/pricing/chat.md"
MOONSHOT_K3_ROW = '["kimi-k3", "1M tokens", <>{"$"}3.00</>, <>{"$"}6.00</>, <>{"$"}0.30</>'


def scrape_moonshot_k3(monkeypatch: pytest.MonkeyPatch, cache_read: str):
    pages = {
        MOONSHOT_INDEX: (FIXTURES / "moonshot_page" / "llms.txt").read_text(),
        MOONSHOT_CHAT: (FIXTURES / "moonshot_page" / "chat.md").read_text(),
    }
    assert pages[MOONSHOT_CHAT].count(MOONSHOT_K3_ROW) == 1
    pages[MOONSHOT_CHAT] = pages[MOONSHOT_CHAT].replace(
        MOONSHOT_K3_ROW, MOONSHOT_K3_ROW.replace('{"$"}0.30', '{"$"}' + cache_read)
    )
    monkeypatch.setattr(moonshot_page, "fetch_text", lambda url: pages[url])
    moonshot_page._load_index.cache_clear()
    cfg = ProviderCfg(
        key="moonshot",
        provider="Moonshot AI",
        detector="moonshot_page",
        detector_url="https://platform.kimi.ai/docs/models.md",
        scraper="moonshot_page",
        scraper_url=MOONSHOT_INDEX,
    )
    try:
        return moonshot_page.scrape(cfg, "kimi-k3")
    finally:
        moonshot_page._load_index.cache_clear()


def test_moonshot_scrape_rejects_a_comma_decimal_amount(monkeypatch):
    with pytest.raises(FetchError) as excinfo:
        scrape_moonshot_k3(monkeypatch, "0,30")
    assert "kimi-k3" in str(excinfo.value)
    assert "0,30" in str(excinfo.value)


def test_moonshot_scrape_reads_a_thousands_group(monkeypatch):
    pricing = scrape_moonshot_k3(monkeypatch, "1,000.30")
    assert pricing is not None
    assert pricing.cache_read_cost_per_token == pytest.approx(1000.30 / 1e6)


def test_cohere_prose_rate_with_a_comma_decimal_skips_with_a_warning(monkeypatch, caplog):
    # the faq prose sentences are cohere's priced rows; a comma-decimal there
    # used to fail the sentence pattern and drop the model with no warning
    text = (FIXTURES / "cohere_page" / "pricing.html").read_text(encoding="utf-8")
    anchor = "<li>Command pricing is $1.00/1M tokens for input"
    assert text.count(anchor) == 1
    page = text.replace(anchor, "<li>Command pricing is $1,00/1M tokens for input")
    soup = BeautifulSoup(page, "html.parser")
    monkeypatch.setattr(cohere_detector, "fetch_soup", lambda url, *args, **kwargs: soup)
    cohere_detector._page.cache_clear()
    caplog.set_level(logging.WARNING)
    try:
        ids = cohere_detector.detect(make_cfg("cohere"))
    finally:
        cohere_detector._page.cache_clear()
    assert "command" not in ids
    skips = [r.getMessage() for r in caplog.records if r.getMessage().startswith("detect skip for")]
    assert any("cohere" in line and "1,00" in line for line in skips)


@pytest.mark.parametrize(
    ("key", "amount", "mixed"),
    [
        ("sambanova", ">0.60 USD", ">0.60 USD (was 0,80 USD)"),
        ("baseten", "$0.15", "$0.15 (was $0,20)"),
    ],
)
def test_scrape_rejects_a_cell_mixing_a_readable_and_a_comma_decimal_amount(
    monkeypatch, key, amount, mixed
):
    case = next(case for case in SCRAPE_CASES if case.key == key)
    assert case.amount == amount
    serve(monkeypatch, case.module, page_with(case, mixed))
    with pytest.raises(FetchError) as excinfo:
        case.module.scrape(make_cfg(case.key), case.model_id)
    assert case.model_id in str(excinfo.value)
    assert "0,80" in str(excinfo.value) or "0,20" in str(excinfo.value)


def test_baseten_cache_cell_mixing_a_comma_decimal_amount_raises(monkeypatch):
    case = next(case for case in SCRAPE_CASES if case.key == "baseten")
    cache_case = Case(
        **{**case.__dict__, "anchor": '!text-r-ps-reg">$0.03</span>', "amount": "$0.03"}
    )
    serve(monkeypatch, baseten_page, page_with(cache_case, "$0.03 (was $0,05)"))
    with pytest.raises(FetchError) as excinfo:
        baseten_page.scrape(make_cfg("baseten"), case.model_id)
    assert case.model_id in str(excinfo.value)
    assert "0,05" in str(excinfo.value)


def test_perplexity_cell_with_text_after_its_amount_stays_unpriced(monkeypatch):
    # a numeric cell must be exactly one amount; "0.25*" is no rate, as before
    case = next(case for case in SCRAPE_CASES if case.key == "perplexity")
    serve(monkeypatch, perplexity_page, page_with(case, ">0.25*<"))
    assert perplexity_page.scrape(make_cfg("perplexity"), case.model_id) is None


def _cohere_detect(
    monkeypatch, caplog, anchor: str, replacement: str
) -> tuple[list[str], list[str]]:
    text = (FIXTURES / "cohere_page" / "pricing.html").read_text(encoding="utf-8")
    assert text.count(anchor) == 1
    soup = BeautifulSoup(text.replace(anchor, replacement), "html.parser")
    monkeypatch.setattr(cohere_detector, "fetch_soup", lambda url, *args, **kwargs: soup)
    cohere_detector._page.cache_clear()
    caplog.set_level(logging.WARNING)
    try:
        ids = cohere_detector.detect(make_cfg("cohere"))
    finally:
        cohere_detector._page.cache_clear()
    skips = [r.getMessage() for r in caplog.records if r.getMessage().startswith("detect skip for")]
    return ids, skips


def test_cohere_vault_cell_must_be_exactly_one_amount(monkeypatch, caplog):
    # an id-only vault row lists only when both rate cells are a bare amount
    ids, skips = _cohere_detect(
        monkeypatch, caplog, 'font-body">$4.00</p>', 'font-body">$4.00 per hour</p>'
    )
    assert "embed-4-small" not in ids
    assert any("cohere" in line and "$4.00 per hour" in line for line in skips)


def test_cohere_prose_sentence_with_two_amounts_skips_with_a_warning(monkeypatch, caplog):
    ids, skips = _cohere_detect(
        monkeypatch,
        caplog,
        "<li>Command pricing is $1.00/1M tokens for input",
        "<li>Command pricing is $1.00 (was $2.00)/1M tokens for input",
    )
    assert "command" not in ids
    assert any("cohere" in line and "$2.00" in line for line in skips)


def test_cohere_prose_sentence_without_an_amount_skips_with_a_warning(monkeypatch, caplog):
    # an unpriced sentence skips its one row; it never fails the whole detector
    ids, skips = _cohere_detect(
        monkeypatch,
        caplog,
        "<li>Command pricing is $1.00/1M tokens for input",
        "<li>Command pricing is $TBD/1M tokens for input",
    )
    assert "command" not in ids
    assert ids
    assert any("cohere" in line and "$TBD" in line for line in skips)


def test_publicai_detect_skips_a_row_with_a_third_comma_decimal_amount(monkeypatch, caplog):
    case = next(case for case in DETECT_CASES if case.key == "publicai")
    serve(monkeypatch, publicai_detector, page_with(case, "$0.20 / $0,30"))
    caplog.set_level(logging.WARNING)
    ids = publicai_detector.detect(make_cfg("publicai"))
    assert case.model_id not in ids
    skips = [r.getMessage() for r in caplog.records if r.getMessage().startswith("detect skip for")]
    assert any("publicai" in line and "0,30" in line for line in skips)


def test_cohere_vault_row_with_a_comma_decimal_skips_with_a_warning(monkeypatch, caplog):
    text = (FIXTURES / "cohere_page" / "pricing.html").read_text(encoding="utf-8")
    anchor = 'font-body">$4.00</p>'
    assert text.count(anchor) == 1
    soup = BeautifulSoup(text.replace(anchor, 'font-body">$4,00</p>'), "html.parser")
    monkeypatch.setattr(cohere_detector, "fetch_soup", lambda url, *args, **kwargs: soup)
    cohere_detector._page.cache_clear()
    caplog.set_level(logging.WARNING)
    try:
        ids = cohere_detector.detect(make_cfg("cohere"))
    finally:
        cohere_detector._page.cache_clear()
    assert "embed-4-small" not in ids
    skips = [r.getMessage() for r in caplog.records if r.getMessage().startswith("detect skip for")]
    assert any("cohere" in line and "4,00" in line for line in skips)

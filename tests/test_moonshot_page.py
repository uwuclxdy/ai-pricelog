from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import moonshot_page as detector
from ai_pricelog.scrapers import moonshot_page as scraper
from ai_pricelog.web import FetchError

MODELS_URL = "https://platform.kimi.ai/docs/models.md"
INDEX_URL = "https://platform.kimi.ai/docs/llms.txt"
CHAT_URL = "https://platform.kimi.ai/docs/pricing/chat.md"
FIXTURES = Path(__file__).parent / "fixtures" / "moonshot_page"

PAGES = {
    "models": (MODELS_URL, "models.md"),
    "llms": (INDEX_URL, "llms.txt"),
    "chat": (CHAT_URL, "chat.md"),
}

EXPECTED_IDS = [
    "kimi-k3",
    "kimi-k2.7-code",
    "kimi-k2.7-code-highspeed",
    "kimi-k2.6",
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="moonshot",
        provider="Moonshot AI",
        detector="moonshot_page",
        detector_url=MODELS_URL,
        scraper="moonshot_page",
        scraper_url=INDEX_URL,
    )


def fixture_fetch(*pages: str) -> Callable[[str], str]:
    data = {PAGES[name][0]: (FIXTURES / PAGES[name][1]).read_text() for name in pages}

    def fake(url: str) -> str:
        if url not in data:
            raise FetchError(f"fetch failed for {url}: no fixture")
        return data[url]

    return fake


@pytest.fixture(autouse=True)
def clear_index_cache():
    scraper._load_index.cache_clear()
    yield
    scraper._load_index.cache_clear()


def test_detect_models(monkeypatch):
    monkeypatch.setattr(detector, "fetch_text", fixture_fetch("models"))
    ids = detector.detect(cfg())
    assert ids == EXPECTED_IDS
    assert "kimi-k2.5" not in ids  # retired 2026-08-31, deprecated table excluded
    assert "moonshot-v1-8k" not in ids


def test_detect_malformed_page_raises(monkeypatch):
    monkeypatch.setattr(detector, "fetch_text", lambda url: "# no tables here\n")
    with pytest.raises(FetchError, match="Model Name"):
        detector.detect(cfg())


def test_detect_header_wording_drift_still_matches(monkeypatch):
    # the Model Name header pins after folding case and whitespace, so a
    # drifted spelling still locates the model tables
    monkeypatch.setattr(
        detector,
        "fetch_text",
        lambda url: "| Model   Name | Context |\n| --- | --- |\n| `kimi-k3` | 1M |\n",
    )
    assert detector.detect(cfg()) == ["kimi-k3"]


def test_scrape_k3(monkeypatch):
    # the live llms.txt also carries an /api/chat.md link; resolution must
    # key on /pricing/ so it cannot match that one
    monkeypatch.setattr(scraper, "fetch_text", fixture_fetch("llms", "chat"))
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.00 / 1e6)  # cache miss, not hit
    assert pricing.cache_read_cost_per_token == pytest.approx(0.30 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(15.00 / 1e6)
    assert pricing.mode == "chat"
    assert pricing.max_tokens_in == 1_048_576
    assert pricing.url == CHAT_URL


def test_scrape_k26(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_text", fixture_fetch("llms", "chat"))
    pricing = scraper.scrape(cfg(), "kimi-k2.6")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.95 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.16 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(4.00 / 1e6)
    assert pricing.max_tokens_in == 262_144
    assert pricing.url == CHAT_URL


def test_scrape_k27_code_and_highspeed(monkeypatch):
    # the two longer ids match their own rows, not each other's
    monkeypatch.setattr(scraper, "fetch_text", fixture_fetch("llms", "chat"))
    code = scraper.scrape(cfg(), "kimi-k2.7-code")
    assert code is not None
    assert code.input_cost_per_token == pytest.approx(0.95 / 1e6)
    assert code.cache_read_cost_per_token == pytest.approx(0.19 / 1e6)
    assert code.output_cost_per_token == pytest.approx(4.00 / 1e6)
    assert code.max_tokens_in == 262_144
    assert code.url == CHAT_URL
    highspeed = scraper.scrape(cfg(), "kimi-k2.7-code-highspeed")
    assert highspeed is not None
    assert highspeed.input_cost_per_token == pytest.approx(1.90 / 1e6)
    assert highspeed.cache_read_cost_per_token == pytest.approx(0.38 / 1e6)
    assert highspeed.output_cost_per_token == pytest.approx(8.00 / 1e6)
    assert highspeed.max_tokens_in == 262_144
    assert highspeed.url == CHAT_URL


def test_scrape_absent_model_returns_none(monkeypatch):
    # no row for the model on the merged page -> unpriced, not an exception
    monkeypatch.setattr(scraper, "fetch_text", fixture_fetch("llms", "chat"))
    assert scraper.scrape(cfg(), "kimi-k9") is None


def test_scrape_index_without_chat_link_raises(monkeypatch):
    # batch/tools/limits are pricing pages but not model-inference ones
    index_text = "\n".join(
        [
            "- [BatchJob Pricing](https://platform.kimi.ai/docs/pricing/batch.md): batch",
            "- [WebSearch Pricing](https://platform.kimi.ai/docs/pricing/tools.md): tools",
            "- [Rate Limiting](https://platform.kimi.ai/docs/pricing/limits.md): limits",
        ]
    )
    monkeypatch.setattr(scraper, "fetch_text", lambda url: index_text)
    with pytest.raises(FetchError, match=INDEX_URL):
        scraper.scrape(cfg(), "kimi-k3")


def test_scrape_index_with_ambiguous_chat_links_raises(monkeypatch):
    index_text = "\n".join(
        [
            "- [Pricing One](https://platform.kimi.ai/docs/pricing/chat.md): one",
            "- [Pricing Two](https://platform.kimi.ai/docs/pricing/chat.md): two",
        ]
    )
    monkeypatch.setattr(scraper, "fetch_text", lambda url: index_text)
    with pytest.raises(FetchError, match=INDEX_URL):
        scraper.scrape(cfg(), "kimi-k3")


def test_scrape_page_without_doctable_raises(monkeypatch):
    def fake(url: str) -> str:
        if url == INDEX_URL:
            return (FIXTURES / "llms.txt").read_text()
        if url == CHAT_URL:
            return "# no pricing table here\n"
        raise AssertionError(f"unexpected fetch of {url}")

    monkeypatch.setattr(scraper, "fetch_text", fake)
    with pytest.raises(FetchError, match="DocTable"):
        scraper.scrape(cfg(), "kimi-k3")


def test_scrape_index_fetched_once(monkeypatch):
    base = fixture_fetch("llms", "chat")
    calls = {"index": 0}

    def counting(url: str) -> str:
        if url == INDEX_URL:
            calls["index"] += 1
        return base(url)

    monkeypatch.setattr(scraper, "fetch_text", counting)
    assert scraper.scrape(cfg(), "kimi-k3") is not None
    assert scraper.scrape(cfg(), "kimi-k2.6") is not None
    assert scraper.scrape(cfg(), "kimi-k9") is None
    assert calls["index"] == 1


def test_scrape_index_failure_propagates(monkeypatch):
    def boom(url):
        raise FetchError(f"fetch failed for {url}")

    monkeypatch.setattr(scraper, "fetch_text", boom)
    with pytest.raises(FetchError, match=INDEX_URL):
        scraper.scrape(cfg(), "kimi-k3")


def test_pricing_plain_input_column_without_cache_split():
    # a table without the cache columns still parses via the plain
    # "Input Price" path (the retired v1 page shape)
    doc = (
        ["Model", "Input Price", "Output Price", "Context Window"],
        [["moonshot-v1-8k", "$0.20", "$2.00", "8,192 tokens"]],
    )
    pricing = scraper._pricing(doc, "moonshot-v1-8k", CHAT_URL)
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.20 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(2.00 / 1e6)
    assert pricing.max_tokens_in == 8192
    assert pricing.cache_read_cost_per_token is None


def test_pricing_tolerates_non_string_context_cell():
    # the context cell is str()-wrapped like its sibling cells
    doc = (
        ["Model", "Input Price (Cache Miss)", "Output Price", "Context Window"],
        [["kimi-k2.6", "$0.95", "$4.00", 262_144]],
    )
    pricing = scraper._pricing(doc, "kimi-k2.6", CHAT_URL)
    assert pricing is not None
    assert pricing.max_tokens_in == 262_144
    assert pricing.cache_read_cost_per_token is None

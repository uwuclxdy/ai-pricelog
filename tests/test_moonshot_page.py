from collections.abc import Callable
from pathlib import Path

import pytest

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import moonshot_page as detector
from ai_pricelog.scrapers import moonshot_page as scraper
from ai_pricelog.web import FetchError

MODELS_URL = "https://platform.kimi.ai/docs/models.md"
INDEX_URL = "https://platform.kimi.ai/docs/llms.txt"
FIXTURES = Path(__file__).parent / "fixtures" / "moonshot_page"

PAGES = {
    "models": (MODELS_URL, "models.md"),
    "llms": (INDEX_URL, "llms.txt"),
    "chat-k3": ("https://platform.kimi.ai/docs/pricing/chat-k3.md", "chat-k3.md"),
    "chat-k26": ("https://platform.kimi.ai/docs/pricing/chat-k26.md", "chat-k26.md"),
    "chat-k27-code": ("https://platform.kimi.ai/docs/pricing/chat-k27-code.md", "chat-k27-code.md"),
    "chat-v1": ("https://platform.kimi.ai/docs/pricing/chat-v1.md", "chat-v1.md"),
}

EXPECTED_IDS = [
    "kimi-k3",
    "kimi-k2.7-code",
    "kimi-k2.7-code-highspeed",
    "kimi-k2.6",
    "kimi-k2.5",
    "moonshot-v1-8k",
    "moonshot-v1-32k",
    "moonshot-v1-128k",
    "moonshot-v1-8k-vision-preview",
    "moonshot-v1-32k-vision-preview",
    "moonshot-v1-128k-vision-preview",
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
    assert "kimi-k2-0905-preview" not in ids


def test_detect_malformed_page_raises(monkeypatch):
    monkeypatch.setattr(detector, "fetch_text", lambda url: "# no tables here\n")
    with pytest.raises(FetchError, match="Model Name"):
        detector.detect(cfg())


def test_scrape_k3(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_text", fixture_fetch("llms", "chat-k3"))
    pricing = scraper.scrape(cfg(), "kimi-k3")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(3.00 / 1e6)  # cache miss, not hit
    assert pricing.cache_read_cost_per_token == pytest.approx(0.30 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(15.00 / 1e6)
    assert pricing.mode == "chat"
    assert pricing.max_tokens == 1_048_576


def test_scrape_highspeed_via_family_prefix(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_text", fixture_fetch("llms", "chat-k27-code"))
    pricing = scraper.scrape(cfg(), "kimi-k2.7-code-highspeed")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(1.90 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.38 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(8.00 / 1e6)
    assert pricing.max_tokens == 262_144


def test_scrape_k27_code_cache_read(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_text", fixture_fetch("llms", "chat-k27-code"))
    pricing = scraper.scrape(cfg(), "kimi-k2.7-code")
    assert pricing is not None
    assert pricing.cache_read_cost_per_token == pytest.approx(0.19 / 1e6)


def test_scrape_v1_plain_input_column(monkeypatch):
    # the v1 page has no cache-hit column, so cache-read stays unset
    monkeypatch.setattr(scraper, "fetch_text", fixture_fetch("llms", "chat-v1"))
    pricing = scraper.scrape(cfg(), "moonshot-v1-8k")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.20 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(2.00 / 1e6)
    assert pricing.max_tokens == 8192
    assert pricing.cache_read_cost_per_token is None


def test_scrape_index_fetched_once(monkeypatch):
    base = fixture_fetch("llms", "chat-k3")
    calls = {"index": 0}

    def counting(url: str) -> str:
        if url == INDEX_URL:
            calls["index"] += 1
        return base(url)

    monkeypatch.setattr(scraper, "fetch_text", counting)
    assert scraper.scrape(cfg(), "kimi-k3") is not None
    assert scraper.scrape(cfg(), "kimi-k3-thinking") is None  # k3 page, no such row
    assert calls["index"] == 1


def test_scrape_unindexed_model_returns_none(monkeypatch):
    # fallback slug fetch 404s -> the model has no pricing page
    monkeypatch.setattr(scraper, "fetch_text", fixture_fetch("llms"))
    assert scraper.scrape(cfg(), "kimi-k9") is None


def test_title_id_drops_trailing_model_and_scrapes_k26(monkeypatch):
    # "Kimi K2.6 Model Pricing" -> kimi-k2.6 (trailing "Model" dropped), not
    # kimi-k2.6-model; the exact mapping hit then scrapes the chat-k26 page
    monkeypatch.setattr(scraper, "fetch_text", fixture_fetch("llms", "chat-k26"))
    assert scraper._load_index(INDEX_URL)["kimi-k2.6"] == (
        "https://platform.kimi.ai/docs/pricing/chat-k26.md"
    )
    pricing = scraper.scrape(cfg(), "kimi-k2.6")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.95 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.16 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(4.00 / 1e6)
    assert pricing.max_tokens == 262_144


def test_scrape_fallback_slug_success(monkeypatch):
    # the index lacks kimi-k2.6, the fallback chat-k26 fetch succeeds
    index_text = (FIXTURES / "llms.txt").read_text()
    index_text = "\n".join(line for line in index_text.splitlines() if "chat-k26" not in line)
    k26 = (FIXTURES / "chat-k26.md").read_text()

    def fake(url: str) -> str:
        if url == INDEX_URL:
            return index_text
        if url == "https://platform.kimi.ai/docs/pricing/chat-k26.md":
            return k26
        raise AssertionError(f"unexpected fetch of {url}")

    monkeypatch.setattr(scraper, "fetch_text", fake)
    pricing = scraper.scrape(cfg(), "kimi-k2.6")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.95 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(4.00 / 1e6)
    assert pricing.max_tokens == 262_144


def test_pricing_tolerates_non_string_context_cell():
    # the context cell is str()-wrapped like its sibling cells
    doc = (
        ["Model", "Input Price (Cache Miss)", "Output Price", "Context Window"],
        [["kimi-k2.6", "$0.95", "$4.00", 262_144]],
    )
    pricing = scraper._pricing(doc, "kimi-k2.6")
    assert pricing is not None
    assert pricing.max_tokens == 262_144
    assert pricing.cache_read_cost_per_token is None


def test_scrape_page_without_doctable_raises(monkeypatch):
    index_text = (FIXTURES / "llms.txt").read_text()

    def fake(url: str) -> str:
        if url == INDEX_URL:
            return index_text
        if url.startswith("https://platform.kimi.ai/docs/pricing/"):
            return "# no pricing table here\n"
        raise AssertionError(f"unexpected fetch of {url}")

    monkeypatch.setattr(scraper, "fetch_text", fake)
    with pytest.raises(FetchError, match="DocTable"):
        scraper.scrape(cfg(), "kimi-k3")


def test_scrape_index_failure_propagates(monkeypatch):
    def boom(url):
        raise FetchError(f"fetch failed for {url}")

    monkeypatch.setattr(scraper, "fetch_text", boom)
    with pytest.raises(FetchError, match=INDEX_URL):
        scraper.scrape(cfg(), "kimi-k3")

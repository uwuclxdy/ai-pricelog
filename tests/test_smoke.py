from pathlib import Path

import pytest

from ai_pricelog import smoke
from ai_pricelog.pricing import Pricing
from ai_pricelog.scrapers import moonshot_page as scraper
from ai_pricelog.web import FetchError

FIXTURES = Path(__file__).parent / "fixtures" / "moonshot_page"
INDEX_URL = "https://platform.kimi.ai/docs/llms.txt"

PAGES = {
    "llms": (INDEX_URL, "llms.txt"),
    "chat-k3": ("https://platform.kimi.ai/docs/pricing/chat-k3.md", "chat-k3.md"),
    "chat-k25": ("https://platform.kimi.ai/docs/pricing/chat-k25.md", "chat-k25.md"),
    "chat-k26": ("https://platform.kimi.ai/docs/pricing/chat-k26.md", "chat-k26.md"),
    "chat-k27-code": ("https://platform.kimi.ai/docs/pricing/chat-k27-code.md", "chat-k27-code.md"),
    "chat-v1": ("https://platform.kimi.ai/docs/pricing/chat-v1.md", "chat-v1.md"),
}


def fixture_fetch(*pages: str):
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


def pricing() -> Pricing:
    return Pricing(input_cost_per_token=3.00 / 1e6, output_cost_per_token=15.00 / 1e6, mode="chat")


def test_pick_model_prefers_kimi_k3():
    assert smoke.pick_model(["kimi-k3", "kimi-k2.6"]) == "kimi-k3"


def test_pick_model_falls_back_to_first_kimi_id():
    assert smoke.pick_model(["moonshot-v1-8k", "kimi-k2.6", "kimi-k2.5"]) == "kimi-k2.6"


def test_pick_model_rejects_empty_list():
    with pytest.raises(ValueError, match="models.md"):
        smoke.pick_model([])


def test_pick_model_rejects_list_without_kimi_id():
    with pytest.raises(ValueError, match="kimi"):
        smoke.pick_model(["moonshot-v1-8k", "moonshot-v1-32k"])


def test_check_pricing_accepts_positive():
    assert smoke.check_pricing(pricing(), "kimi-k3") == pricing()


def test_check_pricing_rejects_missing_row():
    with pytest.raises(ValueError, match="kimi-k3"):
        smoke.check_pricing(None, "kimi-k3")


def test_check_pricing_rejects_non_positive():
    bad = Pricing(input_cost_per_token=0.0, output_cost_per_token=15.00 / 1e6, mode="chat")
    with pytest.raises(ValueError, match="non-positive"):
        smoke.check_pricing(bad, "kimi-k3")


def test_check_pricing_pages_walks_index(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_text",
        fixture_fetch("llms", "chat-k3", "chat-k25", "chat-k26", "chat-k27-code", "chat-v1"),
    )
    mapping = scraper._load_index(INDEX_URL)
    assert smoke.check_pricing_pages(mapping) == len(mapping)


def test_check_pricing_pages_requires_doctable(monkeypatch):
    base = fixture_fetch("llms", "chat-k3", "chat-k25", "chat-k26", "chat-k27-code", "chat-v1")

    def fake(url: str) -> str:
        if url.endswith("chat-v1.md"):
            return "# no pricing table\n"
        return base(url)

    monkeypatch.setattr(scraper, "fetch_text", fake)
    mapping = scraper._load_index(INDEX_URL)
    with pytest.raises(ValueError, match="chat-v1"):
        smoke.check_pricing_pages(mapping)


def test_check_pricing_pages_propagates_fetch_failure(monkeypatch):
    def boom(url: str) -> str:
        raise FetchError(f"fetch failed for {url}")

    monkeypatch.setattr(scraper, "fetch_text", boom)
    with pytest.raises(FetchError, match="chat-k3"):
        smoke.check_pricing_pages({"kimi-k3": "https://platform.kimi.ai/docs/pricing/chat-k3.md"})


def test_check_pricing_pages_rejects_empty_mapping():
    with pytest.raises(ValueError, match="llms.txt"):
        smoke.check_pricing_pages({})

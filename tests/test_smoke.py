from __future__ import annotations

from pathlib import Path

import pytest

from ai_pricelog import smoke
from ai_pricelog.pricing import Pricing
from ai_pricelog.scrapers import moonshot_page as scraper
from ai_pricelog.web import FetchError

FIXTURES = Path(__file__).parent / "fixtures" / "moonshot_page"
INDEX_URL = "https://platform.kimi.ai/docs/llms.txt"
CHAT_URL = "https://platform.kimi.ai/docs/pricing/chat.md"

PAGES = {
    "llms": (INDEX_URL, "llms.txt"),
    "chat": (CHAT_URL, "chat.md"),
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


def test_check_pricing_pages_fetches_resolved_page(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_text", fixture_fetch("llms", "chat"))
    assert smoke.check_pricing_pages(INDEX_URL) == CHAT_URL


def test_check_pricing_pages_requires_doctable(monkeypatch):
    base = fixture_fetch("llms")

    def fake(url: str) -> str:
        if url == CHAT_URL:
            return "# no pricing table\n"
        return base(url)

    monkeypatch.setattr(scraper, "fetch_text", fake)
    with pytest.raises(ValueError, match="chat.md"):
        smoke.check_pricing_pages(INDEX_URL)


def test_check_pricing_pages_propagates_fetch_failure(monkeypatch):
    llms_text = (FIXTURES / "llms.txt").read_text()

    def fake(url: str) -> str:
        if url == INDEX_URL:
            return llms_text
        raise FetchError(f"fetch failed for {url}")

    monkeypatch.setattr(scraper, "fetch_text", fake)
    with pytest.raises(FetchError, match="pricing/chat"):
        smoke.check_pricing_pages(INDEX_URL)

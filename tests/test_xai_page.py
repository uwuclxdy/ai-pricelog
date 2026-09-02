from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ai_pricelog import web
from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import xai_page
from ai_pricelog.pricing import Pricing
from ai_pricelog.scrapers import xai_page as xai_scraper

FIXTURES = Path(__file__).parent / "fixtures" / "xai_page"
PAGE_URL = "https://docs.x.ai/docs/models"

EXPECTED_IDS = [
    "grok-4.3",
    "grok-4.5",
    "grok-4.6",
    "grok-build-0.1",
    "grok-4.20-0309-reasoning",
    "grok-4.20-0309-non-reasoning",
    "grok-4.20-multi-agent-0309",
]


def make_cfg(url: str = PAGE_URL) -> ProviderCfg:
    return ProviderCfg(
        key="xai",
        provider="xAI",
        detector="xai_page",
        detector_url=url,
        scraper="xai_page",
        scraper_url=url,
    )


def serve_html(monkeypatch: pytest.MonkeyPatch, html: str) -> None:
    # the scraper shares the detector's cached _blob, so the single fetch seam
    # is the detector module's fetch_text.
    monkeypatch.setattr(xai_page, "fetch_text", lambda url: html)


@pytest.fixture(autouse=True)
def fresh_blob_cache():
    # _blob is cached per url for the pipeline's detect-then-scrape pass; each
    # test serves its own page content, so the cache must not leak across tests.
    xai_page._blob.cache_clear()
    yield
    xai_page._blob.cache_clear()


@pytest.fixture
def live_blob(monkeypatch: pytest.MonkeyPatch) -> None:
    blob = (FIXTURES / "blob.json").read_text(encoding="utf-8")
    serve_html(monkeypatch, f"<script>globalThis.__XAI_PUBLIC_MODELS__={blob};</script>")


@pytest.fixture
def snippet(monkeypatch: pytest.MonkeyPatch) -> None:
    serve_html(monkeypatch, (FIXTURES / "page_snippet.html").read_text(encoding="utf-8"))


def test_detect_lists_language_models_in_page_order(live_blob):
    # the live page's model order is the provider's concern, not this test's:
    # pin the set of detected ids, not their order
    assert sorted(xai_page.detect(make_cfg())) == sorted(EXPECTED_IDS)


def test_detect_excludes_non_language_entries(live_blob):
    ids = xai_page.detect(make_cfg())
    assert "grok-imagine-image-2.0" not in ids
    assert "grok-tts" not in ids
    assert "grok-stt" not in ids


def test_detect_propagates_fetch_error(monkeypatch):
    def boom(url: str) -> str:
        raise web.FetchError("boom")

    monkeypatch.setattr(xai_page, "fetch_text", boom)
    with pytest.raises(web.FetchError, match="boom"):
        xai_page.detect(make_cfg())


def test_detect_raises_when_marker_missing(monkeypatch):
    serve_html(monkeypatch, "<html><body>nothing here</body></html>")
    with pytest.raises(web.FetchError, match="no __XAI_PUBLIC_MODELS__ blob"):
        xai_page.detect(make_cfg())


def test_detect_raises_on_invalid_blob_json(monkeypatch):
    serve_html(monkeypatch, "globalThis.__XAI_PUBLIC_MODELS__={oops};")
    with pytest.raises(web.FetchError, match="invalid __XAI_PUBLIC_MODELS__ json"):
        xai_page.detect(make_cfg())


def test_detect_raises_when_cluster_configs_missing(monkeypatch):
    serve_html(monkeypatch, "globalThis.__XAI_PUBLIC_MODELS__={};")
    with pytest.raises(web.FetchError, match="clusterConfigs"):
        xai_page.detect(make_cfg())


def test_detect_raises_when_no_model_is_priced(monkeypatch):
    blob = '{"clusterConfigs": [{"languageModels": [{"name": "grok-x"}]}]}'
    serve_html(monkeypatch, f"globalThis.__XAI_PUBLIC_MODELS__={blob};")
    with pytest.raises(web.FetchError, match="no priced language models"):
        xai_page.detect(make_cfg())


def test_detect_non_object_cluster_skips(monkeypatch, caplog):
    # a non-object cluster is additive drift: skipped with a warning, the
    # other clusters still seed
    blob = (
        '{"clusterConfigs": ['
        '{"languageModels": [{"name": "grok-x", "promptTextTokenPrice": 20000,'
        '"completionTextTokenPrice": 60000}]},'
        '"not-an-object",'
        '{"languageModels": [{"name": "grok-y", "promptTextTokenPrice": 10000,'
        '"completionTextTokenPrice": 30000}]}'
        "]}"
    )
    serve_html(monkeypatch, f"globalThis.__XAI_PUBLIC_MODELS__={blob};")
    with caplog.at_level(logging.WARNING):
        assert xai_page.detect(make_cfg()) == ["grok-x", "grok-y"]
    assert "detect skip for xai" in caplog.text
    assert "non-object cluster" in caplog.text


def test_detect_all_clusters_non_object_raises(monkeypatch, caplog):
    # skipping every cluster leaves no ids: the structural raise stays
    serve_html(
        monkeypatch,
        'globalThis.__XAI_PUBLIC_MODELS__={"clusterConfigs": ["not-an-object"]};',
    )
    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(web.FetchError, match="no priced language models"),
    ):
        xai_page.detect(make_cfg())
    assert "detect skip for xai" in caplog.text


def test_scrape_unrelated_non_object_cluster_does_not_block(monkeypatch):
    # a non-object cluster the scan passes over is additive drift detect
    # reported; the chosen model still scrapes
    blob = (
        '{"clusterConfigs": ['
        '"not-an-object",'
        '{"languageModels": [{"name": "grok-x", "promptTextTokenPrice": 20000,'
        '"completionTextTokenPrice": 60000, "maxPromptLength": 100000}]}'
        "]}"
    )
    serve_html(monkeypatch, f"globalThis.__XAI_PUBLIC_MODELS__={blob};")
    pricing = xai_scraper.scrape(make_cfg(), "grok-x")
    assert pricing == Pricing(2e-6, 6e-6, "chat", 100000, None)


def test_detect_extracts_blob_from_html(snippet):
    assert xai_page.detect(make_cfg()) == ["grok-test"]


def test_scrape_exact_prices(live_blob):
    cfg = make_cfg()
    assert xai_scraper.scrape(cfg, "grok-4.5") == Pricing(2e-6, 6e-6, "chat", 500000, 0.3 / 1e6)
    assert xai_scraper.scrape(cfg, "grok-4.6") == Pricing(2e-6, 6e-6, "chat", 500000, 0.5 / 1e6)
    assert xai_scraper.scrape(cfg, "grok-4.3") == Pricing(
        1.25e-6, 2.5e-6, "chat", 1000000, 0.2 / 1e6
    )
    assert xai_scraper.scrape(cfg, "grok-build-0.1") == Pricing(
        1e-6, 2e-6, "chat", 256000, 0.2 / 1e6
    )


def test_dedup_keys_dated_snapshots():
    # page ids spelled as dated snapshots normalize to the tracked base id,
    # measured against prices/providers/x_ai.yml (2026-08-19)
    cases = {
        "grok-4.20-0309-reasoning": "grok-4.20",
        "grok-4.20-0309-non-reasoning": "grok-4.20",
        "grok-4.20-multi-agent-0309": "grok-4.20-multi-agent",
        "grok-4-0709": "grok-4",
    }
    for page_id, base in cases.items():
        assert xai_scraper.dedup_keys(page_id) == [base], page_id


def test_dedup_keys_plain_ids_return_nothing():
    for page_id in ("grok-4.6", "grok-4.5", "grok-4.3", "grok-4.20", "grok-build-0.1"):
        assert xai_scraper.dedup_keys(page_id) == [], page_id


def test_scrape_unknown_model_returns_none(live_blob):
    assert xai_scraper.scrape(make_cfg(), "grok-4") is None


def test_scrape_unpriced_entries_return_none(snippet):
    cfg = make_cfg()
    assert xai_scraper.scrape(cfg, "grok-unpriced") is None
    # image entries are not language models
    assert xai_scraper.scrape(cfg, "grok-imagine-mini") is None


def test_scrape_context_and_cache_read(snippet):
    assert xai_scraper.scrape(make_cfg(), "grok-test") == Pricing(
        2e-6, 6e-6, "chat", 500000, 0.3 / 1e6
    )


def test_blob_parsed_once_per_url(monkeypatch):
    fetches = {"count": 0}

    def counting_fetch(url: str) -> str:
        fetches["count"] += 1
        blob = (FIXTURES / "blob.json").read_text(encoding="utf-8")
        return f"<script>globalThis.__XAI_PUBLIC_MODELS__={blob};</script>"

    monkeypatch.setattr(xai_page, "fetch_text", counting_fetch)
    cfg = make_cfg("https://docs.x.ai/docs/models/once")
    assert sorted(xai_page.detect(cfg)) == sorted(EXPECTED_IDS)
    assert xai_scraper.scrape(cfg, "grok-4.5") is not None
    assert sorted(xai_page.detect(cfg)) == sorted(EXPECTED_IDS)
    assert fetches["count"] == 1

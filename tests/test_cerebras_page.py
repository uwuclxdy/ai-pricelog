"""cerebras pricing pair tests, pinned against the saved live api payload."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import cerebras_page as detector
from ai_pricelog.scrapers import cerebras_page as scraper
from ai_pricelog.web import FetchError

PAGE_URL = "https://api.cerebras.ai/public/v1/models"
FIXTURE = Path(__file__).parent / "fixtures" / "cerebras_page" / "models.json"


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="cerebras",
        provider="Cerebras",
        detector="cerebras_page",
        detector_url=PAGE_URL,
        scraper="cerebras_page",
        scraper_url=PAGE_URL,
    )


def feed(monkeypatch: pytest.MonkeyPatch, text: str | None = None) -> None:
    payload = text if text is not None else FIXTURE.read_text()
    monkeypatch.setattr(detector, "fetch_text", lambda url: payload)
    monkeypatch.setattr(scraper, "fetch_text", lambda url: payload)


def test_detect_ids(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch)
    assert detector.detect(cfg()) == ["gemma-4-31b", "gpt-oss-120b"]


def test_scrape_gemma(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch)
    pricing = scraper.scrape(cfg(), "gemma-4-31b")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.99 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(1.49 / 1e6)
    assert pricing.mode == "chat"
    assert pricing.max_tokens_in == pricing.max_tokens_out == 0


def test_scrape_gpt_oss(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch)
    pricing = scraper.scrape(cfg(), "gpt-oss-120b")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.35 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(0.75 / 1e6)


def test_scrape_unknown_model_returns_none(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch)
    assert scraper.scrape(cfg(), "llama-4-maverick") is None


def test_scrape_entry_without_pricing_returns_none(monkeypatch: pytest.MonkeyPatch):
    payload = '{"data": [{"id": "x", "pricing": {}}]}'
    feed(monkeypatch, payload)
    assert scraper.scrape(cfg(), "x") is None


def test_scrape_zero_rate_prices_zero(monkeypatch: pytest.MonkeyPatch):
    # free is a price: zero pricing strings scrape as a 0.0/0.0 pair,
    # never None
    payload = '{"data": [{"id": "x", "pricing": {"prompt": "0", "completion": "0"}}]}'
    feed(monkeypatch, payload)
    pricing = scraper.scrape(cfg(), "x")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.0
    assert pricing.output_cost_per_token == 0.0


def test_scrape_negative_rate_parses_as_no_price(monkeypatch: pytest.MonkeyPatch):
    # negative strings ("no fixed price") stay unpriced
    payload = '{"data": [{"id": "x", "pricing": {"prompt": "-1", "completion": "0"}}]}'
    feed(monkeypatch, payload)
    assert scraper.scrape(cfg(), "x") is None


def test_detect_bad_json_raises(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch, "not json")
    with pytest.raises(FetchError, match="invalid json"):
        detector.detect(cfg())


def test_non_dict_pricing_raises_named_error(monkeypatch: pytest.MonkeyPatch):
    payload = '{"data": [{"id": "x", "pricing": "0.000001"}]}'
    feed(monkeypatch, payload)
    with pytest.raises(FetchError, match="pricing must be an object"):
        scraper.scrape(cfg(), "x")


def test_detect_non_object_root_raises(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch, "[1, 2]")
    with pytest.raises(FetchError, match="root"):
        detector.detect(cfg())


def test_detect_entry_without_id_skips_with_warning(monkeypatch: pytest.MonkeyPatch, caplog):
    # an entry without an id string is additive drift: detection skips it
    # with a warning and keeps the well-shaped entries
    payload = (
        '{"data": [{"pricing": {}}, {"id": "x", "pricing": {"prompt": "1", "completion": "2"}}]}'
    )
    feed(monkeypatch, payload)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["x"]
    assert "detect skip for cerebras" in caplog.text
    assert "without an id string" in caplog.text


def test_detect_non_object_pricing_skips_with_warning(monkeypatch: pytest.MonkeyPatch, caplog):
    payload = (
        '{"data": [{"id": "a", "pricing": "0.000001"}, '
        '{"id": "x", "pricing": {"prompt": "1", "completion": "2"}}]}'
    )
    feed(monkeypatch, payload)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["x"]
    assert "detect skip for cerebras" in caplog.text
    assert "pricing must be an object" in caplog.text


def test_detect_all_entries_skipped_raises(monkeypatch: pytest.MonkeyPatch):
    # structural: a data list whose entries are all additive drift leaves
    # no ids and still raises
    feed(monkeypatch, '{"data": [{"pricing": {}}]}')
    with pytest.raises(FetchError, match="no model entries"):
        detector.detect(cfg())


def test_scrape_unrelated_odd_entries_tolerated(monkeypatch: pytest.MonkeyPatch):
    # entries without an id string or with a non-object pricing are
    # additive drift detection already reported; the match scan passes
    # them over instead of raising
    payload = (
        '{"data": [{"pricing": {}}, {"id": "a", "pricing": "0.000001"}, '
        '{"id": "x", "pricing": {"prompt": "0.0000001", "completion": "0.0000002"}}]}'
    )
    feed(monkeypatch, payload)
    pricing = scraper.scrape(cfg(), "x")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(0.0000001)
    assert pricing.output_cost_per_token == pytest.approx(0.0000002)

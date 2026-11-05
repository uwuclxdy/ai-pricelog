"""the google provider pair's surface contract over the AI Studio markdown twin.

the watched surface is https://aistudio.google.com/docs/pricing.md (the old
ai.google.dev page 302s into an OAuth auto-signin chain). this file pins the
detector's id list against the live-page fixture; the pair implementation
tests live in test_google_page.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import google_page as detector
from ai_pricelog.web import FetchError

PAGE_URL = "https://aistudio.google.com/docs/pricing.md"
FIXTURE = Path(__file__).parent / "fixtures" / "google_page" / "pricing.md"

# every section carrying a token pricing table, in page order, with the slugs
# the section spells (the `/docs/models/` links' code-span texts, else the
# heading anchor)
EXPECTED_SECTIONS: list[tuple[str, list[str]]] = [
    ("gemini-4-argon", ["gemini-4-argon"]),
    ("gemini-3.8-flash", ["gemini-3.8-flash"]),
    ("gemini-3.6-flash", ["gemini-3.6-flash"]),
    ("gemini-3.5-transcribe-live", ["gemini-3.5-transcribe-live"]),
    ("gemini-3.5-transcribe", ["gemini-3.5-transcribe"]),
    ("gemini-3.5-flash-lite", ["gemini-3.5-flash-lite"]),
    ("gemini-omni-1.1-flash", ["gemini-omni-1.1-flash"]),
    (
        "gemini-3.8-live",
        ["gemini-3.8-live", "gemini-3.8-live-extended-thinking", "gemini-3.1-flash-live-preview"],
    ),
    ("gemini-3.5-live-translate-preview", ["gemini-3.5-live-translate-preview"]),
    ("gemini-3.1-flash-lite", ["gemini-3.1-flash-lite"]),
    ("gemini-3.1-pro-preview", ["gemini-3.1-pro-preview", "gemini-3.1-pro-preview-customtools"]),
    ("gemini-nano-banana-2.1", ["gemini-nano-banana-2.1"]),
    ("gemini-3.1-flash-image", ["gemini-3.1-flash-image"]),
    ("gemini-3.1-flash-lite-image", ["gemini-3.1-flash-lite-image"]),
    ("gemini-3.8-flash-tts", ["gemini-3.8-flash-tts"]),
    ("gemini-3.8-flash-lite-tts", ["gemini-3.8-flash-lite-tts"]),
    ("gemini-3.1-flash-tts-preview", ["gemini-3.1-flash-tts-preview"]),
    ("gemini-3-flash-preview", ["gemini-3-flash-preview"]),
    ("gemini-3-pro-image", ["gemini-3-pro-image"]),
    ("gemini-2.5-pro", ["gemini-2.5-pro"]),
    ("gemini-2.5-flash", ["gemini-2.5-flash"]),
    ("gemini-2.5-flash-lite", ["gemini-2.5-flash-lite"]),
    ("gemini-2.5-flash-native-audio", ["gemini-2.5-flash-native-audio-preview-12-2025"]),
    ("gemini-2.5-flash-image", ["gemini-2.5-flash-image"]),
    ("gemini-2.5-flash-preview-tts", ["gemini-2.5-flash-preview-tts"]),
    ("gemini-2.5-pro-preview-tts", ["gemini-2.5-pro-preview-tts"]),
    ("gemini-embedding-2", ["gemini-embedding-2"]),
    ("gemini-embedding", ["gemini-embedding-001"]),
    ("gemini-robotics-er-2", ["gemini-robotics-er-2-preview"]),
    ("gemini-robotics-er-2-streaming", ["gemini-robotics-er-2-streaming-preview"]),
    ("gemma-4", ["gemma-4"]),
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="google",
        provider="Google",
        detector="google_page",
        detector_url=PAGE_URL,
        scraper="google_page",
        scraper_url=PAGE_URL,
    )


@pytest.fixture
def live_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve the fixture bytes through whatever fetcher the module imports.

    patches both spellings so the test reds through the real entry point on
    the pre-rewrite code (whose fetch_soup parses markdown as html and finds
    no token tables) and greens once the pair reads the text layer.
    """
    text = FIXTURE.read_text(encoding="utf-8")

    def fake_soup(url: str):  # noqa: ANN001, ANN202
        from bs4 import BeautifulSoup

        return BeautifulSoup(text, "html.parser")

    monkeypatch.setattr(detector, "fetch_soup", fake_soup, raising=False)
    monkeypatch.setattr(detector, "fetch_text", lambda url: text, raising=False)


def test_detect_lists_token_priced_models_in_page_order(live_page):
    assert detector.detect(cfg()) == [slug for _a, slugs in EXPECTED_SECTIONS for slug in slugs]


def test_detect_no_token_tables_raises(live_page, monkeypatch: pytest.MonkeyPatch):
    from bs4 import BeautifulSoup

    text = "no pricing content here\n"
    monkeypatch.setattr(detector, "fetch_text", lambda url: text, raising=False)
    monkeypatch.setattr(
        detector, "fetch_soup", lambda url: BeautifulSoup(text, "html.parser"), raising=False
    )
    with pytest.raises(FetchError, match="no token pricing tables"):
        detector.detect(cfg())

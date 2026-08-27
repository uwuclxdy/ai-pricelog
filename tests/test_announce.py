from __future__ import annotations

import pytest

from ai_pricelog import announce, config, web


def make_provider_cfg(key: str, urls: tuple[str, ...] = ()) -> config.ProviderCfg:
    return config.ProviderCfg(
        key=key,
        provider=key.title(),
        detector="fake_det",
        detector_url="https://example.com/models",
        scraper="fake_scr",
        scraper_url="https://example.com/pricing",
        announce_urls=urls,
    )


def make_cfg(*providers: config.ProviderCfg) -> config.Config:
    return config.Config(providers=providers, cap=3)


@pytest.fixture
def fake_fetch(monkeypatch):
    responses: dict[str, str | Exception] = {}

    def fetch(url: str) -> str:
        response = responses[url]
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(web, "fetch_text", fetch)
    return responses


def test_extract_prose_strips_markup_and_scripts():
    text = (
        "<html><head><script>var x = 1;</script><style>p{}</style></head>"
        "<body><h1>New price</h1><p>Input $2 per 1M</p></body></html>"
    )
    assert announce.extract_prose("https://example.com/updates", text) == (
        "New price Input $2 per 1M"
    )


def test_extract_prose_markdown_passthrough():
    text = "# changelog\n\n- entry one\n- entry two\n"
    assert announce.extract_prose("https://example.com/changelog.md", text) == (
        "# changelog - entry one - entry two"
    )


def test_extract_prose_xml_feed():
    text = (
        "<rss><channel><title>Blog</title>"
        "<item><title>A</title><pubDate>2026-08-26</pubDate></item>"
        "</channel></rss>"
    )
    assert announce.extract_prose("https://example.com/rss.xml", text) == "Blog A 2026-08-26"


def test_extract_prose_feed_without_xml_suffix():
    # developers.googleblog.com/feeds/posts/default carries no .xml suffix
    text = '<?xml version="1.0"?><feed><title>T</title><entry><title>E</title></entry></feed>'
    assert announce.extract_prose("https://example.com/feeds/posts/default", text) == "T E"


def test_snapshot_roundtrip(tmp_path):
    path = tmp_path / "announce.json"
    snapshot = {"deepseek": {"https://x": {"text": "hi", "sha256": "abc", "fetched": "2026-08-26"}}}
    announce.save_snapshot(snapshot, path)
    assert announce.load_snapshot(path) == snapshot


def test_load_snapshot_missing_is_empty(tmp_path):
    assert announce.load_snapshot(tmp_path / "nope.json") == {}


def test_load_snapshot_bad_json_names_file(tmp_path):
    path = tmp_path / "announce.json"
    path.write_text("{nope")
    with pytest.raises(ValueError, match="announce file"):
        announce.load_snapshot(path)


def test_load_snapshot_non_object(tmp_path):
    path = tmp_path / "announce.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="must be an object"):
        announce.load_snapshot(path)


def test_differs_false_when_hashes_equal():
    old = {"deepseek": {"https://x": {"sha256": "a"}}}
    new = {"deepseek": {"https://x": {"sha256": "a"}}}
    assert not announce.differs(old, new)


def test_differs_true_on_new_url():
    assert announce.differs({}, {"deepseek": {"https://x": {"sha256": "a"}}})


def test_differs_true_on_removed_url():
    old = {"deepseek": {"https://x": {"sha256": "a"}}}
    assert announce.differs(old, {})


def test_differs_true_on_changed_hash():
    old = {"deepseek": {"https://x": {"sha256": "a"}}}
    new = {"deepseek": {"https://x": {"sha256": "b"}}}
    assert announce.differs(old, new)


def test_first_fetch_is_baseline_not_a_change(fake_fetch):
    fake_fetch["https://x/updates"] = "<html><body>one</body></html>"
    cfg = make_cfg(make_provider_cfg("deepseek", ("https://x/updates",)))
    result = announce.fetch_channels(cfg, {}, "2026-08-26")
    assert result.changes == ()
    assert result.errors == ()
    entry = result.snapshot["deepseek"]["https://x/updates"]
    assert entry["text"] == "one"
    assert entry["fetched"] == "2026-08-26"
    assert entry["sha256"] == announce._sha256("one")


def test_changed_channel_reports_old_to_new(fake_fetch):
    fake_fetch["https://x/updates"] = "<html><body>two</body></html>"
    snapshot = {
        "deepseek": {
            "https://x/updates": {
                "text": "one",
                "sha256": announce._sha256("one"),
                "fetched": "2026-08-19",
            }
        }
    }
    cfg = make_cfg(make_provider_cfg("deepseek", ("https://x/updates",)))
    result = announce.fetch_channels(cfg, snapshot, "2026-08-26")
    (change,) = result.changes
    assert change.provider == "deepseek"
    assert change.url == "https://x/updates"
    assert change.old_text == "one"
    assert change.new_text == "two"
    assert change.old_sha256 == announce._sha256("one")
    assert change.new_sha256 == announce._sha256("two")


def test_fetch_error_keeps_snapshot_entry(fake_fetch):
    fake_fetch["https://x/updates"] = web.FetchError("fetch failed for https://x/updates: boom")
    snapshot = {
        "deepseek": {
            "https://x/updates": {
                "text": "one",
                "sha256": announce._sha256("one"),
                "fetched": "2026-08-19",
            }
        }
    }
    cfg = make_cfg(make_provider_cfg("deepseek", ("https://x/updates",)))
    result = announce.fetch_channels(cfg, snapshot, "2026-08-26")
    assert result.changes == ()
    assert result.errors == (
        "deepseek https://x/updates: FetchError: fetch failed for https://x/updates: boom",
    )
    assert result.snapshot == snapshot
    assert not announce.differs(snapshot, result.snapshot)


def test_removed_url_drops_from_fresh_snapshot(fake_fetch):
    snapshot = {
        "deepseek": {"https://x/old": {"text": "gone", "sha256": "a", "fetched": "2026-08-19"}}
    }
    cfg = make_cfg(make_provider_cfg("deepseek"))
    result = announce.fetch_channels(cfg, snapshot, "2026-08-26")
    assert result.changes == ()
    assert result.snapshot == {}
    assert announce.differs(snapshot, result.snapshot)


def test_provider_without_channels_is_skipped(fake_fetch):
    cfg = make_cfg(make_provider_cfg("avian"))
    result = announce.fetch_channels(cfg, {}, "2026-08-26")
    assert result.changes == ()
    assert result.errors == ()
    assert result.snapshot == {}

from __future__ import annotations

import json
from pathlib import Path

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
    return config.Config(providers=providers)


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
    assert announce.extract_prose("https://example.com/rss.xml", text) == "Blog A"


def test_extract_prose_feed_strips_date_metadata():
    text = (
        "<rss><channel><title>Blog</title>"
        "<lastBuildDate>2026-08-29T08:31:47Z</lastBuildDate>"
        "<item><title>A</title><pubDate>2026-08-26</pubDate>"
        "<dc:date>2026-08-26</dc:date></item>"
        "</channel></rss>"
    )
    assert announce.extract_prose("https://example.com/rss", text) == "Blog A"


def test_extract_prose_atom_feed_strips_timestamps():
    text = (
        "<feed><title>T</title><updated>2026-08-29T00:00:00Z</updated>"
        "<entry><title>E</title><published>2026-08-26</published>"
        "<updated>2026-08-26</updated></entry></feed>"
    )
    assert announce.extract_prose("https://example.com/feeds/x", text) == "T E"


def test_extract_prose_feed_rebuild_dates_do_not_change_prose():
    template = (
        "<rss><channel><title>Blog</title><lastBuildDate>{build}</lastBuildDate>"
        "<item><title>A</title><pubDate>{published}</pubDate></item>"
        "</channel></rss>"
    )
    yesterday = template.format(build="2026-08-28", published="2026-08-26")
    today = template.format(build="2026-08-29", published="2026-08-26")
    assert announce.extract_prose("https://example.com/rss", yesterday) == announce.extract_prose(
        "https://example.com/rss", today
    )


def test_extract_prose_html_keeps_dates_as_content():
    text = "<html><body><time>2026-08-26</time><p>New price</p></body></html>"
    assert announce.extract_prose("https://example.com/updates", text) == "2026-08-26 New price"


def test_extract_prose_feed_without_xml_suffix():
    # developers.googleblog.com/feeds/posts/default carries no .xml suffix
    text = '<?xml version="1.0"?><feed><title>T</title><entry><title>E</title></entry></feed>'
    assert announce.extract_prose("https://example.com/feeds/posts/default", text) == "T E"


def test_slug_examples():
    assert announce.slug("https://api-docs.deepseek.com/updates/") == "updates"
    assert announce.slug("https://api-docs.deepseek.com/sitemap.xml") == "sitemap-xml"
    assert announce.slug("https://ai.google.dev/gemini-api/docs/changelog?hl=en") == "changelog"
    assert announce.slug("https://developers.googleblog.com/feeds/posts/default") == "default"
    assert (
        announce.slug("https://docs.z.ai/devpack/notice/usage-revision.md") == "usage-revision-md"
    )


def test_slug_empty_path_is_index():
    assert announce.slug("https://example.com") == "index"
    assert announce.slug("https://example.com/") == "index"


def test_channel_files_disambiguates_collisions():
    urls = ("https://x/a.b", "https://x/a-b")
    files = announce.channel_files("src", urls)
    assert files[urls[0]] == f"state/announce/src/a-b-{announce._sha256(urls[0])[:8]}.md"
    assert files[urls[1]] == f"state/announce/src/a-b-{announce._sha256(urls[1])[:8]}.md"


def test_channel_files_no_collision_no_suffix():
    files = announce.channel_files("src", ("https://x/updates/",))
    assert files["https://x/updates/"] == "state/announce/src/updates.md"


def test_wrap_is_sentence_per_line_and_round_trips():
    prose = "New price. Input $2 per 1M. Output $3."
    wrapped = announce.wrap(prose)
    assert wrapped == "New price.\nInput $2 per 1M.\nOutput $3.\n"
    assert announce.unwrap(wrapped) == prose


def test_wrap_keeps_decimals_on_one_line():
    assert announce.wrap("Rate 0.5 per 1M.") == "Rate 0.5 per 1M.\n"


def test_wrap_round_trips_without_sentence_boundary():
    prose = " ".join(f"word{n}" for n in range(400))
    assert announce.unwrap(announce.wrap(prose)) == prose


def test_wrap_round_trips_a_token_longer_than_the_ceiling():
    prose = "start " + "x" * 700 + " end"
    wrapped = announce.wrap(prose)
    assert announce.unwrap(wrapped) == prose
    # the long token rides its own line, never cut
    assert "x" * 700 in wrapped.splitlines()


def test_wrap_ceiling_breaks_at_spaces_only():
    prose = " ".join("w" * 599 for _ in range(3))
    for line in announce.wrap(prose).splitlines():
        assert len(line) <= announce._LINE_CEILING


def test_snapshot_roundtrip(tmp_path):
    snapshot = {
        "deepseek": {
            "https://x/updates": {
                "file": "state/announce/deepseek/updates.md",
                "text": "hi there. new price.",
                "sha256": announce._sha256("hi there. new price."),
                "fetched": "2026-08-26",
            }
        }
    }
    announce.save_snapshot(snapshot, tmp_path)
    assert announce.load_snapshot(tmp_path) == snapshot


def test_load_snapshot_missing_is_empty(tmp_path):
    assert announce.load_snapshot(tmp_path) == {}


def test_load_snapshot_bad_json_names_file(tmp_path):
    path = tmp_path / announce.ANNOUNCE_INDEX
    path.parent.mkdir(parents=True)
    path.write_text("{nope")
    with pytest.raises(ValueError, match="announce index"):
        announce.load_snapshot(tmp_path)


def test_load_snapshot_non_object(tmp_path):
    path = tmp_path / announce.ANNOUNCE_INDEX
    path.parent.mkdir(parents=True)
    path.write_text("[]")
    with pytest.raises(ValueError, match="must be an object"):
        announce.load_snapshot(tmp_path)


def test_load_snapshot_rejects_relative_traversal(tmp_path):
    path = tmp_path / announce.ANNOUNCE_INDEX
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "deepseek": {
                    "https://x/updates": {
                        "file": "../outside.md",
                        "sha256": "a" * 64,
                        "fetched": "2026-09-02",
                    }
                }
            }
        )
    )
    with pytest.raises(ValueError, match="derived path"):
        announce.load_snapshot(tmp_path)


def test_load_snapshot_rejects_absolute_file(tmp_path):
    path = tmp_path / announce.ANNOUNCE_INDEX
    path.parent.mkdir(parents=True)
    absolute = (tmp_path / "outside.md").resolve().as_posix()
    path.write_text(
        json.dumps(
            {
                "deepseek": {
                    "https://x/updates": {
                        "file": absolute,
                        "sha256": "a" * 64,
                        "fetched": "2026-09-02",
                    }
                }
            }
        )
    )
    with pytest.raises(ValueError, match="derived path"):
        announce.load_snapshot(tmp_path)


def test_load_snapshot_missing_channel_file_names_index(tmp_path):
    path = tmp_path / announce.ANNOUNCE_INDEX
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "deepseek": {
                    "https://x/updates": {
                        "file": "state/announce/deepseek/updates.md",
                        "sha256": "a" * 64,
                        "fetched": "2026-09-02",
                    }
                }
            }
        )
    )
    with pytest.raises(ValueError, match="is missing"):
        announce.load_snapshot(tmp_path)


def test_save_snapshot_removes_dropped_channel(tmp_path):
    file = "state/announce/deepseek/updates.md"
    entry = {
        "file": file,
        "text": "one",
        "sha256": announce._sha256("one"),
        "fetched": "2026-09-02",
    }
    announce.save_snapshot({"deepseek": {"https://x/updates": entry}}, tmp_path)
    assert (tmp_path / file).exists()
    announce.save_snapshot({}, tmp_path)
    assert not (tmp_path / file).exists()
    assert not (tmp_path / "state/announce/deepseek").exists()


def test_save_snapshot_writes_derived_path_not_stored(tmp_path):
    entry = {
        "file": "../outside/evil.md",
        "text": "one",
        "sha256": announce._sha256("one"),
        "fetched": "2026-09-02",
    }
    announce.save_snapshot({"deepseek": {"https://x/updates": entry}}, tmp_path)
    assert (tmp_path / "state/announce/deepseek/updates.md").exists()
    assert not (tmp_path / "outside" / "evil.md").exists()
    index = json.loads((tmp_path / announce.ANNOUNCE_INDEX).read_text(encoding="utf-8"))
    assert index["deepseek"]["https://x/updates"]["file"] == "state/announce/deepseek/updates.md"


def test_save_snapshot_writes_derived_path_not_absolute_stored(tmp_path):
    absolute = (tmp_path / "outside" / "abs.md").resolve().as_posix()
    entry = {
        "file": absolute,
        "text": "one",
        "sha256": announce._sha256("one"),
        "fetched": "2026-09-02",
    }
    announce.save_snapshot({"deepseek": {"https://x/updates": entry}}, tmp_path)
    assert (tmp_path / "state/announce/deepseek/updates.md").exists()
    assert not (tmp_path / "outside" / "abs.md").exists()


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
    assert entry["file"] == "state/announce/deepseek/updates.md"


def test_changed_channel_reports_old_to_new(fake_fetch):
    fake_fetch["https://x/updates"] = "<html><body>two</body></html>"
    snapshot = {
        "deepseek": {
            "https://x/updates": {
                "text": "one",
                "sha256": announce._sha256("one"),
                "fetched": "2026-08-19",
                "file": "state/announce/deepseek/updates.md",
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
                "file": "state/announce/deepseek/updates.md",
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


def test_fetch_preserves_fetched_when_hash_unchanged(fake_fetch):
    fake_fetch["https://x/updates"] = "<html><body>one</body></html>"
    snapshot = {
        "deepseek": {
            "https://x/updates": {
                "text": "one",
                "sha256": announce._sha256("one"),
                "fetched": "2026-08-19",
                "file": "state/announce/deepseek/updates.md",
            }
        }
    }
    cfg = make_cfg(make_provider_cfg("deepseek", ("https://x/updates",)))
    result = announce.fetch_channels(cfg, snapshot, "2026-09-03")
    assert result.snapshot["deepseek"]["https://x/updates"]["fetched"] == "2026-08-19"


def test_fetch_replaces_fetched_when_hash_changes(fake_fetch):
    fake_fetch["https://x/updates"] = "<html><body>two</body></html>"
    snapshot = {
        "deepseek": {
            "https://x/updates": {
                "text": "one",
                "sha256": announce._sha256("one"),
                "fetched": "2026-08-19",
                "file": "state/announce/deepseek/updates.md",
            }
        }
    }
    cfg = make_cfg(make_provider_cfg("deepseek", ("https://x/updates",)))
    result = announce.fetch_channels(cfg, snapshot, "2026-09-03")
    assert result.snapshot["deepseek"]["https://x/updates"]["fetched"] == "2026-09-03"


def test_committed_index_round_trips_over_the_real_tree():
    root = Path(__file__).resolve().parents[1]
    index = json.loads((root / announce.ANNOUNCE_INDEX).read_text(encoding="utf-8"))
    assert index
    named: set[str] = set()
    for source, urls in index.items():
        derived = announce.channel_files(source, urls.keys())
        for url, entry in urls.items():
            assert entry["file"] == derived[url]
            named.add(entry["file"])
            text = (root / entry["file"]).read_text(encoding="utf-8")
            assert announce._sha256(announce.unwrap(text)) == entry["sha256"]
            assert announce.wrap(announce.unwrap(text)) == text
            assert all(len(line) <= announce._LINE_CEILING for line in text.splitlines())
    on_disk = {
        path.relative_to(root).as_posix() for path in (root / announce.ANNOUNCE_DIR).rglob("*.md")
    }
    assert on_disk == named

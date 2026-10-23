from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ai_pricelog import health
from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import minimax_page as minimax_detect
from ai_pricelog.scrapers import minimax_page as minimax_scrape
from ai_pricelog.web import FetchError

FIXTURES = Path(__file__).parent / "fixtures" / "minimax_page"
_PRICING_URL = "https://platform.minimax.io/docs/guides/pricing-paygo.md"


@pytest.fixture
def minimax_cfg() -> ProviderCfg:
    return ProviderCfg(
        key="minimax",
        provider="MiniMax",
        detector="minimax_page",
        detector_url="https://platform.minimax.io/docs/guides/models-intro.md",
        scraper="minimax_page",
        scraper_url="https://platform.minimax.io/docs/guides/pricing-paygo.md",
    )


@pytest.fixture
def feed_fixtures(monkeypatch: pytest.MonkeyPatch) -> None:
    def feed(url: str) -> str:
        if url.endswith("models-intro.md"):
            return (FIXTURES / "models-intro.md").read_text()
        if url.endswith("pricing-paygo.md"):
            return (FIXTURES / "pricing-paygo.md").read_text()
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(minimax_detect, "fetch_text", feed)
    monkeypatch.setattr(minimax_scrape, "fetch_text", feed)


def test_detect_returns_language_models_in_page_order(minimax_cfg, feed_fixtures):
    assert minimax_detect.detect(minimax_cfg) == [
        "MiniMax-M3.1-Flash-Preview",
        "MiniMax-M3",
        "MiniMax-M2.7",
        "MiniMax-M2.7-highspeed",
        "MiniMax-M2.5",
        "MiniMax-M2.5-highspeed",
        "MiniMax-M2.1",
        "MiniMax-M2.1-highspeed",
        "MiniMax-M2",
    ]


def test_scrape_m3_takes_first_standard_row(minimax_cfg, feed_fixtures):
    pricing = minimax_scrape.scrape(minimax_cfg, "MiniMax-M3")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.3 / 1e6
    assert pricing.output_cost_per_token == 1.2 / 1e6
    assert pricing.mode == "chat"
    assert pricing.max_tokens_in == pricing.max_tokens_out == 0


def test_scrape_m27_prices_exact(minimax_cfg, feed_fixtures):
    pricing = minimax_scrape.scrape(minimax_cfg, "MiniMax-M2.7")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.3 / 1e6
    assert pricing.output_cost_per_token == 1.2 / 1e6


def test_scrape_m27_highspeed_prices_exact(minimax_cfg, feed_fixtures):
    pricing = minimax_scrape.scrape(minimax_cfg, "MiniMax-M2.7-highspeed")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.6 / 1e6
    assert pricing.output_cost_per_token == 2.4 / 1e6


def test_scrape_video_model_has_no_token_pricing(minimax_cfg, feed_fixtures):
    assert minimax_scrape.scrape(minimax_cfg, "MiniMax-H3") is None


def test_scrape_audio_model_has_no_token_pricing(minimax_cfg, feed_fixtures):
    assert minimax_scrape.scrape(minimax_cfg, "speech-2.8-turbo") is None


def test_scrape_token_plan_only_model_has_no_paygo_pricing(minimax_cfg, feed_fixtures):
    assert minimax_scrape.scrape(minimax_cfg, "MiniMax-M3.1-Flash-Preview") is None


def test_scrape_m3_cache_read_takes_last_amount(minimax_cfg, feed_fixtures):
    # strikethrough original first, current price last
    pricing = minimax_scrape.scrape(minimax_cfg, "MiniMax-M3")
    assert pricing is not None
    assert pricing.cache_read_cost_per_token == 0.06 / 1e6


def test_scrape_m27_cache_read(minimax_cfg, feed_fixtures):
    pricing = minimax_scrape.scrape(minimax_cfg, "MiniMax-M2.7")
    assert pricing is not None
    assert pricing.cache_read_cost_per_token == 0.06 / 1e6


def test_scrape_m21_cache_read(minimax_cfg, feed_fixtures):
    pricing = minimax_scrape.scrape(minimax_cfg, "MiniMax-M2.1")
    assert pricing is not None
    assert pricing.cache_read_cost_per_token == 0.03 / 1e6


def test_scrape_table_without_cache_column_leaves_cache_unset(minimax_cfg, monkeypatch):
    page = (
        "| Model | Input | Output |\n"
        "|---|---|---|\n"
        "| **MiniMax-M3** | $0.30 / M tokens | $1.20 / M tokens |\n"
    )
    monkeypatch.setattr(minimax_scrape, "fetch_text", lambda url: page)
    pricing = minimax_scrape.scrape(minimax_cfg, "MiniMax-M3")
    assert pricing is not None
    assert pricing.cache_read_cost_per_token is None


def test_detect_malformed_page_raises_fetch_error(minimax_cfg, monkeypatch):
    monkeypatch.setattr(minimax_detect, "fetch_text", lambda url: "no tables here")
    with pytest.raises(FetchError) as excinfo:
        minimax_detect.detect(minimax_cfg)
    assert str(excinfo.value) == f"no pipe lines found on {minimax_cfg.detector_url}"


def test_detect_tables_without_model_ids_raise_fetch_error(minimax_cfg, monkeypatch):
    monkeypatch.setattr(
        minimax_detect, "fetch_text", lambda url: "| Name | Type |\n|---|---|\n| Hailuo | video |\n"
    )
    with pytest.raises(FetchError, match="model ids"):
        minimax_detect.detect(minimax_cfg)


def test_scrape_malformed_page_raises_fetch_error(minimax_cfg, monkeypatch):
    monkeypatch.setattr(minimax_scrape, "fetch_text", lambda url: "no tables here")
    with pytest.raises(FetchError):
        minimax_scrape.scrape(minimax_cfg, "MiniMax-M3")


_M27_HEADER = "| Model | Input | Output | Prompt caching Read | Prompt caching Write |"


def _page_with_line(fixture: str, lineno: int, old: str, new: str) -> str:
    """the fixture with line `lineno` (1-based) rewritten from `old` to `new`."""
    lines = (FIXTURES / fixture).read_text().split("\n")
    assert old in lines[lineno - 1], f"{fixture}:{lineno} no longer holds {old!r}"
    lines[lineno - 1] = lines[lineno - 1].replace(old, new)
    return "\n".join(lines)


def _pricing_page_with(old: str, new: str) -> str:
    # line 33 heads the table whose first row is MiniMax-M2.7; line 39 repeats
    # the header for the highspeed tab
    return _page_with_line("pricing-paygo.md", 33, old, new)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "| **MiniMax-M2.7** |",
            "| MiniMax-M2.7 |",
            f"unreadable model row for MiniMax-M2.7 on {_PRICING_URL}: 'MiniMax-M2.7'",
        ),
        (
            "| **MiniMax-M2.7** |",
            "| **New** **MiniMax-M2.7** |",
            f"unreadable model row for MiniMax-M2.7 on {_PRICING_URL}: '**New** **MiniMax-M2.7**'",
        ),
        (
            "| **MiniMax-M2.7** |",
            "| minimax-m2.7 |",
            f"unreadable model row for MiniMax-M2.7 on {_PRICING_URL}: 'minimax-m2.7'",
        ),
        (
            "| **MiniMax-M2.7** | \\$0.3 / M tokens | \\$1.2 / M tokens | "
            "\\$0.06 / M tokens | \\$0.375 / M tokens |",
            "| **MiniMax-M2.7** | \\$0.3 / M tokens |",
            f"unreadable model row for MiniMax-M2.7 on {_PRICING_URL}: 2 cells",
        ),
        (
            "| **MiniMax-M2.7** | \\$0.3 / M tokens | \\$1.2 / M tokens | "
            "\\$0.06 / M tokens | \\$0.375 / M tokens |",
            "| **MiniMax-M2.7** | \\$0.3 / M tokens | \\$1.2 / M tokens |",
            f"unreadable model row for MiniMax-M2.7 on {_PRICING_URL}: 3 cells",
        ),
    ],
    ids=[
        "unbolded-name",
        "badge-before-name",
        "lowercase-unbolded-name",
        "row-missing-cells",
        "row-missing-cache-cell",
    ],
)
def test_scrape_unreadable_model_row_raises(minimax_cfg, monkeypatch, old, new, message):
    page = _page_with_line("pricing-paygo.md", 35, old, new)
    monkeypatch.setattr(minimax_scrape, "fetch_text", lambda url: page)
    with pytest.raises(FetchError) as excinfo:
        minimax_scrape.scrape(minimax_cfg, "MiniMax-M2.7")
    assert str(excinfo.value) == message


def test_scrape_m2_never_reads_the_longer_m27_row_as_its_own(minimax_cfg, feed_fixtures):
    # the unreadable-row scan matches a whole id: MiniMax-M2.7 is not MiniMax-M2
    pricing = minimax_scrape.scrape(minimax_cfg, "MiniMax-M2")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.3 / 1e6
    assert pricing.output_cost_per_token == 1.2 / 1e6
    assert pricing.cache_read_cost_per_token == 0.03 / 1e6


def test_scrape_row_naming_the_id_inside_a_longer_token_does_not_raise(minimax_cfg, monkeypatch):
    # the whole-id boundary also holds on the left: X-MiniMax-M2.7 names no row
    page = _page_with_line("pricing-paygo.md", 35, "| **MiniMax-M2.7** |", "| X-MiniMax-M2.7 |")
    monkeypatch.setattr(minimax_scrape, "fetch_text", lambda url: page)
    assert minimax_scrape.scrape(minimax_cfg, "MiniMax-M2.7") is None


def test_scrape_link_target_naming_the_model_does_not_raise(minimax_cfg, monkeypatch):
    # the unreadable-row scan reads the cell's visible text, never a link target
    page = _page_with_line(
        "pricing-paygo.md", 35, "| **MiniMax-M2.7** |", "| [M2.7](/docs/MiniMax-M2.5) |"
    )
    monkeypatch.setattr(minimax_scrape, "fetch_text", lambda url: page)
    pricing = minimax_scrape.scrape(minimax_cfg, "MiniMax-M2.5")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.3 / 1e6
    assert pricing.output_cost_per_token == 1.2 / 1e6
    assert pricing.cache_read_cost_per_token == 0.03 / 1e6


def test_scrape_reads_a_fold_equal_recased_header(minimax_cfg, monkeypatch):
    # a casing or spacing drift on the header trio keeps the table: the
    # columns resolve on folded headers, the zai scraper's shape
    page = _pricing_page_with(
        _M27_HEADER, "| model |  INPUT | output | Prompt Caching Read | Prompt caching Write |"
    )
    monkeypatch.setattr(minimax_scrape, "fetch_text", lambda url: page)
    pricing = minimax_scrape.scrape(minimax_cfg, "MiniMax-M2.7")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.3 / 1e6
    assert pricing.output_cost_per_token == 1.2 / 1e6
    assert pricing.cache_read_cost_per_token == 0.06 / 1e6


def _detect_page_with(lineno: int, old: str, new: str) -> str:
    return _page_with_line("models-intro.md", lineno, old, new)


def _detect_skips(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if (match := health.DETECT_SKIP.search(r.getMessage())) and match.group(1) == "minimax"
    ]


@pytest.mark.parametrize(
    ("lineno", "old", "new"),
    [
        # the first language table's separator
        (14, "| :- | :- | :- |", "|| :- | :- | :- |"),
        (17, "| [MiniMax-M2.7](", "|| [MiniMax-M2.7]("),
    ],
    ids=["doubled-edge-pipe-separator", "empty-name-cell"],
)
def test_detect_unreadable_table_or_row_logs_a_detect_skip(
    minimax_cfg, monkeypatch, caplog, lineno, old, new
):
    # a table or row the detector cannot read used to drop its ids silently,
    # so their absence counters ran toward a removal; a detect skip freezes them
    page = _detect_page_with(lineno, old, new)
    monkeypatch.setattr(minimax_detect, "fetch_text", lambda url: page)
    with caplog.at_level(logging.WARNING):
        ids = minimax_detect.detect(minimax_cfg)
    assert "MiniMax-M2.5" in ids
    assert _detect_skips(caplog)


_ALL_IDS = [
    "MiniMax-M3.1-Flash-Preview",
    "MiniMax-M3",
    "MiniMax-M2.7",
    "MiniMax-M2.7-highspeed",
    "MiniMax-M2.5",
    "MiniMax-M2.5-highspeed",
    "MiniMax-M2.1",
    "MiniMax-M2.1-highspeed",
    "MiniMax-M2",
]


@pytest.mark.parametrize(
    ("lineno", "old", "new"),
    [
        # an empty name cell in the video and the audio tables
        (34, "| [MiniMax H3](", "|| [MiniMax H3]("),
        (49, "| [speech-2.8-hd](", "|| [speech-2.8-hd]("),
        # a spacer row inside the first language table
        (17, "| [MiniMax-M2.7](", "| | | |\n| [MiniMax-M2.7]("),
        # readable non-language rows whose description mentions a MiniMax-M token
        (
            34,
            "video-generation-v2-create) | ",
            "video-generation-v2-create) | Built on MiniMax-M3. ",
        ),
        (
            49,
            "speech-t2a-http) | ",
            "speech-t2a-http) | [weights](https://huggingface.co/MiniMaxAI/MiniMax-Music3) ",
        ),
        (50, "speech-t2a-http) | ", "speech-t2a-http) | works with MiniMax-MCP. "),
        # a video name cell whose link target holds an id-shaped path
        (
            34,
            "[MiniMax H3](/docs/api-reference/video-generation-v2-create)",
            "[MiniMax H3](https://huggingface.co/MiniMaxAI/MiniMax-M3-video)",
        ),
        # a video name cell holding a longer token whose tail is an id
        (
            34,
            "[MiniMax H3](/docs/api-reference/video-generation-v2-create)",
            "[Hailuo-M2.7](/docs/x)",
        ),
        # an audio name cell spelling a MiniMax-M token with no version digit
        (49, "[speech-2.8-hd](/docs/api-reference/speech-t2a-http)", "**MiniMax-MCP**"),
        # a music row named like a MiniMax-M id with no version digit
        (71, "[music-3.0](", "[MiniMax-Music3]("),
    ],
    ids=[
        "empty-name-video-row",
        "empty-name-audio-row",
        "spacer-row",
        "video-description-naming-an-id",
        "audio-description-linking-a-music-repo",
        "audio-description-naming-mcp",
        "video-link-target-naming-an-id",
        "video-name-holding-a-longer-token-tail",
        "audio-name-cell-naming-mcp",
        "music-row-named-music3",
    ],
)
def test_detect_row_naming_no_model_id_never_skips(
    minimax_cfg, monkeypatch, caplog, lineno, old, new
):
    # a detect skip freezes every minimax absence counter for the run, so a row
    # that names no MiniMax-M id must not log one
    page = _detect_page_with(lineno, old, new)
    monkeypatch.setattr(minimax_detect, "fetch_text", lambda url: page)
    with caplog.at_level(logging.WARNING):
        assert minimax_detect.detect(minimax_cfg) == _ALL_IDS
    assert _detect_skips(caplog) == []


def test_detect_ignores_an_id_named_only_in_a_broken_block_description(
    minimax_cfg, monkeypatch, caplog
):
    # the skip scan reads each line's first cell only, so an id linked only
    # from a description cell never freezes the counters
    page = _detect_page_with(33, "| :- | :- | :- | :- |", "|| :- | :- | :- | :- |")
    anchor = "| Next-gen open general-purpose"
    assert page.count(anchor) == 1
    page = page.replace(anchor, "| [MiniMax-M2.7](/docs/x) Next-gen open general-purpose")
    monkeypatch.setattr(minimax_detect, "fetch_text", lambda url: page)
    with caplog.at_level(logging.WARNING):
        assert minimax_detect.detect(minimax_cfg) == _ALL_IDS
    assert _detect_skips(caplog) == []


_DETECT_URL = "https://platform.minimax.io/docs/guides/models-intro.md"


@pytest.mark.parametrize(
    ("name_cell", "named"),
    [
        ("MiniMax-M2.7", "MiniMax-M2.7"),
        ("**MiniMax-M2.7**", "MiniMax-M2.7"),
        ("[MiniMax M2.7](/docs/api-reference/text-anthropic-api)", "MiniMax M2.7"),
        ("MiniMax-M2.7 | see [MiniMax-M2.5](/docs/x)", "MiniMax-M2.7"),
        ("[minimax-m2.7](/docs/api-reference/text-anthropic-api)", "minimax-m2.7"),
        ("[M2.7](/docs/api-reference/text-anthropic-api)", "M2.7"),
    ],
    ids=[
        "unlinked-name",
        "bold-name",
        "spaced-link-name",
        "bare-name-beside-a-linked-id",
        "lowercase-link-name",
        "prefix-less-link-name",
    ],
)
def test_detect_row_whose_name_cannot_be_read_skips_naming_the_id(
    minimax_cfg, monkeypatch, caplog, name_cell, named
):
    # a language row whose name cell carries the id but no readable link drops
    # the id, so the detect skip that freezes its absence counter must name the
    # id the name cell holds, never one its description links
    page = _detect_page_with(
        17, "[MiniMax-M2.7](/docs/api-reference/text-anthropic-api) |", name_cell + " |"
    )
    monkeypatch.setattr(minimax_detect, "fetch_text", lambda url: page)
    with caplog.at_level(logging.WARNING):
        ids = minimax_detect.detect(minimax_cfg)
    assert "MiniMax-M2.7" not in ids
    assert "MiniMax-M2.5" in ids
    assert _detect_skips(caplog) == [
        f"detect skip for minimax: unreadable model row naming {named!r} on {_DETECT_URL}"
    ]


@pytest.mark.parametrize(
    ("new_header", "column"),
    [
        (_M27_HEADER.replace("| Input |", "| Prompt |"), "Input"),
        (_M27_HEADER.replace("| Input |", "| Input (per 1M) |"), "Input"),
        (_M27_HEADER.replace("| Output |", "| Completion |"), "Output"),
    ],
    ids=["input-renamed", "input-reworded", "output-renamed"],
)
def test_scrape_model_row_under_a_header_missing_a_rate_column_raises(
    minimax_cfg, monkeypatch, new_header, column
):
    # the model's own row sits in a table whose header no longer names the
    # column, so the scrape fails loud, naming the model, the column and the url
    page = _pricing_page_with(_M27_HEADER, new_header)
    monkeypatch.setattr(minimax_scrape, "fetch_text", lambda url: page)
    for model_id in ("MiniMax-M2.7", "MiniMax-M2.7-highspeed"):
        with pytest.raises(FetchError) as excinfo:
            minimax_scrape.scrape(minimax_cfg, model_id)
        assert str(excinfo.value) == (
            f"malformed pricing table for {model_id} on {_PRICING_URL}: no {column} column"
        )
    # a model outside the broken table still prices
    pricing = minimax_scrape.scrape(minimax_cfg, "MiniMax-M2.5")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.3 / 1e6


@pytest.mark.parametrize(
    ("new_header", "column"),
    [
        (
            "| **Model** | **Input** | **Output** | **Prompt caching Read**"
            " | **Prompt caching Write** |",
            "Input",
        ),
        (_M27_HEADER.replace("| Model |", "| Models |"), "Model"),
    ],
    ids=["bolded-header-without-unit", "models-first-cell"],
)
def test_scrape_model_row_under_an_unrecognised_header_raises(
    minimax_cfg, monkeypatch, new_header, column
):
    # a header the scraper does not recognise as a pricing table must not turn
    # the model rows under it into "no pricing"; the message names the first
    # heading it cannot resolve
    page = _pricing_page_with(_M27_HEADER, new_header)
    monkeypatch.setattr(minimax_scrape, "fetch_text", lambda url: page)
    with pytest.raises(FetchError) as excinfo:
        minimax_scrape.scrape(minimax_cfg, "MiniMax-M2.7")
    assert str(excinfo.value) == (
        f"malformed pricing table for MiniMax-M2.7 on {_PRICING_URL}: no {column} column"
    )


@pytest.mark.parametrize(
    ("lineno", "old", "new", "model_id"),
    [
        (33, "| Prompt caching Read |", "| Cache Read |", "MiniMax-M2.7"),
        (
            33,
            "| Prompt caching Read | Prompt caching Write |",
            "| Cache Read | Cache Write |",
            "MiniMax-M2.7",
        ),
        # the M3 tables carry a cache-read column and no cache-write one
        (17, "| Prompt caching Read |", "| Cache Read |", "MiniMax-M3"),
    ],
    ids=["read-reworded", "read-and-write-reworded", "m3-read-reworded"],
)
def test_scrape_table_with_a_reworded_cache_read_column_raises(
    minimax_cfg, monkeypatch, lineno, old, new, model_id
):
    # a reworded cache-read header used to scrape cache_read as None, so the
    # refresh row proposed deleting the stored cache rate
    page = _page_with_line("pricing-paygo.md", lineno, old, new)
    monkeypatch.setattr(minimax_scrape, "fetch_text", lambda url: page)
    with pytest.raises(FetchError) as excinfo:
        minimax_scrape.scrape(minimax_cfg, model_id)
    assert str(excinfo.value) == (
        f"malformed pricing table for {model_id} on {_PRICING_URL}: no Prompt caching Read column"
    )


def test_scrape_reads_the_unit_suffixed_bold_header(minimax_cfg, monkeypatch):
    # the live page bolds every header and appends its unit; the M3.1 row
    # prices 0.15 / 0.60 / 0.015 per 1M on it (measured 2026-10-21)
    page = (
        "| **Model** | **Input** \\$ / M tokens | **Output** \\$ / M tokens"
        " | **Prompt caching Read** \\$ / M tokens |\n"
        "| :- | :-: | :-: | :-: |\n"
        "| **MiniMax-M3.1-Flash** | \\$0.15 | \\$0.60 | \\$0.015 |\n"
    )
    monkeypatch.setattr(minimax_scrape, "fetch_text", lambda url: page)
    pricing = minimax_scrape.scrape(minimax_cfg, "MiniMax-M3.1-Flash")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.15 / 1e6
    assert pricing.output_cost_per_token == 0.60 / 1e6
    assert pricing.cache_read_cost_per_token == 0.015 / 1e6


def test_scrape_unbalanced_bold_header_raises(minimax_cfg, monkeypatch):
    # only a matched **pair** drops; stripping each marker independently
    # would accept a half-bold header and silently price it
    page = _pricing_page_with(
        _M27_HEADER,
        "| Model** | **Input** \\$ / M tokens | **Output** \\$ / M tokens"
        " | **Prompt caching Read** \\$ / M tokens |",
    )
    monkeypatch.setattr(minimax_scrape, "fetch_text", lambda url: page)
    with pytest.raises(FetchError) as excinfo:
        minimax_scrape.scrape(minimax_cfg, "MiniMax-M2.7")
    assert str(excinfo.value) == (
        f"malformed pricing table for MiniMax-M2.7 on {_PRICING_URL}: no Model column"
    )


def test_scrape_unbalanced_bold_rate_header_raises(minimax_cfg, monkeypatch):
    # the unit-suffixed rate cell drops its bold pair only as a pair too;
    # a half-bold rate cell must raise, never resolve
    page = _pricing_page_with(
        _M27_HEADER,
        "| **Model** | Input** \\$ / M tokens | **Output** \\$ / M tokens"
        " | **Prompt caching Read** \\$ / M tokens |",
    )
    monkeypatch.setattr(minimax_scrape, "fetch_text", lambda url: page)
    with pytest.raises(FetchError) as excinfo:
        minimax_scrape.scrape(minimax_cfg, "MiniMax-M2.7")
    assert str(excinfo.value) == (
        f"malformed pricing table for MiniMax-M2.7 on {_PRICING_URL}: no Input column"
    )


def test_scrape_reads_past_an_unpriced_table_naming_the_model(minimax_cfg, monkeypatch):
    # an added table that names the model in bold but carries no price is
    # additive drift, never a broken pricing table
    quota = "| Model | Token Plan quota |\n|---|---|\n| **MiniMax-M2.7** | 1500 requests / 5h |\n\n"
    page = _pricing_page_with(_M27_HEADER, quota + _M27_HEADER)
    monkeypatch.setattr(minimax_scrape, "fetch_text", lambda url: page)
    pricing = minimax_scrape.scrape(minimax_cfg, "MiniMax-M2.7")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.3 / 1e6
    assert pricing.output_cost_per_token == 1.2 / 1e6


def test_scrape_never_prices_a_broken_standard_table_from_the_priority_one(
    minimax_cfg, monkeypatch
):
    # with the Standard M3 header unreadable and its rates written without "$",
    # the Standard table must still count as M3's pricing table and raise,
    # never fall through to the Priority tab's higher rates
    lines = (FIXTURES / "pricing-paygo.md").read_text().split("\n")
    header = "| Model | Input | Output | Prompt caching Read |"
    assert header in lines[16], "pricing-paygo.md:17 no longer heads the Standard M3 table"
    lines[16] = lines[16].replace(
        header, "| **Model** | **Input** | **Output** | **Prompt caching Read** |"
    )
    for index in (18, 19):
        assert "**MiniMax-M3**" in lines[index] and "\\$" in lines[index]
        lines[index] = lines[index].replace("\\$", "")
    page = "\n".join(lines)
    monkeypatch.setattr(minimax_scrape, "fetch_text", lambda url: page)
    with pytest.raises(FetchError) as excinfo:
        minimax_scrape.scrape(minimax_cfg, "MiniMax-M3")
    assert str(excinfo.value) == (
        f"malformed pricing table for MiniMax-M3 on {_PRICING_URL}: no Input column"
    )


def test_scrape_reads_past_an_unpriced_price_table_naming_the_model(minimax_cfg, monkeypatch):
    # a `Model | Price` table (a shape the page already uses) naming the model
    # in bold with no amount is no broken rate table: the real one still prices
    note = "| Model | Price |\n|---|---|\n| **MiniMax-M2.7** | Free during preview |\n\n"
    page = _pricing_page_with(_M27_HEADER, note + _M27_HEADER)
    monkeypatch.setattr(minimax_scrape, "fetch_text", lambda url: page)
    pricing = minimax_scrape.scrape(minimax_cfg, "MiniMax-M2.7")
    assert pricing is not None
    assert pricing.input_cost_per_token == 0.3 / 1e6
    assert pricing.output_cost_per_token == 1.2 / 1e6

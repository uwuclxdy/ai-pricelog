"""openai pricing pair tests, pinned against the saved live page."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import openai_page as detector
from ai_pricelog.scrapers import openai_page as scraper
from ai_pricelog.store import build_row
from ai_pricelog.validate import load_schema_keys, validate_row
from ai_pricelog.web import FetchError

PAGE_URL = "https://platform.openai.com/docs/pricing"
FIXTURE = Path(__file__).parent / "fixtures" / "openai_page" / "pricing.html"
SCHEMA_KEYS = load_schema_keys(Path(__file__).resolve().parents[1])

EXPECTED_IDS = [
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "gpt-5.5-pro",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.4-pro",
    "gpt-5.2",
    "gpt-5.2-pro",
    "gpt-5.1",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-5-pro",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-4o",
    "gpt-4o-2024-05-13",
    "gpt-4o-mini",
    "o1",
    "o1-pro",
    "o3-pro",
    "o3",
    "o4-mini",
    "o3-mini",
    "gpt-4-turbo-2024-04-09",
    "gpt-4-0613",
    "gpt-3.5-turbo",
    "gpt-3.5-turbo-0125",
    "gpt-3.5-turbo-1106",
    "gpt-3.5-turbo-instruct",
    "davinci-002",
    "babbage-002",
    "gpt-image-2",
    "gpt-image-1.5",
    "gpt-image-1-mini",
    "gpt-image-1",
    "chatgpt-image-latest",
]


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="openai",
        provider="OpenAI",
        detector="openai_page",
        detector_url=PAGE_URL,
        scraper="openai_page",
        scraper_url=PAGE_URL,
    )


def load_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(), "html.parser")


def island_soup(tier: str, rows: list) -> BeautifulSoup:
    props = json.dumps({"tier": tier, "rows": rows}).replace('"', "&quot;")
    return BeautifulSoup(
        f'<astro-island component-export="TextTokenPricingTables" props="{props}"></astro-island>',
        "html.parser",
    )


def test_detect_ids(monkeypatch):
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_scrape_five_column_row(monkeypatch):
    # five-column row: input, cached read, cache write, output
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "gpt-5.6-sol")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(4 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.4 / 1e6)
    assert pricing.cache_write_cost_per_token == pytest.approx(5 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(20 / 1e6)
    assert pricing.mode == "chat"


def test_scrape_four_column_row(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "gpt-4o")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(2.5 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(1.25 / 1e6)
    assert pricing.cache_write_cost_per_token is None
    assert pricing.output_cost_per_token == pytest.approx(10 / 1e6)


def test_scrape_null_cache_read(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "o3-pro")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(20 / 1e6)
    assert pricing.cache_read_cost_per_token is None
    assert pricing.output_cost_per_token == pytest.approx(80 / 1e6)


def test_scrape_annotation_name(monkeypatch):
    # the page annotates gpt-5.5 with its context window; the bare name is the id
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "gpt-5.5")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(5 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(0.5 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(30 / 1e6)


def test_scrape_unknown_model_returns_none(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    assert scraper.scrape(cfg(), "gpt-6") is None


def test_scrape_missing_standard_island_raises(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: island_soup("batch", [["gpt-5.6-sol", 2, 0.2, 2.5, 10]]),
    )
    with pytest.raises(FetchError, match="no standard pricing table"):
        scraper.scrape(cfg(), "gpt-5.6-sol")


def test_detect_missing_standard_island_raises(monkeypatch):
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: island_soup("flex", [["gpt-5.6-sol", 6, 0.6, 7.5, 30]]),
    )
    with pytest.raises(FetchError, match="no standard pricing table"):
        detector.detect(cfg())


def test_detect_malformed_row_skips_with_warning(monkeypatch, caplog):
    # a row outside the pricing shape is additive drift: the run skips it
    # with a warning and keeps the well-shaped rows
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: island_soup("standard", [["gpt-5.6-sol", 4, 0.4], ["gpt-4o", 2.5, 1.25, 10]]),
    )
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["gpt-4o"]
    assert "detect skip for openai" in caplog.text
    assert "outside the pricing shape" in caplog.text


def test_detect_name_outside_id_shape_skips_with_warning(monkeypatch, caplog):
    # a model name outside the id shape is additive drift and skips with a
    # warning; the well-shaped rows still emit
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: island_soup(
            "standard", [["GPT 5.6 SOL!", 4, 0.4, 5, 20], ["gpt-4o", 2.5, 1.25, 10]]
        ),
    )
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["gpt-4o"]
    assert "detect skip for openai" in caplog.text
    assert "outside the id shape" in caplog.text


def test_scrape_unrelated_malformed_row_tolerated(monkeypatch):
    # a drifted row for another model is additive drift detection already
    # reported; the match scan passes it over instead of raising
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: island_soup("standard", [["gpt-5.6-sol", 4, 0.4], ["gpt-4o", 2.5, 1.25, 10]]),
    )
    pricing = scraper.scrape(cfg(), "gpt-4o")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(2.5 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(10 / 1e6)


def test_scrape_matched_row_unreadable_rate_raises(monkeypatch):
    # the matched row's cells are strict: an unreadable rate raises, it
    # must not read as the model missing
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: island_soup("standard", [["gpt-5.6-sol", "lots", 0.4, 5, 20]]),
    )
    with pytest.raises(FetchError, match="unreadable rate 'lots'"):
        scraper.scrape(cfg(), "gpt-5.6-sol")


def group(model: str, image: list, text: list) -> list:
    """a wire-encoded group, as the page serves it: [0, {model, rows}],
    every row [1, [cells]], every cell [0, value]."""

    def row(label: str, cells: list) -> list:
        return [1, [[0, label]] + [[0, cell] for cell in cells]]

    return [0, {"model": [0, model], "rows": [1, [row("Image", image), row("Text", text)]]}]


def image_props(groups: list) -> str:
    return json.dumps(
        {
            "headings": ["Model", "Modality", "Input", "Cached input", "Output"],
            "groups": [1, groups],
        }
    ).replace('"', "&quot;")


def image_island(props: str) -> str:
    return f'<astro-island component-export="GroupedPricingTable" props="{props}"></astro-island>'


def grouped_soup(panes: dict[str, str | None]) -> BeautifulSoup:
    """a page with the image-generation switcher; panes map pane value -> props or None."""
    body = "".join(
        f'<div data-content-switcher-pane="true" data-value="{value}">{island}</div>'
        if island
        else f'<div data-content-switcher-pane="true" data-value="{value}"></div>'
        for value, island in panes.items()
    )
    return BeautifulSoup(
        f'<div data-content-switcher-id="multimodal-image-pricing">{body}</div>',
        "html.parser",
    )


def both_tables_soup(image_groups: list, image_pane: str = "standard") -> BeautifulSoup:
    """the chat standard island plus the image switcher, one soup.

    `image_pane` names the pane holding the image island; the other stays empty.
    """
    chat = island_soup("standard", [["gpt-5.6-sol", 4, 0.4, 5, 20]])
    panes: dict[str, str | None] = {"standard": None, "batch": None}
    panes[image_pane] = image_island(image_props(image_groups))
    image = grouped_soup(panes)
    chat_island = chat.find("astro-island")
    image.append(chat_island)
    return image


def empty_groups_props() -> str:
    # an image island whose groups list is empty: structural absence, not drift
    return json.dumps(
        {
            "headings": ["Model", "Modality", "Input", "Cached input", "Output"],
            "groups": [1, []],
        }
    ).replace('"', "&quot;")


STANDARD_IMAGE = [
    group("gpt-image-2", [8, 2, 30], [5, 1.25, "-"]),
    group("gpt-image-1.5", [8, 2, 32], [5, 1.25, 10]),
    group("gpt-image-1-mini", [2.5, 0.25, 8], [2, 0.2, "-"]),
    group("gpt-image-1", [10, 2.5, 40], [5, 1.25, "-"]),
    group("chatgpt-image-latest", [8, 2, 32], [5, 1.25, 10]),
]


def test_scrape_image_models(monkeypatch):
    # gpt-image rows price into the image axes: input/cache_read/output from
    # the Text row, image/image_output from the Image row, per-1M / 1e6
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "gpt-image-2")
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(5 / 1e6)
    assert pricing.cache_read_cost_per_token == pytest.approx(1.25 / 1e6)
    assert pricing.output_cost_per_token == pytest.approx(30 / 1e6)
    assert pricing.image_cost_per_token == pytest.approx(8 / 1e6)
    assert pricing.image_output_cost_per_token == pytest.approx(30 / 1e6)
    assert pricing.cache_write_cost_per_token is None
    assert pricing.mode == "chat"


def test_scrape_image_model_text_output_prefers_text(monkeypatch):
    # a Text output cell prices the output axis; the Image output does not
    # override it
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "chatgpt-image-latest")
    assert pricing is not None
    assert pricing.output_cost_per_token == pytest.approx(10 / 1e6)
    assert pricing.image_cost_per_token == pytest.approx(8 / 1e6)
    assert pricing.image_output_cost_per_token == pytest.approx(32 / 1e6)


def test_scrape_image_models_all_five_priced(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    expected = {
        "gpt-image-2": (5, 1.25, 30, 8, 30),
        "gpt-image-1.5": (5, 1.25, 10, 8, 32),
        "gpt-image-1-mini": (2, 0.2, 8, 2.5, 8),
        "gpt-image-1": (5, 1.25, 40, 10, 40),
        "chatgpt-image-latest": (5, 1.25, 10, 8, 32),
    }
    for model_id, (inp, cached, out, image, image_out) in expected.items():
        pricing = scraper.scrape(cfg(), model_id)
        assert pricing is not None, model_id
        assert pricing.input_cost_per_token == pytest.approx(inp / 1e6)
        assert pricing.cache_read_cost_per_token == pytest.approx(cached / 1e6)
        assert pricing.output_cost_per_token == pytest.approx(out / 1e6)
        assert pricing.image_cost_per_token == pytest.approx(image / 1e6)
        assert pricing.image_output_cost_per_token == pytest.approx(image_out / 1e6)


def test_detect_appends_image_ids_in_page_order(monkeypatch, caplog):
    # detection appends the image-generation standard pane's group ids after
    # the chat ids, deduped, page order
    monkeypatch.setattr(detector, "fetch_soup", lambda url: load_soup())
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == EXPECTED_IDS
    # the clean fixture fires no section warning; a drift-skip warning for
    # an off-shape group name is fine and carries "image" in the model id
    assert "image-generation" not in caplog.text


def test_scrape_image_group_missing_modality_row_warns(monkeypatch, caplog):
    # a group whose rows carry no Text row is drift only the scraper sees
    # (detect reads ids, never rows): the missing label warns before the
    # model reads as unpriced, so the stall is visible in the run log
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: both_tables_soup(
            [
                [
                    0,
                    {
                        "model": [0, "gpt-image-2"],
                        "rows": [
                            1,
                            [
                                [1, [[0, "Image"], [0, 8], [0, 2], [0, 30]]],
                                [1, [[0, "Audio"], [0, 1], [0, 1], [0, 1]]],
                            ],
                        ],
                    },
                ]
            ]
        ),
    )
    with caplog.at_level(logging.WARNING):
        assert scraper.scrape(cfg(), "gpt-image-2") is None
    assert "no 'Text' row" in caplog.text


def test_detect_batch_pane_only_keeps_chat_ids(monkeypatch, caplog):
    # a page whose image section holds only a batch pane is additive drift:
    # the chat ids stay and a warning names the image section
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: both_tables_soup(
            [group("gpt-image-2", [4, 1, 15], [2.5, 0.625, "-"])], image_pane="batch"
        ),
    )
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["gpt-5.6-sol"]
    assert "image-generation" in caplog.text
    assert "standard pane" in caplog.text


def test_scrape_batch_pane_only_returns_none(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: both_tables_soup(
            [group("gpt-image-2", [4, 1, 15], [2.5, 0.625, "-"])], image_pane="batch"
        ),
    )
    assert scraper.scrape(cfg(), "gpt-image-2") is None


def test_detect_no_image_section_keeps_chat_ids(monkeypatch, caplog):
    # the whole image section absent is additive drift too: the chat ids
    # stay, a warning names the section
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: island_soup(
            "standard", [["gpt-5.6-sol", 4, 0.4, 5, 20], ["gpt-4o", 2.5, 1.25, 10]]
        ),
    )
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["gpt-5.6-sol", "gpt-4o"]
    assert "image-generation" in caplog.text


def test_detect_image_island_without_groups_raises(monkeypatch):
    # an image island whose groups list is empty is structural absence
    # (plan #22), not additive drift: the source fails loud instead of
    # quietly reading as image-free
    soup = grouped_soup({"standard": image_island(empty_groups_props()), "batch": None})
    chat = island_soup("standard", [["gpt-5.6-sol", 4, 0.4, 5, 20]])
    soup.append(chat.find("astro-island"))
    monkeypatch.setattr(detector, "fetch_soup", lambda url: soup)
    with pytest.raises(FetchError, match="image pricing island without groups"):
        detector.detect(cfg())


def test_detect_image_ids_dedupe_against_chat_ids(monkeypatch):
    # an id appearing in both the chat rows and the image groups emits once
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: both_tables_soup(
            [group("gpt-5.6-sol", [8, 2, 30], [5, 1.25, 10])] + STANDARD_IMAGE[1:]
        ),
    )
    assert detector.detect(cfg()) == ["gpt-5.6-sol"] + EXPECTED_IDS[-4:]


def test_scrape_id_in_both_tables_raises(monkeypatch):
    # an id present in both the chat and image tables is a page-structure
    # anomaly: fail loud, never silently pick one
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: both_tables_soup([group("gpt-5.6-sol", [8, 2, 30], [5, 1.25, 10])]),
    )
    with pytest.raises(FetchError, match="both the chat and image pricing tables"):
        scraper.scrape(cfg(), "gpt-5.6-sol")


def test_detect_offshape_image_group_skips_with_warning(monkeypatch, caplog):
    # an image group with a model name outside the id shape is additive
    # drift: skip with a warning, the well-shaped groups still emit
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: both_tables_soup(
            [group("GPT IMAGE 2!", [8, 2, 30], [5, 1.25, 10])] + STANDARD_IMAGE[1:]
        ),
    )
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["gpt-5.6-sol"] + EXPECTED_IDS[-4:]
    assert "outside the id shape" in caplog.text


def test_detect_offshape_image_group_rows_skips_with_warning(monkeypatch, caplog):
    # a group outside the [model, rows] shape is additive drift too
    monkeypatch.setattr(
        detector,
        "fetch_soup",
        lambda url: both_tables_soup([["gpt-image-2", 8, 2, 30]] + STANDARD_IMAGE[1:]),
    )
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == ["gpt-5.6-sol"] + EXPECTED_IDS[-4:]
    assert "outside the group shape" in caplog.text


def test_image_group_row_validates_through_build_row(monkeypatch):
    # the gpt-image-2 row builds and validates: the Image output fills the
    # output axis when the Text row carries none
    monkeypatch.setattr(scraper, "fetch_soup", lambda url: load_soup())
    pricing = scraper.scrape(cfg(), "gpt-image-2")
    row = build_row("openai", "gpt-image-2", pricing, "2026-09-14", PAGE_URL, SCHEMA_KEYS.version)
    validate_row(row, SCHEMA_KEYS)
    assert row["rates"] == {
        "input": 5.0,
        "cache_read": 1.25,
        "output": 30.0,
        "image": 8.0,
        "image_output": 30.0,
    }


def test_decode_recurses_into_dict_valued_scalars():
    # astro wraps group objects as [0, {...}] scalars; the decoder recurses
    # into the dict so the group's own values come back decoded
    decoded = detector._decode(
        [0, {"model": [0, "gpt-image-2"], "rows": [1, [[0, ["Text", 5, 1.25, "-"]]]]}]
    )
    assert decoded == {"model": "gpt-image-2", "rows": [["Text", 5, 1.25, "-"]]}


def test_scrape_image_group_missing_text_input_returns_none(monkeypatch):
    # a group without a Text row cannot price the input axis: unpriced
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: both_tables_soup([group("gpt-image-2", [8, 2, 30], ["-", 1.25, 10])]),
    )
    assert scraper.scrape(cfg(), "gpt-image-2") is None


def test_scrape_image_group_missing_image_input_returns_none(monkeypatch):
    # a group without an Image row cannot price the image axis: unpriced
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: both_tables_soup([group("gpt-image-2", ["-", 2, 30], [5, 1.25, 10])]),
    )
    assert scraper.scrape(cfg(), "gpt-image-2") is None


def test_scrape_image_group_unreadable_rate_raises(monkeypatch):
    # the matched group's cells are strict, like the chat row's
    monkeypatch.setattr(
        scraper,
        "fetch_soup",
        lambda url: both_tables_soup([group("gpt-image-2", ["lots", 2, 30], [5, 1.25, 10])]),
    )
    with pytest.raises(FetchError, match="unreadable rate 'lots'"):
        scraper.scrape(cfg(), "gpt-image-2")

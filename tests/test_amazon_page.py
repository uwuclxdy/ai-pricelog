"""amazon (bedrock nova) pricing pair tests, pinned against trimmed live
bulk price-list api payloads (region index + the us-east-1 versioned
per-region file, publication 2026-09-11)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ai_pricelog.config import ProviderCfg
from ai_pricelog.detectors import amazon_page as detector
from ai_pricelog.scrapers import amazon_page as scraper
from ai_pricelog.store import build_row
from ai_pricelog.validate import load_schema_keys, validate_row
from ai_pricelog.web import FetchError

ROOT = Path(__file__).resolve().parents[1]
REGION_URL = (
    "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/"
    "current/region_index.json"
)
# urljoin of the fixture region index's us-east-1 currentVersionUrl: the
# versioned per-region file, never the 16MB global index
INDEX_URL = (
    "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/"
    "20260911124408/us-east-1/index.json"
)
FIXTURES = Path(__file__).parent / "fixtures" / "amazon_page"
VERSION = load_schema_keys(ROOT).version

EXPECTED_IDS = [
    "amazon.nova-lite-v1:0",
    "amazon.nova-micro-v1:0",
    "amazon.nova-pro-v1:0",
    "amazon.nova-premier-v1:0",
    "amazon.nova-2-lite-v1:0",
]

# model_id -> (display name, input, output, cache read), each rate in the
# api's per-1K usd; the row round-trip must land them x1000 per-1M. the
# fixture's publication carries these four with every chat axis; nova 2.0
# lite sits in it with its input row only, so its scrape coverage rides the
# injected-axis test below (rates from the live 2026-09-17 publication)
RATES = {
    "amazon.nova-lite-v1:0": ("Nova Lite", 0.00006, 0.00024, 0.000015),
    "amazon.nova-micro-v1:0": ("Nova Micro", 0.000035, 0.00014, 0.00000875),
    "amazon.nova-pro-v1:0": ("Nova Pro", 0.0008, 0.0032, 0.0002),
    "amazon.nova-premier-v1:0": ("Nova Premier", 0.0025, 0.0125, 0.000625),
}

NOVA_2_LITE_ID = "amazon.nova-2-lite-v1:0"
NOVA_2_LITE_RATES = ("Nova 2.0 Lite", 0.00033, 0.00275, 0.0000825)


def cfg() -> ProviderCfg:
    return ProviderCfg(
        key="amazon",
        provider="Amazon Bedrock",
        detector="amazon_page",
        detector_url=REGION_URL,
        scraper="amazon_page",
        scraper_url=REGION_URL,
        vendor="amazon",
        kind="first_party",
    )


@pytest.fixture(autouse=True)
def clear_region_cache():
    detector.region_file_url.cache_clear()
    yield
    detector.region_file_url.cache_clear()


def feed(
    monkeypatch: pytest.MonkeyPatch, region: str | None = None, index: str | None = None
) -> None:
    pages = {
        REGION_URL: region if region is not None else (FIXTURES / "region_index.json").read_text(),
        INDEX_URL: index if index is not None else (FIXTURES / "index.json").read_text(),
    }

    def fake(url: str) -> str:
        if url not in pages:
            raise FetchError(f"fetch failed for {url}: no fixture")
        return pages[url]

    # every fetch routes through the detector module (region_file_url and
    # offer_payload), so one patch site covers both halves
    monkeypatch.setattr(detector, "fetch_text", fake)


def mutated_index(change) -> str:
    data = json.loads((FIXTURES / "index.json").read_text())
    change(data)
    return json.dumps(data)


def _sku(data: dict, model: str, inference_type: str) -> str:
    """the on-demand product's sku for (model, inferenceType) in the fixture."""
    for sku, product in data["products"].items():
        attrs = product["attributes"]
        if (
            attrs.get("model") == model
            and attrs.get("feature") == "On-demand Inference"
            and attrs.get("inferenceType") == inference_type
        ):
            return sku
    raise AssertionError(f"no on-demand {inference_type} product for {model} in the fixture")


def _sole_dimension(data: dict, sku: str) -> dict:
    """the sku's single on-demand price dimension (the fixture's shape)."""
    offers = data["terms"]["OnDemand"][sku]
    dimensions = [
        dimension for offer in offers.values() for dimension in offer["priceDimensions"].values()
    ]
    assert len(dimensions) == 1
    return dimensions[0]


def test_detect_ids(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch)
    assert detector.detect(cfg()) == EXPECTED_IDS


def test_detect_joins_carded_names_without_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # every carded nova name in the fixture joins silently, nova 2.0 lite
    # included (its card is model-card-amazon-nova-2-lite.md). nova canvas
    # sits in the fixture too, but only as a T2I image product: no chat
    # axis, so the name never reaches the join and stays silently invisible
    # (no crash, no guessed id)
    feed(monkeypatch)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == EXPECTED_IDS
    assert "detect skip" not in caplog.text


def test_detect_unknown_nova_name_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # a nova name with a chat axis and no docs model card is additive
    # drift: skipped with a warning (plan #22), the other ids still emit

    def rename_lite(data: dict) -> None:
        for product in data["products"].values():
            attrs = product.get("attributes", {})
            if attrs.get("model") == "Nova Lite":
                attrs["model"] = "Nova Future"

    feed(monkeypatch, index=mutated_index(rename_lite))
    with caplog.at_level(logging.WARNING):
        ids = detector.detect(cfg())
    assert "amazon.nova-lite-v1:0" not in ids
    assert "nova name 'Nova Future' has no model-card id join" in caplog.text


def test_detect_cardless_tier_variant_skips_silently(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # a serving tier of a carded model (latency optimized) has chat axes
    # but no card of its own and never joins: excluded by name, so its
    # perpetual presence cannot mask a genuinely new unmapped name

    def add_latency_optimized(data: dict) -> None:
        sku = _sku(data, "Nova Pro", "Input tokens")
        for inference_type, rate in (("Input tokens", "0.0010"), ("Output tokens", "0.0040")):
            clone_sku = sku + "LAT" + inference_type[:3].upper()
            clone = json.loads(json.dumps(data["products"][sku]))
            clone["sku"] = clone_sku
            clone["attributes"]["model"] = "Nova Pro Latency Optimized"
            clone["attributes"]["inferenceType"] = inference_type
            data["products"][clone_sku] = clone
            terms = json.loads(json.dumps(data["terms"]["OnDemand"][sku]))
            for offer in terms.values():
                for dimension in offer["priceDimensions"].values():
                    dimension["pricePerUnit"]["USD"] = rate
            data["terms"]["OnDemand"][clone_sku] = terms

    feed(monkeypatch, index=mutated_index(add_latency_optimized))
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == EXPECTED_IDS
    assert "Latency Optimized" not in caplog.text


def test_detect_skips_third_party_models_silently(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # ministral 8B 3.0 sits in the fixture with a real chat on-demand row:
    # bedrock serves dozens of third-party models, and they are another
    # provider's coverage — no warning, no id, or every run logs ~60 skips
    # that bury the provider's only new-model signal
    feed(monkeypatch)
    with caplog.at_level(logging.WARNING):
        assert detector.detect(cfg()) == EXPECTED_IDS
    assert "Ministral" not in caplog.text


def test_detect_duplicate_chat_axis_product_raises(monkeypatch: pytest.MonkeyPatch):
    # two on-demand input products for one display name is an ambiguity the
    # parser must raise on, never a silent pick

    def clone_input(data: dict) -> None:
        sku = _sku(data, "Nova Lite", "Input tokens")
        clone_sku = sku + "CLONE"
        clone = json.loads(json.dumps(data["products"][sku]))
        clone["sku"] = clone_sku
        data["products"][clone_sku] = clone

    feed(monkeypatch, index=mutated_index(clone_input))
    with pytest.raises(FetchError, match="two on-demand"):
        detector.detect(cfg())


def test_region_index_resolves_once_per_run(monkeypatch: pytest.MonkeyPatch):
    # detect and every scrape read one pinned publication version per run:
    # a mid-run republish cannot split the run across two versions, so a
    # row observed today always names the same provenance url. the offer
    # file itself is re-read per call (each scrape is an independent read)
    counts = {"region": 0, "offer": 0}

    def fake(url: str) -> str:
        if url == REGION_URL:
            counts["region"] += 1
            return (FIXTURES / "region_index.json").read_text()
        if url == INDEX_URL:
            counts["offer"] += 1
            return (FIXTURES / "index.json").read_text()
        raise FetchError(f"fetch failed for {url}: no fixture")

    monkeypatch.setattr(detector, "fetch_text", fake)
    assert detector.detect(cfg()) == EXPECTED_IDS
    for model_id in EXPECTED_IDS[:2]:
        assert scraper.scrape(cfg(), model_id) is not None
    assert counts["region"] == 1
    assert counts["offer"] == 3


def test_detect_bad_region_index_json_raises(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch, region="not json")
    with pytest.raises(FetchError, match="invalid json"):
        detector.detect(cfg())


def test_detect_missing_watched_region_raises(monkeypatch: pytest.MonkeyPatch):
    data = json.loads((FIXTURES / "region_index.json").read_text())
    del data["regions"]["us-east-1"]
    feed(monkeypatch, region=json.dumps(data))
    with pytest.raises(FetchError, match="us-east-1"):
        detector.detect(cfg())


def test_detect_region_index_without_regions_object_raises(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch, region='{"formatVersion": "v1.0"}')
    with pytest.raises(FetchError, match="regions"):
        detector.detect(cfg())


def test_detect_invalid_index_json_raises(monkeypatch: pytest.MonkeyPatch):
    feed(monkeypatch, index="not json")
    with pytest.raises(FetchError, match="invalid json"):
        detector.detect(cfg())


def test_detect_no_nova_products_raises(monkeypatch: pytest.MonkeyPatch):
    # only the titan product (no model attribute) is left: structural absence
    # raises, so the provider goes loud instead of reading every stored nova
    # id absent and faking delistings

    def keep_titan(data: dict) -> None:
        keep = [
            sku
            for sku, product in data["products"].items()
            if product["attributes"].get("usagetype") == "USE1-TitanTextG1-Lite-input-tokens"
        ]
        data["products"] = {sku: data["products"][sku] for sku in keep}

    feed(monkeypatch, index=mutated_index(keep_titan))
    with pytest.raises(FetchError, match="no carded nova"):
        detector.detect(cfg())


def test_detect_nova_names_without_a_carded_join_raises(monkeypatch: pytest.MonkeyPatch):
    # a fully stale name map (every nova chat name outside it) is structural,
    # not drift; the message names the names it saw

    def keep_uncarded(data: dict) -> None:
        keep = [
            sku
            for sku, product in data["products"].items()
            if product["attributes"].get("model") in ("Nova 2.0 Lite", "Nova Canvas")
        ]
        data["products"] = {sku: data["products"][sku] for sku in keep}
        for product in data["products"].values():
            attrs = product.get("attributes", {})
            if attrs.get("model") == "Nova 2.0 Lite":
                attrs["model"] = "Nova Future"

    feed(monkeypatch, index=mutated_index(keep_uncarded))
    with pytest.raises(FetchError, match="Nova Future"):
        detector.detect(cfg())


@pytest.mark.parametrize("model_id", sorted(RATES))
def test_scrape_rates(monkeypatch: pytest.MonkeyPatch, model_id: str):
    # the pro flex, batch, customization and provisioned-throughput rows sit
    # in the fixture: exact feature/inferenceType matching must read only the
    # standard on-demand axes (the duplicate guard would fire otherwise)
    feed(monkeypatch)
    _, input_1k, output_1k, cache_read_1k = RATES[model_id]
    pricing = scraper.scrape(cfg(), model_id)
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(input_1k / 1000)
    assert pricing.output_cost_per_token == pytest.approx(output_1k / 1000)
    assert pricing.cache_read_cost_per_token == pytest.approx(cache_read_1k / 1000)
    assert pricing.cache_write_cost_per_token is None
    assert pricing.mode == "chat"
    assert pricing.url == INDEX_URL
    assert pricing.effective_at == "2026-08-01"
    assert pricing.max_tokens_in == pricing.max_tokens_out == 0


@pytest.mark.parametrize("model_id", sorted(RATES))
def test_row_round_trips_per_mtok(monkeypatch: pytest.MonkeyPatch, model_id: str):
    # per-1K api rates x1000 -> the per-1M rate axes every other provider
    # stores; cache_write stays out because the docs model cards corroborate
    # no write price, so the api's $0.0000 rows are never recorded blind
    feed(monkeypatch)
    name, input_1k, output_1k, cache_read_1k = RATES[model_id]
    pricing = scraper.scrape(cfg(), model_id)
    row = build_row("amazon", model_id, pricing, "2026-09-15", cfg().scraper_url, VERSION)
    validate_row(row, load_schema_keys(ROOT))
    assert row["rates"] == {
        "input": round(input_1k * 1000, 6),
        "output": round(output_1k * 1000, 6),
        "cache_read": round(cache_read_1k * 1000, 6),
    }
    assert "cache_write" not in row["rates"]
    assert row["effective_at"] == "2026-08-01"
    assert row["provenance"]["url"] == INDEX_URL


def _complete_nova_2_lite(data: dict) -> None:
    """the fixture publication's Nova 2.0 Lite output + cache-read rows.

    the 2026-09-11 fixture carries its input row only; the live 2026-09-17
    publication carries all three chat axes at the rates pinned in
    NOVA_2_LITE_RATES, cloned here in the fixture's own product/term shape.
    """
    axes = {
        "Output tokens": NOVA_2_LITE_RATES[2],
        "Prompt cache read input tokens": NOVA_2_LITE_RATES[3],
    }
    base_sku = _sku(data, "Nova Lite", "Input tokens")
    lite_input_sku = _sku(data, "Nova 2.0 Lite", "Input tokens")
    lite_terms = data["terms"]["OnDemand"][lite_input_sku]
    for offer in lite_terms.values():
        for dimension in offer["priceDimensions"].values():
            dimension["pricePerUnit"]["USD"] = f"{NOVA_2_LITE_RATES[1]:.10f}"
        offer["effectiveDate"] = "2026-09-01T00:00:00Z"
    for inference_type, rate in axes.items():
        clone_sku = base_sku + "N2L" + inference_type[:3].upper()
        clone = json.loads(json.dumps(data["products"][base_sku]))
        clone["sku"] = clone_sku
        clone["attributes"]["model"] = "Nova 2.0 Lite"
        clone["attributes"]["inferenceType"] = inference_type
        data["products"][clone_sku] = clone
        terms = json.loads(json.dumps(data["terms"]["OnDemand"][base_sku]))
        for offer in terms.values():
            offer["effectiveDate"] = "2026-09-01T00:00:00Z"
            for dimension in offer["priceDimensions"].values():
                dimension["pricePerUnit"]["USD"] = f"{rate:.10f}"
                dimension["description"] = f"${rate} per 1K tokens for Nova2.0Lite"
        data["terms"]["OnDemand"][clone_sku] = terms


def test_scrape_nova_2_lite_partial_axes_returns_none(monkeypatch: pytest.MonkeyPatch):
    # the fixture publication carries only the input row: a carded model
    # without both input and output axes skips-and-retries (decision 8),
    # never a partial row
    feed(monkeypatch)
    assert scraper.scrape(cfg(), NOVA_2_LITE_ID) is None


def test_scrape_nova_2_lite_full_axes(monkeypatch: pytest.MonkeyPatch):
    name, input_1k, output_1k, cache_read_1k = NOVA_2_LITE_RATES
    feed(monkeypatch, index=mutated_index(_complete_nova_2_lite))
    pricing = scraper.scrape(cfg(), NOVA_2_LITE_ID)
    assert pricing is not None
    assert pricing.input_cost_per_token == pytest.approx(input_1k / 1000)
    assert pricing.output_cost_per_token == pytest.approx(output_1k / 1000)
    assert pricing.cache_read_cost_per_token == pytest.approx(cache_read_1k / 1000)
    assert pricing.effective_at == "2026-09-01"
    row = build_row("amazon", NOVA_2_LITE_ID, pricing, "2026-09-22", cfg().scraper_url, VERSION)
    validate_row(row, load_schema_keys(ROOT))
    assert row["rates"] == {
        "input": round(input_1k * 1000, 6),
        "output": round(output_1k * 1000, 6),
        "cache_read": round(cache_read_1k * 1000, 6),
    }


def test_scrape_unknown_id_returns_none(monkeypatch: pytest.MonkeyPatch):
    # only carded ids have a display name to join; anything else is not on
    # this page
    feed(monkeypatch)
    assert scraper.scrape(cfg(), "amazon.nova-sonic-v1:0") is None


def test_scrape_missing_input_row_returns_none(monkeypatch: pytest.MonkeyPatch):
    # a carded name whose on-demand input row is gone carries no usable
    # rates: skip-and-retry (decision 8), never a partial row

    def drop_input(data: dict) -> None:
        del data["products"][_sku(data, "Nova Lite", "Input tokens")]

    feed(monkeypatch, index=mutated_index(drop_input))
    assert scraper.scrape(cfg(), "amazon.nova-lite-v1:0") is None


def test_scrape_non_token_unit_raises(monkeypatch: pytest.MonkeyPatch):
    # the /1000 conversion assumes per-1K tokens; any other unit is a shape
    # break, never a silent misconversion into the rate axes

    def retag_unit(data: dict) -> None:
        dimension = _sole_dimension(data, _sku(data, "Nova Lite", "Input tokens"))
        dimension["unit"] = "hour"

    feed(monkeypatch, index=mutated_index(retag_unit))
    with pytest.raises(FetchError, match="1K tokens"):
        scraper.scrape(cfg(), "amazon.nova-lite-v1:0")


def test_scrape_duplicate_axis_product_raises(monkeypatch: pytest.MonkeyPatch):
    # two on-demand input rows for one model is an ambiguity to raise on,
    # never a pick

    def clone_input(data: dict) -> None:
        sku = _sku(data, "Nova Lite", "Input tokens")
        clone_sku = sku + "CLONE"
        clone = json.loads(json.dumps(data["products"][sku]))
        clone["sku"] = clone_sku
        data["products"][clone_sku] = clone
        data["terms"]["OnDemand"][clone_sku] = json.loads(
            json.dumps(data["terms"]["OnDemand"][sku])
        )

    feed(monkeypatch, index=mutated_index(clone_input))
    with pytest.raises(FetchError, match="two on-demand"):
        scraper.scrape(cfg(), "amazon.nova-lite-v1:0")


def test_scrape_unreadable_price_raises(monkeypatch: pytest.MonkeyPatch):
    def break_price(data: dict) -> None:
        dimension = _sole_dimension(data, _sku(data, "Nova Lite", "Input tokens"))
        dimension["pricePerUnit"]["USD"] = "free"

    feed(monkeypatch, index=mutated_index(break_price))
    with pytest.raises(FetchError, match="unreadable USD rate"):
        scraper.scrape(cfg(), "amazon.nova-lite-v1:0")


def test_scrape_missing_usd_price_raises(monkeypatch: pytest.MonkeyPatch):
    def drop_usd(data: dict) -> None:
        dimension = _sole_dimension(data, _sku(data, "Nova Lite", "Input tokens"))
        del dimension["pricePerUnit"]["USD"]

    feed(monkeypatch, index=mutated_index(drop_usd))
    with pytest.raises(FetchError, match="USD"):
        scraper.scrape(cfg(), "amazon.nova-lite-v1:0")


def test_scrape_negative_price_raises(monkeypatch: pytest.MonkeyPatch):
    def go_negative(data: dict) -> None:
        dimension = _sole_dimension(data, _sku(data, "Nova Lite", "Input tokens"))
        dimension["pricePerUnit"]["USD"] = "-0.00006"

    feed(monkeypatch, index=mutated_index(go_negative))
    with pytest.raises(FetchError, match="negative"):
        scraper.scrape(cfg(), "amazon.nova-lite-v1:0")


def test_scrape_divergent_effective_dates_take_the_latest(monkeypatch: pytest.MonkeyPatch):
    # an axis that changed later must never backdate the row: the row takes
    # effect when every axis it carries has

    def redate_output(data: dict) -> None:
        offers = data["terms"]["OnDemand"][_sku(data, "Nova Lite", "Output tokens")]
        next(iter(offers.values()))["effectiveDate"] = "2026-09-01T00:00:00Z"

    feed(monkeypatch, index=mutated_index(redate_output))
    pricing = scraper.scrape(cfg(), "amazon.nova-lite-v1:0")
    assert pricing is not None
    assert pricing.effective_at == "2026-09-01"


def test_scrape_unreadable_effective_date_raises(monkeypatch: pytest.MonkeyPatch):
    def break_date(data: dict) -> None:
        offers = data["terms"]["OnDemand"][_sku(data, "Nova Lite", "Input tokens")]
        next(iter(offers.values()))["effectiveDate"] = "August"

    feed(monkeypatch, index=mutated_index(break_date))
    with pytest.raises(FetchError, match="effectiveDate"):
        scraper.scrape(cfg(), "amazon.nova-lite-v1:0")


def test_scrape_product_without_on_demand_terms_raises(monkeypatch: pytest.MonkeyPatch):
    # a product matching the on-demand chat shape but carrying no terms is a
    # shape break, not an unpriced row

    def drop_terms(data: dict) -> None:
        del data["terms"]["OnDemand"][_sku(data, "Nova Lite", "Input tokens")]

    feed(monkeypatch, index=mutated_index(drop_terms))
    with pytest.raises(FetchError, match="no on-demand terms"):
        scraper.scrape(cfg(), "amazon.nova-lite-v1:0")

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_pricelog import announce
from ai_pricelog.scrapers import deepseek_page

DATA = Path(__file__).parents[1] / "data" / "catalog" / "billing-rules.json"


def make_rules(**overrides: object) -> dict:
    base: dict[str, object] = {
        "id": "deepseek-weekend-off-peak",
        "provider": "deepseek",
        "effective": "2026-08-23",
        "timezone": "Asia/Shanghai",
        "statement": "weekends bill at off-peak",
        "citation": ["https://example.com/a"],
    }
    base.update(overrides)
    return {"rules": [base]}


@pytest.fixture
def rules_file(tmp_path: Path):
    path = tmp_path / "billing-rules.json"

    def write(data: dict) -> Path:
        path.write_text(json.dumps(data) + "\n")
        return path

    return write


def test_committed_billing_rules_pass_schema():
    rules = announce.load_billing_rules(DATA)
    assert len(rules) == 27
    rule = rules[0]
    assert rule["id"] == "deepseek-weekend-off-peak"
    assert rule["provider"] == "deepseek"
    assert rule["effective"] == "2026-08-23"
    # the scraper stamps the same date on weekday-schedule rows
    assert rule["effective"] == deepseek_page._WEEKEND_RULE_EFFECTIVE
    assert rule["timezone"] == "Asia/Shanghai"
    assert "weekend" in rule["statement"].lower()
    assert len(rule["citation"]) == 4
    promo = rules[1]
    assert promo["id"] == "zai-glm-5.3-flash-promo"
    assert promo["provider"] == "zai"
    assert promo["timezone"] == "Asia/Singapore"
    uplift = rules[2]
    assert uplift["id"] == "openai-regional-processing-uplift"
    assert uplift["provider"] == "openai"
    assert uplift["effective"] == "2026-03-05"
    assert uplift["timezone"] == "UTC"
    assert "10%" in uplift["statement"]
    assert "https://platform.openai.com/docs/pricing" in uplift["citation"]
    quota = rules[4]
    assert quota["id"] == "zai-glm-quota-multipliers"
    assert quota["provider"] == "zai"
    assert quota["effective"] == "2026-07-30"
    assert quota["timezone"] == "Asia/Singapore"
    assert "not prices" in quota["statement"]
    assert "https://docs.z.ai/devpack/notice/usage-revision.md" in quota["citation"]
    moonshot = rules[5]
    assert moonshot["id"] == "moonshot-k25-v1-retirement-2026-08-31"
    assert moonshot["provider"] == "moonshot"
    assert moonshot["effective"] == "2026-08-31"
    assert "kimi-k2.5" in moonshot["statement"]
    assert "https://platform.kimi.ai/docs/platform-changelog.md" in moonshot["citation"]
    intro = rules[6]
    assert intro["id"] == "google-gemini-3.8-flash-intro-2026-09-02"
    assert intro["provider"] == "google"
    assert intro["effective"] == "2026-09-02"
    assert "2026-12-31" in intro["statement"]
    novita = rules[7]
    assert novita["id"] == "novita-multimodal-deprecation-2026-09-30"
    assert novita["provider"] == "novita"
    assert novita["effective"] == "2026-09-30"
    assert "Multimodal Model Deprecation Notice" in novita["statement"]
    do = rules[8]
    assert do["id"] == "digitalocean-model-deprecation-2026-09-08"
    assert do["provider"] == "digitalocean"
    assert do["effective"] == "2026-09-08"
    assert "Nemotron-3-Super-120B" in do["statement"]
    assert "https://docs.digitalocean.com/release-notes/" in do["citation"]
    together = rules[9]
    assert together["id"] == "together-serverless-deprecation-2026-09-14"
    assert together["provider"] == "together"
    assert together["effective"] == "2026-09-14"
    assert "gpt-oss-20b" in together["statement"]
    assert "https://docs.together.ai/docs/changelog.md" in together["citation"]
    promo_ppx = rules[10]
    assert promo_ppx["id"] == "perplexity-gemini-3.8-flash-promo-2026-09-09"
    assert promo_ppx["provider"] == "perplexity"
    assert promo_ppx["effective"] == "2026-09-09"
    assert "2026-12-31" in promo_ppx["statement"]
    assert "keys only perplexity/-prefixed Agent API catalog rows" in promo_ppx["statement"]
    assert "https://docs.perplexity.ai/docs/resources/changelog.md" in promo_ppx["citation"]
    grok_intro = rules[16]
    assert grok_intro["id"] == "xai-grok-4.7-intro-2026-09-21"
    fast_rates = "twice the standard token rates (1.5x for long-context requests)"
    assert fast_rates in grok_intro["statement"]
    openai_retire = rules[17]
    assert openai_retire["id"] == "perplexity-openai-model-retirement-2026-10-24"
    assert openai_retire["statement"].startswith("Perplexity's Agent API and Orchestrator API")
    assert "keys only perplexity/-prefixed Agent API catalog rows" in openai_retire["statement"]
    deepseek_v4 = rules[11]
    assert deepseek_v4["id"] == "deepseek-v4-retirement-2026-09-10"
    assert deepseek_v4["provider"] == "deepseek"
    assert deepseek_v4["effective"] == "2026-09-10"
    assert "deepseek-v4-pro" in deepseek_v4["statement"]
    assert "https://api-docs.deepseek.com/updates/" in deepseek_v4["citation"]
    deepseek_cont = rules[12]
    assert deepseek_cont["id"] == "deepseek-v4-pro-continuation-2026-09-12"
    assert deepseek_cont["provider"] == "deepseek"
    assert deepseek_cont["effective"] == "2026-09-12"
    assert deepseek_cont["timezone"] == "Asia/Shanghai"
    assert "billing method remaining unchanged" in deepseek_cont["statement"]
    assert "deepseek-v4-retirement-2026-09-10" in deepseek_cont["statement"]
    assert "https://api-docs.deepseek.com/updates/" in deepseek_cont["citation"]
    argon = rules[24]
    assert argon["id"] == "perplexity-gemini-4-argon-promo-2026-10-16"
    assert argon["provider"] == "perplexity"
    assert argon["effective"] == "2026-10-16"
    assert "2026-11-30" in argon["statement"]
    assert "https://docs.perplexity.ai/docs/resources/changelog.md" in argon["citation"]
    ppx_delist = rules[25]
    assert ppx_delist["id"] == "perplexity-agent-api-model-delisting-2026-10-17"
    assert ppx_delist["provider"] == "perplexity"
    assert ppx_delist["effective"] == "2026-10-17"
    assert "xai/grok-4.20-multi-agent" in ppx_delist["statement"]
    assert "https://docs.perplexity.ai/docs/resources/changelog.md" in ppx_delist["citation"]
    ds_search = rules[26]
    assert ds_search["id"] == "deepseek-search-api-billing-2026-10-17"
    assert ds_search["provider"] == "deepseek"
    assert ds_search["effective"] == "2026-10-17"
    assert ds_search["timezone"] == "Asia/Shanghai"
    assert "$0.75 per 1,000" in ds_search["statement"]
    assert "November 1, 2026" in ds_search["statement"]
    assert "https://api-docs.deepseek.com/guides/search" in ds_search["citation"]


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"bogus": "x"}, "unknown key"),
        ({"id": ""}, "non-empty string"),
        ({"effective": "2026/08/23"}, "YYYY-MM-DD"),
        ({"timezone": "Mars/Olympus"}, "unknown"),
        ({"citation": []}, "citation"),
        ({"citation": [""]}, "citation"),
    ],
)
def test_billing_rule_schema_rejections(rules_file, overrides, match):
    with pytest.raises(ValueError, match=match):
        announce.load_billing_rules(rules_file(make_rules(**overrides)))


def test_billing_rules_reject_duplicate_ids(rules_file):
    rule = make_rules()["rules"][0]
    with pytest.raises(ValueError, match="duplicate"):
        announce.load_billing_rules(rules_file({"rules": [rule, rule]}))


def test_billing_rules_missing_rules_key(rules_file):
    with pytest.raises(ValueError, match="'rules'"):
        announce.load_billing_rules(rules_file({}))


def test_billing_rules_missing_file(tmp_path):
    with pytest.raises(ValueError, match="missing"):
        announce.load_billing_rules(tmp_path / "nope.json")

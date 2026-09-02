from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_pricelog import announce
from ai_pricelog.scrapers import deepseek_page

DATA = Path(__file__).parents[1] / "data" / "billing-rules.json"


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
    assert len(rules) == 8
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

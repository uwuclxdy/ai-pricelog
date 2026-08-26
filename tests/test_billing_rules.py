import json
from pathlib import Path

import pytest

from ai_pricelog import announce

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
    assert len(rules) == 2
    rule = rules[0]
    assert rule["id"] == "deepseek-weekend-off-peak"
    assert rule["provider"] == "deepseek"
    assert rule["effective"] == "2026-08-23"
    assert rule["timezone"] == "Asia/Shanghai"
    assert "weekend" in rule["statement"].lower()
    assert len(rule["citation"]) == 4
    promo = rules[1]
    assert promo["id"] == "zai-glm-5.3-flash-promo"
    assert promo["provider"] == "zai"
    assert promo["timezone"] == "Asia/Singapore"


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

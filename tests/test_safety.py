import json
from pathlib import Path

import pytest

from mhagent.safety import (
    Risk,
    RiskResult,
    check_outbound,
    classify_rules,
    combine,
    crisis_message,
    from_phq9,
)
from mhagent.tools.scales import score_phq9

CORPUS = json.loads((Path(__file__).resolve().parent / "data" / "risk_corpus.json").read_text(encoding="utf-8"))


def _cases(level):
    return [c for c in CORPUS["cases"] if c["expected"] == level]


def test_corpus_composition():
    assert len(_cases("HIGH")) >= 25
    assert len(_cases("MEDIUM")) >= 20
    assert len(_cases("LOW")) >= 15
    assert len(CORPUS["cases"]) >= 60


def test_high_corpus_never_missed():
    missed = [c["text"] for c in _cases("HIGH") if classify_rules(c["text"]).level != Risk.HIGH]
    assert missed == [], f"HIGH 漏判: {missed}"


def test_medium_corpus_at_least_medium():
    missed = [c["text"] for c in _cases("MEDIUM") if classify_rules(c["text"]).level < Risk.MEDIUM]
    assert missed == [], f"MEDIUM 漏判: {missed}"


def test_low_corpus_false_positive_rate():
    false_positives = [c["text"] for c in _cases("LOW") if classify_rules(c["text"]).level != Risk.LOW]
    assert len(false_positives) / len(_cases("LOW")) <= 0.1, f"LOW 误判: {false_positives}"


@pytest.mark.parametrize("text", ["", "   ", None])
def test_empty_text_is_low(text):
    assert classify_rules(text).level == Risk.LOW


def test_negation_downgrades_but_not_missed():
    for text in ["我不会自杀", "我不想死,只是累了", "我从没想过自杀"]:
        result = classify_rules(text)
        assert result.level == Risk.MEDIUM


def test_third_person_is_medium():
    result = classify_rules("我朋友说他想自杀")
    assert result.level == Risk.MEDIUM
    assert any("third_party" in r for r in result.reasons)


def test_combine_takes_max():
    assert combine(Risk.LOW, Risk.MEDIUM) == Risk.MEDIUM
    assert combine(Risk.MEDIUM, Risk.HIGH, Risk.LOW) == Risk.HIGH
    assert combine(RiskResult(Risk.LOW), Risk.HIGH) == Risk.HIGH
    assert combine() == Risk.LOW


def test_phq9_item9_mapping():
    assert from_phq9(score_phq9([0] * 8 + [0])).level == Risk.LOW
    assert from_phq9(score_phq9([0] * 8 + [1])).level == Risk.MEDIUM
    assert from_phq9(score_phq9([0] * 8 + [2])).level == Risk.HIGH
    assert from_phq9(score_phq9([0] * 8 + [3])).level == Risk.HIGH


def test_crisis_message_contains_hotline():
    authorized = crisis_message(True)
    unauthorized = crisis_message(False)
    for text in (authorized, unauthorized):
        assert "12356" in text
        assert "120" in text
    assert "将通知你的紧急联系人" in authorized
    assert "请联系身边信任的人" in unauthorized
    assert "将通知你的紧急联系人" not in unauthorized


def test_outbound_blocks_method_details():
    assert check_outbound("今天天气不错").blocked is False
    for text in ["你可以尝试割腕", "具体方法是跳楼", "吃安眠药就能结束", "看看自杀教程"]:
        result = check_outbound(text)
        assert result.blocked is True
        assert result.text != text
        assert "12356" in result.text
        assert "120" in result.text


def test_reasons_do_not_leak_text():
    text = "我朋友跟我说他想自杀"
    result = classify_rules(text)
    reasons_text = " ".join(result.reasons)
    assert "我朋友" not in reasons_text
    assert "自杀" not in reasons_text
    high = classify_rules("我想死")
    assert "我想死" not in " ".join(high.reasons)

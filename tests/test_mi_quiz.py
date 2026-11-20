"""多元智能题库与计分测试。"""

from __future__ import annotations

import pytest

from mhagent.mi import QuestionBank, QuizError, normalize_answers, score_quiz


@pytest.fixture(scope="module")
def bank():
    return QuestionBank.load()


def test_question_bank_shape(bank):
    assert bank.version == "I-051"
    assert bank.labels == ["完全不符合", "比较不符合", "一半一半", "比较符合", "完全符合"]
    assert len(bank.intelligences) == 8
    assert len(bank.questions) == 80
    assert len(bank.intel_ids) == 8
    assert all(q["text"].strip() for q in bank.questions)


def test_every_indicator_has_forward_then_reverse(bank):
    for intel in bank.intelligences:
        assert len(intel["indicators"]) == 5
        for ind in intel["indicators"]:
            positive, reverse = bank.pairs(ind["id"])
            assert positive["reverse"] is False
            assert reverse["reverse"] is True
            assert reverse["id"] == positive["id"] + 1
            assert intel["id"] == positive["intelligence"]


def _answers_for(pair, positive_value, reverse_value=None):
    positive, reverse = pair
    answers = {positive: positive_value}
    if reverse_value is not None:
        answers[reverse] = reverse_value
    return answers


@pytest.mark.parametrize(
    "positive,reverse,expected",
    [
        (5, 1, 100.0),
        (4, 2, 75.0),
        (3, 3, 50.0),
        (2, 4, 25.0),
        (1, 5, 0.0),
    ],
)
def test_indicator_score_mapping(bank, positive, reverse, expected):
    pair = (1, 2)
    result = score_quiz(_answers_for(pair, positive, reverse), bank)
    assert result["indicators"]["l1"]["score"] == expected


def test_reverse_answer_is_inferred_when_forward_is_clear(bank):
    result = score_quiz({1: 4}, bank)
    item = result["indicators"]["l1"]
    assert item["inferred"] is True
    assert item["reverse"] == 2
    assert item["score"] == 75.0
    assert result["done_items"] == 1


def test_neutral_forward_requires_both_answers(bank):
    result = score_quiz({1: 3}, bank)
    assert result["indicators"]["l1"]["score"] is None
    assert result["done_items"] == 0

    result = score_quiz({1: 3, 2: 3}, bank)
    assert result["indicators"]["l1"]["score"] == 50.0
    assert result["done_items"] == 1


def test_reverse_only_is_not_scored(bank):
    result = score_quiz({2: 1}, bank)
    assert result["indicators"]["l1"]["done"] is False


def test_valid_threshold_is_ten_items(bank):
    pairs = [(q["id"], q["id"] + 1) for q in bank.questions if not q["reverse"]]
    nine = {}
    for positive, _ in pairs[:9]:
        nine[positive] = 4
    assert score_quiz(nine, bank)["valid"] is False

    ten = dict(nine)
    ten[pairs[9][0]] = 4
    result = score_quiz(ten, bank)
    assert result["done_items"] == 10
    assert result["valid"] is True


def test_intelligence_score_is_group_average(bank):
    answers = {}
    for qid in range(1, 11):
        answers[qid] = 5 if qid % 2 else 1
    result = score_quiz(answers, bank)
    assert result["intelligences"]["lang"]["score"] == 100.0
    assert result["intelligences"]["logic"]["score"] is None


def test_normalize_answers_drops_invalid_values():
    assert normalize_answers({"1": 5, "2": 0, "3": 9, "x": 4, "4": "3"}) == {1: 5, 4: 3}
    assert normalize_answers(None) == {}
    assert normalize_answers([]) == {}


def test_unknown_question_raises(bank):
    with pytest.raises(QuizError):
        bank.question(999)
    with pytest.raises(QuizError):
        bank.indicator("zz9")

"""多元智能三源融合（FUSION-1.0）测试。"""

from __future__ import annotations

import pytest

from mhagent.mi import QuestionBank, QuizError, fuse_scores, score_quiz
from mhagent.mi.fusion import indicator_target, intel_target


@pytest.fixture(scope="module")
def bank():
    return QuestionBank.load()


def _rankings(bank):
    return {
        "intel_rank": list(bank.intel_ids),
        "ind_rank": {
            item["id"]: [ind["id"] for ind in item["indicators"]]
            for item in bank.intelligences
        },
    }


def _quiz(bank, value: int = 4):
    answers = {
        q["id"]: (6 - value if q["reverse"] else value) for q in bank.questions
    }
    return score_quiz(answers, bank)


def test_targets_match_document():
    assert [intel_target(rank) for rank in range(1, 9)] == [
        72.5, 67.5, 62.5, 57.5, 52.5, 47.5, 42.5, 37.5
    ]
    assert [indicator_target(rank) for rank in range(1, 6)] == [75, 65, 55, 45, 35]
    with pytest.raises(QuizError):
        intel_target(0)
    with pytest.raises(QuizError):
        indicator_target(6)


def test_no_gene_fusion_matches_manual_formula(bank):
    quiz = _quiz(bank, value=3)  # 全部指标 50 分
    result = fuse_scores(quiz, **_rankings(bank), gene=None, bank=bank)
    # 组内第 1 名：0.4*50 + 0.6*75 = 65；依此类推
    assert result["ind"]["l1"]["inner"] == 65.0
    assert result["ind"]["l5"]["inner"] == 41.0
    # inner 均值 53，向 72.5 靠拢 0.5：(72.5-53)*0.5 = 9.75
    assert result["ind"]["l1"]["score"] == 75
    assert result["ind"]["l5"]["score"] == 51
    assert result["intel"]["lang"]["score"] == 63
    assert result["intel"]["lang"]["rank"] == 1
    assert result["gene_used"] is False


def test_gene_fusion_uses_65_35_weights(bank):
    quiz = _quiz(bank, value=3)
    gene = {"scores": {iid: 80 for iid in bank.intel_ids}, "confidence": "high"}
    result = fuse_scores(quiz, **_rankings(bank), gene=gene, bank=bank)
    # 0.65*80 + 0.35*53 = 70.55
    assert result["intel"]["lang"]["score"] == 71
    assert result["ind"]["l1"]["score"] == round(65 + (70.55 - 53))
    assert result["gene_used"] is True


def test_exempt_indicators_keep_quiz_score(bank):
    answers = {q["id"]: 5 for q in bank.questions if not q["reverse"]}
    answers.update({q["id"]: 1 for q in bank.questions if q["reverse"]})
    quiz = score_quiz(answers, bank)
    assert quiz["indicators"]["l1"]["score"] == 100.0

    result = fuse_scores(quiz, **_rankings(bank), bank=bank)
    assert result["ind"]["l1"]["score"] == 100
    assert result["ind"]["l1"]["inner"] == 100.0
    # 其余指标问卷分均为 100，也全部豁免
    assert result["ind"]["l5"]["score"] == 100
    assert 0 <= result["intel"]["lang"]["score"] <= 100


def test_scores_are_clamped(bank):
    quiz = _quiz(bank, value=5)
    gene = {"scores": {iid: 100 for iid in bank.intel_ids}}
    result = fuse_scores(quiz, **_rankings(bank), gene=gene, bank=bank)
    assert all(0 <= item["score"] <= 100 for item in result["intel"].values())
    assert all(0 <= item["score"] <= 100 for item in result["ind"].values())


def test_ranking_must_cover_all_items(bank):
    quiz = _quiz(bank, value=4)
    rankings = _rankings(bank)
    with pytest.raises(QuizError):
        fuse_scores(quiz, rankings["intel_rank"][:7], rankings["ind_rank"], bank=bank)

    broken = dict(rankings["ind_rank"])
    broken["lang"] = broken["lang"][:4]
    with pytest.raises(QuizError):
        fuse_scores(quiz, rankings["intel_rank"], broken, bank=bank)


def test_incomplete_quiz_rejected(bank):
    quiz = score_quiz({1: 5}, bank)
    with pytest.raises(QuizError):
        fuse_scores(quiz, **_rankings(bank), bank=bank)


def test_ranking_orders_are_respected(bank):
    quiz = _quiz(bank, value=3)
    rankings = _rankings(bank)
    reversed_intel = list(reversed(bank.intel_ids))
    reversed_ind = {
        iid: list(reversed(order)) for iid, order in rankings["ind_rank"].items()
    }
    result = fuse_scores(quiz, reversed_intel, reversed_ind, bank=bank)
    # 语言被排到最后：组内目标均值不变，但整组位移会向 37.5 靠拢。
    assert result["intel"]["lang"]["rank"] == 8
    assert result["intel"]["lang"]["score"] < 53
    assert result["intel"]["inner"]["score"] > result["intel"]["lang"]["score"]

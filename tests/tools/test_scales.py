import pytest

from mhagent.tools.scales import score_gad7, score_phq9, score_pss10, ScaleError


@pytest.mark.parametrize(
    "answers,total,level",
    [
        ([0] * 9, 0, "minimal"),
        ([1, 1, 1, 1, 0, 0, 0, 0, 0], 4, "minimal"),
        ([1, 1, 1, 1, 1, 0, 0, 0, 0], 5, "mild"),
        ([1] * 9, 9, "mild"),
        ([2, 2, 1, 1, 1, 1, 1, 1, 0], 10, "moderate"),
        ([2] * 7 + [1, 0], 15, "moderately_severe"),
        ([3] * 9, 27, "severe"),
    ],
)
def test_phq9_levels(answers, total, level):
    r = score_phq9(answers)
    assert (r.total, r.level) == (total, level)


def test_phq9_item9_flag():
    assert score_phq9([0] * 8 + [1]).item9_positive is True
    assert score_phq9([3] * 8 + [0]).item9_positive is False
    assert score_phq9([0] * 8 + [3]).item9_score == 3


@pytest.mark.parametrize(
    "answers,total,level",
    [
        ([0] * 7, 0, "minimal"),
        ([1] * 5 + [0, 0], 5, "mild"),
        ([2] * 5 + [0, 0], 10, "moderate"),
        ([3] * 7, 21, "severe"),
    ],
)
def test_gad7_levels(answers, total, level):
    r = score_gad7(answers)
    assert (r.total, r.level) == (total, level)


def test_pss10_reverse_items():
    # 全部答 0:正向题 0,反向题(4,5,7,8)各得 4 => 16
    assert score_pss10([0] * 10).total == 16
    # 全部答 4:正向题 4*6=24,反向题 0 => 24
    assert score_pss10([4] * 10).total == 24


def test_pss10_levels():
    assert score_pss10([0, 0, 0, 4, 4, 0, 4, 4, 0, 0]).level == "low"  # 0
    assert score_pss10([4, 4, 4, 0, 0, 4, 0, 0, 4, 4]).level == "high"  # 40
    assert score_pss10([2] * 10).total == 20 and score_pss10([2] * 10).level == "moderate"


@pytest.mark.parametrize("fn,n", [(score_phq9, 9), (score_gad7, 7), (score_pss10, 10)])
def test_invalid_input(fn, n):
    with pytest.raises(ScaleError):
        fn([0] * (n - 1))
    with pytest.raises(ScaleError):
        fn([9] * n)
    with pytest.raises(ScaleError):
        fn(["a"] * n)
    with pytest.raises(ScaleError):
        fn([True] * n)

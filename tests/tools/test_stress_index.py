import pytest

from mhagent.tools.stress_index import stress_index


def test_pss_only():
    r = stress_index(pss_total=20, recent_negative_intensities=[])
    assert r.value == 50 and r.band == "medium" and r.used_journal is False


def test_with_journal():
    # pss_norm=50, journal_norm=80 => 0.7*50+0.3*80 = 59
    r = stress_index(20, [8, 8, 8])
    assert r.value == 59 and r.used_journal is True


def test_bounds():
    assert stress_index(0, []).value == 0
    assert stress_index(40, [10]).value == 100
    assert stress_index(40, [10]).band == "high"


def test_band_edges():
    # 32.5 必须四舍五入为 33(不能用银行家舍入得到 32)
    assert stress_index(13, []).value == 33
    assert stress_index(13, []).band == "low"
    assert stress_index(14, []).band == "medium"
    # 67.5 必须四舍五入为 68
    assert stress_index(27, []).value == 68
    assert stress_index(27, []).band == "high"


def test_rounding_half_up():
    assert stress_index(1, []).value == 3  # 2.5 -> 3
    assert stress_index(3, []).value == 8  # 7.5 -> 8


def test_invalid():
    with pytest.raises(ValueError):
        stress_index(41, [])
    with pytest.raises(ValueError):
        stress_index(-1, [])
    with pytest.raises(ValueError):
        stress_index(10, [11])
    with pytest.raises(ValueError):
        stress_index(10, [-1])
    with pytest.raises(ValueError):
        stress_index("10", [])


def test_used_journal_flag():
    assert stress_index(10, []).used_journal is False
    assert stress_index(10, [5]).used_journal is True

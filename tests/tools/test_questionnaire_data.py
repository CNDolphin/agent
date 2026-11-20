import pytest

from mhagent.tools.scales import ScaleError, load_questionnaire


def test_phq9_data():
    q = load_questionnaire("phq9")
    assert len(q.items) == 9
    assert [o["value"] for o in q.options] == [0, 1, 2, 3]
    assert q.available is True
    assert q.version == "1"


def test_gad7_data():
    q = load_questionnaire("gad7")
    assert len(q.items) == 7
    assert [o["value"] for o in q.options] == [0, 1, 2, 3]
    assert q.available is True


def test_pss10_unavailable_until_authorized():
    q = load_questionnaire("pss10")
    assert q.items == ()
    assert q.available is False


def test_unknown_scale():
    with pytest.raises(ScaleError):
        load_questionnaire("unknown")

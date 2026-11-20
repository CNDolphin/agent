from datetime import datetime, timezone

import pytest

from mhagent.store.db import LocalStore
from mhagent.tools.journal import Journal, JournalError

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def journal(tmp_path):
    store = LocalStore(tmp_path, "pw")
    yield Journal(store, now=lambda: NOW)
    store.close()


def _entry(day="2026-11-06", intensity=7, name="焦虑"):
    return {
        "date": day,
        "event": "开会时被打断",
        "emotions": [{"name": name, "intensity": intensity}],
        "thoughts": "我觉得自己很没用",
        "note": "",
    }


def test_add_entry_validates(journal):
    with pytest.raises(JournalError):
        journal.add_entry({"date": "2026-11-06", "event": "", "emotions": []})
    with pytest.raises(JournalError):
        journal.add_entry(_entry(intensity=11))
    with pytest.raises(JournalError):
        journal.add_entry(_entry(intensity="7"))
    with pytest.raises(JournalError):
        journal.add_entry(_entry(name=""))
    with pytest.raises(JournalError):
        journal.add_entry({**_entry(), "date": "not-a-date"})
    assert journal.add_entry(_entry()) >= 1


def test_recent_negative_intensities(journal):
    journal.add_entry(_entry(day="2026-11-06", intensity=8, name="焦虑"))
    journal.add_entry(_entry(day="2026-11-05", intensity=4, name="悲伤"))
    journal.add_entry(_entry(day="2026-11-05", intensity=6, name="开心"))  # 非消极,不计入
    journal.add_entry(_entry(day="2026-10-20", intensity=9, name="焦虑"))  # 超出 14 天窗口
    assert journal.recent_negative_intensities(days=14) == [4, 8]


def test_weekly_review(journal):
    journal.add_entry(_entry(day="2026-11-02", intensity=6, name="焦虑"))
    journal.add_entry(_entry(day="2026-11-04", intensity=8, name="焦虑"))
    journal.add_entry(_entry(day="2026-11-04", intensity=4, name="疲惫"))
    review = journal.weekly_review("2026-11-02")
    assert review["count"] == 3
    assert review["top_emotions"][0] == {"name": "焦虑", "count": 2}
    assert review["avg_intensity"] == 6.0
    assert review["prev_week_avg_intensity"] is None
    assert review["change"] is None


def test_weekly_review_change(journal):
    journal.add_entry(_entry(day="2026-10-28", intensity=3))
    journal.add_entry(_entry(day="2026-11-03", intensity=7))
    review = journal.weekly_review("2026-11-02")
    assert review["prev_week_avg_intensity"] == 3.0
    assert review["change"] == 4.0


def test_weekly_review_empty(journal):
    assert journal.weekly_review("2026-11-02") is None

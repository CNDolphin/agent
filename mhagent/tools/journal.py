"""情绪日记与周回顾。

条目结构:`{date, event, emotions: [{name, intensity 0-10}], thoughts, note}`。
只存用户明确要记录的内容,落盘为密文。
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

RECORD_KIND = "journal"

# 消极情绪名单(配置),用于给压力指数提供输入
NEGATIVE_EMOTIONS = frozenset(
    {
        "焦虑",
        "悲伤",
        "愤怒",
        "内疚",
        "恐惧",
        "孤独",
        "无助",
        "沮丧",
        "难过",
        "担心",
        "烦躁",
        "压力",
        "羞耻",
        "失落",
    }
)


class JournalError(ValueError):
    """日记数据非法。"""


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError as exc:
            raise JournalError(f"日期格式错误: {value}") from exc
    raise JournalError("日期缺失或格式错误")


def _as_dt(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        dt = datetime.fromisoformat(value)
    else:
        raise JournalError("时间格式错误")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _validate_entry(entry: dict) -> dict:
    if not isinstance(entry, dict):
        raise JournalError("entry 必须是字典")
    entry_date = _as_date(entry.get("date"))
    event = entry.get("event")
    if not isinstance(event, str) or not event.strip():
        raise JournalError("事件(event)不能为空")
    emotions = entry.get("emotions")
    if not isinstance(emotions, (list, tuple)) or not emotions:
        raise JournalError("至少记录一种情绪")
    normalized_emotions = []
    for item in emotions:
        if not isinstance(item, dict):
            raise JournalError("情绪项必须是字典")
        name = item.get("name")
        intensity = item.get("intensity")
        if not isinstance(name, str) or not name.strip():
            raise JournalError("情绪名称不能为空")
        if isinstance(intensity, bool) or not isinstance(intensity, int) or not 0 <= intensity <= 10:
            raise JournalError("情绪强度必须是 0-10 的整数")
        normalized_emotions.append({"name": name.strip(), "intensity": intensity})
    thoughts = entry.get("thoughts", "")
    note = entry.get("note", "")
    for field_name, value in (("thoughts", thoughts), ("note", note)):
        if value is not None and not isinstance(value, str):
            raise JournalError(f"{field_name} 必须是字符串")
    return {
        "date": entry_date.isoformat(),
        "event": event.strip(),
        "emotions": normalized_emotions,
        "thoughts": (thoughts or "").strip(),
        "note": (note or "").strip(),
    }


class Journal:
    """日记读写;`now` 可注入,测试不依赖系统时间。"""

    def __init__(self, store, *, negative_emotions=None, now=None):
        self.store = store
        self.negative_emotions = frozenset(negative_emotions) if negative_emotions else NEGATIVE_EMOTIONS
        self._now = now or (lambda: datetime.now(timezone.utc))

    def now(self) -> datetime:
        return _as_dt(self._now())

    def add_entry(self, entry: dict, *, created_at=None) -> int:
        normalized = _validate_entry(entry)
        created = created_at or f"{normalized['date']}T00:00:00+00:00"
        return self.store.add_record(RECORD_KIND, normalized, created_at=created)

    def _entries(self) -> list[dict]:
        return [r["payload"] for r in self.store.list_records(kind=RECORD_KIND)]

    def recent_negative_intensities(self, days: int = 14, now=None) -> list[int]:
        """返回近 N 天内消极情绪强度列表,供压力指数使用。"""
        if not isinstance(days, int) or days <= 0:
            raise JournalError("days 必须是正整数")
        current = _as_dt(now) if now is not None else self.now()
        start_date = (current - timedelta(days=days - 1)).date()
        end_date = current.date()
        result: list[int] = []
        for entry in sorted(self._entries(), key=lambda e: e["date"]):
            entry_date = _as_date(entry["date"])
            if not start_date <= entry_date <= end_date:
                continue
            for emotion in entry["emotions"]:
                if emotion["name"] in self.negative_emotions:
                    result.append(int(emotion["intensity"]))
        return result

    def weekly_review(self, week_start, now=None) -> dict | None:
        start = _as_date(week_start)
        end = start + timedelta(days=7)
        entries = [e for e in self._entries() if start.isoformat() <= e["date"] < end.isoformat()]
        if not entries:
            return None
        counter: Counter = Counter()
        intensities: list[int] = []
        for entry in entries:
            for emotion in entry["emotions"]:
                counter[emotion["name"]] += 1
                intensities.append(int(emotion["intensity"]))
        prev_start = start - timedelta(days=7)
        prev_entries = [e for e in self._entries() if prev_start.isoformat() <= e["date"] < start.isoformat()]
        prev_intensities = [
            int(emotion["intensity"]) for entry in prev_entries for emotion in entry["emotions"]
        ]
        avg = sum(intensities) / len(intensities)
        prev_avg = sum(prev_intensities) / len(prev_intensities) if prev_intensities else None
        top = counter.most_common(3)
        return {
            "week_start": start.isoformat(),
            "week_end": (end - timedelta(days=1)).isoformat(),
            "count": len(entries),
            "top_emotions": [{"name": name, "count": count} for name, count in top],
            "avg_intensity": round(avg, 2),
            "prev_week_avg_intensity": round(prev_avg, 2) if prev_avg is not None else None,
            "change": round(avg - prev_avg, 2) if prev_avg is not None else None,
        }

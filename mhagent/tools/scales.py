"""量表计分与分级(纯函数)。

所有量表分数与等级都由本模块确定性计算,模型不得参与计算或改写等级。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from mhagent import content_paths

DATA_DIR = Path(__file__).resolve().parent / "data"


class ScaleError(ValueError):
    """量表答案非法。"""


@dataclass(frozen=True)
class ScaleResult:
    scale: str
    total: int
    max_total: int
    level: str
    item9_positive: bool = False  # 仅 PHQ-9 使用
    item9_score: int = 0  # 仅 PHQ-9 使用:第 9 题原始分值 0-3


@dataclass(frozen=True)
class Questionnaire:
    scale: str
    version: str
    intro: str
    options: tuple[dict, ...]
    items: tuple[str, ...]
    available: bool

    def option_value(self, label: str) -> int | None:
        """按选项文案取分值,取不到返回 None。"""
        label = str(label).strip()
        for opt in self.options:
            if str(opt.get("label", "").strip()) == label:
                return int(opt["value"])
        return None


def _validate(answers, n: int, lo: int, hi: int) -> None:
    if not isinstance(answers, (list, tuple)) or len(answers) != n:
        raise ScaleError(f"expected {n} answers")
    for a in answers:
        if isinstance(a, bool) or not isinstance(a, int) or not lo <= a <= hi:
            raise ScaleError(f"answer must be int in [{lo},{hi}]")


def _level(total: int, bands) -> str:
    for upper, name in bands:
        if total <= upper:
            return name
    raise ScaleError("total out of range")


_PHQ9 = [(4, "minimal"), (9, "mild"), (14, "moderate"), (19, "moderately_severe"), (27, "severe")]
_GAD7 = [(4, "minimal"), (9, "mild"), (14, "moderate"), (21, "severe")]
_PSS10 = [(13, "low"), (26, "moderate"), (40, "high")]
# 0 起算的下标,对应第 4、5、7、8 题(1 起算),需要反向计分
_PSS_REVERSE = {3, 4, 6, 7}


def score_phq9(answers) -> ScaleResult:
    _validate(answers, 9, 0, 3)
    total = sum(answers)
    return ScaleResult(
        "phq9",
        total,
        27,
        _level(total, _PHQ9),
        item9_positive=answers[8] > 0,
        item9_score=answers[8],
    )


def score_gad7(answers) -> ScaleResult:
    _validate(answers, 7, 0, 3)
    total = sum(answers)
    return ScaleResult("gad7", total, 21, _level(total, _GAD7))


def score_pss10(answers) -> ScaleResult:
    _validate(answers, 10, 0, 4)
    total = sum(4 - a if i in _PSS_REVERSE else a for i, a in enumerate(answers))
    return ScaleResult("pss10", total, 40, _level(total, _PSS10))


def load_questionnaire(scale: str) -> Questionnaire:
    """加载题库数据文件。

    PSS-10 的题目文本商用授权尚未确认,因此 `items` 为空且 `available=False`。
    """
    path = content_paths.resolve("scales", f"{scale}.json", DATA_DIR / f"{scale}.json")
    if not path.exists():
        raise ScaleError(f"unknown scale: {scale}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = tuple(str(x) for x in raw.get("items", []))
    # 题目文本缺失时该量表不可用
    available = bool(items) and bool(raw.get("available", True))
    return Questionnaire(
        scale=str(raw.get("scale", scale)),
        version=str(raw.get("version", "1")),
        intro=str(raw.get("intro", "")),
        options=tuple(raw.get("options", [])),
        items=items,
        available=available,
    )


LEVEL_LABELS = {
    "minimal": "极轻微",
    "mild": "轻度",
    "moderate": "中度",
    "moderately_severe": "中重度",
    "severe": "重度",
    "low": "较低",
    "high": "较高",
}

SCALE_NAMES = {
    "phq9": "PHQ-9 抑郁筛查",
    "gad7": "GAD-7 焦虑筛查",
    "pss10": "PSS-10 压力感知量表",
}

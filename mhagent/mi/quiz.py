"""多元智能自测问卷：题库加载与计分。

题库来自 `mhagent/data/mi_quiz.json`（I-051，8 智能 × 5 指标 × 2 题 = 80 题）。
每项指标由一正一反两题组成，反向题得分 = 6 - 原始作答；
合并得分 2–10 线性映射到 0–100：((正 + (6-反)) - 2) / 8 * 100。
"""

from __future__ import annotations

import json
from pathlib import Path

from mhagent import content_paths

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "mi_quiz.json"
VALID_ANSWERS = (1, 2, 3, 4, 5)
# 正向题选择这些档位时，反向题按 6-答案 推定，不要求作答
INFERABLE_ANSWERS = (1, 2, 4, 5)
VALID_ITEM_THRESHOLD = 10


class QuizError(ValueError):
    """题库缺失或作答数据不合法。"""


def _combine(positive: int, reverse: int) -> int:
    """合并得分：两项都指向同一倾向时为 2–10。"""
    return positive + (6 - reverse)


def _to_percent(combined: int) -> float:
    return (combined - 2) / 8 * 100


class QuestionBank:
    """不可变题库，提供题目、指标与智能的索引。"""

    def __init__(self, payload: dict):
        self.version = str(payload.get("version") or "")
        scale = payload.get("scale") or {}
        self.scale_min = int(scale.get("min", 1))
        self.scale_max = int(scale.get("max", 5))
        self.labels = list(scale.get("labels") or [])
        self.intelligences = [
            {
                "id": str(item["id"]),
                "name": str(item["name"]),
                "indicators": [
                    {
                        "id": str(ind["id"]),
                        "name": str(ind["name"]),
                        "definition": str(ind.get("definition") or ""),
                    }
                    for ind in item.get("indicators", [])
                ],
            }
            for item in payload.get("intelligences", [])
        ]
        self.questions = [
            {
                "id": int(item["id"]),
                "indicator": str(item["indicator"]),
                "intelligence": str(item["intelligence"]),
                "reverse": bool(item.get("reverse")),
                "text": str(item.get("text") or ""),
            }
            for item in sorted(payload.get("questions", []), key=lambda q: int(q["id"]))
        ]
        self._question_map = {item["id"]: item for item in self.questions}
        self._indicator_map = {
            ind["id"]: {**ind, "intelligence": item["id"], "intelligence_name": item["name"]}
            for item in self.intelligences
            for ind in item["indicators"]
        }
        self.intel_ids = [item["id"] for item in self.intelligences]
        if len(self.intel_ids) != 8 or len(self._indicator_map) != 40 or len(self.questions) != 80:
            raise QuizError("题库结构不完整：需要 8 智能 / 40 指标 / 80 题")

    @classmethod
    def load(cls, path=None) -> "QuestionBank":
        target = Path(path) if path else content_paths.resolve("quiz", "mi_quiz.json", DATA_PATH)
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise QuizError(f"题库文件不存在：{target}") from exc
        except json.JSONDecodeError as exc:
            raise QuizError("题库文件不是合法 JSON") from exc
        return cls(payload)

    # ---- 查询 ----
    def indicator(self, indicator_id: str) -> dict:
        try:
            return dict(self._indicator_map[indicator_id])
        except KeyError as exc:
            raise QuizError(f"未知指标：{indicator_id}") from exc

    def question(self, question_id: int) -> dict:
        try:
            return dict(self._question_map[int(question_id)])
        except (KeyError, TypeError, ValueError) as exc:
            raise QuizError(f"未知题目：{question_id}") from exc

    def indicator_ids(self, intelligence_id: str) -> list[str]:
        for item in self.intelligences:
            if item["id"] == intelligence_id:
                return [ind["id"] for ind in item["indicators"]]
        raise QuizError(f"未知智能：{intelligence_id}")

    def pairs(self, indicator_id: str) -> tuple[dict, dict]:
        """返回该指标的正向题与反向题。"""
        items = [q for q in self.questions if q["indicator"] == indicator_id]
        positive = next((q for q in items if not q["reverse"]), None)
        reverse = next((q for q in items if q["reverse"]), None)
        if positive is None or reverse is None:
            raise QuizError(f"指标 {indicator_id} 缺少正向或反向题")
        return positive, reverse


def normalize_answers(raw) -> dict[int, int]:
    """把外部作答统一成 {题号: 1–5}，非法值直接丢弃。"""
    result: dict[int, int] = {}
    if not isinstance(raw, dict):
        return result
    for key, value in raw.items():
        try:
            qid = int(key)
            score = int(value)
        except (TypeError, ValueError):
            continue
        if qid in VALID_RANGE and score in VALID_ANSWERS:
            result[qid] = score
    return result


VALID_RANGE = frozenset(range(1, 81))


def score_quiz(answers, bank: QuestionBank | None = None, *, infer_reverse: bool = True) -> dict:
    """按指标计分。

    返回 `{indicators, intelligences, done_items, answered_questions, valid}`：
    - `indicators[ind]["score"]` 为 None 表示该指标尚未答完；
    - `done_items` 是答完的指标数，`valid` 表示是否达到 10 项有效门槛。
    """
    bank = bank or QuestionBank.load()
    data = normalize_answers(answers)
    indicators: dict[str, dict] = {}
    intelligences: dict[str, dict] = {}

    for intel in bank.intelligences:
        iid = intel["id"]
        scores: list[float] = []
        for ind in intel["indicators"]:
            ind_id = ind["id"]
            positive, reverse = bank.pairs(ind_id)
            pos_value = data.get(positive["id"])
            rev_value = data.get(reverse["id"])
            inferred = False
            if infer_reverse and pos_value in INFERABLE_ANSWERS:
                rev_value = 6 - pos_value
                inferred = True
            score = None
            if pos_value is not None and rev_value is not None:
                score = round(_to_percent(_combine(pos_value, rev_value)), 2)
                scores.append(score)
            indicators[ind_id] = {
                "id": ind_id,
                "name": ind["name"],
                "intelligence": iid,
                "intelligence_name": intel["name"],
                "score": score,
                "forward": pos_value,
                "reverse": rev_value,
                "inferred": inferred,
                "done": score is not None,
            }
        intelligences[iid] = {
            "id": iid,
            "name": intel["name"],
            "score": round(sum(scores) / len(scores), 2) if scores else None,
            "done_items": len(scores),
        }

    done_items = sum(1 for item in indicators.values() if item["done"])
    return {
        "indicators": indicators,
        "intelligences": intelligences,
        "done_items": done_items,
        "answered_questions": len(
            [qid for qid in data if 1 <= qid <= 80]
        ),
        "valid": done_items >= VALID_ITEM_THRESHOLD,
    }

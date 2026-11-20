"""安全层:风险分级、危机话术与出站检查。

安全层是最高优先级:
- 每轮用户消息先经过 `classify_rules`,规则命中 HIGH 时立即输出危机话术,
  不调用网关,也不等待模型复核。
- 否定句、过去时、他人话题会降级为 MEDIUM,但不能漏判。
- `RiskResult.reasons` 只保存规则名,绝不包含用户原文。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import IntEnum
from functools import lru_cache
from pathlib import Path

from mhagent import content_paths

RULES_PATH = Path(__file__).resolve().parent / "data" / "risk_rules.json"


class Risk(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2


@dataclass(frozen=True)
class RiskResult:
    level: Risk
    reasons: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def _rules() -> dict:
    path = content_paths.resolve("rules", "risk_rules.json", RULES_PATH)
    return json.loads(path.read_text(encoding="utf-8"))


def reload_rules() -> None:
    """内容更新后清理规则缓存,使新规则立即生效。"""
    _rules.cache_clear()


def _to_risk(value) -> Risk:
    if isinstance(value, Risk):
        return value
    if isinstance(value, RiskResult):
        return value.level
    if isinstance(value, str):
        return {"LOW": Risk.LOW, "MEDIUM": Risk.MEDIUM, "HIGH": Risk.HIGH}[value.upper()]
    return Risk(int(value))


def combine(*levels) -> Risk:
    """取最高风险级别。"""
    result = Risk.LOW
    for level in levels:
        result = max(result, _to_risk(level))
    return result


def _window(text: str, start: int, end: int, before: int = 12, after: int = 12) -> str:
    return text[max(0, start - before):min(len(text), end + after)]


def _has_any(haystack: str, needles) -> str | None:
    for needle in needles:
        if needle and needle in haystack:
            return needle
    return None


def _is_miss_you(text: str, match: re.Match) -> bool:
    """区分「我想死你了」这类想念的口语表达。"""
    if not match.group(0).startswith("想死"):
        return False
    suffix = text[match.end():match.end() + 2]
    return any(suffix.startswith(s) for s in _rules()["miss_you_suffix"])


def classify_rules(text: str) -> RiskResult:
    """只用规则判定风险等级;命中的规则名写入 reasons。"""
    if not text or not isinstance(text, str):
        return RiskResult(Risk.LOW, [])
    lowered = text.lower()
    reasons: list[str] = []
    medium_hit = False

    for rule in _rules()["high"]:
        for pattern in rule["patterns"]:
            if pattern.isascii():
                matches = [m for m in re.finditer(pattern, lowered)]
            else:
                matches = [m for m in re.finditer(pattern, text)]
            for match in matches:
                if _is_miss_you(text, match):
                    continue
                around = _window(text, match.start(), match.end())
                topic = _has_any(around, _rules()["topic_cues"])
                if topic:
                    # 新闻、科普、影视等话题语境,不作为个人风险信号
                    continue
                negated = _has_any(
                    text[max(0, match.start() - 14):match.end() + 4],
                    _rules()["negated_patterns"],
                )
                if negated:
                    medium_hit = True
                    reasons.append(f"{rule['name']}:negated")
                    continue
                past = _has_any(text[max(0, match.start() - 14):match.start()], _rules()["past_cues"])
                recovered = _has_any(text[match.end():match.end() + 20], _rules()["past_recovery_cues"])
                if past or recovered:
                    medium_hit = True
                    reasons.append(f"{rule['name']}:past")
                    continue
                third_party = _has_any(
                    text[max(0, match.start() - 14):match.start()],
                    _rules()["third_party_cues"],
                )
                if third_party:
                    medium_hit = True
                    reasons.append(f"{rule['name']}:third_party")
                    continue
                return RiskResult(Risk.HIGH, [rule["name"]])

    for rule in _rules()["medium"]:
        for pattern in rule["patterns"]:
            if pattern.isascii():
                hit = re.search(pattern, lowered)
            else:
                hit = re.search(pattern, text)
            if hit:
                medium_hit = True
                reasons.append(rule["name"])
                break

    if medium_hit:
        return RiskResult(Risk.MEDIUM, reasons)
    return RiskResult(Risk.LOW, [])


def _field(obj, key, default=0):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def from_phq9(result) -> RiskResult:
    """PHQ-9 第 9 题映射:0→LOW,1→MEDIUM,HIGH 候选为 2/3。"""
    score = int(_field(result, "item9_score", 0) or 0)
    positive = bool(_field(result, "item9_positive", False))
    if score >= 2:
        return RiskResult(Risk.HIGH, ["phq9_item9_high"])
    if score == 1 or positive:
        return RiskResult(Risk.MEDIUM, ["phq9_item9_positive"])
    return RiskResult(Risk.LOW, [])


_CRISIS_BASE = (
    "我听到了你现在的痛苦,这很重要,也很紧急。你的安全是第一位的。\n"
    "请现在就做下面几件事:\n"
    "1. 立刻联系身边信任的人,请对方陪着你;\n"
    "2. 拨打心理援助热线 12356(24 小时),情况紧急时拨打急救电话 120;\n"
    "3. 如果手边有可以伤害自己的物品,请先把它放到远处,或交给别人保管。\n"
    "我不会给你做评估或练习,只在这里陪你。"
)

_CRISIS_AUTHORIZED = (
    "按你之前的授权,我将通知你的紧急联系人,请对方尽快联系你。"
)

_CRISIS_UNAUTHORIZED = (
    "请联系身边信任的人,也可以把这段话直接发给对方:「我现在状态很不好,"
    "需要你陪着我。如果联系不上我,请帮我拨打 12356 或 120。」"
)


def crisis_message(authorized_contact: bool) -> str:
    """固定危机话术,本地生成,不依赖网关。"""
    tail = _CRISIS_AUTHORIZED if authorized_contact else _CRISIS_UNAUTHORIZED
    return f"{_CRISIS_BASE}\n{tail}"


SAFE_REPLACEMENT = (
    "我不能提供任何具体的方式或细节,这可能会带来危险。\n"
    "如果你现在有伤害自己的念头,请立即拨打心理援助热线 12356 或急救电话 120,"
    "也可以前往就近的急诊,或请身边信任的人陪着你。"
)


@dataclass(frozen=True)
class OutboundCheck:
    blocked: bool
    text: str
    reasons: list[str] = field(default_factory=list)


def check_outbound(text: str) -> OutboundCheck:
    """检查模型输出是否包含具体自伤方法细节;命中则替换为安全文本。"""
    if not text:
        return OutboundCheck(False, text, [])
    lowered = text.lower()
    hits = [kw for kw in _rules()["method_keywords"] if kw in lowered]
    if hits:
        return OutboundCheck(True, SAFE_REPLACEMENT, ["outbound_method_detail"])
    return OutboundCheck(False, text, [])

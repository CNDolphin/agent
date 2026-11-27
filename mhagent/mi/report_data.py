"""解读报告静态文案数据加载。

数据来自交付包 `agent_data1.js` / `agent_data2.js` 导出的 JSON，
包含八大智能、40 项指标、块状分析、相似辨析、对角线、学习五到、
才艺 / 专业 / 职业 / 课程 / 行为对照、敏感期与左右脑描述。
"""

from __future__ import annotations

import json
from pathlib import Path

from mhagent import content_paths

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "mi_report.json"


def load() -> dict:
    """读取报告文案数据，优先使用在线更新的内容包。"""
    target = content_paths.resolve("quiz", "mi_report.json", DATA_PATH)
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"解读报告数据不存在：{target}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("解读报告数据不是合法 JSON") from exc


_DATA = load()

INTEL = _DATA["INTEL"]
IND = _DATA["IND"]
INTEL_ORDER = _DATA["INTEL_ORDER"]
INTEL_MAP = {item["id"]: item for item in INTEL}
BLOCK_ANALYSIS = _DATA["BLOCK_ANALYSIS"]
SIMILAR_PAIRS = _DATA["SIMILAR_PAIRS"]
DIAGONAL = _DATA["DIAGONAL"]
WUDAO = _DATA["WUDAO"]
TALENT = _DATA["TALENT"]
MAJOR = _DATA["MAJOR"]
CAREER = _DATA["CAREER"]
COURSE = _DATA["COURSE"]
BEHAVIOR = _DATA["BEHAVIOR"]
DEV_WINDOW = _DATA["DEV_WINDOW"]
TIMING_WINDOW = _DATA["TIMING_WINDOW"]
SENSITIVE_PERIOD = _DATA["SENSITIVE_PERIOD"]
BRAIN_LEFT_DESC = _DATA["BRAIN_LEFT_DESC"]
BRAIN_RIGHT_DESC = _DATA["BRAIN_RIGHT_DESC"]

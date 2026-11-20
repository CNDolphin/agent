"""练习脚本、CBT 模板与知识库的加载(数据文件由人审阅)。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from mhagent import content_paths

DATA_DIR = Path(__file__).resolve().parent / "data"


def _path(filename: str) -> Path:
    return content_paths.resolve("scales", filename, DATA_DIR / filename)


@lru_cache(maxsize=1)
def _practices() -> dict:
    return json.loads(_path("practices.json").read_text(encoding="utf-8"))["practices"]


@lru_cache(maxsize=1)
def _cbt() -> dict:
    return json.loads(_path("cbt_templates.json").read_text(encoding="utf-8"))["templates"]


@lru_cache(maxsize=1)
def _knowledge() -> list[dict]:
    return json.loads(_path("knowledge.json").read_text(encoding="utf-8"))["articles"]


def list_practices() -> list[str]:
    return list(_practices().keys())


def get_practice(practice_id: str) -> dict:
    try:
        return _practices()[practice_id]
    except KeyError as exc:
        raise KeyError(f"未知的练习: {practice_id}") from exc


def list_cbt_templates() -> list[str]:
    return list(_cbt().keys())


def get_cbt_template_detail(template_id: str) -> dict:
    try:
        return _cbt()[template_id]
    except KeyError as exc:
        raise KeyError(f"未知的 CBT 模板: {template_id}") from exc


def get_cbt_template(template_id: str) -> list[str]:
    """返回模板的有序字段列表。"""
    return list(get_cbt_template_detail(template_id)["fields"])


def pick_knowledge(topic: str) -> list[dict]:
    if not topic:
        return []
    return [item for item in _knowledge() if item.get("topic") == topic]


def knowledge_topics() -> list[str]:
    seen: list[str] = []
    for item in _knowledge():
        topic = item.get("topic")
        if topic and topic not in seen:
            seen.append(topic)
    return seen

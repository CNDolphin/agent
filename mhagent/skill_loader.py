"""技能加载与意图路由。

技能以 `skills/<name>/SKILL.md` 形式存在,文件头是 YAML frontmatter
(`name`、`description`、`triggers`),正文包含使用时机、流程、边界与固定声明。

加载器支持两种来源:
- 明文目录:仓库开发态,直接读 `skills/`;
- 密文包:发布态,读取 `mhagent/data/skills.enc`(整个目录的加密 ZIP)。

MVP 用关键词匹配路由,保留替换为模型路由的接口(`route` 是纯函数)。
"""

from __future__ import annotations

import functools
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from mhagent import content_paths
from mhagent.skill_crypto import decrypt_file, encrypted_path

DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
MODE_ENV = "MHAGENT_SKILLS_MODE"


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    triggers: tuple[str, ...]


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = yaml.safe_load(parts[1]) or {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, parts[2].lstrip("\n")


def _read(path: Path) -> tuple[dict, str]:
    return _split_frontmatter(path.read_text(encoding="utf-8"))


def _has_plain_skills(root: Path) -> bool:
    return root.is_dir() and any(root.glob("*/SKILL.md"))


def _resolve_source(skills_dir=None) -> tuple[str, Path]:
    """决定读取明文目录还是密文包。

    - 显式传入文件 → 视为密文包;传入目录 → 明文(测试与自定义目录);
    - 否则按 MHAGENT_SKILLS_MODE=plain|encrypted 强制;
    - 默认优先明文(开发态改动即时生效),没有明文时回退密文包。
    """
    if skills_dir is not None:
        path = Path(skills_dir)
        return ("enc" if path.is_file() else "plain"), path
    mode = os.environ.get(MODE_ENV, "").strip().lower()
    if mode == "encrypted":
        return "enc", encrypted_path()
    if mode == "plain":
        return "plain", DEFAULT_SKILLS_DIR
    online = content_paths.skills_dir()
    if online is not None:
        return "plain", online
    if _has_plain_skills(DEFAULT_SKILLS_DIR):
        return "plain", DEFAULT_SKILLS_DIR
    bundle = encrypted_path()
    if bundle.is_file():
        return "enc", bundle
    return "plain", DEFAULT_SKILLS_DIR


@functools.lru_cache(maxsize=4)
def _decrypt_cached(path: str, mtime: float) -> dict[str, bytes]:
    del mtime  # 仅用于文件变更时让缓存失效
    return decrypt_file(path)


def _load_all(skills_dir=None) -> dict[str, dict]:
    """读取全部技能,返回 {技能名: {"meta": dict, "body": str}}。"""
    kind, root = _resolve_source(skills_dir)
    loaded: dict[str, dict] = {}

    if kind == "enc":
        if not root.is_file():
            return loaded
        try:
            files = _decrypt_cached(str(root), root.stat().st_mtime)
        except ValueError:
            return loaded
        for name, content in files.items():
            parts = Path(name).parts
            if len(parts) != 2 or parts[1] != "SKILL.md":
                continue
            meta, body = _split_frontmatter(content.decode("utf-8", errors="replace"))
            loaded[parts[0]] = {"meta": meta, "body": body}
        return loaded

    if not root.is_dir():
        return loaded
    for path in root.glob("*/SKILL.md"):
        meta, body = _read(path)
        loaded[path.parent.name] = {"meta": meta, "body": body}
    return loaded


def list_skills(skills_dir=None) -> list[SkillMeta]:
    result = []
    for folder, entry in sorted(_load_all(skills_dir).items()):
        meta = entry["meta"]
        result.append(
            SkillMeta(
                name=str(meta.get("name", folder)),
                description=str(meta.get("description", "")),
                triggers=tuple(str(t) for t in (meta.get("triggers") or [])),
            )
        )
    return result


def load_skill(name: str, skills_dir=None) -> str:
    entry = _load_all(skills_dir).get(name)
    if entry is None:
        raise KeyError(f"未知技能: {name}")
    return entry["body"]


def find_skill_meta(name: str, skills_dir=None) -> SkillMeta:
    for meta in list_skills(skills_dir):
        if meta.name == name:
            return meta
    raise KeyError(f"未知技能: {name}")


_GENE_MARKERS = ("基因", "天赋", "特长", "适合什么", "职业方向", "学什么专业", "专业方向")
_MULTIPLE_INTELLIGENCE_MARKERS = ("多元智能", "八大智能", "潜能档案", "成长顾问", "加德纳", "智能雷达", "优势智能")
# 只有明确表达"要做筛查"的词才算;「分数」是能力报告场景的高频词,不能作为触发词。
_ASSESSMENT_MARKERS = ("测试", "量表", "筛查", "测评", "phq", "gad", "抑郁", "焦虑", "压力指数")
# 「评估」单独出现过于宽泛(如"评估我的报告"),仅在无报告语境时才算。
_ASSESSMENT_WEAK_MARKERS = ("评估",)
# 报告语境标记:出现时优先按报告解读/普通对话处理,避免被筛查劫持。
_REPORT_MARKERS = ("报告", "分数", "得分", "评分", "解读", "能力项", "智能")
_MENTAL_HEALTH_MARKERS = (
    "呼吸", "放松", "冥想", "正念", "练习", "日记", "情绪", "睡眠", "cbt",
    "想法记录", "知识", "科普", "压力", "难过", "低落",
)


def route(text: str, skills_dir=None) -> str | None:
    """按关键词把用户输入路由到技能名;闲聊返回 None。"""
    if not text or not text.strip():
        return None
    normalized = text.strip().lower()
    report_context = any(marker in normalized for marker in _REPORT_MARKERS)
    if any(marker in normalized for marker in _GENE_MARKERS):
        return "gene-guidance"
    # 须先于 assessment/mental-health:避免「智能分数」「评估」「压力」等通用词劫持。
    if any(marker in normalized for marker in _MULTIPLE_INTELLIGENCE_MARKERS):
        return "multiple-intelligence"
    if any(marker in normalized for marker in _ASSESSMENT_MARKERS):
        return "assessment"
    if not report_context and any(
        marker in normalized for marker in _ASSESSMENT_WEAK_MARKERS
    ):
        return "assessment"
    if any(marker in normalized for marker in _MENTAL_HEALTH_MARKERS):
        return "mental-health"
    for meta in list_skills(skills_dir):
        for trigger in meta.triggers:
            lowered = trigger.lower()
            if lowered not in normalized:
                continue
            # 报告语境下的「评估」是解读请求,不当作筛查意图。
            if report_context and lowered in _ASSESSMENT_WEAK_MARKERS:
                continue
            return meta.name
    return None

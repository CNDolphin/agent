"""本地内容包路径解析。

在线更新下载的内容包会写入 ``<data_dir>/content/<kind>/<version>``,
并在 ``<kind>/active.json`` 记录当前生效版本。各加载器优先读取该目录,
不存在时回退仓库内置内容。

``MHAGENT_CONTENT_DIR`` 由客户端 Runtime 在打开主档案时设置。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

CONTENT_DIR_ENV = "MHAGENT_CONTENT_DIR"


def content_root() -> Path | None:
    raw = os.environ.get(CONTENT_DIR_ENV, "").strip()
    return Path(raw) if raw else None


def active_dir(kind: str) -> Path | None:
    """返回已应用的内容目录,不存在返回 None。"""
    root = content_root()
    if root is None:
        return None
    base = root / kind
    current = base / "current"
    if current.is_dir():
        return current
    meta = base / "active.json"
    if not meta.is_file():
        return None
    try:
        version = str(json.loads(meta.read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError):
        return None
    target = base / version
    return target if version and target.is_dir() else None


def skills_dir() -> Path | None:
    """返回已应用的技能目录(需包含 */SKILL.md)。"""
    base = active_dir("skills")
    if base is None:
        return None
    nested = base / "skills"
    if any(nested.glob("*/SKILL.md")):
        return nested
    return base if any(base.glob("*/SKILL.md")) else None


def resolve(kind: str, filename: str, default: Path) -> Path:
    """优先返回更新目录下的文件,否则返回内置文件。"""
    current = active_dir(kind)
    if current is not None:
        candidate = current / filename
        if candidate.is_file():
            return candidate
    return default

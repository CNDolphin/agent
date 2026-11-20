"""技能 3(基因报告解读)的预留接口。

MVP 不实现任何业务逻辑:所有方法都抛 `FeatureNotEnabled`,主循环只返回固定说明。
"""

from __future__ import annotations

from typing import Protocol

FIXED_MESSAGE = (
    "基因报告解读功能暂未启用。这个版本只保留了接口,不会读取或分析你的报告,"
    "也不会给出专业或职业方向建议。你可以先关注自己的兴趣和实际体验,"
    "重要决定建议结合老师、职业咨询师或专业人士的意见。"
)


class FeatureNotEnabled(Exception):
    """功能尚未启用。"""


class ReportProvider(Protocol):
    enabled: bool

    def import_report(self, path: str) -> str: ...

    def get_dimensions(self, report_id: str) -> dict: ...

    def guidance(self, report_id: str, context: dict) -> dict: ...


class NotEnabled:
    """未启用时的占位实现:不读取文件、不联网、不产生建议。"""

    enabled = False

    def _raise(self):
        raise FeatureNotEnabled(FIXED_MESSAGE)

    def import_report(self, path: str) -> str:
        self._raise()

    def get_dimensions(self, report_id: str) -> dict:
        self._raise()

    def guidance(self, report_id: str, context: dict) -> dict:
        self._raise()


def get_provider() -> ReportProvider:
    return NotEnabled()

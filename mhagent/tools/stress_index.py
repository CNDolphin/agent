"""压力指数(纯函数)。

公式:
- pss_norm = pss_total / 40 * 100
- journal_norm = mean(近 14 天日记中消极情绪的强度 0-10) / 10 * 100,无条目则为 None
- 有日记:index = round(0.7 * pss_norm + 0.3 * journal_norm)
- 无日记:index = round(pss_norm)
- 区间:0-33 low、34-66 medium、67-100 high

注意:Python 内置 `round` 是银行家舍入(round(32.5) == 32),这里统一用
`int(x + 0.5)` 做四舍五入,保证 13→32.5→33、27→67.5→68 等边界符合预期。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StressResult:
    value: int
    band: str
    used_journal: bool


def _round_half_up(x: float) -> int:
    return int(x + 0.5)


def _band(value: int) -> str:
    if value <= 33:
        return "low"
    if value <= 66:
        return "medium"
    return "high"


def stress_index(pss_total: int, recent_negative_intensities: list[int] | tuple[int, ...]) -> StressResult:
    """合成压力指数 0-100。

    `recent_negative_intensities` 只应包含近 14 天日记中的消极情绪强度。
    """
    if isinstance(pss_total, bool) or not isinstance(pss_total, int) or not 0 <= pss_total <= 40:
        raise ValueError("pss_total must be int in [0,40]")
    if not isinstance(recent_negative_intensities, (list, tuple)):
        raise ValueError("recent_negative_intensities must be a list")
    for v in recent_negative_intensities:
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 10:
            raise ValueError("negative intensity must be int in [0,10]")

    pss_norm = pss_total / 40 * 100
    if recent_negative_intensities:
        journal_norm = sum(recent_negative_intensities) / len(recent_negative_intensities) / 10 * 100
        value = _round_half_up(0.7 * pss_norm + 0.3 * journal_norm)
        used_journal = True
    else:
        value = _round_half_up(pss_norm)
        used_journal = False
    value = min(100, max(0, value))
    return StressResult(value=value, band=_band(value), used_journal=used_journal)

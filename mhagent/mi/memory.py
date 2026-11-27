"""把测评结果整理成「基础测评记忆」，作为后续对话的长期上下文。

只产出纯文本，不生成报告文件。措辞遵守表达规范：不贴标签，
低分用「靠后 / 最值得补」描述，并保留「近似值、非诊断」的免责声明。
"""

from __future__ import annotations

import math
from datetime import datetime

DISCLAIMER = (
    "说明：以上是自评问卷、主观排序（及可选的基因报告）得到的近似值，不是诊断结论，"
    "也不能替代专业评估；融合权重为专家先验，未经临床校准。"
)

REPORT_DISCLAIMER = (
    "说明：以上分数来自会话提交的报告，自评问卷与基因融合不再参与；"
    "仍为近似值、不是诊断结论，也不能替代专业评估。"
)

REPORT_DIGEST_VERSION = "REPORT-DIGEST-1.0"


def _format_time(generated_at) -> str:
    if isinstance(generated_at, datetime):
        return generated_at.strftime("%Y-%m-%d")
    if generated_at:
        return str(generated_at)[:10]
    return datetime.now().strftime("%Y-%m-%d")


def _short(name: str) -> str:
    return str(name).replace("智能", "")


def ranked_by_rank(intel: dict) -> list[str]:
    return sorted(intel, key=lambda iid: intel[iid].get("rank") or 99)


def _fmt_score(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:.1f}" if math.isfinite(number) else "—"


def _plain(name) -> str:
    return str(name or "").split("（")[0].split("(")[0].strip()


def _item_names(items, limit: int = 3) -> str:
    names = [_plain(item.get("n") or item.get("name")) for item in items[:limit]]
    return "、".join(name for name in names if name) or "—"


def build_report_digest(analysis: dict) -> str:
    """把 `analyze_report()` 的结论压缩成对话可用的报告要点。"""
    if not analysis:
        return ""
    rank = analysis.get("rank") or []
    if not rank:
        return ""

    lines = [
        "【解读报告要点】排序："
        + " > ".join(f"{_short(item['name'])} {_fmt_score(item['score'])}" for item in rank)
    ]

    wudao = (analysis.get("wudao") or [{}])[0]
    diagonal = (analysis.get("diagonals") or [{}])[0]
    channel = []
    if diagonal.get("name"):
        channel.append(
            f"先天学习线：{_plain(diagonal['name'])}（{diagonal.get('type') or '—'}）"
            f"{_fmt_score(diagonal.get('score'))}"
        )
    if wudao.get("name"):
        channel.append(
            f"五到：{_plain(wudao['name'])}（{wudao.get('type') or '—'}）"
            f"{_fmt_score(wudao.get('score'))}"
        )
    channel.append(
        f"左右脑：左 {_fmt_score(analysis.get('lScore'))} / 右 {_fmt_score(analysis.get('rScore'))}"
    )
    lines.append("【学习通道】" + "；".join(channel))
    lines.append(
        f"【学习能力】S1 {_fmt_score(analysis.get('s1'))}、S2 {_fmt_score(analysis.get('s2'))}"
    )

    rev_high = "、".join(_plain(item.get("name")) for item in (analysis.get("revHigh") or [])[:3])
    rev_low = "、".join(_plain(item.get("name")) for item in (analysis.get("revLow") or [])[:3])
    lines.append(
        "【强弱信号】高分反转：" + (rev_high or "无")
        + "；低分反转：" + (rev_low or "无")
        + "（分数高低只表示信号强弱，不代表好坏）。"
    )

    lines.append(
        "【方向建议】才艺：" + _item_names(analysis.get("talents") or [])
        + "；课程：" + _item_names(analysis.get("courses") or [])
        + "；专业：" + _item_names(analysis.get("majors") or [])
        + "；职业：" + _item_names(analysis.get("careers") or [])
        + "；行为关注：" + _item_names(analysis.get("behaviors") or [], 2)
    )
    lines.append(
        "【执行建议】先按学习通道调整辅导方式，再为优势方向安排 1-2 项体验；"
        "以强带弱，避免贴标签与一次报多班。"
    )
    return "\n".join(lines)


def build_memory_text(
    result: dict,
    nickname: str = "",
    *,
    gene: dict | None = None,
    generated_at=None,
    report: dict | None = None,
    source: dict | None = None,
) -> str:
    """生成纯文本记忆；`report` 为 `analyze_report()` 输出时追加报告要点。"""
    intel = result.get("intel") or {}
    ind = result.get("ind") or {}
    if not intel:
        raise ValueError("测评结果为空，无法生成记忆")

    ranked = sorted(intel.values(), key=lambda item: item["score"], reverse=True)
    name = (nickname or "").strip()

    lines: list[str] = []
    header = f"{name}的多元智能基础测评" if name else "多元智能基础测评"
    lines.append(f"{header}（{_format_time(generated_at)} 完成，口径 {result.get('fusion_version', 'FUSION-1.0')}）")

    lines.append(
        "【八大智能】"
        + "；".join(f"{_short(item['name'])} {item['score']}" for item in ranked)
    )
    top = ranked[:3]
    low = ranked[-2:]
    lines.append(
        "【相对优势】" + "、".join(f"{_short(item['name'])}{item['score']}" for item in top)
        + "。【相对靠后、最值得补】" + "、".join(f"{_short(item['name'])}{item['score']}" for item in low)
        + "（仅表示相对位置，不是能力缺陷）。"
    )

    digest = build_report_digest(report or {})
    if digest:
        lines.append(digest)

    lines.append("【40 项指标】")
    for intel_id in sorted(intel, key=lambda iid: -intel[iid]["score"]):
        items = sorted(
            (item for item in ind.values() if item["intelligence"] == intel_id),
            key=lambda item: item["score"],
            reverse=True,
        )
        lines.append(
            _short(intel[intel_id]["name"]) + "：" + "、".join(f"{item['name']}{item['score']}" for item in items)
        )

    intel_order = ranked_by_rank(intel)
    lines.append(
        "【主观排序】智能从强到弱：" + ">".join(_short(intel[iid]["name"]) for iid in intel_order)
    )
    for intel_id in intel_order:
        items = sorted(
            (item for item in ind.values() if item["intelligence"] == intel_id),
            key=lambda item: item["rank"],
        )
        lines.append(
            _short(intel[intel_id]["name"]) + "组内：" + ">".join(item["name"] for item in items)
        )

    source_kind = str((source or {}).get("kind") or "")
    if source_kind == "report":
        label = str(source.get("label") or "会话提交报告")
        coverage = source.get("coverage") or {}
        intel_total = len(intel) or 8
        ind_total = len(ind) or 40
        lines.append(
            f"【数据来源】{label}（智能 {coverage.get('intel', intel_total)}/{intel_total}、"
            f"指标 {coverage.get('ind', ind_total)}/{ind_total} 已覆盖；缺失维度沿用原测评）。"
        )
        lines.append("【基因来源】本结果以会话提交的报告为准，问卷与基因融合不再参与。")
    else:
        lines.append("【数据来源】基础测评（问卷 + 主观排序 + 可选基因融合）。")
        if gene and gene.get("scores"):
            confidence = {"high": "高", "medium": "中", "low": "低"}.get(
                str(gene.get("confidence") or ""), "未标注"
            )
            filename = str(gene.get("filename") or "已上传报告")
            if gene.get("report_id") is not None:
                lines.append(
                    f"【基因来源】已参考《{filename}》，AI 抽取置信度{confidence}；"
                    "基因分参与智能级融合，报告中的 40 项指标按报告覆盖，缺失项沿用融合结果。"
                )
            else:
                lines.append(
                    f"【基因来源】已参考《{filename}》，AI 抽取置信度{confidence}；"
                    "基因分只参与智能级融合，不改变 40 项指标的相对结构。"
                )
            notes = str(gene.get("notes") or "").strip()
            if notes:
                lines.append(f"提取依据：{notes[:160]}")
        else:
            lines.append("【基因来源】本次未提供基因检测报告，结果只基于问卷与主观排序。")

    lines.append(REPORT_DISCLAIMER if source_kind == "report" else DISCLAIMER)
    lines.append(
        "使用方式：先以【解读报告要点】为框架，再用 40 项分数作为证据，结合当下情境讨论；"
        "谈低分方向时给可执行的小步骤，避免「你就是……」式定性。"
    )
    return "\n".join(lines)

"""把测评结果整理成「基础测评记忆」，作为后续对话的长期上下文。

只产出纯文本，不生成报告文件。措辞遵守表达规范：不贴标签，
低分用「靠后 / 最值得补」描述，并保留「近似值、非诊断」的免责声明。
"""

from __future__ import annotations

from datetime import datetime

DISCLAIMER = (
    "说明：以上是自评问卷、主观排序（及可选的基因报告）得到的近似值，不是诊断结论，"
    "也不能替代专业评估；融合权重为专家先验，未经临床校准。"
)


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


def build_memory_text(
    result: dict,
    nickname: str = "",
    *,
    gene: dict | None = None,
    generated_at=None,
) -> str:
    """生成约 600–1000 字的纯文本记忆。"""
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

    if gene and gene.get("scores"):
        confidence = {"high": "高", "medium": "中", "low": "低"}.get(
            str(gene.get("confidence") or ""), "未标注"
        )
        filename = str(gene.get("filename") or "已上传报告")
        lines.append(
            f"【基因来源】已参考《{filename}》，AI 抽取置信度{confidence}；"
            "基因分只参与智能级融合，不改变 40 项指标的相对结构。"
        )
        notes = str(gene.get("notes") or "").strip()
        if notes:
            lines.append(f"提取依据：{notes[:160]}")
    else:
        lines.append("【基因来源】本次未提供基因检测报告，结果只基于问卷与主观排序。")

    lines.append(DISCLAIMER)
    lines.append(
        "使用方式：回答时以这些分数为证据，结合当下情境讨论；"
        "谈低分方向时给可执行的小步骤，避免「你就是……」式定性。"
    )
    return "\n".join(lines)

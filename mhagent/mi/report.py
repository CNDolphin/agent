"""多元智能解读报告：分析引擎与 17 章 HTML 渲染。

从交付包 `agent_engine.js` / `agent_ui.js` 迁移：
- `analyzeReport` → `analyze_report`
- `renderReport` + 17 个 `sec*` → `render_report` / `sec_*`
报告数据来源为成员已完成的基础测评结果（`mi_assessment.result`），
输出自包含 HTML 片段，由前端 `.mi-report` 容器承载。
"""

from __future__ import annotations

import math
import re
from datetime import datetime

from mhagent.mi import report_data
from mhagent.mi.report_data import (
    BLOCK_ANALYSIS,
    BRAIN_LEFT_DESC,
    BRAIN_RIGHT_DESC,
    BEHAVIOR,
    CAREER,
    COURSE,
    DEV_WINDOW,
    DIAGONAL,
    IND,
    INTEL,
    INTEL_MAP,
    INTEL_ORDER,
    MAJOR,
    SENSITIVE_PERIOD,
    SIMILAR_PAIRS,
    TALENT,
    TIMING_WINDOW,
    WUDAO,
)

STATUS_HIGH = 77
STATUS_LOW = 33
STATUS_STANDARD = 55
AGE_ADULT_THRESHOLD = 23

_ESCAPE_MAP = str.maketrans(
    {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}
)


def esc(value) -> str:
    """HTML 转义：与交付包 `esc()` 保持一致。"""
    return str("" if value is None else value).translate(_ESCAPE_MAP)


def fmt(number) -> str:
    """保留一位小数；非有限数返回 `—`。"""
    try:
        value = float(number)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(value):
        return "—"
    return f"{value:.1f}"


def round1(value: float) -> float:
    return round(value * 10) / 10


def mean(values) -> float:
    values = [float(item) for item in values if item is not None]
    return sum(values) / len(values) if values else 0.0


def clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def parse_float(value):
    """解析第一个数字；失败返回 nan。"""
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
    if not match:
        return float("nan")
    try:
        return float(match.group(0))
    except ValueError:
        return float("nan")


def first_number(value) -> str:
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return match.group(0) if match else ""


def age_text(age: float) -> str:
    """数字年龄转展示文本（10.0 → 10）。"""
    return str(int(age)) if float(age).is_integer() else str(age)


def level_of(score: float) -> int:
    if score >= 90:
        return 7
    if score >= 75:
        return 6
    if score >= 60:
        return 5
    if score >= 45:
        return 4
    if score >= 30:
        return 3
    if score >= 15:
        return 2
    return 1


def score_bar(score) -> str:
    value = clamp(float(score or 0), 0, 100)
    tag = "tag-hi" if value > STATUS_HIGH else ("tag-lo" if value < STATUS_LOW else "")
    return (
        f'<div class="sbar"><div class="sbar-fill" style="width:{value}%"></div>'
        f'<span class="sbar-tag {tag}">{fmt(score)}</span></div>'
    )


def badge(text, cls: str = "") -> str:
    return f'<span class="badge {cls or ""}">{esc(text)}</span>'


def stage_short(value: str) -> str:
    if not value:
        return ""
    return str(value).split("（")[0].split("(")[0].strip()


def age_ok(value: str, age) -> bool:
    if not value or not math.isfinite(age):
        return True
    match = re.search(r"(\d+(?:\.\d+)?)", str(value))
    return age >= float(match.group(1)) if match else True


def age_start(value: str) -> str:
    if not value:
        return ""
    match = re.search(r"(\d+(?:\.\d+)?)", str(value))
    return f"{match.group(1)} 岁+" if match else ""


def parse_age_range(value: str):
    match = re.search(r"(\d+(?:\.\d+)?)\s*[—\-~]\s*(\d+(?:\.\d+)?)\s*岁?", str(value or ""))
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def intel_card(rows, cls: str, title: str) -> str:
    body = "".join(
        f'<div class="tc-row"><span class="tc-rank">{item["rank"]}</span>'
        f'<span class="tc-name">{esc(item["name"])}</span><b>{fmt(item["score"])}</b></div>'
        for item in rows
    )
    return f'<div class="three-card {cls}"><div class="tc-title">{title}</div>{body}</div>'


def radar_points(scores: dict):
    """雷达图坐标（0-100 归一化，8 个顶点）。"""
    cx, cy, radius, count = 120, 110, 80, 8
    points = []
    for index, intel_id in enumerate(INTEL_ORDER):
        ratio = clamp(float(scores.get(intel_id, 0) or 0), 0, 100) / 100
        angle = -math.pi / 2 + index * 2 * math.pi / count
        points.append(
            (cx + radius * ratio * math.cos(angle), cy + radius * ratio * math.sin(angle))
        )

    def ring(factor: float) -> str:
        coords = []
        for index in range(count):
            angle = -math.pi / 2 + index * 2 * math.pi / count
            coords.append(
                f"{cx + radius * factor * math.cos(angle):.1f},"
                f"{cy + radius * factor * math.sin(angle):.1f}"
            )
        return " ".join(coords)

    return points, ring(0.25), ring(0.5), ring(0.75), ring(1.0), cx, cy, radius


def build_script(adv, boost, weak, intel_scores, scores):
    """以强带弱的自动话术。"""
    top = adv[0] if adv else None
    bottom = weak[-1] if weak else None
    if top is None or bottom is None:
        return {"text": "数据不足，无法生成话术。", "principle": "", "example": ""}
    top_ind = sorted(
        ({"k": key, "s": scores[key]} for key in INTEL_MAP[top["id"]]["inds"]),
        key=lambda item: -item["s"],
    )[0]
    bot_ind = sorted(
        ({"k": key, "s": scores[key]} for key in INTEL_MAP[bottom["id"]]["inds"]),
        key=lambda item: item["s"],
    )[0]
    principle = (
        "从优势能力出发，以优势带动弱势；从优势能力中的细项，给予更贴近需求的建议；"
        "非鉴定单位，以正面角度解读。"
    )
    example = (
        f"您的孩子在「{top['name']}」较占优势（{fmt(top['score'])} 分），"
        f"尤其是其中的「{IND[top_ind['k']]['n']}」表现突出，说明孩子愿意花更长的时间从事这类活动。"
        f"针对「{bottom['name']}」中相对需要提升的「{IND[bot_ind['k']]['n']}」，"
        f"建议您善用「{IND[top_ind['k']]['n']}」的优势来带动：{IND[bot_ind['k']]['adv']}"
    )
    return {
        "principle": principle,
        "example": example,
        "top": top,
        "bottom": bottom,
        "topInd": top_ind,
        "botInd": bot_ind,
    }


def _fit_by_intel(items, intel_scores: dict):
    result = []
    for item in items:
        fit = round1(mean(intel_scores.get(intel_id, 0) for intel_id in item.get("intels", [])))
        result.append({**item, "fit": fit})
    return result


def _new_tag(item: dict, cls: str = "tag-new", text: str = "2026 新增") -> str:
    return f' <span class="{cls}">{text}</span>' if item.get("n2026") else ""


def _mini_tag(item: dict) -> str:
    return '<i class="tag-mini">新</i>' if item.get("n2026") else ""


def _age_tag(display: str) -> str:
    return f'<i class="tag-age">{esc(display)}</i>' if display else ""


def _rank_cell(rank) -> str:
    return f'<b class="fu-rank">第 {rank} 名</b>' if rank else "—"


def analyze_report(result: dict, meta: dict, intel_manual: dict | None = None) -> dict:
    """对应交付包 `analyzeReport()`。"""
    scores = {
        ind_id: float((result.get("ind") or {}).get(ind_id, {}).get("score") or 0)
        for ind_id in IND
    }
    manual = intel_manual or {
        intel_id: (result.get("intel") or {}).get(intel_id, {}).get("score")
        for intel_id in INTEL_ORDER
    }

    intel_scores: dict[str, float] = {}
    for intel_id in INTEL_ORDER:
        try:
            value = float(manual.get(intel_id))
        except (TypeError, ValueError):
            value = float("nan")
        if math.isfinite(value):
            intel_scores[intel_id] = round1(clamp(value, 0, 120))
        else:
            intel_scores[intel_id] = round1(
                mean(scores[key] for key in INTEL_MAP[intel_id]["inds"])
            )

    rank = sorted(
        (
            {"id": intel_id, "name": INTEL_MAP[intel_id]["name"], "score": intel_scores[intel_id]}
            for intel_id in INTEL_ORDER
        ),
        key=lambda item: -item["score"],
    )
    total = sum(item["score"] for item in rank)
    for index, item in enumerate(rank, 1):
        item["rank"] = index
        item["ratio"] = round1(item["score"] / total * 100) if total > 0 else 0

    adv = [item for item in rank if item["rank"] <= 3]
    boost = [item for item in rank if 4 <= item["rank"] <= 6]
    weak = [item for item in rank if item["rank"] >= 7]

    rev_high, rev_low = [], []
    for intel_id in INTEL_ORDER:
        for key in INTEL_MAP[intel_id]["inds"]:
            score = scores[key]
            if score > STATUS_HIGH:
                rev_high.append(
                    {
                        "id": key,
                        "name": IND[key]["n"],
                        "intel": INTEL_MAP[intel_id]["name"],
                        "score": score,
                    }
                )
            if score < STATUS_LOW:
                rev_low.append(
                    {
                        "id": key,
                        "name": IND[key]["n"],
                        "intel": INTEL_MAP[intel_id]["name"],
                        "score": score,
                    }
                )
    for intel_id, score in intel_scores.items():
        if score > STATUS_HIGH:
            rev_high.append(
                {
                    "id": intel_id,
                    "name": INTEL_MAP[intel_id]["name"],
                    "intel": "智能总分",
                    "score": score,
                    "isIntel": True,
                }
            )
        if score < STATUS_LOW:
            rev_low.append(
                {
                    "id": intel_id,
                    "name": INTEL_MAP[intel_id]["name"],
                    "intel": "智能总分",
                    "score": score,
                    "isIntel": True,
                }
            )
    rev_high.sort(key=lambda item: -item["score"])
    rev_low.sort(key=lambda item: item["score"])

    diagonals = []
    for item in DIAGONAL:
        diagonals.append(
            {
                **item,
                "score": round1(mean(intel_scores[intel_id] for intel_id in item["intels"])),
                "intelNames": " + ".join(INTEL_MAP[intel_id]["name"] for intel_id in item["intels"]),
            }
        )
    diagonals.sort(key=lambda item: -item["score"])

    left = ["lang", "logic", "nature", "inner"]
    right = ["visual", "music", "body", "social"]
    l_score = round1(mean(intel_scores[intel_id] for intel_id in left))
    r_score = round1(mean(intel_scores[intel_id] for intel_id in right))

    wudao = []
    for item in WUDAO:
        wudao.append(
            {
                **item,
                "score": round1(mean(scores[key] for key in item["inds"])),
                "indNames": "、".join(IND[key]["n"] for key in item["inds"]),
            }
        )
    wudao.sort(key=lambda item: -item["score"])

    s1 = round1(mean(scores[key] for key in ["l1", "l4", "g1", "g2", "g3", "g4"]))
    s2 = round1(mean(scores[key] for key in scores))

    talents = sorted(_fit_by_intel(TALENT, intel_scores), key=lambda item: -item["fit"])
    majors = sorted(_fit_by_intel(MAJOR, intel_scores), key=lambda item: -item["fit"])
    careers = sorted(_fit_by_intel(CAREER, intel_scores), key=lambda item: -item["fit"])

    courses = []
    for item in COURSE:
        courses.append(
            {
                **item,
                "fit": round1(mean(scores[key] for key in item["inds"])),
                "indNames": "、".join(IND[key]["n"] for key in item["inds"]),
            }
        )
    courses.sort(key=lambda item: -item["fit"])

    behaviors = []
    for item in BEHAVIOR:
        behaviors.append(
            {
                **item,
                "fit": round1(mean(scores[key] for key in item["inds"])),
                "indNames": "、".join(IND[key]["n"] for key in item["inds"]),
            }
        )
    behaviors.sort(key=lambda item: item["fit"])

    script = build_script(adv, boost, weak, intel_scores, scores)

    report = {
        "meta": meta,
        "intelScores": intel_scores,
        "scores": scores,
        "rank": rank,
        "adv": adv,
        "boost": boost,
        "weak": weak,
        "revHigh": rev_high,
        "revLow": rev_low,
        "diagonals": diagonals,
        "lScore": l_score,
        "rScore": r_score,
        "wudao": wudao,
        "s1": s1,
        "s2": s2,
        "talents": talents,
        "majors": majors,
        "careers": careers,
        "courses": courses,
        "behaviors": behaviors,
        "script": script,
    }

    from mhagent.mi import topics as topics_module

    report["topics"] = topics_module.analyze_topics(scores, intel_scores, meta, report)
    return report


# ---------------------------------------------------------------- 融合说明块


def build_fusion(result: dict, gene: dict | None) -> dict | None:
    """基于当前项目的融合结果组装三源融合说明数据。"""
    intel = result.get("intel") or {}
    ind = result.get("ind") or {}
    if not intel:
        return None
    gene_scores = (gene or {}).get("scores") or {}
    case = "B" if result.get("gene_used") else "A"
    rows = []
    exempt = 0
    for intel_id in INTEL_ORDER:
        items = [ind[key] for key in INTEL_MAP[intel_id]["inds"] if key in ind]
        quiz_values = [float(item.get("quiz") if item.get("quiz") is not None else item.get("score") or 0) for item in items]
        for value in quiz_values:
            if value > STATUS_HIGH or value < STATUS_LOW:
                exempt += 1
        item = intel.get(intel_id) or {}
        gene_value = gene_scores.get(intel_id) if case == "B" else None
        rows.append(
            {
                "id": intel_id,
                "name": INTEL_MAP[intel_id]["name"],
                "quiz": round1(mean(quiz_values)) if quiz_values else None,
                "rank": item.get("rank"),
                "gene": float(gene_value) if gene_value is not None else None,
                "final": float(item.get("score") or 0),
            }
        )
    gene_count = len([value for value in gene_scores.values() if value is not None])
    return {
        "case": case,
        "caseName": "基因检测 × 问卷 × 主观排序" if case == "B" else "问卷 × 主观排序（无基因检测）",
        "weights": "基因 65% + 问卷/排序 35%" if case == "B" else "问卷 40% + 主观排序 60%",
        "exemptN": exempt,
        "geneN": gene_count,
        "rows": rows,
    }


def sec_fusion(R: dict) -> str:
    fusion = R.get("fusion")
    if not fusion:
        return ""
    rows = "".join(
        f'<tr><td class="fu-name">{esc(str(row["name"]).replace("智能", ""))}</td>'
        f'<td>{fmt(row["quiz"]) if row["quiz"] is not None else "—"}</td>'
        f'<td>{_rank_cell(row["rank"])}</td>'
        f'<td>{fmt(row["gene"]) if row["gene"] is not None else "—"}</td>'
        f'<td><b class="fu-final">{fmt(row["final"])}</b></td></tr>'
        for row in fusion["rows"]
    )
    if fusion["case"] == "B":
        desc = (
            "以<b>基因检测结果（先天）</b>为基准（智能级权重 65%），叠加"
            "<b>问卷 × 主观排序</b>的调整结果（权重 35%，其中问卷 40% + 排序 60%，"
            "主观认知 &gt; 客观测评）——<b>先天 + 后天环境 + 现实状态</b>综合评定。"
        )
    else:
        desc = (
            "以<b>问卷作答（客观测评）</b>为基础，叠加<b>主观排序</b>调整"
            "（主观认知 &gt; 客观测评：问卷 40% + 排序 60%）；智能级排序以 0.5 权重整组微调，"
            "避免与能力级排序双重叠加。"
        )
    exempt = (
        f"📌 已对 {fusion['exemptN']} 项原始分 &gt;77（高分反转）或 &lt;33（低分反转）的能力项"
        "豁免排序调整，直接保留原始信号。"
        if fusion["exemptN"] > 0
        else ""
    )
    return f'''<div class="fusion-note" id="fusionNote">
    <div class="fu-hd">🧮 三源融合说明 · {esc(fusion["caseName"])}（权重：{esc(fusion["weights"])}）</div>
    <p class="fu-desc">{desc}</p>
    <p class="fu-desc">{exempt}⚖ 融合权重为系统设定，非临床校准值；当前口径由本机融合引擎（{esc(R.get("fusionVersion", "FUSION-1.0"))}）计算。</p>
    <table class="fu-table">
      <thead><tr><th>智能</th><th>问卷分</th><th>主观排序</th><th>基因分</th><th>融合后</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>'''


def sec_report_source(R: dict) -> str:
    """报告覆盖来源说明：替代融合块，标明每项智能分来自报告还是原测评。"""
    source = R.get("reportSource")
    if not source:
        return ""
    coverage = source.get("coverage") or {}
    missing = set(coverage.get("missing_intel") or [])
    covered_intel = int(coverage.get("intel") or 0)
    covered_ind = int(coverage.get("ind") or 0)
    intel_total = covered_intel + len(missing)
    ind_total = covered_ind + len(coverage.get("missing_ind") or [])
    title = str(source.get("title") or "提交报告")
    filename = str(source.get("filename") or "")
    uploaded = str(source.get("uploaded_at") or "").replace("T", " ")[:19]
    rows = "".join(
        f'<tr><td class="fu-name">{esc(str(item["name"]).replace("智能", ""))}</td>'
        f'<td><b class="fu-final">{fmt(item["score"])}</b></td>'
        f'<td>{badge("原测评补位", "b-boost") if item["id"] in missing else badge("报告分数", "b-adv")}</td></tr>'
        for item in (R.get("rank") or [])
    )
    file_line = f" · 文件：{esc(filename)}" if filename else ""
    time_line = f" · 提交时间：{esc(uploaded)}" if uploaded else ""
    return f'''<div class="fusion-note" id="reportSourceNote">
    <div class="fu-hd">📄 数据来源 · 会话提交报告《{esc(title)}》</div>
    <p class="fu-desc">本报告分数直接采用成员提交的报告（智能 {intel_total} 项覆盖 {covered_intel} 项、指标 {ind_total} 项覆盖 {covered_ind} 项）；自评问卷与基因融合不再参与，缺失维度沿用原测评分数。{file_line}{time_line}</p>
    <p class="fu-desc">⚖ 报告分数为原文抽取的近似值，非诊断结论；如与既往结果冲突，以本次最新提交的报告为准。</p>
    <table class="fu-table">
      <thead><tr><th>智能</th><th>采用分</th><th>分数来源</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>'''


# ---------------------------------------------------------------- 章节渲染


def sec_overview(R: dict) -> str:
    points, ring25, ring50, ring75, ring100, cx, cy, radius = radar_points(R["intelScores"])
    labels = []
    for index, intel_id in enumerate(INTEL_ORDER):
        angle = -math.pi / 2 + index * 2 * math.pi / 8
        lx = cx + (radius + 24) * math.cos(angle)
        ly = cy + (radius + 24) * math.sin(angle)
        name = INTEL_MAP[intel_id]["name"].replace("智能", "")
        labels.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" dominant-baseline="middle" '
            f'class="radar-label">{esc(name)}</text>'
        )
    polygon = " ".join(f"{point[0]:.1f},{point[1]:.1f}" for point in points)
    dots = "".join(
        f'<circle cx="{point[0]:.1f}" cy="{point[1]:.1f}" r="3" fill="#0d9c8a"/>'
        for point in points
    )
    grid_lines = "".join(
        (
            f'<line x1="{cx}" y1="{cy}" x2="{cx + radius * math.cos(-math.pi / 2 + i * 2 * math.pi / 8):.1f}" '
            f'y2="{cy + radius * math.sin(-math.pi / 2 + i * 2 * math.pi / 8):.1f}" stroke="#d2e3df" stroke-width="1"/>'
        )
        for i in range(8)
    )
    rows = "".join(
        f'<tr><td>{item["rank"]}</td><td>{esc(item["name"])}</td><td><b>{fmt(item["score"])}</b></td>'
        f'<td>{item["ratio"]}%</td><td>{"★" * level_of(item["score"])}{"☆" * (7 - level_of(item["score"]))}</td>'
        f'<td>{badge("优势", "b-adv") if item["rank"] <= 3 else (badge("提升", "b-boost") if item["rank"] <= 6 else badge("补足", "b-weak"))}</td></tr>'
        for item in R["rank"]
    )
    return f'''<section class="sec" id="s1">
    <h2>一、八大智能总览（天赋雷达）</h2>
    <div class="grid-2">
      <div class="radar-box">
        <svg viewBox="0 0 240 220" class="radar">
          <polygon points="{ring100}" fill="none" stroke="#d2e3df" stroke-width="1"/>
          <polygon points="{ring75}" fill="none" stroke="#d2e3df" stroke-width="1"/>
          <polygon points="{ring50}" fill="none" stroke="#d2e3df" stroke-width="1"/>
          <polygon points="{ring25}" fill="none" stroke="#d2e3df" stroke-width="1"/>
          {grid_lines}
          <polygon points="{polygon}" fill="rgba(13,156,138,.25)" stroke="#0d9c8a" stroke-width="2"/>
          {dots}{"".join(labels)}
        </svg>
      </div>
      <div>
        <table class="tbl">
          <thead><tr><th>排序</th><th>智能</th><th>分数</th><th>比率</th><th>1-7级</th><th>判定</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </div>
    <div class="three">
      {intel_card(R["adv"], "c-adv", "优势的智能 · 我的天性优秀天赋")}
      {intel_card(R["boost"], "c-boost", "提升的智能 · 以强带弱三项")}
      {intel_card(R["weak"], "c-weak", "补足的智能 · 需补弱的智能")}
    </div>
    <p class="note">排序好比生命动力：排序靠前代表该智能内在驱动力较强、兴趣及无意识使用频率较高。排序高且能力指标高＝热情与才华兼备；排序高但指标弱＝有热情仍需培养能力；排序低但指标高＝潜在智能，可用能力激发兴趣。评分以 55 为界，55 以上为优势智能、55 以下为潜在智能。</p>
  </section>'''


def sec_scoring(R: dict) -> str:
    def rev_html(items, cls, label):
        if not items:
            return f'<p class="ok-line">✓ 未检测到{label}项。</p>'
        body = "".join(
            f'<li><b>{esc(item["name"])}</b>（{esc(item["intel"])}）'
            f'<span class="{cls}">{fmt(item["score"])} 分</span> — '
            f'{"智能总分反转" if item.get("isIntel") else "指标反转"}</li>'
            for item in items
        )
        return f'<ul class="rev-list">{body}</ul>'

    return f'''<section class="sec" id="s2">
    <h2>二、分数判定与反转提示</h2>
    <div class="rule-box"><b>判定口径：</b>55 分为标准分；&gt;77 分＝高分反转（该能力要求高、对活动呈「选择性」，过度追求完美反而失常，强中转弱）；&lt;33 分＝低分反转（对该活动有意外效果，弱中转强）。解读看细项、不看总分。</div>
    <div class="grid-2">
      <div class="rev-card"><h3>🔺 高分反转（&gt;77）</h3>{rev_html(R["revHigh"], "rev-hi", "高分反转")}</div>
      <div class="rev-card"><h3>🔻 低分反转（&lt;33）</h3>{rev_html(R["revLow"], "rev-lo", "低分反转")}</div>
    </div>
  </section>'''


def sec_diagonal(R: dict) -> str:
    top = R["diagonals"][0] if R["diagonals"] else None
    cards = "".join(
        f'<div class="diag-card {"diag-top" if index == 0 else ""}">'
        f'<div class="diag-name">{esc(item["name"])} <span class="diag-rank">{index + 1}</span></div>'
        f'<div class="diag-score">{fmt(item["score"])}</div>'
        f'<div class="diag-type">{esc(item["type"])}学习者 · {esc(item["intelNames"])}</div>'
        f'<p>{esc(item["desc"])}</p>'
        f'<p class="diag-sug">💡 {esc(item["suggest"])}</p></div>'
        for index, item in enumerate(R["diagonals"])
    )
    highlight = (
        f'<div class="highlight-box">🏆 最匹配的学习类型：<b>{esc(top["type"])}学习者</b>'
        f'（{esc(top["name"])}，{fmt(top["score"])} 分）——{esc(top["desc"])}</div>'
        if top
        else ""
    )
    return f'''<section class="sec" id="s3">
    <h2>三、对角线分析 · 先天学习类型</h2>
    <p class="note">四条学习线由相邻智能相加构成：听觉线＝语言+音乐；视觉线＝人际沟通+视觉空间；触觉线＝逻辑数学+肢体动觉；意识环境线＝个人内省+自然观察。最高的一条线即最适合的学习通道。</p>
    <div class="diag-cards">{cards}</div>
    {highlight}
  </section>'''


def sec_brain(R: dict) -> str:
    left = ["lang", "logic", "nature", "inner"]
    right = ["visual", "music", "body", "social"]
    l_items = "".join(
        f'<li>{esc(INTEL_MAP[intel_id]["name"])} <b>{fmt(R["intelScores"][intel_id])}</b></li>'
        for intel_id in left
    )
    r_items = "".join(
        f'<li>{esc(INTEL_MAP[intel_id]["name"])} <b>{fmt(R["intelScores"][intel_id])}</b></li>'
        for intel_id in right
    )
    left_higher = R["lScore"] >= R["rScore"]
    desc_left = "<br>".join("· " + item for item in BRAIN_LEFT_DESC)
    desc_right = "<br>".join("· " + item for item in BRAIN_RIGHT_DESC)
    conclusion = (
        "左脑总分高于右脑" if left_higher else "右脑总分高于左脑"
    ) + (
        f"（左 {fmt(R['lScore'])} vs 右 {fmt(R['rScore'])}）——"
        + (
            "偏重语言逻辑、组织管理、观察记忆等理性功能；建议补强右脑的艺术创作、空间心像与肢体律动活动"
            if left_higher
            else "偏重空间心像、艺术鉴赏、人际创造等感性功能；建议补强左脑的逻辑推理、计划判断与语言记忆训练"
        )
    )
    return f'''<section class="sec" id="s4">
    <h2>四、先天左右脑功能分析</h2>
    <div class="grid-2">
      <div class="brain-card b-left"><h3>🧠 左脑 · 知性脑 <span>{fmt(R["lScore"])} 分</span></h3>
        <ul>{l_items}</ul>
        <p class="b-desc">{desc_left}</p></div>
      <div class="brain-card b-right"><h3>🧠 右脑 · 艺术脑 <span>{fmt(R["rScore"])} 分</span></h3>
        <ul>{r_items}</ul>
        <p class="b-desc">{desc_right}</p></div>
    </div>
    <div class="highlight-box">{conclusion}。左右脑均衡发展是最佳状态，盲目开发某侧并不科学。</div>
  </section>'''


def sec_wudao(R: dict) -> str:
    top = R["wudao"][0] if R["wudao"] else None
    items = "".join(
        f'<div class="wudao-item {"w-top" if index == 0 else ""}">'
        f'<div class="wd-name">{esc(item["name"])} <span class="wd-type">{esc(item["type"])}</span></div>'
        f'<div class="wd-score">{fmt(item["score"])}</div>'
        f'<p class="wd-desc">{esc(item["desc"])}</p></div>'
        for index, item in enumerate(R["wudao"])
    )
    highlight = (
        f'<div class="highlight-box">📖 最适合的学习方式：<b>{esc(top["name"])}（{esc(top["type"])}）</b> — {esc(top["strong"])}</div>'
        if top
        else ""
    )
    return f'''<section class="sec" id="s5">
    <h2>五、先天学习方式分析 · 学习五到</h2>
    <p class="note">心到（思考型）、手到（体觉型）、口到（人际型）、耳到（听觉型）、眼到（视觉型）。使用擅长的感官通道学习，事半功倍。</p>
    <div class="wudao-row">{items}</div>
    {highlight}
  </section>'''


def sec_s12(R: dict) -> str:
    six = [("l1", "阅读"), ("l4", "理解"), ("g1", "思辩"), ("g2", "归纳"), ("g3", "演绎"), ("g4", "运算")]
    chips = "".join(f'<span class="chip">{name} {fmt(R["scores"][key])}</span>' for key, name in six)
    return f'''<section class="sec" id="s6">
    <h2>六、学习能力预测（S1 / S2）</h2>
    <div class="s12-box">
      <div class="s12-item"><div class="s12-k">S1 · 六项先天学习能力</div>
        <div class="s12-v">{fmt(R["s1"])}</div>
        <p class="s12-p">阅读 + 理解 + 思辩 + 归纳 + 演绎 + 运算，预测 6-12 岁学习状况</p>
        <div class="s12-ind">{chips}</div></div>
      <div class="s12-item"><div class="s12-k">S2 · 综合 40 项核心能力</div>
        <div class="s12-v">{fmt(R["s2"])}</div>
        <p class="s12-p">综合 40 项核心能力对 6-12 岁学习状况的预测</p></div>
    </div>
    <p class="note">S1 侧重「会不会学」的六项关键能力，S2 反映综合潜能。两者结合可判断：优势在学习通道（阅读/计算/思辨）还是非学习通道（艺术/运动/社交），据此安排学业与兴趣的精力配比。</p>
  </section>'''


def sec_indicators(R: dict) -> str:
    blocks = []
    for intel_id in INTEL_ORDER:
        intel = INTEL_MAP[intel_id]
        rows = []
        for key in intel["inds"]:
            item = IND[key]
            score = R["scores"][key]
            if score > STATUS_HIGH:
                tag = badge("高分反转", "b-hi")
            elif score < STATUS_LOW:
                tag = badge("低分反转", "b-lo")
            elif score >= STATUS_STANDARD:
                tag = badge("优势", "b-adv")
            else:
                tag = badge("潜在", "b-weak")
            rows.append(
                f'<div class="ind-detail"><div class="ind-hd"><span class="ind-n">{esc(item["n"])}</span>'
                f'{tag}<span class="ind-score">{fmt(score)}</span></div>'
                f'<div class="ind-bar">{score_bar(score)}</div>'
                f'<p class="ind-def"><b>定义：</b>{esc(item["def"])}</p>'
                f'<p class="ind-hi"><b>{"高分表现（生活例子）：" if score >= STATUS_STANDARD else "当前水平偏低时需留意："}</b>'
                f'{esc(item["hi"] if score >= STATUS_STANDARD else item["lo"])}</p>'
                f'<p class="ind-adv"><b>💡 改善建议：</b>{esc(item["adv"])}</p></div>'
            )
        blocks.append(
            f'<div class="intel-block"><div class="ib-head"><span class="ib-name">{esc(intel["name"])}</span>'
            f'<span class="ib-score">总分 {fmt(R["intelScores"][intel_id])} · {esc(intel["role"])} · {esc(intel["side"])}</span></div>'
            f'{"".join(rows)}'
            f'<div class="block-note block-note2"><b>块状分析方法：</b>{esc(BLOCK_ANALYSIS[intel_id])}</div></div>'
        )
    return f'''<section class="sec" id="s7">
    <h2>七、40 项核心指标逐项解读</h2>
    <p class="note">解读看细项不看总分；每一项给「定义 → 表现 → 改善建议」，并附智能内块状分析（同智能指标间的关系比较）。</p>
    {"".join(blocks)}
  </section>'''


def sec_similar() -> str:
    rows = "".join(
        f'<tr><td>{esc(item["items"])}</td><td>{esc(item["intels"])}</td>'
        f'<td>{esc(item["common"])}</td><td>{esc(item["diff"])}</td></tr>'
        for item in SIMILAR_PAIRS
    )
    return f'''<section class="sec" id="s8">
    <h2>八、40 项相似智能差异辨析（易混淆对照）</h2>
    <p class="note">部分指标名称相近易混淆，解读时需清晰区分所属智能与侧重点，避免误导家长。</p>
    <table class="tbl">
      <thead><tr><th>指标组</th><th>所属智能</th><th>相同点</th><th>差异点（侧重点）</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </section>'''


def _fit_top(items, limit: int, with_age: bool) -> str:
    rows = []
    for index, item in enumerate(items[:limit]):
        age_cell = f'<td class="td-sm">{esc(item.get("age") or "—")}</td>' if with_age else ""
        new_tag = ' <span class="tag-new">2026 新增</span>' if item.get("n2026") else ""
        intel_names = "、".join(INTEL_MAP[intel_id]["name"] for intel_id in item.get("intels", []))
        rows.append(
            f'<tr><td>{index + 1}</td><td>{esc(item["n"])}{new_tag}</td>{age_cell}'
            f'<td><b>{fmt(item["fit"])}</b></td><td class="td-sm">{esc(intel_names)}</td></tr>'
        )
    return "".join(rows)


def _fit_table(items, with_age: bool, col_name: str = "建议年龄") -> str:
    age_header = f"<th>{esc(col_name)}</th>" if with_age else ""
    return (
        f'<table class="tbl"><thead><tr><th>#</th><th>项目</th>{age_header}'
        f"<th>匹配分</th><th>匹配智能</th></tr></thead><tbody>"
        f'{_fit_top(items, len(items), with_age)}</tbody></table>'
    )


def sec_talent(R: dict) -> str:
    age = parse_float(R["meta"].get("age"))
    has_age = math.isfinite(age)
    items = R["talents"]
    filtered = False
    if has_age:
        ok = [item for item in R["talents"] if age_ok(item.get("age"), age)]
        if ok:
            items = ok
            filtered = True
    if has_age:
        if filtered:
            tip = (
                f'按当前年龄 {age_text(age)} 岁过滤：达到建议起步年龄的才艺共 '
                f'<b>{len(items)}/{len(R["talents"])}</b> 项'
            )
        else:
            tip = "已按年龄过滤（暂无完全适龄才艺，显示全部）"
    else:
        tip = "⚠ 未填写年龄，暂不过滤 — 可在页面上方「报告设置」填写年龄后重新生成"
    chips = "".join(
        f'<span class="chip chip-big">{index + 1}. {esc(item["n"])}'
        f'{_mini_tag(item)}{_age_tag(age_start(item.get("age", "")))}'
        f'<b>{fmt(item["fit"])}</b></span>'
        for index, item in enumerate(items[:10])
    )
    filtered_note = (
        f'<p class="note">🔒 已按年龄 {age_text(age)} 岁过滤，仅显示达到建议起步年龄的 {len(items)} 项才艺。</p>'
        if filtered
        else ""
    )
    return f'''<section class="sec" id="s9">
    <h2>九、才艺天赋推荐（25 项排序）</h2>
    <p class="note">按「匹配智能得分均分」自动计算匹配度（原表为 20000 份抽样适性分数，仅供排序参考）。Top 10 为当前分数下匹配度最高的才艺方向；「建议年龄」依据手册《智能开发最佳时期对应表》《天赋智能时效窗》与敏感期阶段标注，早于起步年龄可先做亲子体验式接触；<span class="tag-new">2026 新增</span>项结合新课标（AI 编程纳入综合实践课、科学「做中学」）与行业趋势：</p>
    <div class="age-filter"><span class="age-filter-tip">{tip}</span></div>
    <div class="top-chips">{chips}</div>
    {_fit_table(items, True)}
    {filtered_note}
    <p class="note">参考原报告排序（按 20000 份抽样适性分数）：绘画类 138.47、围棋/国际象棋 136.03、珠心算 132.3、捏陶/DIY 131.37、绘本 128.61、书法 124.87、儿童戏剧/主持人/演讲/小记者 122.61、声乐 121.28、直排轮 120.95、儿童瑜伽 119.43……请结合孩子天赋在咨询师指导下科学选择。</p>
  </section>'''


def sec_major(R: dict) -> str:
    chips = "".join(
        f'<span class="chip chip-big">{index + 1}. {esc(str(item["n"]).split("（")[0])}'
        f'{_mini_tag(item)}{_age_tag(stage_short(item.get("age", "")))}'
        f'<b>{fmt(item["fit"])}</b></span>'
        for index, item in enumerate(R["majors"][:8])
    )
    return f'''<section class="sec" id="s10">
    <h2>十、高考志愿专业推荐（30 类排序）</h2>
    <p class="note">选择专业本质是找到与兴趣、天赋最匹配的方向。以下按当前分数匹配度自动排序；「发展阶段」面向高考年龄段，标注大学本科阶段的学制与建议选科路径；<span class="tag-new">2026 新增</span>项来自教育部《普通高等学校本科专业目录(2026年)》新增的 38 种专业（如具身智能、脑机科学与技术、低空经济与管理、储能科学与工程、数字金融、计算语言学等），已在「十四五」专业调整比例超 30%、新增布点 1.02 万个的背景下优先适配新兴赛道：</p>
    <div class="top-chips">{chips}</div>
    {_fit_table(R["majors"], True, "发展阶段")}
  </section>'''


def sec_career(R: dict) -> str:
    chips = "".join(
        f'<span class="chip chip-big">{index + 1}. {esc(str(item["n"]).split("（")[0])}'
        f'{_mini_tag(item)}{_age_tag(stage_short(item.get("age", "")))}'
        f'<b>{fmt(item["fit"])}</b></span>'
        for index, item in enumerate(R["careers"][:8])
    )
    return f'''<section class="sec" id="s11">
    <h2>十一、职业方向推荐（30 类排序）</h2>
    <p class="note">充分发挥强项、找对位置乐在工作。以下按当前分数匹配度自动排序；「发展阶段」标注职业发展期的进入路径（学历起点/执业资格/认证要求）；<span class="tag-new">2026 新增</span>项对应人社部新增的 AI训练师、碳管理师、无人机群飞行规划员等 30+ 新职业，聚焦 AI 数字经济、绿色低碳、健康养老、低空经济、智慧农业五大高增长赛道：</p>
    <div class="top-chips">{chips}</div>
    {_fit_table(R["careers"], True, "发展阶段")}
  </section>'''


def sec_course(R: dict) -> str:
    top = R["courses"][0] if R["courses"] else None
    age = parse_float(R["meta"].get("age"))
    has_age = math.isfinite(age)
    items = R["courses"]
    filtered = False
    if has_age:
        ok = [item for item in R["courses"] if age_ok(item.get("age"), age)]
        if ok:
            items = ok
            filtered = True
    if has_age:
        if filtered:
            tip = (
                f'按当前年龄 {age_text(age)} 岁过滤：达到建议起步年龄的课程共 '
                f'<b>{len(items)}/{len(R["courses"])}</b> 门'
            )
        else:
            tip = "已按年龄过滤（暂无完全适龄课程，显示全部）"
    else:
        tip = "⚠ 未填写年龄，暂不过滤 — 可在页面上方「报告设置」填写年龄后重新生成"
    highlight = (
        f'<div class="highlight-box">🏫 当前匹配度最高的课程：<b>{esc(top["n"])}</b>'
        f'（{fmt(top["fit"])} 分）· 建议年龄 <b>{esc(top.get("age") or "—")}</b> — 对应指标：{esc(top["indNames"])}</div>'
        if top
        else ""
    )
    rows = "".join(
        f'<tr><td>{index + 1}</td><td>{esc(item["n"])}{_new_tag(item)}</td>'
        f'<td class="td-sm">{esc(item.get("age") or "—")}</td><td><b>{fmt(item["fit"])}</b></td>'
        f'<td class="td-sm">{esc(item["indNames"])}</td></tr>'
        for index, item in enumerate(items)
    )
    filtered_note = (
        f'<p class="note">🔒 已按年龄 {age_text(age)} 岁过滤，仅显示达到建议起步年龄的 {len(items)} 门课程。</p>'
        if filtered
        else ""
    )
    return f'''<section class="sec" id="s12">
    <h2>十二、课程规划建议（32 门课程 × 指标匹配）</h2>
    <p class="note">按家长需求的课程类型，以主要智能的核心指标优势/弱势出发规划。以下按「课程对应指标均分」自动匹配排序；「建议年龄」依据手册《智能开发最佳时期对应表》《天赋智能时效窗》与敏感期阶段标注，早于起步年龄可先做亲子体验式接触；<span class="tag-new">2026 新增</span>门类结合教育部 2026 课标修订（AI 编程每周≥1 课时、科学「做中学」领航行动、跨学科主题学习≥15%、心理健康课时提升至 3%）与少儿素质教育市场趋势（AIGC 启蒙、STEM、信奥进阶）：</p>
    <div class="age-filter"><span class="age-filter-tip">{tip}</span></div>
    {highlight}
    <table class="tbl"><thead><tr><th>#</th><th>课程</th><th>建议年龄</th><th>匹配分</th><th>对应核心指标</th></tr></thead>
    <tbody>{rows}</tbody></table>
    {filtered_note}
  </section>'''


def sec_behavior(R: dict) -> str:
    chips = "".join(
        f'<span class="chip chip-warn">⚠ {esc(item["n"])}</span>'
        for item in R["behaviors"][:5]
    )
    items = "".join(
        f'<div class="beh-item {"beh-hot" if index < 5 else ""}">'
        f'<div class="beh-hd"><span class="beh-n">{esc(item["n"])}</span>'
        f'<span class="beh-fit">关联均分 {fmt(item["fit"])}{" · 重点关注" if index < 5 else ""}</span></div>'
        f'<p class="beh-ind"><b>对应指标：</b>{esc(item["indNames"])}</p>'
        f'<p class="beh-note">{esc(item["note"])}</p></div>'
        for index, item in enumerate(R["behaviors"])
    )
    return f'''<section class="sec" id="s13">
    <h2>十三、行为 × 指标速查（家长常规提问）</h2>
    <p class="note">行为问题先判断与哪些智慧领域有关，再依核心指标给建议。以下按「关联指标均分」从低到高排序——<b>均分越低，越可能是当前最需要家长关注的方面</b>（Top 5 已标注）：</p>
    <div class="top-chips">{chips}</div>
    <div class="beh-list">{items}</div>
  </section>'''


def sec_timing(R: dict) -> str:
    age = parse_float(R["meta"].get("age"))

    def table(rows, label):
        body = []
        for row in rows:
            hit = False
            if math.isfinite(age):
                span = parse_age_range(row[1])
                hit = bool(span and span[0] <= age <= span[1])
            prefix = '<td class="hit-tag">🔔</td>' if hit else ""
            body.append(
                f'<tr class="{"row-hit" if hit else ""}">{prefix}<td>{esc(row[0])}</td>'
                f'<td>{esc(row[1])}</td><td>{esc(row[2])}</td></tr>'
            )
        return (
            f'<table class="tbl"><thead><tr><th>{label}</th><th>最佳开发期</th><th>常规实效</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>'
        )

    hits = []
    if math.isfinite(age):
        for row in DEV_WINDOW:
            span = parse_age_range(row[1])
            if span and span[0] <= age <= span[1]:
                hits.append(row)
    highlight = (
        f'<div class="highlight-box">🔔 按受测者年龄 {age_text(age)} 岁，当前正处于以下开发窗口内：'
        f'<b>{"、".join(esc(item[0]) for item in hits)}</b> ——建议把握时机、重点培养。</div>'
        if math.isfinite(age) and hits
        else ""
    )
    sensitive = "".join(
        f'<div class="sp-item"><b>{esc(item[0])}</b><span>{esc(item[1])}</span></div>'
        for item in SENSITIVE_PERIOD
    )
    return f'''<section class="sec" id="s14">
    <h2>十四、敏感期与天赋时效窗</h2>
    <p class="note">0-12 岁是多元智慧发展的最关键期；抓住关键期事半功倍，错过则需几倍努力弥补。0-4 岁智力发展已达成年 50%，8 岁达 80%。</p>
    {highlight}
    <h3>智能开发最佳时期对应表</h3>
    {table(DEV_WINDOW, "智能特长")}
    <h3>天赋智能时效窗</h3>
    {table(TIMING_WINDOW, "天赋名称")}
    <h3>八大智能敏感期（培训手册）</h3>
    <div class="sp-grid">{sensitive}</div>
  </section>'''


def sec_script(R: dict) -> str:
    script = R["script"]
    return f'''<section class="sec" id="s15">
    <h2>十五、家长话术参考（自动生成）</h2>
    <div class="script-box">
      <h3>回应原则</h3>
      <p>{esc(script["principle"])}</p>
      <h3>自动生成示例话术（以强带弱）</h3>
      <p class="script-demo">{esc(script["example"])}</p>
      <h3>话术要点提示</h3>
      <ul class="script-tips">
        <li>先看优势、以优势带动弱势；从优势能力中的细项给更贴近需求的建议。</li>
        <li>课程规划：按家长需求的课程类型，以主要智能的核心指标优势、弱势出发规划（参考第十二节 32 门课程匹配表）。</li>
        <li>行为问题：先判断行为与哪些智慧领域有关（参考第十三节行为速查表），再依核心指标给建议。</li>
        <li>全程保持正面角度解读，非鉴定单位，让家长放心。</li>
      </ul>
    </div>
  </section>'''


def sec_next(R: dict) -> str:
    age = parse_float(R["meta"].get("age"))
    has_age = math.isfinite(age)
    top = R["adv"][0] if len(R["adv"]) > 0 else None
    second = R["adv"][1] if len(R["adv"]) > 1 else top
    third = R["adv"][2] if len(R["adv"]) > 2 else second
    weakest = R["weak"][-1] if R["weak"] else None
    wd = R["wudao"][0] if R["wudao"] else None
    diag = R["diagonals"][0] if R["diagonals"] else None
    if not (top and second and third and weakest and wd and diag):
        return ""

    ok_talent = [item for item in R["talents"] if age_ok(item.get("age"), age)] if has_age else R["talents"]
    ok_course = [item for item in R["courses"] if age_ok(item.get("age"), age)] if has_age else R["courses"]

    def short(value):
        return str(value or "").split("（")[0]

    def pick(items, count):
        return "、".join(short(item["n"]) for item in items[:count]) or "—"

    script = R["script"]
    hero = (
        f"三大优势是「{esc(top['name'])}、{esc(second['name'])}、{esc(third['name'])}」，"
        f"相对最需要耐心引导的是「{esc(weakest['name'])}」；"
        f"最容易吸收知识的方式是「{esc(wd['name'])}（{esc(wd['type'])}）」，"
        f"先天学习通道偏向「{esc(diag['type'])}学习者」。"
        + (
            f"当前 {age_text(age)} 岁，正处于天赋培养的关键窗口期。"
            if has_age
            else "（未填写年龄，敏感期与适龄推荐未做个性化匹配，建议补填后重新生成。）"
        )
    )

    steps = [
        {
            "tag": "第 1 步 · 本周就做",
            "t": "先换辅导方式，再谈成绩",
            "d": (
                f"家庭辅导、讲知识点时优先走「{esc(wd['name'])}」通道：{esc(wd['strong'])}。"
                "先在最有优势的科目试用 1-2 周，看到配合度提升后再推广到其他科目——方式对了，接受速度会明显不一样。"
            ),
        },
        {
            "tag": "第 2 步 · 1 个月内",
            "t": "给优势智能安排一次「试水」",
            "d": (
                f"从匹配度最高的方向里挑 <b>1-2 项</b>安排体验（切忌一次报多班）："
                f"才艺方向 {esc(pick(ok_talent, 3))}；课程方向 {esc(pick(ok_course, 3))}"
                + (f"（均已按 {age_text(age)} 岁过滤为适龄项目）。" if has_age else "。")
                + "体验期连续观察 2-4 周，只看两件事：是否专注、回家后是否主动想继续。"
            ),
        },
        {
            "tag": "第 3 步 · 3-6 个月",
            "t": "定 1 个主方向 + 1 组「以强带弱」",
            "d": (
                f"主攻「{esc(top['name'])}」相关的 1 项深度培养（考级/展演/项目均可，让积累被看见）；"
                "同时做一组强弱搭配："
                + (
                    f"用「{esc(IND[script['topInd']['k']]['n'])}」的擅长场景（{esc(top['name'])}中的强项）"
                    f"带动「{esc(IND[script['botInd']['k']]['n'])}」（{esc(weakest['name'])}中的短板），"
                    "具体做法见上方「改善建议」。"
                    if script.get("topInd") and script.get("botInd")
                    else "用优势智能中的强项指标带动弱势智能中的短板指标，具体做法见第七节逐项解读。"
                )
                + "一学期只保留 1-2 项深度兴趣，其余以广泛接触为主。"
            ),
        },
    ]

    cautions = []
    rev_high = [item["name"] for item in R["revHigh"] if not item.get("isIntel")][:3]
    rev_low = [item["name"] for item in R["revLow"] if not item.get("isIntel")][:3]
    if rev_high:
        cautions.append(
            {
                "t": "「" + "」「".join(esc(name) for name in rev_high) + "」为高分反转项",
                "d": "分数高≠可以无限加码：对这类活动自我要求高、呈选择性，只挑自己喜欢的做。保持欣赏即可，苛求完美或强迫加练容易适得其反（强中转弱）。",
            }
        )
    if rev_low:
        cautions.append(
            {
                "t": "「" + "」「".join(esc(name) for name in rev_low) + "」为低分反转项",
                "d": "分数低≠没天赋：这类活动可能出现意外好效果。多创造低门槛、无考核的尝试机会，观察 2-3 次再下结论，不要一票否决。",
            }
        )
    beh_top = R["behaviors"][:2]
    if beh_top and beh_top[0]["fit"] < STATUS_STANDARD:
        cautions.append(
            {
                "t": f"行为信号：{esc('、'.join(item['n'] for item in beh_top))} 当前更值得关注",
                "d": "关联指标均分偏低，是现阶段家庭教育的重点课题。先看第十三节对应建议调整应对方式，行为改善通常滞后于方法调整，给 4-6 周观察期。",
            }
        )
    if has_age:
        hits = [
            row for row in DEV_WINDOW
            if (span := parse_age_range(row[1])) and span[0] <= age <= span[1]
        ]
        if hits:
            cautions.append(
                {
                    "t": f"敏感期窗口：{esc('、'.join(row[0] for row in hits))} 正当时",
                    "d": f"当前 {age_text(age)} 岁正处于上述天赋的最佳开发期（详见第十四节），培养投入回报最高；错过窗口后需数倍努力弥补，建议优先安排、重点保障。",
                }
            )
    cautions.append(
        {
            "t": "三个「不要」",
            "d": "① 不要贴标签——不说「你就是数学不行」，分数是当前快照不是终身定论；② 不要横向比较——不拿「别人家孩子」对标弱势项；③ 不要贪多——同时超过 2 个培训班会挤占自由探索时间，反而抑制天赋显现。",
        }
    )

    timeline = [
        {"t": "每 1-2 年", "d": "复测一次多元智能，动态跟踪分数变化（培养会改变强弱格局），据此调整方向。"},
        {"t": "每学期", "d": "做一次复盘：保留 1-2 项深度兴趣 + 学校课业平衡，砍掉持续抗拒的项目。"},
        {"t": "有疑虑时", "d": "涉及注意力、情绪、发育等专业问题，本报告不具诊断意义，请寻求专业咨询师或医疗机构面对面评估。"},
    ]

    step_html = "".join(
        f'<div class="next-step"><div class="ns-tag">{esc(step["tag"])}</div>'
        f'<div class="ns-t">{esc(step["t"])}</div><p class="ns-d">{step["d"]}</p></div>'
        for step in steps
    )
    caution_html = "".join(
        f'<div class="cau-item"><div class="cau-t">{item["t"]}</div>'
        f'<p class="cau-d">{esc(item["d"])}</p></div>'
        for item in cautions
    )
    timeline_html = "".join(
        f'<div class="tl-item"><div class="tl-k">{esc(item["t"])}</div>'
        f'<p class="tl-d">{esc(item["d"])}</p></div>'
        for item in timeline
    )
    return f'''<section class="sec" id="s16">
    <h2>十六、总结 · 接下来该怎么做（白话版）</h2>
    <p class="note">本节把前面 16 节的结论压缩成「一句话画像 + 三步行动 + 注意事项 + 长期节奏」，按顺序执行即可；每条建议都能在对应章节找到依据。</p>
    <div class="next-hero"><span class="nh-k">天赋一句话</span><p>{hero}</p></div>
    <div class="next-steps">{step_html}</div>
    <h3>⚠️ 特别注意（避坑清单）</h3>
    <div class="next-caution">{caution_html}</div>
    <h3>🗓 长期节奏</h3>
    <div class="next-tl">{timeline_html}</div>
    <div class="highlight-box">✅ 一句话记住：先顺着天性养优势，再用优势带弱势，按敏感期排优先级——教育不是补齐短板，而是让长板更长、短板够用。</div>
  </section>'''


def sec_topic(R: dict) -> str:
    from mhagent.mi import topics as topics_module

    return topics_module.render_topic_section(R)


def report_sections(R: dict) -> list[str]:
    """固定输出第 1–17 章，不做模式裁剪。"""
    return [
        sec_overview(R),
        sec_scoring(R),
        sec_diagonal(R),
        sec_brain(R),
        sec_wudao(R),
        sec_s12(R),
        sec_indicators(R),
        sec_similar(),
        sec_talent(R),
        sec_major(R),
        sec_career(R),
        sec_course(R),
        sec_behavior(R),
        sec_timing(R),
        sec_script(R),
        sec_next(R),
        sec_topic(R),
    ]


def render_report(R: dict) -> str:
    from mhagent.mi import topics as topics_module

    meta = R["meta"]
    purpose_name = ""
    purpose = meta.get("purpose")
    if purpose and purpose != "all":
        item = topics_module.PURPOSES.get(purpose)
        if item:
            purpose_name = item["name"]
    mode_chip = "<span>解读模式：完整版（1-17 项）</span>"
    edition_text = "成年版（职业发展）" if meta.get("edition") == "adult" else "教育版（成长培养）"
    who_text = "孩子 / 他人（家长视角）" if meta.get("who") == "kid" else "本人（自测视角）"
    gender = meta.get("gender") or ""
    age = meta.get("age") or ""
    job = meta.get("job") or ""
    note = meta.get("note") or ""
    purpose_chip = f"<span>解读目的：{esc(purpose_name)}</span>" if purpose_name else ""
    age_chip = f"<span>年龄：{esc(age)} 岁</span>" if age else ""
    gender_chip = f"<span>性别：{esc(gender)}</span>" if gender else ""
    job_text = esc(job) if job else "—"
    job_chip = f"<span>职业：{job_text}</span>" if meta.get("edition") == "adult" else ""
    note_chip = f"<span>备注：{esc(note)}</span>" if note else ""
    report_source = R.get("reportSource") or {}
    source_title = str(report_source.get("title") or "提交报告")
    source_chip = (
        f"<span>数据来源：提交报告《{esc(source_title)}》</span>" if report_source else ""
    )
    disclaimer = (
        "⚠ 本报告为系统自动初判，供检测者本人参考，非鉴定报告、不具医学诊断意义；"
        "涉及健康或心理困扰请咨询专业人士。"
        if meta.get("who") != "kid"
        else "⚠ 本报告为系统自动初判，供解读师与家长参考，非鉴定报告、不具医学诊断意义；"
        "最终以专业咨询师一对一解读为准。"
    )
    generated = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    html = f'''<div class="report-hd">
    <h1>多元智能检测 · 自动解读报告</h1>
    <p class="rep-sub">依据官方报告模板与解读手册 SOP 自动生成 · 生成时间 {esc(generated)}</p>
    <div class="rep-meta">{mode_chip}<span>版本：{edition_text}</span>{purpose_chip}<span>受测者：{esc(meta.get("name"))}</span>{age_chip}{gender_chip}{job_chip}<span>解读对象：{who_text}</span>{source_chip}{note_chip}</div>
  </div>
  <div class="disclaimer">{disclaimer}</div>
  {sec_report_source(R) if report_source else sec_fusion(R)}
  {"".join(report_sections(R))}
  <div class="rep-foot">本报告依据《多元智能检测报告模板》与《多元智能教育咨询师培训手册》整理生成 · 解读原则：看细项不看总分 · 以优势带动弱势 · 因材施教</div>'''
    return topics_module.subject_tune(html, meta.get("who") or "me")


# ---------------------------------------------------------------- 对外入口


def build_meta(profile: dict, options: dict | None = None) -> dict:
    options = options or {}
    nickname = str(profile.get("nickname") or "").strip() or "受测者"
    age = str(options.get("age") or "").strip()
    if not age:
        age = first_number(profile.get("age_range"))
    gender = str(options.get("gender") or "").strip()
    if gender not in ("男", "女"):
        gender = ""
    age_value = parse_float(age)
    edition = options.get("edition")
    if edition not in ("edu", "adult"):
        edition = "adult" if (math.isfinite(age_value) and age_value > AGE_ADULT_THRESHOLD) else "edu"
    who = options.get("who")
    if who not in ("me", "kid"):
        who = "me"
    purpose = str(options.get("purpose") or "").strip() or "all"
    job = str(options.get("job") or "").strip()
    return {
        "name": nickname,
        "age": age,
        "gender": gender,
        "edition": edition,
        "who": who,
        "purpose": purpose,
        "job": job,
        "note": "",
        "mode": "interpreter",
    }


def render_interpretation_report(
    result: dict,
    profile: dict,
    options: dict | None = None,
    gene: dict | None = None,
    source: dict | None = None,
) -> dict:
    """生成解读报告 HTML。

    `source.kind == "report"` 时结果来自会话提交的报告，用来源块替代融合块。
    返回 `{"available": True, "html": str, "meta": dict, "generated_at": str, "source": dict, "gene": dict|None}`。
    """
    meta = build_meta(profile, options)
    report = analyze_report(result, meta)
    report["fusionVersion"] = str(result.get("fusion_version") or "FUSION-1.0")
    is_report = (source or {}).get("kind") == "report" or (
        result.get("fusion_version") == "REPORT-OVERRIDE"
    )
    if is_report:
        report["reportSource"] = source or {"kind": "report", "title": "提交报告"}
        report["fusion"] = None
    else:
        report["fusion"] = build_fusion(result, gene)
    html = render_report(report)
    gene_info = None
    if gene:
        gene_info = {
            "filename": gene.get("filename") or "",
            "confidence": gene.get("confidence") or "",
            "uploaded_at": gene.get("uploaded_at") or "",
        }
    source_info = report.get("reportSource") or dict(source or {})
    if not source_info:
        source_info = {"kind": "assessment", "label": "基础测评"}
    return {
        "available": True,
        "html": html,
        "meta": meta,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": source_info,
        "gene": gene_info,
    }


__all__ = [
    "analyze_report",
    "build_meta",
    "render_interpretation_report",
    "render_report",
    "report_sections",
    "report_data",
]

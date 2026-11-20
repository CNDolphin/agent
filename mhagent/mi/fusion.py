"""三源融合（FUSION-1.0）。

- 场景 A（问卷 + 排序，无基因）：指标 inner = 0.4*问卷分 + 0.6*排序目标分；
  随后智能级整组向排序目标分靠拢 0.5。
- 场景 B（有基因）：智能 final = 0.65*基因分 + 0.35*场景 A 智能分；
  该智能下 5 项指标按同一差值整体位移。
- 反转豁免：问卷分 >77 或 <33 的指标不参与混合与位移，保留问卷原始值。
- 所有输出取整并限制在 0–100。
"""

from __future__ import annotations

from mhagent.mi.quiz import QuestionBank, QuizError

FUSION_VERSION = "FUSION-1.0"
INTEL_TARGET_START = 72.5
INTEL_TARGET_STEP = 5.0
IND_TARGETS = (75.0, 65.0, 55.0, 45.0, 35.0)
QUIZ_WEIGHT = 0.4
RANK_WEIGHT = 0.6
GENE_WEIGHT = 0.65
INNER_WEIGHT = 0.35
SHIFT_WEIGHT = 0.5
EXEMPT_HIGH = 77
EXEMPT_LOW = 33


def _clamp(value: float) -> int:
    return int(round(max(0.0, min(100.0, value))))


def intel_target(rank: int) -> float:
    """智能排序名次（1 起）对应的目标分：72.5 起，每名递减 5。"""
    if not 1 <= rank <= 8:
        raise QuizError("智能排序必须覆盖 8 项且在 1–8 名之间")
    return INTEL_TARGET_START - (rank - 1) * INTEL_TARGET_STEP


def indicator_target(rank: int) -> float:
    """组内指标排名（1 起）对应的目标分：75/65/55/45/35。"""
    if not 1 <= rank <= len(IND_TARGETS):
        raise QuizError("组内指标排序必须覆盖 5 项且在 1–5 名之间")
    return IND_TARGETS[rank - 1]


def _normalize_order(order, expected: list[str], label: str) -> list[str]:
    if not isinstance(order, (list, tuple)):
        raise QuizError(f"{label}排序缺失")
    cleaned = [str(item) for item in order]
    if sorted(cleaned) != sorted(expected):
        raise QuizError(f"{label}排序必须完整覆盖：{'、'.join(expected)}")
    return cleaned


def _normalize_gene(gene, intel_ids: list[str]) -> dict[str, float] | None:
    if not gene:
        return None
    scores = gene.get("scores") if isinstance(gene, dict) else None
    if not isinstance(scores, dict):
        return None
    normalized: dict[str, float] = {}
    for iid in intel_ids:
        value = scores.get(iid)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        normalized[iid] = max(0.0, min(100.0, number))
    return normalized


def fuse_scores(quiz_result, intel_rank, ind_rank, gene=None, bank: QuestionBank | None = None) -> dict:
    """融合问卷、排序与基因，返回 8 智能与 40 项最终分。

    `quiz_result` 为 `score_quiz()` 的返回值；`intel_rank` 是 8 个智能 id 的
    排序（最强在前）；`ind_rank` 是 `{智能id: [5 个指标 id]}`。
    """
    bank = bank or QuestionBank.load()
    intel_ids = bank.intel_ids
    intel_order = _normalize_order(intel_rank, intel_ids, "智能")
    intel_rank_map = {iid: index + 1 for index, iid in enumerate(intel_order)}

    quiz_indicators = quiz_result.get("indicators") or {}
    gene_scores = _normalize_gene(gene, intel_ids)

    ind_scores: dict[str, dict] = {}
    intel_scores: dict[str, dict] = {}

    for intel in bank.intelligences:
        iid = intel["id"]
        ind_ids = [ind["id"] for ind in intel["indicators"]]
        order = _normalize_order((ind_rank or {}).get(iid), ind_ids, f"{intel['name']}组内指标")
        rank_map = {ind_id: index + 1 for index, ind_id in enumerate(order)}

        inner_values: dict[str, float] = {}
        for ind_id in ind_ids:
            quiz_score = (quiz_indicators.get(ind_id) or {}).get("score")
            if quiz_score is None:
                raise QuizError(f"指标 {ind_id} 尚未完成作答")
            quiz_score = float(quiz_score)
            target = indicator_target(rank_map[ind_id])
            if quiz_score > EXEMPT_HIGH or quiz_score < EXEMPT_LOW:
                inner_values[ind_id] = quiz_score
            else:
                inner_values[ind_id] = QUIZ_WEIGHT * quiz_score + RANK_WEIGHT * target

        inner_mean = sum(inner_values.values()) / len(inner_values)
        final_values: dict[str, float] = {}
        if gene_scores is not None:
            final_intel = GENE_WEIGHT * gene_scores[iid] + INNER_WEIGHT * inner_mean
            shift = final_intel - inner_mean
            for ind_id in ind_ids:
                quiz_score = float(quiz_indicators[ind_id]["score"])
                if quiz_score > EXEMPT_HIGH or quiz_score < EXEMPT_LOW:
                    final_values[ind_id] = quiz_score
                else:
                    final_values[ind_id] = inner_values[ind_id] + shift
            source = "gene+quiz+rank"
        else:
            target = intel_target(intel_rank_map[iid])
            shift = SHIFT_WEIGHT * (target - inner_mean)
            for ind_id in ind_ids:
                quiz_score = float(quiz_indicators[ind_id]["score"])
                if quiz_score > EXEMPT_HIGH or quiz_score < EXEMPT_LOW:
                    final_values[ind_id] = quiz_score
                else:
                    final_values[ind_id] = inner_values[ind_id] + shift
            final_intel = sum(final_values.values()) / len(final_values)
            source = "quiz+rank"

        for ind_id in ind_ids:
            final_score = _clamp(final_values[ind_id])
            ind_scores[ind_id] = {
                "id": ind_id,
                "name": bank.indicator(ind_id)["name"],
                "intelligence": iid,
                "quiz": round(float(quiz_indicators[ind_id]["score"]), 1),
                "inner": round(inner_values[ind_id], 1),
                "score": final_score,
                "rank": rank_map[ind_id],
            }
        intel_scores[iid] = {
            "id": iid,
            "name": intel["name"],
            "score": _clamp(final_intel),
            "inner": round(inner_mean, 1),
            "rank": intel_rank_map[iid],
            "source": source,
        }

    intel_ranking = sorted(intel_scores, key=lambda iid: intel_scores[iid]["score"], reverse=True)
    return {
        "intel": intel_scores,
        "ind": ind_scores,
        "ranking": intel_ranking,
        "fusion_version": FUSION_VERSION,
        "gene_used": gene_scores is not None,
    }

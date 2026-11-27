"""多元智能测评：题库、计分、融合与基础记忆。"""

from __future__ import annotations

from mhagent.mi.fusion import FUSION_VERSION, fuse_scores
from mhagent.mi.memory import build_memory_text
from mhagent.mi.quiz import QuestionBank, QuizError, normalize_answers, score_quiz
from mhagent.mi.report import analyze_report, build_meta, render_interpretation_report

__all__ = [
    "FUSION_VERSION",
    "QuestionBank",
    "QuizError",
    "analyze_report",
    "build_memory_text",
    "build_meta",
    "fuse_scores",
    "normalize_answers",
    "render_interpretation_report",
    "score_quiz",
]

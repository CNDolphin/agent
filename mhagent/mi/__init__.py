"""多元智能测评：题库、计分、融合与基础记忆。"""

from __future__ import annotations

from mhagent.mi.fusion import FUSION_VERSION, fuse_scores
from mhagent.mi.memory import build_memory_text
from mhagent.mi.quiz import QuestionBank, QuizError, normalize_answers, score_quiz

__all__ = [
    "FUSION_VERSION",
    "QuestionBank",
    "QuizError",
    "build_memory_text",
    "fuse_scores",
    "normalize_answers",
    "score_quiz",
]

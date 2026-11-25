"""对话循环:安全优先的状态机。

状态:`NORMAL` / `ASSESSING(scale, index, answers)` / `PRACTICING(id, step)` / `CRISIS`。

每轮流程:
1. 规则安全检查;HIGH 立即输出危机话术,不调用网关;
2. 技能路由与工具调用(评估状态下收集答案并确定性处理);
3. 调用 LLM(系统提示词 + 技能正文 + 近期上下文,按字符预算裁剪);
4. 对模型回复做出站检查;
5. 模型复核(仅在规则为 LOW/MEDIUM 时,结果取最大值;复核失败不影响主流程);
6. 写本地加密会话记录。
"""

from __future__ import annotations

import inspect
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

from mhagent.consent import ConsentStore
from mhagent.insight.provider import FIXED_MESSAGE, get_provider
from mhagent.llm.base import (
    AuthExpired,
    DuplicateRequest,
    GatewayUnavailable,
    InsufficientCredits,
    LLMError,
)
from mhagent.prompts import build_messages, build_system_prompt
from mhagent.safety import (
    Risk,
    check_outbound,
    classify_rules,
    combine,
    crisis_message,
    from_phq9,
)
from mhagent.skill_loader import load_skill, route
from mhagent.tools.journal import Journal, JournalError
from mhagent.tools.practices import get_practice
from mhagent.tools.scales import (
    LEVEL_LABELS,
    SCALE_NAMES,
    load_questionnaire,
    score_gad7,
    score_phq9,
    score_pss10,
)

logger = logging.getLogger(__name__)


def _accepts_argument(provider) -> bool:
    """判断上下文提供方是否接受当前提问作为参数。"""
    try:
        params = inspect.signature(provider).parameters
    except (TypeError, ValueError):
        return True
    return any(
        param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD, param.VAR_POSITIONAL)
        for param in params.values()
    )


class State(str, Enum):
    NORMAL = "NORMAL"
    ASSESSING = "ASSESSING"
    PRACTICING = "PRACTICING"
    CRISIS = "CRISIS"


@dataclass
class AssessmentState:
    scale: str
    version: str
    index: int = 0
    answers: list[int] = field(default_factory=list)


@dataclass
class PracticeState:
    practice_id: str
    step: int = 0


@dataclass
class AssessmentOutcome:
    """一次量表提交的确定性结果,供 CLI 与界面共用。"""

    scale: str
    total: int
    max_total: int
    level: str
    label: str
    advice: str | None
    high_risk: bool
    notified: bool
    text: str


SCORERS = {"phq9": score_phq9, "gad7": score_gad7, "pss10": score_pss10}

CRISIS_COPY_TEXT = (
    "我现在状态很不好,需要你陪着我。如果联系不上我,请帮我拨打 12356 或 120。"
)

LOW_BALANCE_HINT = "\n\n（提示：你的积分余额较低，可购买套餐获取积分。）"

EXIT_WORDS = (
    "不想继续", "退出", "停止评估", "不做了", "算了", "结束评估", "停止",
    "换个话题", "答非所问", "不想答", "不想做", "别问了",
)
START_ASSESSMENT_WORDS = (
    "开始", "好的", "好呀", "好啊", "可以", "确认", "是的",
    "重新测评", "重新做", "再做一次", "嗯",
)
ASSESSMENT_COOLDOWN = timedelta(hours=24)
STOP_WORDS = ("停止", "不舒服", "不练了", "结束")
NEXT_WORDS = ("下一步", "继续", "好了", "完成")

_LEVEL_ADVICE = {
    "minimal": "当前筛查分数较低,可以继续保持规律作息,并留意自己的状态变化。",
    "mild": "筛查显示轻度困扰,可以从规律作息、情绪记录和小练习开始,观察一两周。",
    "moderate": "筛查显示中度困扰,建议把感受告诉信任的人,并考虑联系专业机构做进一步评估。",
    "moderately_severe": "筛查显示中重度困扰,建议尽快联系专业机构或医生做进一步评估。",
    "severe": "筛查显示重度困扰,建议尽快联系专业机构或医生;如果出现伤害自己的想法,请立即拨打 12356 或 120。",
}


def _parse_emotions(text: str) -> list[dict] | None:
    matches = re.findall(r"([\u4e00-\u9fa5A-Za-z]+)\s*[:：]?\s*(\d{1,2})", text)
    if not matches:
        return None
    emotions = []
    for name, value in matches:
        intensity = int(value)
        if intensity > 10:
            return None
        emotions.append({"name": name, "intensity": intensity})
    return emotions


class AgentLoop:
    def __init__(
        self,
        llm,
        store,
        *,
        journal: Journal | None = None,
        consent: ConsentStore | None = None,
        notifier=None,
        provider=None,
        clock=None,
        max_tokens: int = 1024,
        max_history_chars: int = 1600,
        skills_dir=None,
        context_provider=None,
        context_chars: int = 1200,
    ):
        self.llm = llm
        self.store = store
        self.journal = journal or Journal(store, now=clock)
        self.consent = consent
        self.notifier = notifier
        self.provider = provider or get_provider()
        self._clock = clock
        self.max_tokens = max_tokens
        self.max_history_chars = max_history_chars
        self.skills_dir = skills_dir
        self.context_provider = context_provider
        self.context_chars = context_chars

        self.state = State.NORMAL
        self._assessment: AssessmentState | None = None
        self._assessment_failures = 0
        self._pending_assessment: str | None = None
        self._practice: PracticeState | None = None
        self._journal_draft: dict | None = None
        self._journal_step: str | None = None
        self._history: list[dict] = []
        self._low_balance_notified = False
        self._crisis_notified = False

    # ---- 工具 ----
    def now(self) -> datetime:
        current = self._clock() if self._clock else datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc)

    def _authorized(self) -> bool:
        return bool(self.consent and self.consent.get().emergency_authorized)

    # ---- 会话切换 ----
    def reset_conversation(self, messages: list[dict]) -> None:
        """切换会话:清空进行中的评估/练习,并用历史消息重建上下文。"""
        self.state = State.NORMAL
        self._assessment = None
        self._assessment_failures = 0
        self._pending_assessment = None
        self._practice = None
        self._journal_draft = None
        self._journal_step = None
        self._crisis_notified = False
        self._low_balance_notified = False
        history = []
        for item in messages or []:
            role = str(item.get("role") or "")
            if role not in ("user", "assistant"):
                continue
            content = str(item.get("text") or item.get("content") or "")
            if content:
                history.append({"role": role, "content": content})
        self._history = history

    # ---- 入口 ----
    def handle(self, user_text: str) -> str:
        text = "" if user_text is None else str(user_text).strip()
        risk = classify_rules(text)
        if risk.level == Risk.HIGH:
            self._assessment = None
            self._pending_assessment = None
            reply = self._enter_crisis()
            self._record(text, reply)
            return reply
        reply = self._dispatch(text, risk)
        self._record(text, reply)
        return reply

    def _dispatch(self, text: str, risk) -> str:
        if self._journal_step:
            return self._handle_journal(text)
        if self.state == State.ASSESSING and self._assessment:
            return self._handle_assessment(text)
        if self.state == State.PRACTICING and self._practice:
            return self._handle_practice(text)
        if self.state == State.CRISIS:
            return self._handle_crisis_companion(text)
        if self._pending_assessment:
            return self._handle_pending_assessment(text, risk)
        return self._handle_normal(text, risk)

    # ---- 危机 ----
    def _enter_crisis(self, prefix: str = "") -> str:
        self.state = State.CRISIS
        self._assessment = None
        self._assessment_failures = 0
        self._pending_assessment = None
        self._practice = None
        self._journal_draft = None
        self._journal_step = None
        authorized = self._authorized()
        parts = []
        if prefix:
            parts.append(prefix)
        parts.append(crisis_message(authorized))
        if authorized:
            if not self._crisis_notified:
                self._crisis_notified = True
                try:
                    if self.notifier is not None:
                        self.notifier.send_emergency()
                        parts.append("已向你的紧急联系人发送通知。")
                    else:
                        parts.append("紧急通知通道未配置,请直接联系你的紧急联系人。")
                except Exception:
                    parts.append(
                        "紧急通知发送失败,下面是可复制的求助文字,请直接发给对方:\n" + CRISIS_COPY_TEXT
                    )
        return "\n\n".join(parts)

    def _handle_crisis_companion(self, text: str) -> str:
        self.state = State.CRISIS
        system = build_system_prompt(None, crisis=True)
        messages = build_messages(self._history, text, system, max_history_chars=self.max_history_chars)
        try:
            result = self.llm.chat(messages, max_tokens=self.max_tokens)
            content = check_outbound(result.content).text
        except LLMError:
            content = (
                "我在这里陪你。你愿意的话,可以说说现在身边有没有人。"
                "如果情况紧急,请拨打心理援助热线 12356 或急救电话 120。"
            )
        self._history.extend(
            [{"role": "user", "content": text}, {"role": "assistant", "content": content}]
        )
        return content

    # ---- 普通对话 ----
    def _handle_normal(self, text: str, risk, *, allow_assessment: bool = True) -> str:
        if self._is_weekly_review(text):
            return self._weekly_review_text()
        skill = route(text, self.skills_dir)
        context = self._context_text(text)
        if skill == "gene-guidance" and not getattr(self.provider, "enabled", False):
            # 没有已归档报告时保持“解读未启用”;有报告则允许概述内容(不给方向性建议)。
            if not context:
                return FIXED_MESSAGE
        if skill == "assessment" and allow_assessment:
            return self._confirm_assessment(text)
        if skill == "mental-health":
            if self._is_journal_start(text):
                return self._begin_journal()
            if self._is_practice_start(text):
                return self._begin_practice(text)
        body = load_skill(skill, self.skills_dir) if skill else None
        return self._chat(text, body, risk, context=context)

    def _context_text(self, user_text: str = "") -> str | None:
        """读取额外上下文(如已归档的检测报告);失败时不影响对话。"""
        provider = self.context_provider
        if not callable(provider):
            return None
        try:
            if _accepts_argument(provider):
                text = provider(user_text)
            else:
                text = provider()
        except Exception:
            logger.debug("构建报告记忆失败", exc_info=True)
            return None
        text = (text or "").strip()
        return text or None

    def _chat(self, text: str, skill_body: str | None, risk, *, context: str | None = None) -> str:
        system = build_system_prompt(
            skill_body,
            crisis=False,
            extra_context=context,
            max_context_chars=self.context_chars,
        )
        messages = build_messages(self._history, text, system, max_history_chars=self.max_history_chars)
        try:
            result = self.llm.chat(messages, max_tokens=self.max_tokens)
        except InsufficientCredits:
            return "积分不足，可购买套餐获取积分。危机热线 12356 与急救电话 120 始终可用。"
        except GatewayUnavailable:
            return "模型服务暂时不可用,请稍后重试。安全检查与危机热线仍然有效。"
        except AuthExpired:
            return "登录已过期,请重新登录后继续。"
        except DuplicateRequest:
            return "这条消息已经处理过了,请继续。"
        except LLMError:
            return "服务暂时不可用,请稍后重试。"

        content = check_outbound(result.content).text
        if result.low_balance and not self._low_balance_notified:
            self._low_balance_notified = True
            content += LOW_BALANCE_HINT
        self._history.extend(
            [{"role": "user", "content": text}, {"role": "assistant", "content": content}]
        )

        review = getattr(self.llm, "review_risk", None)
        if callable(review) and risk.level <= Risk.MEDIUM:
            try:
                review_level = review(text)
            except Exception:
                review_level = None
            if review_level is not None and combine(risk.level, review_level) == Risk.HIGH:
                return content + "\n\n" + self._enter_crisis()
        return content

    # ---- 评估 ----
    def _pick_scale(self, text: str) -> str:
        lowered = text.lower()
        if "焦虑" in lowered or "gad" in lowered:
            return "gad7"
        if "压力" in lowered or "pss" in lowered:
            return "pss10"
        return "phq9"

    def _recent_assessment(self, scale: str) -> dict | None:
        """最近 24 小时内已完成的同量表记录;用于避免重复自动触发筛查。"""
        if not self.store:
            return None
        try:
            records = self.store.list_records(
                "assessment", since=self.now() - ASSESSMENT_COOLDOWN
            )
        except Exception:
            logger.debug("读取历史评估失败", exc_info=True)
            return None
        for record in reversed(records):
            payload = record.get("payload") or {}
            if payload.get("scale") == scale:
                return record
        return None

    def _confirm_assessment(self, text: str) -> str:
        """先确认再做:不把普通对话里的词直接变成一轮问答。"""
        scale = self._pick_scale(text)
        questionnaire = load_questionnaire(scale)
        if not questionnaire.available:
            return (
                f"{SCALE_NAMES.get(scale, scale)}该量表暂不可用"
                "(题目文本待授权确认)。你可以先做 PHQ-9 抑郁筛查或 GAD-7 焦虑筛查。"
            )
        self.state = State.NORMAL
        self._pending_assessment = scale
        name = SCALE_NAMES.get(scale, scale)
        recent = self._recent_assessment(scale)
        if recent is not None:
            payload = recent.get("payload") or {}
            level = str(payload.get("level", ""))
            label = LEVEL_LABELS.get(level, level)
            return (
                f"你在最近 24 小时内已经完成过一次{name}"
                f"(总分 {payload.get('total')}/{payload.get('max_total')},{label})。\n"
                "如果确实想重做,回复「重新测评」;回复其他内容我们继续聊。"
            )
        return (
            f"看起来你想做一次{name}(共 {len(questionnaire.items)} 题,大约两分钟)。\n"
            "回复「开始」我就开始;回复其他内容我们继续聊,不做也没关系。"
        )

    def _handle_pending_assessment(self, text: str, risk) -> str:
        scale = self._pending_assessment
        self._pending_assessment = None
        if any(word in text for word in START_ASSESSMENT_WORDS):
            return self._begin_assessment(scale)
        # 未确认就按普通对话处理,且本轮不再触发筛查,避免"问了又问"。
        return self._handle_normal(text, risk, allow_assessment=False)

    def _begin_assessment(self, scale: str) -> str:
        questionnaire = load_questionnaire(scale)
        if not questionnaire.available:
            return (
                f"{SCALE_NAMES.get(scale, scale)}该量表暂不可用"
                "(题目文本待授权确认)。你可以先做 PHQ-9 抑郁筛查或 GAD-7 焦虑筛查。"
            )
        self._assessment = AssessmentState(
            scale=scale, version=questionnaire.version, index=0, answers=[]
        )
        self._assessment_failures = 0
        self.state = State.ASSESSING
        return (
            "这是一次筛查,结果是筛查提示,不是诊断。\n"
            "请按最近两周的真实情况作答,随时回复「退出」可以结束。\n\n"
            + self._question_text()
        )

    def _question_text(self) -> str:
        current = self._assessment
        questionnaire = load_questionnaire(current.scale)
        item = questionnaire.items[current.index]
        options = " / ".join(f"{opt['value']} {opt['label']}" for opt in questionnaire.options)
        return (
            f"第 {current.index + 1}/{len(questionnaire.items)} 题:{item}\n"
            f"请回复序号或选项文字:{options}"
        )

    def _parse_answer(self, text: str) -> int | None:
        current = self._assessment
        questionnaire = load_questionnaire(current.scale)
        number = re.search(r"\d+", text)
        if number:
            value = int(number.group())
            if value in [int(opt["value"]) for opt in questionnaire.options]:
                return value
            return None
        for opt in questionnaire.options:
            if str(opt["label"]) in text:
                return int(opt["value"])
        return None

    def _handle_assessment(self, text: str) -> str:
        if any(word in text for word in EXIT_WORDS):
            self._assessment = None
            self._assessment_failures = 0
            self.state = State.NORMAL
            return (
                "好的,已退出这次评估,答案不会保存。"
                "我们可以继续聊别的;想重新做可以回复「重新测评」。"
            )
        value = self._parse_answer(text)
        if value is None:
            self._assessment_failures += 1
            if self._assessment_failures >= 2:
                # 连续答不上来说明用户并不在做题:退出,避免把后续对话全部吞掉。
                self._assessment = None
                self._assessment_failures = 0
                self.state = State.NORMAL
                return (
                    "看起来你现在不想按题目回答,我先退出这次筛查,答案不会保存。\n"
                    "我们可以继续聊别的;想重新做可以回复「重新测评」。"
                )
            return (
                "我没太明白,请回复选项序号或选项文字;"
                "如果不想继续,回复「退出」。\n" + self._question_text()
            )
        self._assessment_failures = 0
        current = self._assessment
        current.answers.append(value)
        current.index += 1
        questionnaire = load_questionnaire(current.scale)
        if current.index >= len(questionnaire.items):
            return self._finish_assessment()
        return self._question_text()

    def _finish_assessment(self) -> str:
        current = self._assessment
        outcome = self.evaluate_assessment(
            current.scale, current.answers, version=current.version
        )
        self._assessment = None
        if self.state != State.CRISIS:
            self.state = State.NORMAL
        return outcome.text

    def evaluate_assessment(
        self,
        scale: str,
        answers,
        *,
        persist: bool = True,
        version: str | None = None,
    ) -> AssessmentOutcome:
        """确定性计分与分级,供 CLI 与界面共用。

        `persist=True` 时写入本地 assessment 记录;PHQ-9 判定为 HIGH 时进入危机状态。
        答案非法或量表不可用时抛 `ValueError`(ScaleError 是其子类)。
        """
        questionnaire = load_questionnaire(scale)
        if not questionnaire.available:
            raise ValueError(f"{SCALE_NAMES.get(scale, scale)}暂不可用")
        if scale not in SCORERS:
            raise ValueError(f"未知的量表:{scale}")
        result = SCORERS[scale](answers)

        if persist and self.store:
            self.store.add_record(
                "assessment",
                {
                    "scale": scale,
                    "version": version or questionnaire.version,
                    "answers": list(answers),
                    "total": result.total,
                    "max_total": result.max_total,
                    "level": result.level,
                    "item9_score": result.item9_score,
                },
                created_at=self.now(),
            )

        label = LEVEL_LABELS.get(result.level, result.level)
        text = (
            f"{SCALE_NAMES.get(scale, scale)}结果:"
            f"总分 {result.total}/{result.max_total},分级:{label}({result.level})。\n"
            "这是一次筛查提示,不是诊断,也不能替代专业评估。"
        )
        advice = _LEVEL_ADVICE.get(result.level)
        if advice:
            text += "\n" + advice

        high_risk = False
        notified = False
        if scale == "phq9":
            risk = from_phq9(result)
            if risk.level == Risk.HIGH:
                high_risk = True
                crisis_text = self._enter_crisis()
                notified = "已向你的紧急联系人发送通知。" in crisis_text
                text = text + "\n\n" + crisis_text
            elif risk.level == Risk.MEDIUM:
                text += (
                    "\n你提到过伤害自己的念头,谢谢你说出来。愿意的话,"
                    "可以多说一点现在的状态;必要时请联系专业人士或拨打 12356。"
                )

        return AssessmentOutcome(
            scale=scale,
            total=result.total,
            max_total=result.max_total,
            level=result.level,
            label=label,
            advice=advice,
            high_risk=high_risk,
            notified=notified,
            text=text,
        )

    # ---- 练习 ----
    def _is_practice_start(self, text: str) -> bool:
        markers = ("呼吸", "放松", "冥想", "正念", "身体扫描", "接地", "练习")
        return any(marker in text for marker in markers)

    def _pick_practice(self, text: str) -> str:
        if "478" in text or "4-7-8" in text or "4—7—8" in text:
            return "breathing_478"
        if "箱式" in text:
            return "box_breathing"
        if "身体" in text or "扫描" in text:
            return "body_scan"
        if "接地" in text or "54321" in text or "5-4-3-2-1" in text:
            return "grounding_54321"
        if "呼吸" in text:
            return "breathing_478"
        return "box_breathing"

    def _begin_practice(self, text: str) -> str:
        practice_id = self._pick_practice(text)
        data = get_practice(practice_id)
        self._practice = PracticeState(practice_id, 0)
        self.state = State.PRACTICING
        step = data["steps"][0]
        return (
            f"我们一起做「{data['name']}」。{data['summary']}\n"
            f"第 1/{len(data['steps'])} 步:{step['instruction']}(约 {step['seconds']} 秒)\n"
            f"{data['stop_hint']}\n完成后回复「下一步」,不舒服请回复「停止」。"
        )

    def _handle_practice(self, text: str) -> str:
        current = self._practice
        data = get_practice(current.practice_id)
        if any(word in text for word in STOP_WORDS):
            self._practice = None
            self.state = State.NORMAL
            return "好的,我们停下来。" + data["stop_hint"]
        if any(word in text for word in NEXT_WORDS):
            current.step += 1
        if current.step >= len(data["steps"]):
            self._practice = None
            self.state = State.NORMAL
            return f"「{data['name']}」到这里就完成了。{data['stop_hint']}"
        step = data["steps"][current.step]
        return (
            f"第 {current.step + 1}/{len(data['steps'])} 步:{step['instruction']}"
            f"(约 {step['seconds']} 秒)\n完成后回复「下一步」,不舒服请回复「停止」。"
        )

    # ---- 日记 ----
    def _is_journal_start(self, text: str) -> bool:
        return "日记" in text or ("记录" in text and "情绪" in text)

    def _begin_journal(self) -> str:
        self._journal_draft = {"date": self.now().date().isoformat(), "emotions": []}
        self._journal_step = "event"
        return "好,我们记一笔情绪日记。\n第一步:刚才发生了什么?用一两句话说说事件。"

    def _handle_journal(self, text: str) -> str:
        draft = self._journal_draft
        if self._journal_step == "event":
            if not text:
                return "可以简单说说发生了什么,哪怕只有一句话。"
            draft["event"] = text
            self._journal_step = "emotions"
            return "当时有哪些情绪?请按「名称 强度」写,强度 0-10,例如:焦虑 8、疲惫 6。"
        if self._journal_step == "emotions":
            emotions = _parse_emotions(text)
            if not emotions:
                return "我没读到情绪和强度,可以写成「焦虑 8、疲惫 6」这样的格式。"
            draft["emotions"] = emotions
            self._journal_step = "thoughts"
            return "当时脑子里在想什么?不想写可以回复「跳过」。"
        if self._journal_step == "thoughts":
            thoughts = "" if text in {"跳过", "不写", "没有", "空"} else text
            entry = {**draft, "thoughts": thoughts, "note": ""}
            try:
                self.journal.add_entry(entry)
            except JournalError as exc:
                return f"这条记录没有保存:{exc}。可以补充完整后再说一次。"
            self._journal_draft = None
            self._journal_step = None
            return "已保存今天的情绪日记。想看这周的回顾,可以说「周回顾」。"
        self._journal_step = None
        return "我们接着聊。"

    def _is_weekly_review(self, text: str) -> bool:
        return "周回顾" in text or "本周回顾" in text

    def _weekly_review_text(self) -> str:
        today = self.now().date()
        week_start = today - timedelta(days=today.weekday())
        review = self.journal.weekly_review(week_start)
        if review is None:
            return "这周还没有情绪日记记录。想记录的时候告诉我。"
        top = "、".join(f"{item['name']}({item['count']}次)" for item in review["top_emotions"])
        lines = [
            f"本周({review['week_start']} 至 {review['week_end']})共记录 {review['count']} 条。",
            f"常见情绪:{top}",
            f"平均强度:{review['avg_intensity']}/10",
        ]
        if review["change"] is not None:
            direction = "上升" if review["change"] > 0 else "下降"
            lines.append(f"与上周相比,平均强度{direction} {abs(review['change'])}。")
        return "\n".join(lines) + "\n这只是你自己的记录趋势,不是诊断。"

    # ---- 记录 ----
    def snapshot(self) -> dict:
        """返回界面需要的状态快照,不含对话正文。"""
        state = self.state.value if isinstance(self.state, State) else str(self.state)
        return {
            "state": state,
            "assessing": self._assessment is not None,
            "practicing": self._practice is not None,
        }

    def _record(self, user_text: str, reply: str) -> None:
        if not self.store:
            return
        state = self.state.value if isinstance(self.state, State) else str(self.state)
        try:
            self.store.add_record(
                "session",
                {"user": user_text, "assistant": reply, "state": state},
                created_at=self.now(),
            )
        except Exception:
            # 本地记录失败不影响对话
            pass

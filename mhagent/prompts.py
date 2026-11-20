"""系统提示词与消息构造。

约束:角色边界明确(非医生、不诊断、不开药)、分数只能由工具计算、
危机时只做陪伴、总长度有上限。
"""

from __future__ import annotations

BASE_PROMPT = (
    "你是一个本地运行的心理健康支持助手。你不是医生,不具备诊断资质,"
    "不替代专业帮助。\n"
    "请遵守以下边界:\n"
    "1. 不诊断任何疾病,不推荐、不调整、不评价任何药物或保健品;\n"
    "2. 只做心理健康科普、情绪支持与自助练习引导,不承诺疗效;\n"
    "3. 量表分数与等级只能由工具计算并原样展示,禁止你自行计算、改写或猜测;\n"
    "4. 涉及诊断、用药或症状持续加重时,建议用户联系专业机构或医生;\n"
    "5. 若用户出现自伤或自杀念头:停止评估与练习,只做陪伴与安全确认,"
    "引导其联系身边信任的人,并拨打心理援助热线 12356 或急救电话 120;"
    "绝不提供任何具体方法、步骤或工具细节;\n"
    "6. 不评判、不说教,用简洁、温和、具体的中文回应。\n"
    "回答长度控制在 200 字以内,除非用户明确要求展开。"
)

CRISIS_PROMPT = (
    "当前用户处于危机状态。你只做陪伴与安全确认:"
    "不评估、不练习、不分析原因、不提供任何具体方法;"
    "鼓励用户联系身边信任的人,并再次提醒心理援助热线 12356 与急救电话 120。"
)

DEFAULT_MAX_CHARS = 2600


def build_system_prompt(
    skill_body: str | None = None,
    *,
    crisis: bool = False,
    extra_context: str | None = None,
    max_context_chars: int = 1200,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """拼接系统提示词;长度受限时优先保留基础边界,其次是额外上下文与技能说明。"""
    head = BASE_PROMPT
    if crisis:
        head = head + "\n\n" + CRISIS_PROMPT
    parts = [head]

    remaining = max_chars - len(head)
    context = (extra_context or "").strip()
    if context and remaining > 1:
        limit = min(max_context_chars, remaining - 1)
        if limit > 0:
            if len(context) > limit:
                context = context[: max(limit - 1, 0)].rstrip() + "…"
            parts.append(context)
            remaining = max_chars - len("\n\n".join(parts))

    if skill_body:
        prefix = "当前技能说明:\n"
        body = skill_body.strip()
        limit = remaining - len(prefix) - 2
        if limit > 0:
            if len(body) > limit:
                body = body[: max(limit - 1, 0)].rstrip() + "…"
            if body:
                parts.append(prefix + body)

    prompt = "\n\n".join(parts)
    if len(prompt) > max_chars:
        prompt = prompt[: max_chars - 1].rstrip() + "…"
    return prompt


def build_messages(
    history: list[dict],
    user_text: str,
    system_prompt: str,
    *,
    max_history_chars: int = 1600,
) -> list[dict]:
    """按字符预算从最近的消息开始裁剪上下文。"""
    messages = [{"role": "system", "content": system_prompt}]
    kept: list[dict] = []
    used = 0
    for message in reversed(history):
        content = str(message.get("content", ""))
        if used + len(content) > max_history_chars:
            break
        kept.append({"role": message.get("role", "user"), "content": content})
        used += len(content)
    messages.extend(reversed(kept))
    messages.append({"role": "user", "content": user_text})
    return messages

import pytest

from mhagent.prompts import BASE_PROMPT, build_messages, build_system_prompt


def test_role_boundaries():
    for phrase in ["不是医生", "不诊断", "药物", "不替代专业帮助", "禁止你自行计算", "12356", "120"]:
        assert phrase in BASE_PROMPT


def test_skill_body_included_and_limited():
    body = "技能正文内容"
    prompt = build_system_prompt(body)
    assert body in prompt
    long_prompt = build_system_prompt("很长" * 2000, max_chars=1000)
    assert len(long_prompt) <= 1000


def test_crisis_prompt():
    prompt = build_system_prompt("技能", crisis=True)
    assert "只做陪伴" in prompt
    assert "12356" in prompt


def test_extra_context_included_and_limited():
    prompt = build_system_prompt(extra_context="报告正文:PHQ-9 总分 12")
    assert "PHQ-9 总分 12" in prompt
    assert len(prompt) <= 2600


def test_extra_context_truncated_keeps_boundaries():
    prompt = build_system_prompt(
        "技能正文",
        crisis=True,
        extra_context="报告" * 3000,
        max_context_chars=300,
        max_chars=1200,
    )
    assert len(prompt) <= 1200
    assert BASE_PROMPT in prompt
    assert "只做陪伴" in prompt
    assert "报告报告报告" in prompt


def test_build_messages_trims_history():
    history = [
        {"role": "user", "content": "a" * 500},
        {"role": "assistant", "content": "b" * 500},
        {"role": "user", "content": "c" * 500},
        {"role": "assistant", "content": "d" * 500},
    ]
    messages = build_messages(history, "现在的问题", "sys", max_history_chars=1100)
    assert messages[0] == {"role": "system", "content": "sys"}
    assert messages[-1] == {"role": "user", "content": "现在的问题"}
    # 只保留最近的两条
    assert [m["content"][0] for m in messages[1:-1]] == ["c", "d"]


def test_build_messages_keeps_short_history():
    history = [{"role": "user", "content": "你好"}]
    messages = build_messages(history, "在吗", "sys")
    assert len(messages) == 3

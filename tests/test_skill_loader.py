import pytest

from mhagent.skill_loader import list_skills, load_skill, route


def test_list_skills():
    skills = list_skills()
    names = {s.name for s in skills}
    assert names == {"mental-health", "assessment", "gene-guidance", "multiple-intelligence"}
    for skill in skills:
        assert skill.description


def test_load_skill():
    body = load_skill("assessment")
    assert "筛查提示" in body
    assert "不是诊断" in body
    assert "不能自行计算" in body or "必须由工具计算" in body
    with pytest.raises(KeyError):
        load_skill("unknown")


def test_gene_guidance_says_not_enabled():
    body = load_skill("gene-guidance")
    assert "暂未启用" in body


def test_route():
    assert route("我想做个焦虑测试") == "assessment"
    assert route("教我呼吸放松") == "mental-health"
    assert route("帮我看看适合什么专业") == "gene-guidance"
    assert route("今天天气不错") is None
    assert route("") is None


def test_multiple_intelligence_body_rules():
    body = load_skill("multiple-intelligence")
    for phrase in ("证据", "不是定论", "专家先验", "不是诊断", "把握度", "回放", "裁决卡", "事实"):
        assert phrase in body
    assert "gene-guidance" in body or "暂未启用" in body


def test_multiple_intelligence_fits_prompt_budget():
    from mhagent.prompts import build_system_prompt

    body = load_skill("multiple-intelligence")
    prompt = build_system_prompt(body)
    assert not prompt.endswith("…")
    assert body.strip().splitlines()[-1] in prompt
    assert len(body) <= 2200


def test_route_multiple_intelligence():
    assert route("帮我解读一下孩子的多元智能报告") == "multiple-intelligence"
    assert route("我想建一份潜能档案") == "multiple-intelligence"
    # 不能被 assessment 的 分数/评估 或 mental-health 的 压力 劫持
    assert route("语言智能 82 分数偏高吗，多元智能怎么看") == "multiple-intelligence"
    assert route("评估一下孩子的八大智能") == "multiple-intelligence"
    # 基因相关仍走未启用的 gene-guidance
    assert route("多元智能的基因检测结果能解读吗") == "gene-guidance"
    # 原有路由不受影响
    assert route("我想做个焦虑测试") == "assessment"


def test_route_more_cases():
    assert route("我想记录一下今天的情绪") == "mental-health"
    assert route("给我一份 PHQ-9 量表") == "assessment"
    assert route("看看我的基因报告") == "gene-guidance"


def test_route_report_scores_not_hijacked():
    # 报告/分数是解读场景的高频词,不能被当成"要做筛查"
    assert route("我比分数更了解我自己,你记住我的行为特点") is None
    assert route("我的好多个能力分数都达到一百分,评分标准是怎么样的?") is None
    assert route("帮我评估一下我的报告") is None
    # 明确要做筛查时仍然命中
    assert route("我想做个心理评估") == "assessment"
    assert route("重新测评") == "assessment"

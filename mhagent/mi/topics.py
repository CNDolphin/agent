"""多元智能报告 · 十七、专题解读模块。

从交付包 `agent_topic.js` 迁移：年龄阶段 × 性别视角 × 为谁解读 ×
解读目的 × 40 项分数剖面 → 自动匹配专题模块并渲染。
报告页面展示全部已解锁模块；解读目的只影响置顶顺序与导语。
"""

from __future__ import annotations

import math

from mhagent.mi.report import clamp, esc, fmt, mean, parse_float, round1
from mhagent.mi.report_data import IND, INTEL, INTEL_MAP

AGE_STAGES = [
    {
        "id": "preschool",
        "name": "幼儿期",
        "range": [0, 6],
        "note": "语言、动作协调、想象力的黄金开发期；以体验式、游戏化培养为主。",
    },
    {
        "id": "primary-low",
        "name": "小学低段",
        "range": [6, 9],
        "note": "读写算能力奠基期；学习习惯与社会规范敏感期。",
    },
    {
        "id": "primary-high",
        "name": "小学高段",
        "range": [9, 12],
        "note": "抽象思维起步；兴趣分化与自信心塑造关键期。",
    },
    {
        "id": "middle",
        "name": "初中",
        "range": [12, 15],
        "note": "青春期自我意识觉醒；选科方向初现。",
    },
    {
        "id": "high",
        "name": "高中",
        "range": [15, 18],
        "note": "升学决策关键期；生涯规划与学科深耕并行。",
    },
    {
        "id": "adult",
        "name": "大学与职业发展期",
        "range": [18, 100],
        "note": "专业深化与职业定位期；终身学习与优势复用。",
    },
]

GENDER_NOTES = {
    "男": {
        "tag": "男孩视角提示",
        "text": "从群体统计看，男孩的语言发展总体略晚、大肌肉运动发展略早，但个体差异远大于性别差异，请勿用性别框住孩子。同时社会常期望男孩「坚强、不许哭」，可能压抑情绪表达——请主动给情绪一个出口，允许示弱与求助。",
    },
    "女": {
        "tag": "女孩视角提示",
        "text": "从群体统计看，女孩的语言与精细动作发展总体略早、社交更倾向一对一的亲密关系，但个体差异远大于性别差异，请勿用性别框住孩子。同时社会常期望女孩「乖巧、别冒险」，可能限制探索欲——请鼓励大胆试错、敢于冒险与拒绝。",
    },
}

GENDER_NOTES_ADULT = {
    "男": {
        "tag": "男性职场视角提示",
        "text": "统计口径仅供参考，个体差异远大于性别差异：职场中男性常被默认承担「开拓/扛压」角色，压力之下容易推迟求助——请主动建立情绪出口与支持系统，示弱与求助是管理能力，不是弱点。",
    },
    "女": {
        "tag": "女性职场视角提示",
        "text": "统计口径仅供参考，个体差异远大于性别差异：职场中女性更常遇到「能见度折价」——请主动争取高曝光项目、公开呈现成果；同时警惕「高标准 + 过度承接」带来的耗竭，学会战略性放手与授权。",
    },
}

PURPOSES = {
    "all": {
        "icon": "🧭",
        "name": "全面解读",
        "focus": "不限定解读目的，按「版本 × 年龄 × 性别 × 40 项剖面」展示全部可用专题模块。",
        "modules": None,
        "hint": "",
    },
    "family": {
        "icon": "👨‍👩‍👧",
        "name": "亲子家庭沟通",
        "focus": "聚焦家庭关系与亲子互动：读懂孩子行为背后的需求，用对沟通通道，建立「温暖 + 规则 + 自主」的权威型家庭氛围（依恋理论 / Baumrind 教养类型 / 正面管教）。",
        "modules": ["parenting", "emotion", "social", "focus", "talent"],
        "hint": "「亲子沟通桥」需要家长视角——请将「为谁解读」切换为「我的孩子 / 他人」后重新生成；家长的情绪稳定是孩子情绪调节最好的示范，先照顾好自己的情绪，再处理孩子的行为。",
    },
    "emotion": {
        "icon": "💞",
        "name": "情感咨询",
        "focus": "聚焦情绪与关系议题：评估情绪觉察、调控、共情三维度，给出可练习的情绪管理与关系修复路径（Goleman 情绪智力理论 / 认知重评 / 非暴力沟通）。",
        "modules": ["emotion", "social", "selfmgmt", "talent"],
        "hint": "本报告面向发展性解读、不具心理咨询诊断意义；若情绪困扰持续两周以上并影响睡眠、饮食、学习/工作或社交，请及时寻求专业心理咨询师面对面帮助。",
    },
    "study": {
        "icon": "🎓",
        "name": "学业规划",
        "focus": "聚焦学习效率与升学决策：识别最有效的学习通道，匹配学科方向，用行为学方法改善专注与习惯（学习策略 / 元认知 / 学科×智能映射 / 平衡单决策工具）。",
        "modules": ["learning", "academy", "focus", "selfmgmt", "talent"],
        "hint": "「升学导航」面向 12-18 岁；低龄段请先聚焦学习通道与专注习惯——升学方向随优势剖面动态变化，12 岁后再做正式选科决策。",
    },
    "career": {
        "icon": "💼",
        "name": "职业规划",
        "focus": "聚焦人-职匹配与优势变现：判断当前职业与优势智能的重合度，给出深耕 / 借势 / 双轨的在岗发展策略（Holland 六型 / Super 生涯彩虹 / Person-Job Fit）。",
        "modules": ["career", "talent", "selfmgmt", "learning", "social"],
        "hint": "建议使用「成年版」并填写当前职业，可解锁「职业 × 优势」个性化人-职匹配分析；教育版（15 岁+）按职业探索口径展示。",
    },
    "life": {
        "icon": "🚀",
        "name": "生涯规划",
        "focus": "覆盖全生命周期的角色与能力布局：以优势为轴心，贯通学业（升学导航）→ 职业（职业罗盘）→ 终身成长（创造力 / 自律），动态平衡多重角色（Super 生涯彩虹理论）。",
        "modules": ["talent", "academy", "career", "creativity", "learning", "selfmgmt"],
        "hint": "生涯是「探索—建立—维持—退出」的连续过程（Super）：每 1-2 年复测一次，让方向随优势剖面与人生阶段动态校准，而非一次定终身。",
    },
}

OCC_MAP = {
    "lang": ["教师", "培训", "翻译", "外语", "编辑", "记者", "文案", "主持", "播音", "律师", "销售", "客服", "公关", "导游", "主播", "写作", "作家", "编剧", "配音", "语文"],
    "logic": ["程序", "软件", "开发", "算法", "数据", "分析", "会计", "审计", "金融", "统计", "工程", "测试", "量化", "架构", "研发", "精算", "风控", "运维", "AI", "人工智能", "数学"],
    "visual": ["设计", "美术", "建筑", "装修", "摄影", "摄像", "视频", "制图", "测绘", "游戏", "动画", "UI", "平面", "剪辑", "导演", "景观", "规划", "广告"],
    "nature": ["农业", "园艺", "环保", "兽医", "养殖", "林业", "地质", "气象", "园林", "宠物", "生态", "植保", "水产", "种植"],
    "music": ["音乐", "歌手", "乐手", "钢琴", "作曲", "音频", "DJ", "声乐", "乐器", "编曲", "调音"],
    "body": ["体育", "运动员", "教练", "健身", "舞蹈", "外科", "护士", "消防", "警察", "司机", "厨师", "康复", "按摩", "技工", "电工", "维修", "木工", "施工", "美发", "美容", "医生", "牙医", "理疗", "营养师"],
    "social": ["销售", "市场", "运营", "管理", "人力", "HR", "公关", "客服", "顾问", "咨询", "社工", "老师", "导游", "主播", "餐饮", "酒店", "门店", "店长", "行政", "招募", "猎头", "护理"],
    "inner": ["心理", "咨询", "研究", "作家", "策划", "产品", "创业", "分析师", "学者", "法务", "合规", "情报", "档案"],
}


def age_stage_of(age):
    """按年龄返回阶段；空值返回 None。"""
    if age is None or str(age).strip() == "":
        return None
    try:
        value = float(age)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    for stage in AGE_STAGES:
        if stage["range"][0] <= value < stage["range"][1]:
            return stage
    return AGE_STAGES[-1]


def purpose_of(meta: dict) -> str:
    purpose = str((meta or {}).get("purpose") or "").strip()
    return purpose if purpose and purpose != "all" and purpose in PURPOSES else "all"


def subject_tune(html: str, who: str) -> str:
    """自测视角：把面向家长的「孩子」口径转换为「你」，并保护固定短语。"""
    if who != "me" or not html:
        return html
    placeholder = "\x01"
    text = str(html)
    text = text.replace("别人家孩子", placeholder + "1" + placeholder)
    text = text.replace("我的孩子 / 他人（家长视角）", placeholder + "2" + placeholder)
    text = text.replace("我的孩子 / 他人", placeholder + "3" + placeholder)
    text = text.replace("孩子 / 他人（家长视角）", placeholder + "4" + placeholder)
    text = text.replace("我的孩子", placeholder + "5" + placeholder)
    text = text.replace("孩子当导演你当配角", "自己当导演、家人当配角")
    text = text.replace("帮孩子说出感受", "试着说出自己的感受")
    text = text.replace("教孩子在 7 分前就求助", "练习在 7 分前就求助")
    text = text.replace("告诉孩子", "提醒自己")
    text = text.replace("每个孩子", "每个人")
    text = text.replace("请勿用性别框住孩子", "请勿让性别期待框住自己")
    text = text.replace("孩子天赋一句话", "你的天赋一句话")
    text = text.replace("孩子优势在", "你的优势在")
    text = text.replace("解读师与家长参考", "解读师与本人参考")
    text = text.replace("孩子", "你")
    text = text.replace(placeholder + "1" + placeholder, "别人家孩子")
    text = text.replace(placeholder + "2" + placeholder, "我的孩子 / 他人（家长视角）")
    text = text.replace(placeholder + "3" + placeholder, "我的孩子 / 他人")
    text = text.replace(placeholder + "4" + placeholder, "孩子 / 他人（家长视角）")
    text = text.replace(placeholder + "5" + placeholder, "我的孩子")
    return text


def gender_note_for(edition: str, who: str, gender: str):
    if not gender:
        return None
    if edition == "adult":
        return GENDER_NOTES_ADULT.get(gender)
    note = GENDER_NOTES.get(gender)
    if not note:
        return None
    if who == "me":
        return {"tag": note["tag"], "text": note["text"].replace("请勿用性别框住孩子", "请勿让性别期待框住自己")}
    return note


def _ti(intel_id: str) -> dict:
    return INTEL_MAP[intel_id]


def _top_i(intel_id: str, scores: dict, count: int):
    return sorted(
        ({"k": key, "s": scores[key]} for key in _ti(intel_id)["inds"]),
        key=lambda item: -item["s"],
    )[:count]


def _bot_i(intel_id: str, scores: dict, count: int):
    return sorted(
        ({"k": key, "s": scores[key]} for key in _ti(intel_id)["inds"]),
        key=lambda item: item["s"],
    )[:count]


def _chips(ids, scores: dict) -> str:
    return "".join(f'<span class="chip">{esc(IND[key]["n"])} {fmt(scores[key])}</span>' for key in ids)


def _pick_by(items, intel_id: str, count: int):
    return [item for item in items if intel_id in (item.get("intels") or [])][:count]


def _g_tip(ctx: dict, male_text: str, female_text: str) -> str:
    if ctx.get("edition") == "adult":
        return ""
    gender = ctx.get("gender")
    if gender not in ("男", "女"):
        return ""
    label = "男孩" if gender == "男" else "女孩"
    text = male_text if gender == "男" else female_text
    return f'<div class="t-tip gtip">🚻 <b>{label}视角提示：</b>{text}</div>'


def _stage_tips(stage, tips: dict):
    return tips[stage["id"]] if stage and stage["id"] in tips else tips["adult"]


def _stage_title(ctx: dict, suffix: str) -> str:
    stage = ctx.get("stage")
    if not stage:
        return f"分龄{suffix}"
    age = ctx.get("age")
    age_label = str(int(age)) if isinstance(age, (int, float)) and float(age).is_integer() else str(age)
    return f"{esc(stage['name'])}（{age_label} 岁）{suffix}"


def occ_analyze(ctx: dict) -> dict:
    job = str(ctx.get("job") or "").strip()
    demands = []
    for item in INTEL:
        keywords = [kw for kw in OCC_MAP.get(item["id"], []) if kw in job]
        if keywords:
            demands.append(
                {"id": item["id"], "name": item["name"], "kws": keywords, "score": ctx["intelScores"][item["id"]]}
            )
    top3 = [item["id"] for item in ctx["R"]["adv"][:3]]
    hit = [item for item in demands if item["id"] in top3]
    if not demands:
        level = "unknown"
    elif len(hit) >= 2 or (len(demands) == 1 and len(hit) == 1):
        level = "high"
    elif len(hit) == 1:
        level = "part"
    else:
        level = "gap"
    return {"job": job, "demands": demands, "hit": hit, "top3": top3, "level": level}


def occ_match_html(occ: dict, ctx: dict) -> str:
    R = ctx["R"]
    level_text = {
        "high": "🟢 高匹配",
        "part": "🟡 部分匹配",
        "gap": "🟠 优势错配",
        "unknown": "⚪ 未识别",
    }[occ["level"]]
    level_desc = {
        "high": "当前职业的核心能力需求与你的前三大优势智能高度重合——你正在「用优势工作」，这是职业满意度与长期绩效的最佳配置（人-职匹配理论）。",
        "part": "职业需求与优势部分重合：存在一条「借势通道」——把优势智能刻意注入当前岗位，形成差异化竞争力。",
        "gap": "当前职业的核心需求与你最强的三项智能基本不重合：并非「不能做」，而是更容易感到耗能。建议采用双轨策略：短期在岗借优势，中长期评估轮岗/转型。",
        "unknown": "未在职业库中识别到关键词——可把职业描述写得更具体（如「软件工程师」「小学语文教师」），或按右侧优势智能 × 职业类型表手动对照。",
    }[occ["level"]]
    def level_cell(score: float) -> str:
        if score >= 60:
            return '<b style="color:#16a34a">强</b>'
        if score >= 45:
            return "中"
        return '<b style="color:#d97706">待提升</b>'

    demand_rows = "".join(
        f'<tr><td>{esc(item["name"])}</td>'
        f'<td>{"、".join(esc(kw) for kw in item["kws"])}</td>'
        f'<td>{fmt(item["score"])}</td>'
        f'<td>{level_cell(item["score"])}</td></tr>'
        for item in occ["demands"]
    )
    top_careers = "、".join(esc(str(item["n"]).split("（")[0]) for item in R["careers"][:3])
    advice = {
        "high": (
            '<h4>深耕策略（高匹配情景）</h4><ul class="t-list">'
            "<li><b>把优势继续拉开差距：</b>向行业头部标准对齐——认证、作品集、行业影响力，建立「优势护城河」。</li>"
            "<li><b>警惕「优势陷阱」：</b>高匹配 ≠ 高回报，关注行业趋势与新兴赛道（AI 数字经济 / 绿色低碳 / 健康养老 / 低空经济 / 智慧农业）。</li>"
            "<li><b>补短板到「够用」即可：</b>职业天花板常出现在岗位的第二项能力需求上，识别并补到合格线，不必追求全面优秀。</li></ul>"
        ),
        "part": (
            '<h4>借势策略（部分匹配情景）</h4><ul class="t-list">'
            "<li><b>把命中的一项优势做到「团队里最显眼」：</b>主动成为该环节的默认负责人，让优势被看见。</li>"
            "<li><b>用另一项未命中的优势做差异化：</b>例：「语言 + 逻辑」双强的市场岗，既会写方案又会看数据。</li>"
            "<li><b>每季度复盘：</b>哪些工作给你能量（优势信号）、哪些消耗你（错配信号），逐步调整工作配比。</li></ul>"
        ),
        "gap": (
            '<h4>双轨策略（优势错配情景）</h4><ul class="t-list">'
            "<li><b>短期（0-6 个月）· 在岗借势：</b>把优势智能注入现岗位——例：优势是「视觉空间」的运营，用可视化内容做出差异化；优势是「人际沟通」的技术岗，主动承担跨部门协作与需求沟通角色。</li>"
            "<li><b>中期（6-18 个月）· 补齐或内部转岗：</b>错配的核心智能若分数 ≥45 可刻意练习补到「够用」；同时观察公司内更匹配优势的岗位——轮岗/内部转岗成本远低于跳槽。</li>"
            f"<li><b>长期（18 个月+）· 转型评估：</b>系统高匹配方向参考：{top_careers}；转型前先做 2-3 次职业访谈 + 一个低成本试错项目，用体验代替想象。</li></ul>"
        ),
        "unknown": (
            '<h4>手动对照指引</h4><ul class="t-list">'
            "<li>在下方「优势智能 × 职业兴趣类型」表中找到你前三大优势对应的 Holland 类型。</li>"
            f"<li>系统高匹配方向参考：{top_careers}（详见第十一节完整排序）。</li></ul>"
        ),
    }[occ["level"]]
    top_names = "、".join(esc(INTEL_MAP[intel_id]["name"]) for intel_id in occ["top3"])
    if occ["demands"]:
        demand_html = (
            '<table class="tbl tbl-mini"><tbody><tr><td>需求智能</td><td>命中关键词</td>'
            f'<td>你的分数</td><td>水平</td></tr>{demand_rows}</tbody></table>'
        )
    else:
        demand_html = '<p>未识别到职业关键词——请把职业描述写得更具体（如「软件工程师」「小学语文教师」）。</p>'
    return f'''<div class="topic-grid-2">
      <div class="t-box"><b>🧾 职业需求画像（录入职业：{esc(occ["job"])}）</b>
        {demand_html}
        <p class="t-micro">匹配口径：职业关键词 → 核心智能需求，再与你的前三大优势智能（{top_names}）求重合度。</p>
      </div>
      <div class="t-box"><b>⚖️ 人-职匹配结论（心理学 · Person-Job Fit）</b>
        <p>匹配等级：<b>{level_text}</b></p>
        <p>{level_desc}</p>
      </div>
    </div>
    {advice}'''


# ---------------------------------------------------------------- 专题渲染函数


def _render_learning(ctx: dict) -> str:
    R, scores = ctx["R"], ctx["scores"]
    wd, diag = R["wudao"][0], R["diagonals"][0]
    lang_top = _top_i("lang", scores, 2)
    logic_top = _top_i("logic", scores, 2)
    lang_bot = _bot_i("lang", scores, 1)
    logic_bot = _bot_i("logic", scores, 1)
    s1_label = "强" if R["s1"] >= 60 else ("中等" if R["s1"] >= 45 else "待提升")
    tips = {
        "preschool": [
            "把学习变成游戏与身体体验：学数数用积木、学语言用儿歌与角色扮演",
            "坚持亲子共读 15-20 分钟/天，阅读是语言+逻辑双通道的底层基建",
            "用「你做我猜」等动作类任务学习，先动后静更高效",
        ],
        "primary-low": [
            "每天固定时间+固定位置写作业，用可视化清单（做完一项打一个勾）",
            "朗读法记忆：语文英语多出声读，调动听觉通道（耳到）",
            "错题当天订正并用红笔标注，建立「错题=礼物」的积极认知",
        ],
        "primary-high": [
            "引入费曼学习法：让孩子把今天学的讲给家长听，讲不明白的地方就是漏洞",
            "用思维导图整理单元知识框架（匹配图像/逻辑优势）",
            "间隔复习：当天、3 天后、1 周后三次回顾，记忆更牢固",
        ],
        "middle": [
            "主动回忆法：合上书本先默写/口述要点，再对照检查（比反复阅读高效得多）",
            "错题本分类管理，考前只复习错题本",
            "引入番茄钟：25 分钟专注 + 5 分钟休息，逐步延长专注单元",
        ],
        "high": [
            "构建学科知识框架图，先框架后细节",
            "限时训练培养考场节奏；考后做「失分归因」而非只看分数",
            "同伴互教：给别人讲题是最深度的学习方式",
        ],
        "adult": [
            "输出式学习：把学到的写成笔记、讲给别人、做项目，输入输出比建议 1:3",
            "碎片时间整块化：通勤听书 + 午休整理 + 晚间深度学习",
            "目标倒推：先定 3 个月想达成的成果，再拆解为每周可执行任务",
        ],
    }
    tips_list = _stage_tips(ctx.get("stage"), tips)
    lang_extra = (
        f' · 待提升：{esc(IND[lang_bot[0]["k"]]["n"])} {fmt(lang_bot[0]["s"])}' if lang_bot else ""
    )
    logic_extra = (
        f' · 待提升：{esc(IND[logic_bot[0]["k"]]["n"])} {fmt(logic_bot[0]["s"])}' if logic_bot else ""
    )
    return f'''<div class="topic-grid-2">
      <div class="t-box"><b>🎯 学习通道画像</b>
        <p>最有效的输入通道：<b>{esc(wd["name"])}（{esc(wd["type"])}）</b> — {esc(wd["strong"])}</p>
        <p>先天学习线：<b>{esc(diag["name"])}（{esc(diag["type"])}）</b> — {esc(diag["suggest"])}</p>
      </div>
      <div class="t-box"><b>📊 学习能力剖面（教育学 · 学习策略）</b>
        <p>S1 六项先天学习能力：<b>{fmt(R["s1"])}（{s1_label}）</b> · S2 综合潜能：<b>{fmt(R["s2"])}</b></p>
        <p>语言侧强项：{_chips([item["k"] for item in lang_top], scores)}{lang_extra}</p>
        <p>逻辑侧强项：{_chips([item["k"] for item in logic_top], scores)}{logic_extra}</p>
      </div>
    </div>
    <h4>{_stage_title(ctx, "适配的学习策略")}</h4>
    <ul class="t-list">{"".join(f"<li>{item}</li>" for item in tips_list)}</ul>
    <div class="t-tip">🧠 <b>心理学小知识 · 元认知：</b>知道自己是怎么学会的、哪里没懂、怎么改进——是解释学习成绩差异的最大因素之一（研究贡献度远超智商）。每次学完问三个问题：① 我学到了什么？② 哪里还不懂？③ 下次怎么改进？坚持 21 天会内化为自动习惯。</div>'''


def _render_talent(ctx: dict) -> str:
    R, scores = ctx["R"], ctx["scores"]
    age = ctx.get("age")
    show_career = isinstance(age, (int, float)) and math.isfinite(age) and age >= 15
    cards = []
    for item in R["adv"][:3]:
        top = "、".join(esc(IND[x["k"]]["n"]) for x in _top_i(item["id"], scores, 2))
        talents = "、".join(esc(str(x["n"]).split("（")[0]) for x in _pick_by(R["talents"], item["id"], 2))
        majors = (
            "、".join(esc(str(x["n"]).split("（")[0]) for x in _pick_by(R["majors"], item["id"], 2))
            if show_career
            else ""
        )
        careers = (
            "、".join(esc(str(x["n"]).split("（")[0]) for x in _pick_by(R["careers"], item["id"], 2))
            if show_career
            else ""
        )
        major_html = f"<p>🎓 专业方向：{majors}</p>" if majors else ""
        career_html = f"<p>💼 职业方向：{careers}</p>" if careers else ""
        cards.append(
            f'<div class="t-box"><b>{esc(item["name"])}（{fmt(item["score"])}）</b>'
            f"<p>代表强项：{top}</p>"
            f"<p>🎨 才艺方向：{talents or '—'}</p>"
            f"{major_html}{career_html}</div>"
        )
    rev_low = "、".join(
        esc(item["name"]) for item in [x for x in R["revLow"] if not x.get("isIntel")][:3]
    )
    rev_html = (
        f'<div class="t-tip">🔻 <b>低分反转的「隐藏天赋」：</b>{rev_low} 分数低于 33，按解读规则属于「低分反转」——这类活动孩子反而可能出现意外的好效果。请务必给低门槛、无考核的尝试机会，观察 2-3 次再下结论，不要一票否决。</div>'
        if rev_low
        else ""
    )
    return f'''<div class="topic-grid-3">{"".join(cards)}</div>
    {rev_html}
    <div class="t-tip">💡 <b>心理学视角 · 优势理论：</b>研究表明，把精力投在优势上，比拼命补短板更能提升成就感与长期成就。教育的正确姿势：让长板更长、短板够用。</div>
    <h4>行动建议</h4>
    <ul class="t-list">
      <li><b>1 个月内</b>：从上面 3 大优势中挑 1-2 项对应活动试水（只报 1-2 个班，切忌贪多），连续观察 2-4 周「是否专注、是否主动想继续」。</li>
      <li><b>3-6 个月</b>：确定 1 个主方向深度培养（考级/展演/项目均可），另做一组「以强带弱」组合练习。</li>
      <li><b>避免</b>：用优势智能对标「别人家孩子」；把低分项当「缺陷」反复敲打。</li>
    </ul>'''


def _render_emotion(ctx: dict) -> str:
    scores = ctx["scores"]
    awareness = round1(mean([scores[k] for k in ["i1", "l5", "s2"]]))
    regulation = round1(mean([scores[k] for k in ["i3", "i2"]]))
    care = round1(mean([scores[k] for k in ["i4", "i5"]]))
    tips = {
        "preschool": [
            "情绪命名法：帮孩子说出感受——「你很生气，因为积木倒了」；认识情绪才能管理情绪",
            "情绪脸谱游戏：画/认 4 种基础情绪（喜、怒、哀、惧），每天睡前聊聊「今天的心情是什么颜色」",
            "父母示范：孩子 3 岁前的情绪调节主要靠「借」父母的冷静，大人先稳住",
        ],
        "primary-low": [
            "设置「冷静角」：生气时去安静角落待 5 分钟（不是惩罚，是练习暂停）",
            "情绪温度计：0-10 打分，教孩子在 7 分前就求助，而不是等到 10 分爆发",
            "共情式倾听：先接住情绪再讲道理——「我知道你很难过」优先于「你应该」",
        ],
        "primary-high": [
            "情绪日记：每天 3 行记录「发生了什么+我的感受+下次可以怎么做」",
            "红绿灯法则：红灯停（深呼吸 3 次）→ 黄灯想（我为什么生气）→ 绿灯做（表达或求助）",
            "鼓励求助：告诉孩子「向大人求助情绪不是软弱，是智慧」",
        ],
        "middle": [
            "认知重评：换个角度解读事件——「这次考砸是信息，不是判决」，练习把灾难化想法改写为可行动方案",
            "给情绪一个出口：运动（跑步/打球）、写日记、画出来，选一种适合自己的方式",
            "青春期情绪波动是生理+心理双重作用，减少自责，增加自我关怀",
        ],
        "high": [
            "把情绪管理当「技能」刻意练习：正念呼吸、情绪记录、延迟反应（数 10 秒再回应）",
            "建立支持系统：确定 1-2 个可以随时倾诉的人（家人/老师/好友）",
            "压力管理：规律作息 + 每周运动 ≥150 分钟，是情绪稳定的生理基础",
        ],
        "adult": [
            "正念减压：每天 5 分钟正念呼吸，降低杏仁核过度激活",
            "情绪记账：记录触发事件+身体反应+应对方式，找到自己的情绪模式",
            "边界管理：学会说「不」，情绪耗竭往往源于边界不清",
        ],
    }
    tips_list = _stage_tips(ctx.get("stage"), tips)

    def bar(value, label):
        return (
            f'<div class="t-bar"><span class="t-bar-k">{label}</span>'
            f'<div class="t-bar-v"><i style="width:{clamp(value, 0, 100)}%"></i></div>'
            f"<b>{fmt(value)}</b></div>"
        )

    return f'''<div class="topic-grid-2">
      <div class="t-box"><b>😊 情绪能力三维度（心理学 · 情绪智力理论）</b>
        {bar(awareness, "情绪觉察")}{bar(regulation, "情绪调控")}{bar(care, "关怀共情")}
        <p class="t-micro">觉察=识别自己与他人的情绪；调控=暂停-思考-选择反应；关怀=理解与付出。三者合起来决定情绪智力（EQ）。</p>
      </div>
      <div class="t-box"><b>🧭 本模块解读重点</b>
        <p>{"情绪觉察是优势：" if awareness >= 55 else "情绪觉察待提升："}{"能较快识别情绪信号，适合进一步练习「在 7 分前求助」。" if awareness >= 55 else "建议从情绪命名与每日记录开始，把模糊感受变成说得出的词。"}</p>
        <p>{"情绪调控是优势：" if regulation >= 55 else "情绪调控待提升："}{"暂停-思考-选择已形成习惯，可挑战更高难度情境（如被批评时保持冷静）。" if regulation >= 55 else "冲动是大脑前额叶尚未成熟的正常表现，练习「数 10 秒再回应」最有效。"}</p>
        <p>{"关怀共情是优势：" if care >= 55 else "关怀共情待提升："}{"易感知他人情绪，适合承担倾听与助人角色。" if care >= 55 else "可通过共情提问练习：多问「如果你是他，你会怎么想？」。"}</p>
      </div>
    </div>
    <h4>{_stage_title(ctx, "情绪管理方法")}</h4>
    <ul class="t-list">{"".join(f"<li>{item}</li>" for item in tips_list)}</ul>
    {_g_tip(ctx, "男孩常见议题：社会常期望「坚强、不许哭」，情绪表达通道容易被窄化——请允许示弱，并借助运动、绘画等非语言方式疏通情绪。", "女孩常见议题：社会常期望「乖巧、懂事」，情绪容易被压抑——请明确传递「生气、拒绝都是可以的」，练习表达真实需求。")}'''


def _render_social(ctx: dict) -> str:
    R, scores = ctx["R"], ctx["scores"]
    s3, s4 = scores["s3"], scores["s4"]
    eq3 = round1(mean([scores[k] for k in ["s1", "s2", "s5"]]))
    role = (
        "更偏「领导主导型」"
        if s3 > s4
        else ("更偏「协同配合型」" if s4 > s3 else "领导与协同并重的「多面手」")
    )
    tips = {
        "preschool": [
            "从平行游戏过渡到合作游戏：一起搭积木、轮流玩，练习等待与分享",
            "多安排家庭合力任务（一起做饭、收玩具），让「帮忙」成为社交的起点",
            "示范打招呼与道谢，社交礼仪是教出来的，不是天生的",
        ],
        "primary-low": [
            "小组任务与运动队：在真实团队里练轮流发言、互相鼓励",
            "轮值小队长/值日生：给每个孩子当「小领导」的机会，练习分配与照顾",
            "冲突时先问「你感觉怎么样」再问「发生了什么」",
        ],
        "primary-high": [
            "社团/班干部/辩论：把口语优势转化为影响力",
            "练习「解决冲突三步」：说明情况→表达感受→提出方案",
            "安排服务他人（图书馆志愿者、帮助低年级同学），领导力从服务开始",
        ],
        "middle": [
            "经营 1-2 段深度友谊：真诚 > 受欢迎；练习冲突后主动修复关系",
            "异性同学正常交往：尊重边界、礼貌互动，青春期社交技能是练习出来的",
            "加入 1 个兴趣社团，用共同爱好降低社交压力",
        ],
        "high": [
            "团队项目/学生会/社会服务：在真实任务中练协作与领导",
            "非暴力沟通四步：观察-感受-需要-请求",
            "练习向上沟通：与老师/学长有效表达自己的需求",
        ],
        "adult": [
            "向上管理与跨部门协作：理解不同角色的目标再沟通",
            "把「让别人舒服」变成习惯：及时回应、主动同步、公开表扬私下批评",
            "建立弱连接：行业活动、校友网络——机会常来自弱连接（Granovetter 弱连接理论）",
        ],
    }
    tips_list = _stage_tips(ctx.get("stage"), tips)
    return f'''<div class="topic-grid-2">
      <div class="t-box"><b>🤝 社交角色定位（行为学 · 社交是行为技能）</b>
        <p>领导能力（s3）{fmt(s3)} vs 协同能力（s4）{fmt(s4)} → <b>{role}</b></p>
        <p>情商三件套：了解他人 {fmt(scores["s1"])} · 感同身受 {fmt(scores["s2"])} · 有效沟通 {fmt(scores["s5"])} → 综合 <b>{fmt(eq3)}</b></p>
        <p class="t-micro">社交不是性格，是「练出来」的行为技能——目光接触、倾听点头、轮流发言都可以像学打球一样分解练习。</p>
      </div>
      <div class="t-box"><b>📖 心理学视角（社会学习理论 Bandura）</b>
        <p>观察-模仿-强化是社交能力习得的三大路径：孩子先看（观察家人互动），再试（模仿），最后靠反馈（强化/调整）定型。</p>
        <p>家庭是最好的练习场：饭桌讨论、家庭会议就是低风险的社交模拟。</p>
      </div>
    </div>
    <h4>{_stage_title(ctx, "社交培养方案")}</h4>
    <ul class="t-list">{"".join(f"<li>{item}</li>" for item in tips_list)}</ul>
    {_g_tip(ctx, "男孩常见社交议题：多围绕共同活动展开，可在运动、游戏合作中建立关系；注意用语言表达感受而非只用行动。", "女孩常见社交议题：更在意关系质量，冲突后需要「谈心」修复；注意避免讨好型关系，练习坚定表达。")}'''


def _render_focus(ctx: dict) -> str:
    R, scores = ctx["R"], ctx["scores"]
    sensitivity = round1(mean([scores[k] for k in ["m1", "n1", "v1"]]))
    i3, body = scores["i3"], scores["b3"]
    age = ctx.get("age")
    if isinstance(age, (int, float)) and math.isfinite(age) and age < 18:
        length = (
            "5-10" if age <= 6 else ("15-25" if age <= 12 else "25-45")
        ) + " 分钟专注 + 5 分钟休息"
    else:
        length = "25-45 分钟专注 + 5 分钟休息（成人番茄钟）"
    beh = next(
        (item for item in R["behaviors"] if item["n"] == "分心、注意力分散"),
        R["behaviors"][0] if R["behaviors"] else None,
    )
    beh_html = (
        f'<div class="t-tip">📋 <b>对照行为速查：</b>「{esc(beh["n"])}」的官方建议——{esc(beh["note"])}（详见第十三节行为速查）。</div>'
        if beh
        else ""
    )
    return f'''<div class="topic-grid-2">
      <div class="t-box"><b>🔍 注意力影响因素分析（行为学 · ABC 模型）</b>
        <p>感官敏感度（听觉/观察/图像）：<b>{fmt(sensitivity)}</b> {"——较高，容易被环境刺激（声音/画面/动静）吸引而分心" if sensitivity >= 60 else "——适中，环境干扰相对可控"}</p>
        <p>自律自控（i3）：<b>{fmt(i3)}</b> {"——具备较好的自我控制基础" if i3 >= 55 else "——自控力仍在发育，需要外部结构辅助"}</p>
        <p>身体活动需求（平衡 b3）：<b>{fmt(body)}</b> — 动觉需求高的孩子，先动后静更易专注</p>
      </div>
      <div class="t-box"><b>⚙️ 行为塑造方案（前因-行为-后果）</b>
        <p><b>前因（环境设计）：</b>固定学习区；桌面只放当前任务必需物品；学习前收起手机/玩具；把「分心源」物理隔离。</p>
        <p><b>行为（任务结构）：</b>番茄钟分龄：{length}；一次只做一个任务。</p>
        <p><b>后果（正向强化）：</b>完成后立即给予及时、具体的肯定或小奖励；多表扬「专注的过程」而非结果。</p>
      </div>
    </div>
    {beh_html}
    <h4>常见误区</h4>
    <ul class="t-list">
      <li>❌ 批评「坐不住」贴标签 → ✅ 先排除生理因素（饿、困、憋尿、运动不足），再谈注意力</li>
      <li>❌ 期望长时间学习 → ✅ 专注时长与年龄成正比（{length} 即达标），短而多次优于长而一次</li>
      <li>❌ 边学边吃/边看电视写作业 → ✅ 建立「学习=单一任务」的条件反射</li>
    </ul>
    <div class="t-tip">🏃 <b>动觉先行：</b>动觉需求高的孩子，学习前安排 10-20 分钟大肌肉活动（跳绳、打球、快走），把多余能量释放掉，专注力反而更持久。</div>'''


def _render_academy(ctx: dict) -> str:
    R, scores = ctx["R"], ctx["scores"]
    logic, lang = R["intelScores"]["logic"], R["intelScores"]["lang"]
    sci = round1(mean([scores[k] for k in ["g4", "g5", "n3", "b2"]]))
    hum = round1(mean([scores[k] for k in ["l2", "l4", "s5", "i4"]]))
    direction = (
        "物理类（理）方向更匹配" if logic >= lang else ("历史类（文）方向更匹配" if lang > logic else "文理均衡，按兴趣+目标专业双向决策")
    )
    top_majors = "、".join(esc(str(item["n"]).split("（")[0]) for item in R["majors"][:3])
    return f'''<div class="topic-grid-2">
      <div class="t-box"><b>🧭 学科方向画像（教育学 · 学科 × 智能映射）</b>
        <table class="tbl tbl-mini"><tbody>
          <tr><td>语文 / 外语</td><td>语言智能（{fmt(lang)}）</td></tr>
          <tr><td>数学 / 物理 / 化学</td><td>逻辑数学智能（{fmt(logic)}）</td></tr>
          <tr><td>艺术 / 通用技术</td><td>视觉空间 + 音乐智能</td></tr>
          <tr><td>生物 / 地理</td><td>自然观察智能</td></tr>
          <tr><td>政治 / 历史</td><td>人际 + 内省智能</td></tr>
          <tr><td>体育</td><td>肢体动觉智能</td></tr>
        </tbody></table>
      </div>
      <div class="t-box"><b>🎓 选科与升学建议</b>
        <p>理科倾向分（运算/实验/识别/反应）：<b>{fmt(sci)}</b> vs 文科倾向分（口语/理解/沟通/同理）：<b>{fmt(hum)}</b></p>
        <p>初步建议：<b>{direction}</b></p>
        <p>当前匹配度最高的专业方向：<b>{top_majors}</b>（详见第十节完整排序）</p>
      </div>
    </div>
    <div class="t-tip">🧠 <b>心理学 · 生涯发展理论（Super）：</b>12-18 岁正处于生涯「探索期」——任务是多尝试、多收集信息，而不是一次定终身。选科只是阶段性选择，大学、读研、转行都留有改道空间，不必过度焦虑。</div>
    <h4>决策工具：平衡单（推荐实操）</h4>
    <ul class="t-list">
      <li>列出 2-3 个备选方向（如：物化生 vs 物化地 vs 史地政）</li>
      <li>对每个方向按 4 项打分（1-10）：① 能力匹配（参考本报告智能分数）② 兴趣程度 ③ 就业/专业前景 ④ 家人支持度</li>
      <li>加权求和后比较——分数最高者未必是最终答案，但决策过程会清晰很多</li>
    </ul>
    <h4>行动建议</h4>
    <ul class="t-list">
      <li>寒暑假安排 1-2 次职业/专业体验（职业访谈、大学开放日、线上公开课）</li>
      <li>高一前做一次选科预演：用平衡单写下当前倾向，高二再复核一次</li>
    </ul>'''


def _render_career(ctx: dict) -> str:
    R = ctx["R"]
    holland = {
        "lang": "艺术型(A) · 企业型(E)",
        "logic": "研究型(I) · 常规型(C)",
        "visual": "艺术型(A)",
        "nature": "研究型(I)",
        "music": "艺术型(A)",
        "body": "现实型(R)",
        "social": "社会型(S)",
        "inner": "社会型(S) · 研究型(I)",
    }
    rows = "".join(
        f'<tr><td>{esc(item["name"])}（{fmt(item["score"])}）</td>'
        f'<td>{holland.get(item["id"], "—")}</td></tr>'
        for item in R["adv"][:3]
    )
    top_careers = "、".join(esc(str(item["n"]).split("（")[0]) for item in R["careers"][:3])
    new_careers = "、".join(
        esc(str(item["n"]).split("（")[0]) for item in [x for x in R["careers"] if x.get("n2026")][:2]
    )
    is_adult = ctx.get("edition") == "adult"
    if is_adult:
        occ_box = (
            occ_match_html(occ_analyze(ctx), ctx)
            if ctx.get("job")
            else '<div class="t-tip">📝 <b>尚未录入职业：</b>成年版解读需在页面顶部「当前职业」填写后重新生成报告，即可解锁「职业 × 优势」个性化匹配分析。</div>'
        )
        action = """<h4>职场行动清单（生涯心理学 · 行动比测评更重要）</h4>
    <ul class="t-list">
      <li><b>职业复盘：</b>每季度回答三个问题——我在哪件事上最容易进入状态？哪件事最耗能？别人最常找我帮什么忙？（三者的交集就是你的优势信号）</li>
      <li><b>优势曝光：</b>主动申请能用上优势智能的项目，让优势被看见——晋升与机会永远流向「被看见的优势」。</li>
      <li><b>作品/成果积累：</b>无论技术、管理还是创意，留下可展示的成果，比简历更有说服力。</li>
      <li><b>警惕性别刻板印象：</b>职业发展以能力剖面与兴趣为准，不被「男性该做什么 / 女性该做什么」框住。</li>
    </ul>"""
    else:
        occ_box = ""
        action = """<h4>职业探索行动（生涯心理学 · 行动比测评更重要）</h4>
    <ul class="t-list">
      <li><b>职业访谈</b>：找 2-3 位目标行业从业者各聊 30 分钟（问：日常做什么 / 怎么入行 / 最需要什么能力 / 最大挑战）</li>
      <li><b>低成本试错</b>：实习、志愿、社团项目、比赛——用 1-2 个月的真实体验代替想象</li>
      <li><b>作品/项目积累</b>：无论艺术、技术还是管理，留下可展示的成果，比简历更有说服力</li>
      <li><b>警惕性别刻板印象</b>：职业选择以能力剖面与兴趣为准，不被「男生该做什么 / 女生该做什么」框住</li>
    </ul>"""
    new_html = (
        f'<p class="t-micro">🚀 2026 新兴赛道参考：{new_careers} —— AI 数字经济、绿色低碳、健康养老、低空经济、智慧农业为五大高增长方向。</p>'
        if new_careers
        else ""
    )
    return f'''<div class="topic-grid-2">
      <div class="t-box"><b>💼 优势智能 × 职业兴趣类型（Holland 六型）</b>
        <table class="tbl tbl-mini"><tbody>{rows}</tbody></table>
        <p class="t-micro">Holland 职业兴趣六型（现实/研究/艺术/社会/企业/常规）是应用最广的职业匹配理论：优势智能与职业类型越一致，职业满意度与稳定性越高。</p>
      </div>
      <div class="t-box"><b>🎯 高匹配职业方向</b>
        <p>当前匹配度最高的职业：<b>{top_careers}</b>（详见第十一节完整排序）</p>
        {new_html}
      </div>
    </div>
    {occ_box}
    {action}'''


def _render_parenting(ctx: dict) -> str:
    R, scores = ctx["R"], ctx["scores"]
    expression = round1(mean([scores[k] for k in ["l2", "l5", "s2"]]))
    visual = round1(mean([scores[k] for k in ["v1", "v4"]]))
    body = round1(mean([scores[k] for k in ["b1", "b2", "b5"]]))
    channels = []
    if expression >= 55:
        channels.append(("语言沟通", "多交谈、复盘、睡前聊聊今天"))
    if visual >= 55:
        channels.append(("视觉沟通", "用图画、便签、表格代替说教"))
    if body >= 55:
        channels.append(("动觉沟通", "边说边动、边散步边谈、用行动示范"))
    if not channels:
        channels.append(("倾听沟通", "先听再说，保持每天 10 分钟无评判倾听"))
    top = channels[0]
    behs = "、".join(esc(item["n"]) for item in R["behaviors"][:3])
    backup = (
        f'<p class="t-micro">备用通道：{"；".join(f"{name}（{desc}）" for name, desc in channels[1:])}</p>'
        if len(channels) > 1
        else ""
    )
    beh_html = (
        f'<div class="t-tip">📋 <b>孩子当前最值得关注的 3 个行为信号：</b>{behs} —— 每个行为背后都是需求（详见第十三节行为速查与对应建议）。</div>'
        if behs
        else ""
    )
    return f'''<div class="topic-grid-2">
      <div class="t-box"><b>❤️ 读懂孩子的沟通通道（教育学 · 以优势为通道）</b>
        <p>孩子最顺的沟通方式：<b>{top[0]}</b> — {top[1]}</p>
        {backup}
        <p class="t-micro">每个孩子都有一个「信号通道」：用对通道，说一遍就通；用错通道，说十遍都像噪音。</p>
      </div>
      <div class="t-box"><b>👨‍👩‍👧 权威型教养三要素（Baumrind）</b>
        <p>① <b>温暖</b>：情感回应优先于道理说教；② <b>规则</b>：3-5 条家庭底线清晰一致；③ <b>自主</b>：底线内给孩子选择权。</p>
        <p class="t-micro">研究（Baumrind, 1991）表明：温暖+规则+自主并重的「权威型」教养，是儿童社会能力与学业表现最优的组合——既不是放任，也不是控制。</p>
      </div>
    </div>
    {beh_html}
    <h4>行为学沟通技巧（先连接，后纠正）</h4>
    <ul class="t-list">
      <li>表扬具体行为：「你主动把玩具收好了，妈妈看到了你的责任心」优于笼统的「你真棒」</li>
      <li>忽视小问题：安全与品格之外的小毛病（顶嘴、磨蹭），忽略比惩罚更有效（行为消退原理）</li>
      <li>设置可预期的家庭常规：固定的作息、吃饭、作业时间，减少「随时讨价还价」的消耗</li>
      <li>情绪失控时先处理自己的情绪：你冷静，孩子才学得会冷静（镜像神经元示范）</li>
    </ul>
    {_g_tip(ctx, "养育男孩提示：社会对男孩的期望（坚强/勇敢）容易让孩子压抑情绪——请定期创造「可以脆弱」的专属时间；男孩的服从性常低于女孩，规则需要「讲清楚为什么」而非只下命令。", "养育女孩提示：社会对女孩的期望（乖巧/懂事）容易让孩子学会讨好——请鼓励表达拒绝与不满；女孩对关系冲突更敏感，处理争端时多给修复关系的支持。")}'''


def _render_selfmgmt(ctx: dict) -> str:
    scores = ctx["scores"]
    i3, i2 = scores["i3"], scores["i2"]
    goal = round1(mean([scores[k] for k in ["g5", "s3"]]))
    tips = {
        "primary-low": [
            "家长陪练：固定作息表+可视化任务清单（贴墙），完成后打勾",
            "2 分钟法则：不想做时先做 2 分钟，启动后惯性会接管",
            "正向强化：完成即给即时肯定，奖励跟任务本身无关",
            "一次只养成一个习惯，21-30 天后再加新习惯",
        ],
        "primary-high": [
            "工具自主：引入计划表、打卡表，让孩子自己打勾自己复盘",
            "「家庭会议」每周 10 分钟：总结本周做得好/待改进，孩子主导",
            "目标要小：把「好好学习」拆成「每天 20 分钟阅读」这类可执行动作",
        ],
        "middle": [
            "自主设计：让孩子自己制定每日计划（家长只把关底线）",
            "执行意图（if-then）：「如果我回到家，就先写最难的作业」——把决策提前，减少意志力消耗",
            "延迟满足练习：先完成再娱乐，电子屏幕放在任务之后",
        ],
        "high": [
            "SMART 目标：具体、可衡量、可达成、相关、有时限",
            "周复盘制度：每周日 15 分钟总结进度，调整下周计划",
            "建立「最小可行习惯」：每天 10 分钟，坚持比强度重要",
        ],
        "adult": [
            "把习惯嵌入环境：把瑜伽垫铺好=瑜伽习惯；手机放另一个房间=专注习惯",
            "习惯叠加：在已有习惯后接新习惯（刷牙后=做 10 个深蹲）",
            "追踪记录：用打卡表/App 记录，看见进度本身就是强化",
        ],
    }
    tips_list = _stage_tips(ctx.get("stage"), tips)
    return f'''<div class="topic-grid-2">
      <div class="t-box"><b>⏰ 自律三维度画像</b>
        <p>情绪自控（i3 自律）：<b>{fmt(i3)}</b> {"——有较好的自我约束基础" if i3 >= 55 else "——自控力仍在发育，需要结构辅助"}</p>
        <p>目标感（实验 g5 + 领导 s3）：<b>{fmt(goal)}</b> — 计划-执行-复盘的习惯基础</p>
        <p>反省能力（i2）：<b>{fmt(i2)}</b> {"——具备复盘改进的自觉" if i2 >= 55 else "——需要引导式的「事后回顾」练习"}</p>
      </div>
      <div class="t-box"><b>🧠 心理学 · 自我决定理论（Deci & Ryan）</b>
        <p>内在动力来自三大需求：<b>自主感</b>（自己有选择权）、<b>胜任感</b>（难度刚好）、<b>归属感</b>（有人一起/被看见）。</p>
        <p>安排任务时问自己：孩子有选择吗？难度合适吗？有人陪伴或反馈吗？三缺一，动力就会打折。</p>
      </div>
    </div>
    <h4>{_stage_title(ctx, "习惯养成方案")}</h4>
    <ul class="t-list">{"".join(f"<li>{item}</li>" for item in tips_list)}</ul>
    <div class="t-tip">🔁 <b>行为学 · 习惯回环（Cue → Routine → Reward）：</b>触发线索（固定时间/地点）→ 行为动作（尽量小、可执行）→ 即时奖励（完成即满足）。把「想自律」翻译成「可重复的动作」，习惯就自然形成。</div>'''


def _render_creativity(ctx: dict) -> str:
    scores = ctx["scores"]
    g3 = scores["g3"]
    v45 = round1(mean([scores[k] for k in ["v4", "v5"]]))
    m5, b5, n2 = scores["m5"], scores["b5"], scores["n2"]
    tips = {
        "preschool": [
            "自由涂鸦：给白纸和颜料，不教画法、不评「像不像」——想象力先于技法",
            "假装游戏：医生、超市、恐龙世界，孩子当导演你当配角",
            "废旧材料创作：纸箱、瓶盖、布头变成任何东西",
            "开放式提问：「这个还能有什么用？」",
        ],
        "primary-low": [
            "每天一个「为什么」问题，鼓励孩子自己猜答案再一起查证",
            "乐高/搭建类自由创作（不按图纸）、编故事接龙",
            "「还有什么用途」游戏：水杯除了喝水还能做什么？——发散思维训练",
            "保留「弄乱权」：创作区允许不整洁",
        ],
        "primary-high": [
            "项目式创作：自选主题（动画、手工、科学实验），完成一个完整作品",
            "戏剧/演讲/写作：把想法「做出来」并展示",
            "引入 AI 工具：用 AIGC 生成图像/故事，人机协作创作",
            "鼓励参加科创/艺术类比赛：以赛代练，看见积累",
        ],
        "middle": [
            "设计思维五步：共情-定义-构思-原型-测试，解决真实问题",
            "跨学科项目：把科学+艺术+技术结合（如环保装置、校园改造提案）",
            "科创竞赛、编程创作、自媒体内容：作品集意识从这时建立",
        ],
        "high": [
            "跨学科创新：选一个真实问题做项目（环保、社区、AI 应用）",
            "AIGC 协作：提示词创作、人机共创，创造力=人的想法+工具的执行",
            "TRIZ 创新方法：把矛盾拆开，反向思考找解法",
        ],
        "adult": [
            "把创造力当工作方法：每天留 30 分钟「无目的探索」",
            "AIGC 提示词工程：会用 AI 的人，效率是别人的 3-10 倍",
            "跨界连接：把 A 领域经验移植到 B 领域，创新常发生在交叉处",
        ],
    }
    tips_list = _stage_tips(ctx.get("stage"), tips)
    return f'''<div class="topic-grid-2">
      <div class="t-box"><b>💡 创造力指标剖面</b>
        <p>发散思维（演绎 g3）：<b>{fmt(g3)}</b> — 举一反三、多角度想问题</p>
        <p>创作执行（绘图 v4 / 组砌 v5）：<b>{fmt(v45)}</b> — 把想法做出来</p>
        <p>音乐创作（m5）：<b>{fmt(m5)}</b> · 肢体律动（b5）：<b>{fmt(b5)}</b> · 探索欲（n2）：<b>{fmt(n2)}</b></p>
        <p class="t-micro">创造力 = 发散思维（想得多）× 执行能力（做得成）——两者缺一，创意都会「流产」。</p>
      </div>
      <div class="t-box"><b>🤖 AI 时代为什么要培养创造力（2026 视角）</b>
        <p>新课标已把跨学科学习提高到 ≥15%、AI 编程纳入综合实践课——标准答案类能力正被 AI 快速替代，而「提出好问题、做出新东西」的能力空前值钱。</p>
        <p class="t-micro">创造力是 AI 时代的护城河：机器负责「知道」，人负责「创造」。</p>
      </div>
    </div>
    <h4>{_stage_title(ctx, "创造力培养")}</h4>
    <ul class="t-list">{"".join(f"<li>{item}</li>" for item in tips_list)}</ul>
    <div class="t-tip">🏠 <b>家庭环境支持（心理学 · 心流 Csikszentmihalyi）：</b>① 容错：允许弄乱、允许失败，创作区不因整洁要求而限制；② 开放提问：少问「是不是」，多问「如果是你你会怎么做」；③ 留白时间：不要把时间表排满，无聊是创造力的温床。</div>'''


def _fit_talent(ctx: dict) -> float:
    values = [ctx["intelScores"][intel_id] for intel_id in [item["id"] for item in INTEL]]
    avg = mean(values)
    return round1(math.sqrt(mean([(value - avg) ** 2 for value in values])))


def _why_social(ctx: dict) -> str:
    score = ctx["intelScores"]["social"]
    if score >= 60:
        return f"人际沟通智能总分 {fmt(score)}（优势）：适合重点发展领导力、协作与沟通等社交资本。"
    if score >= 45:
        return f"人际沟通智能总分 {fmt(score)}：具备基础社交能力，可通过结构化练习向优势转化。"
    return f"人际沟通智能总分 {fmt(score)}：社交是「练出来」的行为技能，建议从低压力场景开始练习。"


def _why_focus(ctx: dict) -> str:
    if ctx.get("who") == "kid":
        return "家长高频关注课题：注意力与习惯养成是学龄期最常见的行为议题，适合用行为学方法系统改善。"
    i3 = ctx["scores"]["i3"]
    if i3 < 50:
        return f"自律指标 {fmt(i3)} 偏低：注意力管理是当前最值得投入的提升点。"
    sensitivity = mean([ctx["scores"][k] for k in ["m1", "n1", "v1"]])
    if sensitivity >= 60:
        return f"感官敏感度偏高（听觉/观察/图像 {fmt(sensitivity)}）：对环境刺激易分心，需要环境设计辅助。"
    return "专注力是学习效率的放大器：通过环境设计与行为塑造，任何人都能显著提升。"


def _why_career(ctx: dict) -> str:
    if ctx.get("edition") == "adult" and ctx.get("job"):
        return f"已录入职业「{ctx['job']}」：对照你的优势智能剖面，分析当前职业的匹配度与在岗发展/转型建议。"
    if ctx.get("edition") == "adult":
        return "成年版核心模块：在页面顶部「当前职业」录入职业后重新生成报告，可解锁「职业 × 优势」个性化匹配分析。"
    return "职业方向初探（15 岁+）：从八大智能优势出发，定位适合的未来赛道与职业路径。"


def _why_selfmgmt(ctx: dict) -> str:
    i3 = ctx["scores"]["i3"]
    return (
        f"自律指标 {fmt(i3)} 已是优势：可进一步升级为目标管理与习惯系统。"
        if i3 >= 60
        else f"自律指标 {fmt(i3)} 仍有提升空间：小步习惯养成正当时，越早建立越省力。"
    )


def _why_creativity(ctx: dict) -> str:
    return (
        f"创造力相关指标均分 {fmt(ctx['fit'])}（突出）：适合把创新思维作为差异化优势重点培养。"
        if ctx["fit"] >= 60
        else f"创造力相关指标均分 {fmt(ctx['fit'])}：创造力是可训练的核心素养，AI 时代尤其值得投入。"
    )


TOPICS = [
    {
        "id": "learning",
        "icon": "📚",
        "name": "学习引擎",
        "sub": "高效学习策略与学科提升",
        "age": None,
        "who": "both",
        "core": True,
        "tags": ["教育学", "心理学"],
        "basis": "教育学学习策略与认知心理学元认知理论：学习效率取决于「输入通道 × 自我监控」，是任何年龄学业表现的第一杠杆。",
        "inds": ["l1", "l2", "l3", "l4", "l5", "g1", "g2", "g3", "g4", "g5"],
        "fitLabel": "匹配",
        "why": lambda ctx: "核心素养模块：高效的学习通道与学习策略，是任何年龄阶段学业与成长的基础。",
        "render": _render_learning,
    },
    {
        "id": "talent",
        "icon": "🎯",
        "name": "天赋雷达",
        "sub": "优势识别与兴趣定位",
        "age": None,
        "who": "both",
        "core": True,
        "tags": ["心理学", "教育学"],
        "basis": "积极心理学优势理论（Peterson & Seligman）：把精力投在优势上比拼命补短板更能提升成就感与长期成就；教育学因材施教。",
        "inds": list(IND.keys()),
        "fitLabel": "天赋分化度",
        "fitFn": _fit_talent,
        "why": lambda ctx: "核心素养模块：先看清优势在哪里，再做培养投入与方向选择的决策。",
        "render": _render_talent,
    },
    {
        "id": "emotion",
        "icon": "🌈",
        "name": "情绪小管家",
        "sub": "情绪管理与心理韧性",
        "age": None,
        "who": "both",
        "core": True,
        "tags": ["心理学", "行为学"],
        "basis": "情绪智力理论（Goleman）：情绪觉察-调控-共情决定 EQ，对学业与事业的影响长期研究可达 20-30%；发展心理学分龄情绪技能。",
        "inds": ["i1", "i2", "i3", "i4", "i5", "l5", "s2"],
        "fitLabel": "匹配",
        "why": lambda ctx: "核心素养模块：情绪觉察与调节能力，是所有学习与人际关系的地基。",
        "render": _render_emotion,
    },
    {
        "id": "social",
        "icon": "🤝",
        "name": "社交成长营",
        "sub": "人际交往与情商培养",
        "age": None,
        "who": "both",
        "tags": ["心理学", "行为学", "教育学"],
        "basis": "社会学习理论（Bandura）：观察-模仿-强化是社交能力习得路径；行为学视角——社交是「练出来」的行为技能，可分解练习。",
        "inds": ["s1", "s2", "s3", "s4", "s5", "i4", "i5"],
        "fitLabel": "匹配",
        "why": _why_social,
        "render": _render_social,
    },
    {
        "id": "focus",
        "icon": "⏱",
        "name": "专注力工坊",
        "sub": "注意力管理与行为习惯",
        "age": None,
        "who": "both",
        "tags": ["行为学", "心理学"],
        "basis": "行为学 ABC 模型（前因-行为-后果）与认知心理学注意理论：专注力可被环境设计、任务结构与强化方式系统塑造。",
        "inds": ["i3", "g1", "b3", "n1", "m1", "v1"],
        "fitLabel": "匹配",
        "why": _why_focus,
        "render": _render_focus,
    },
    {
        "id": "academy",
        "icon": "🧭",
        "name": "升学导航",
        "sub": "选科与升学规划",
        "age": [12, 18],
        "who": "both",
        "edition": "edu",
        "tags": ["教育学", "心理学"],
        "basis": "教育学学科×能力匹配与生涯发展理论（Super）：12-18 岁处于生涯「探索期」，选科与专业方向需要提前与能力优势对齐。",
        "inds": ["l1", "l2", "l4", "g1", "g2", "g3", "g4", "g5", "s5", "n3"],
        "fitLabel": "匹配",
        "why": lambda ctx: "升学关键期（12-18 岁）：选科与专业方向需要提前与能力优势对齐，避免临门一脚才做决定。",
        "render": _render_academy,
    },
    {
        "id": "career",
        "icon": "💼",
        "name": "职业罗盘",
        "sub": "职业匹配与优势定位",
        "age": [15, 100],
        "who": "both",
        "adultCore": True,
        "tags": ["心理学", "教育学"],
        "basis": "生涯心理学 Holland 职业兴趣六型、Super 生涯彩虹与人-职匹配理论（Person-Job Fit）：优势智能与职业类型越一致，职业满意度与稳定性越高；行动比测评更重要。",
        "inds": list(IND.keys()),
        "fitLabel": "匹配",
        "why": _why_career,
        "render": _render_career,
    },
    {
        "id": "parenting",
        "icon": "❤️",
        "name": "亲子沟通桥",
        "sub": "读懂孩子与关系经营",
        "age": [0, 18],
        "who": "kid",
        "edition": "edu",
        "tags": ["心理学", "教育学", "行为学"],
        "basis": "依恋理论（Bowlby）+ 权威型教养（Baumrind，温暖+规则+自主）+ 正面管教：先连接后纠正，行为背后都是需求。",
        "inds": ["s1", "s2", "s5", "i4", "i5", "l5"],
        "fitLabel": "匹配",
        "why": lambda ctx: "家长视角：孩子每个「问题行为」背后都是未被满足的需求——读懂信号，沟通才有效。",
        "render": _render_parenting,
    },
    {
        "id": "selfmgmt",
        "icon": "⏰",
        "name": "自律教练",
        "sub": "目标管理与习惯养成",
        "age": [6, 100],
        "who": "both",
        "tags": ["行为学", "心理学"],
        "basis": "行为学习惯回环（Cue-Routine-Reward）与自我决定理论（Deci & Ryan：自主感/胜任感/归属感）：自律是「可训练的系统」而非性格。",
        "inds": ["i3", "i2", "g5", "s3", "n4"],
        "fitLabel": "匹配",
        "why": _why_selfmgmt,
        "render": _render_selfmgmt,
    },
    {
        "id": "creativity",
        "icon": "💡",
        "name": "创造力工坊",
        "sub": "创新思维与未来素养",
        "age": None,
        "who": "both",
        "tags": ["教育学", "心理学"],
        "basis": "发散思维理论（Guilford）+ 心流理论（Csikszentmihalyi）+ 2026 新课标（跨学科≥15%、AI 编程进课堂）：创造力是 AI 时代的差异化护城河。",
        "inds": ["g3", "v4", "v5", "m5", "b5", "n2"],
        "fitLabel": "匹配",
        "why": _why_creativity,
        "render": _render_creativity,
    },
]


# ---------------------------------------------------------------- 分析与渲染


def analyze_topics(scores: dict, intel_scores: dict, meta: dict, report: dict) -> list:
    R = {**report, "intelScores": intel_scores}
    raw_age = parse_float(meta.get("age"))
    has_age = math.isfinite(raw_age) and str(meta.get("age") or "").strip() != ""
    edition = meta.get("edition")
    if edition not in ("edu", "adult"):
        edition = "adult" if has_age and raw_age > 23 else "edu"
    gender = meta.get("gender") if meta.get("gender") in ("男", "女") else ""
    who = meta.get("who") if meta.get("who") in ("me", "kid") else "me"
    purpose = purpose_of(meta)
    purpose_modules = PURPOSES[purpose]["modules"]
    stage = age_stage_of(raw_age if has_age else None)
    gate_age = raw_age if has_age else (30 if edition == "adult" else float("nan"))

    result = []
    for topic in TOPICS:
        base = {
            "scores": scores,
            "intelScores": intel_scores,
            "meta": meta,
            "stage": stage,
            "age": raw_age if has_age else None,
            "gender": gender,
            "who": who,
            "edition": edition,
            "job": str(meta.get("job") or "").strip(),
            "purpose": purpose,
            "R": R,
        }
        fit_fn = topic.get("fitFn")
        if fit_fn:
            fit = fit_fn(base)
        else:
            fit = round1(mean(scores[key] for key in topic["inds"]))
        edition_ok = not topic.get("edition") or topic["edition"] == edition
        age_range = topic.get("age")
        if not age_range:
            age_pass = True
        else:
            age_pass = (
                math.isfinite(gate_age) and gate_age >= age_range[0] and gate_age < age_range[1]
            )
        who_ok = topic["who"] == "both" or topic["who"] == who
        eligible = edition_ok and age_pass and who_ok
        lock_reason = ""
        if not edition_ok:
            lock_reason = "教育版专属模块（当前为成年版）" if topic["edition"] == "edu" else "成年版专属模块（当前为教育版）"
        elif not age_pass:
            lock_reason = (
                f"适龄 {age_range[0]}-{age_range[1]} 岁"
                if math.isfinite(gate_age)
                else "请先填写年龄"
            )
        elif not who_ok:
            lock_reason = "适合家长为孩子解读" if topic["who"] == "kid" else "适合自测者本人解读"
        ctx = {**base, "fit": fit}
        result.append(
            {
                "id": topic["id"],
                "icon": topic["icon"],
                "name": topic["name"],
                "sub": topic["sub"],
                "age": topic.get("age"),
                "who": topic["who"],
                "core": bool(topic.get("core")) or (edition == "adult" and bool(topic.get("adultCore"))),
                "edition": topic.get("edition") or None,
                "inPurpose": bool(purpose_modules) and topic["id"] in purpose_modules,
                "tags": topic["tags"],
                "basis": topic["basis"],
                "inds": topic["inds"],
                "fitLabel": topic.get("fitLabel") or "匹配",
                "fit": fit,
                "eligible": eligible,
                "lockReason": lock_reason,
                "why": topic["why"](ctx) if eligible else "",
                "ctx": ctx,
                "render": topic["render"],
            }
        )
    if purpose_modules:
        order = {topic_id: index for index, topic_id in enumerate(purpose_modules)}
        default = len(purpose_modules)
        result.sort(key=lambda item: order.get(item["id"], default))
    return result


def purpose_guide_html(R: dict, purpose: str) -> str:
    purpose_item = PURPOSES[purpose]
    topics = R.get("topics") or []
    items = []
    for topic_id in purpose_item["modules"]:
        topic = next((item for item in topics if item["id"] == topic_id), None)
        if not topic:
            continue
        if topic["eligible"]:
            items.append(
                f'<li><span class="pg-ok">{topic["icon"]} <b>{esc(topic["name"])}</b></span>——{esc(topic["sub"])}</li>'
            )
        else:
            items.append(
                f'<li><span class="pg-lock">🔒 {topic["icon"]} <b>{esc(topic["name"])}</b>（{esc(topic["lockReason"])}，暂未解锁）</span></li>'
            )
    dynamic = []
    meta = R.get("meta") or {}
    if purpose == "family" and meta.get("who") != "kid":
        dynamic.append("当前「为谁解读」为本人（自测视角），「亲子沟通桥」需要家长视角——请切换为「我的孩子 / 他人」后重新生成。")
    if purpose == "career" and meta.get("edition") != "adult":
        dynamic.append("当前为教育版：建议切换「成年版」并填写当前职业，解锁「职业 × 优势」人-职匹配分析。")
    if purpose == "career" and meta.get("edition") == "adult" and not str(meta.get("job") or "").strip():
        dynamic.append("成年版已选择但未录入职业，请填写「当前职业」以生成人-职匹配分析。")
    eligible_in_purpose = [
        topic_id
        for topic_id in purpose_item["modules"]
        if (topic := next((item for item in topics if item["id"] == topic_id), None)) and topic["eligible"]
    ]
    if purpose != "career" and not eligible_in_purpose:
        dynamic.append("该目的推荐模块当前均未解锁（见上方锁定原因）——可补填年龄/切换视角，或直接查看其他模块解读。")
    dynamic_html = f'<p class="pg-hint">⚙️ {" ".join(esc(item) for item in dynamic)}</p>' if dynamic else ""
    return f'''<div class="purpose-guide">
    <div class="pg-hd">{purpose_item["icon"]} 解读目的 · {esc(purpose_item["name"])}</div>
    <p class="pg-focus">{esc(purpose_item["focus"])}</p>
    <div class="pg-order"><b>推荐阅读顺序：</b><ol>{"".join(items)}</ol></div>
    <p class="pg-hint">💡 {esc(purpose_item["hint"])}</p>
    {dynamic_html}
  </div>'''


def render_topic_card(topic: dict) -> str:
    purpose = (topic.get("ctx") or {}).get("purpose")
    prefix = f'【{PURPOSES[purpose]["name"]}】' if topic.get("inPurpose") and purpose and purpose != "all" else ""
    body = topic["render"](topic["ctx"]) if topic.get("render") else ""
    return f'''<div class="topic-card" id="topic_{topic["id"]}">
    <div class="tc-hd"><span class="tc-ic">{topic["icon"]}</span><span class="tc-t">{esc(topic["name"])} · 专题解读</span>
      <span class="tc-fit">{esc(topic["fitLabel"])} {fmt(topic["fit"])} · 关联 {len(topic["inds"])} 项指标</span></div>
    <div class="tc-why">📌 <b>为什么推荐：</b>{prefix}{esc(topic["why"])}</div>
    <div class="tc-basis">🧬 <b>设计依据：</b>{esc(topic["basis"])}（{" + ".join(topic["tags"])}）</div>
    {body}
  </div>'''


def render_topic_section(R: dict) -> str:
    topics = R.get("topics") or []
    if not topics:
        return ""
    meta = R.get("meta") or {}
    age = parse_float(meta.get("age"))
    stage = age_stage_of(age if math.isfinite(age) else None)
    gender = str(meta.get("gender") or "")
    who = "kid" if meta.get("who") == "kid" else "me"
    edition = "adult" if meta.get("edition") == "adult" else "edu"
    job = str(meta.get("job") or "").strip()
    purpose = purpose_of(meta)
    purpose_item = PURPOSES[purpose]
    note = gender_note_for(edition, who, gender)
    cards = [topic for topic in topics if topic["eligible"]]
    if edition == "adult":
        if stage:
            age_chip = f'{str(int(age)) + " 岁 · " if math.isfinite(age) else ""}{esc(stage["name"])}'
        else:
            age_chip = "成年版（按成人解读）"
    else:
        if stage:
            age_chip = f'{str(int(age)) + " 岁 · " if math.isfinite(age) else ""}{esc(stage["name"])}'
        else:
            age_chip = "未填写（年龄专属模块未解锁）"
    gender_chip = esc(gender) if gender else "未填写（不显示性别提示）"
    job_chip = f'<span class="topic-chip">💼 当前职业：<b>{esc(job) if job else "未录入"}</b></span>' if edition == "adult" else ""
    gender_html = (
        f'<div class="gender-note">🚻 <b>{esc(note["tag"])}：</b>{esc(note["text"])}</div>' if note else ""
    )
    guide = purpose_guide_html(R, purpose) if purpose != "all" else ""
    cards_html = (
        f'<div class="topic-cards">{"".join(render_topic_card(topic) for topic in cards)}</div>'
        if cards
        else '<div class="highlight-box">当前没有已解锁的专题模块：可补填年龄或切换解读视角后重新生成。</div>'
    )
    return f'''<section class="sec" id="s17">
    <h2>十七、专题解读模块 · 按目的 × 版本 × 年龄 × 性别 × 40 项结果</h2>
    <p class="note">本节<b>结合教育学（学习策略/生涯教育）、心理学（积极心理学/情绪智力/发展心理学/依恋理论）与行为学（行为塑造/习惯养成/环境设计）</b>，从 40 项能力结果出发，按「解读目的 × 解读版本 × 年龄阶段 × 性别视角 × 为谁解读」自动匹配专题模块。<b>已解锁的模块全部展示</b>；选择「解读目的」后，目的相关模块会置顶并给出推荐阅读顺序与导语。</p>
    <div class="topic-profile">
      <span class="topic-chip">🎯 解读目的：<b>{purpose_item["icon"]} {esc(purpose_item["name"])}</b></span>
      <span class="topic-chip">📦 解读版本：<b>{"成年版（职业发展）" if edition == "adult" else "教育版（成长培养）"}</b></span>
      <span class="topic-chip">🎂 年龄阶段：<b>{age_chip}</b></span>
      <span class="topic-chip">🚻 性别视角：<b>{gender_chip}</b></span>
      <span class="topic-chip">👤 为谁解读：<b>{"孩子 / 他人（家长视角）" if who == "kid" else "本人（自测视角）"}</b></span>
      {job_chip}
    </div>
    {gender_html}
    {guide}
    {cards_html}
  </section>'''

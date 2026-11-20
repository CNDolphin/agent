# Python Agent 开发计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一个本地运行的 Python Agent,具备心理健康支持与评估筛查技能,所有隐私数据本地加密存储,模型调用经后端网关。

**Architecture:** 确定性逻辑(量表计分、压力指数、风险规则、积分/余额处理)全部用代码实现并充分测试;LLM 只负责对话、解释和引导。每轮对话先过安全层,危机话术不依赖网关。技能以 `SKILL.md` + 数据文件形式存在,按意图加载。

**Tech Stack:** Python 3.11+、pytest、httpx、cryptography(Fernet + scrypt)、sqlite3(字段级加密)、PyYAML、pydantic。

契约见 `00-overview-and-contracts.md` 第 3 节。

---

## 文件结构

```
agent/                              # 项目根:/Users/jiapenghuang/project/service/program/agent
├── pyproject.toml
├── config.yaml                     # gateway.base_url、model、本地数据目录等,不含密钥
├── main.py                         # 命令行入口
├── mhagent/
│   ├── __init__.py
│   ├── loop.py                     # 对话循环
│   ├── prompts.py                  # 系统提示词
│   ├── skill_loader.py             # 技能加载与意图路由
│   ├── safety.py                   # 风险分级、危机话术、出站检查
│   ├── notifier.py                 # 紧急通知(需用户授权)
│   ├── consent.py                  # 授权状态读写
│   ├── llm/{base,gateway,mock}.py
│   ├── store/{crypto,db,export}.py
│   ├── tools/
│   │   ├── scales.py               # 计分与分级(纯函数)
│   │   ├── stress_index.py
│   │   ├── journal.py
│   │   ├── practices.py
│   │   └── data/{phq9,gad7,pss10}.json, practices.json, cbt_templates.json, knowledge.json
│   └── insight/provider.py         # ReportProvider 接口(技能 3 预留)
├── skills/{mental-health,assessment,gene-guidance}/SKILL.md
└── tests/
```

## Chunk 1: 纯逻辑(M1)

### Task 0: 项目初始化

**Files:** Create `pyproject.toml`、`mhagent/__init__.py`、`tests/__init__.py`、`.gitignore`

- [ ] **Step 1: 初始化仓库与环境**

```bash
cd /Users/jiapenghuang/project/service/program/agent
git init
python3 -m venv .venv && source .venv/bin/activate
```

- [ ] **Step 2: 写 `pyproject.toml`**(依赖:httpx、cryptography、pyyaml、pydantic;dev:pytest、pytest-asyncio、respx)并安装

```bash
pip install -e '.[dev]'
```

- [ ] **Step 3: `.gitignore` 加入** `.venv/ __pycache__/ *.db *.enc .env`;写一个 `tests/test_smoke.py` 断言 `import mhagent`。

- [ ] **Step 4: 运行**

Run: `pytest -q`
Expected: `1 passed`

- [ ] **Step 5: 提交** `git add -A && git commit -m "chore: init python agent project"`

### Task 1: 量表计分与分级(TDD)

**Files:** Create `mhagent/tools/scales.py`;Test `tests/tools/test_scales.py`

计分规则:
- PHQ-9:9 题,每题 0–3,总分 0–27。分级:0–4 minimal、5–9 mild、10–14 moderate、15–19 moderately_severe、20–27 severe。
- GAD-7:7 题,每题 0–3,总分 0–21。分级:0–4 minimal、5–9 mild、10–14 moderate、15–21 severe。
- PSS-10:10 题,每题 0–4,第 4、5、7、8 题(1 起算)反向计分(`4 - x`),总分 0–40。分级:0–13 low、14–26 moderate、27–40 high。

- [ ] **Step 1: 写失败测试**

```python
import pytest
from mhagent.tools.scales import score_phq9, score_gad7, score_pss10, ScaleError


@pytest.mark.parametrize("answers,total,level", [
    ([0] * 9, 0, "minimal"),
    ([1, 1, 1, 1, 0, 0, 0, 0, 0], 4, "minimal"),
    ([1, 1, 1, 1, 1, 0, 0, 0, 0], 5, "mild"),
    ([1] * 9, 9, "mild"),
    ([2, 2, 1, 1, 1, 1, 1, 1, 0], 10, "moderate"),
    ([2] * 7 + [1, 0], 15, "moderately_severe"),
    ([3] * 9, 27, "severe"),
])
def test_phq9_levels(answers, total, level):
    r = score_phq9(answers)
    assert (r.total, r.level) == (total, level)


def test_phq9_item9_flag():
    assert score_phq9([0] * 8 + [1]).item9_positive is True
    assert score_phq9([3] * 8 + [0]).item9_positive is False


@pytest.mark.parametrize("answers,total,level", [
    ([0] * 7, 0, "minimal"),
    ([1] * 5 + [0, 0], 5, "mild"),
    ([2] * 5 + [0, 0], 10, "moderate"),
    ([3] * 7, 21, "severe"),
])
def test_gad7_levels(answers, total, level):
    r = score_gad7(answers)
    assert (r.total, r.level) == (total, level)


def test_pss10_reverse_items():
    # 全部答 0:正向题 0,反向题(4,5,7,8)各得 4 => 16
    assert score_pss10([0] * 10).total == 16
    # 全部答 4:正向题 4*6=24,反向题 0 => 24
    assert score_pss10([4] * 10).total == 24


def test_pss10_levels():
    assert score_pss10([0, 0, 0, 4, 4, 0, 4, 4, 0, 0]).level == "low"      # 0
    assert score_pss10([4, 4, 4, 0, 0, 4, 0, 0, 4, 4]).level == "high"     # 24 + 16 = 40


@pytest.mark.parametrize("fn,n", [(score_phq9, 9), (score_gad7, 7), (score_pss10, 10)])
def test_invalid_input(fn, n):
    with pytest.raises(ScaleError):
        fn([0] * (n - 1))          # 题数不对
    with pytest.raises(ScaleError):
        fn([9] * n)                # 超出范围
    with pytest.raises(ScaleError):
        fn(["a"] * n)              # 类型错误
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/tools/test_scales.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 最小实现**

```python
from dataclasses import dataclass

class ScaleError(ValueError):
    pass

@dataclass(frozen=True)
class ScaleResult:
    scale: str
    total: int
    max_total: int
    level: str
    item9_positive: bool = False   # 仅 PHQ-9 使用

def _validate(answers, n, lo, hi):
    if not isinstance(answers, (list, tuple)) or len(answers) != n:
        raise ScaleError(f"expected {n} answers")
    for a in answers:
        if isinstance(a, bool) or not isinstance(a, int) or not lo <= a <= hi:
            raise ScaleError(f"answer must be int in [{lo},{hi}]")

def _level(total, bands):
    for upper, name in bands:
        if total <= upper:
            return name
    raise ScaleError("total out of range")

_PHQ9 = [(4, "minimal"), (9, "mild"), (14, "moderate"), (19, "moderately_severe"), (27, "severe")]
_GAD7 = [(4, "minimal"), (9, "mild"), (14, "moderate"), (21, "severe")]
_PSS10 = [(13, "low"), (26, "moderate"), (40, "high")]
_PSS_REVERSE = {3, 4, 6, 7}   # 0 起算的下标,对应第 4、5、7、8 题

def score_phq9(answers):
    _validate(answers, 9, 0, 3)
    t = sum(answers)
    return ScaleResult("phq9", t, 27, _level(t, _PHQ9), item9_positive=answers[8] > 0)

def score_gad7(answers):
    _validate(answers, 7, 0, 3)
    t = sum(answers)
    return ScaleResult("gad7", t, 21, _level(t, _GAD7))

def score_pss10(answers):
    _validate(answers, 10, 0, 4)
    t = sum(4 - a if i in _PSS_REVERSE else a for i, a in enumerate(answers))
    return ScaleResult("pss10", t, 40, _level(t, _PSS10))
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/tools/test_scales.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交** `git add -A && git commit -m "feat: add phq9/gad7/pss10 scoring"`

### Task 2: 题库数据文件与加载

**Files:** Create `mhagent/tools/data/phq9.json`、`gad7.json`、`pss10.json`;Modify `scales.py`(新增 `load_questionnaire`);Test `tests/tools/test_questionnaire_data.py`

数据格式:
```json
{"scale": "phq9", "version": "1", "intro": "...", "options": [{"value": 0, "label": "完全不会"}, ...], "items": ["...", "..."]}
```

- [ ] **Step 1: 写失败测试**:`load_questionnaire("phq9")` 的 `items` 长度为 9、`options` 值为 0–3;`gad7` 长度 7;`pss10` 若题目文本尚未填入(授权待确认),`items` 为空列表且 `available` 为 False,调用评估入口时返回"该量表暂不可用"。
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 写 `phq9.json`(中文题干,选项:完全不会 / 好几天 / 一半以上的天数 / 几乎每天)与 `gad7.json`**;`pss10.json` 仅放 `version`、`options` 和空 `items`,并在文件中加注释字段 `"todo": "待授权确认后填入题目文本"`。实现 `load_questionnaire`。
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `git commit -m "feat: add questionnaire data files"`

### Task 3: 压力指数(TDD)

**Files:** Create `mhagent/tools/stress_index.py`;Test `tests/tools/test_stress_index.py`

公式(写进代码注释与测试):
- `pss_norm = pss_total / 40 * 100`
- `journal_norm = mean(近 14 天日记情绪强度 0–10) / 10 * 100`,只统计消极情绪条目;无条目则为 `None`
- 有日记:`index = round(0.7 * pss_norm + 0.3 * journal_norm)`;无日记:`index = round(pss_norm)`
- 区间:0–33 low、34–66 medium、67–100 high

- [ ] **Step 1: 写失败测试**

```python
from mhagent.tools.stress_index import stress_index

def test_pss_only():
    r = stress_index(pss_total=20, recent_negative_intensities=[])
    assert r.value == 50 and r.band == "medium" and r.used_journal is False

def test_with_journal():
    # pss_norm=50, journal_norm=80 => 0.7*50+0.3*80 = 59
    r = stress_index(20, [8, 8, 8])
    assert r.value == 59 and r.used_journal is True

def test_bounds():
    assert stress_index(0, []).value == 0
    assert stress_index(40, [10]).value == 100
    assert stress_index(40, [10]).band == "high"

def test_band_edges():
    assert stress_index(13, []).band == "low"      # 32.5 -> 33
    assert stress_index(14, []).band == "medium"   # 35
    assert stress_index(27, []).band == "high"     # 67.5 -> 68

def test_invalid():
    import pytest
    with pytest.raises(ValueError):
        stress_index(41, [])
    with pytest.raises(ValueError):
        stress_index(10, [11])
```

- [ ] **Step 2: 运行确认失败** `pytest tests/tools/test_stress_index.py -v`
- [ ] **Step 3: 实现**(注意 Python 的 `round` 是银行家舍入,必须用 `int(x + 0.5)` 做四舍五入:13→32.5→33(low)、27→67.5→68(high),与上面边界用例一致)
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `git commit -m "feat: add stress index"`

### Task 4: 安全层(TDD,最高优先级)

**Files:** Create `mhagent/safety.py`、`tests/data/risk_corpus.json`;Test `tests/test_safety.py`

接口:
```python
class Risk(IntEnum): LOW = 0; MEDIUM = 1; HIGH = 2

@dataclass(frozen=True)
class RiskResult:
    level: Risk
    reasons: list[str]      # 规则名,不含原文

def classify_rules(text: str) -> RiskResult: ...
def combine(*levels: Risk) -> Risk: ...          # 取最大值
def from_phq9(result) -> Risk: ...               # item9_positive -> HIGH 候选,见下
def crisis_message(authorized_contact: bool) -> str: ...
def check_outbound(text: str) -> OutboundCheck: ...
```

规则:
- HIGH:明确的自杀/自伤意图或计划表达(中文:"想死""不想活""自杀""结束生命""结束自己""了结""割腕""跳楼""吃药自杀"等;英文:`kill myself`、`end my life`、`suicide`);否定句("我不会自杀""以前想过现在没有了")需要能降为 MEDIUM,不能直接漏判也不能全部误判——见语料。
- MEDIUM:持续低落、绝望("活着没意思""撑不下去""没有希望""什么都不想做")。
- PHQ-9 第 9 题非 0 → 至少 MEDIUM;为 3 或 2 → HIGH;为 1 → MEDIUM 并触发追问。
- `combine` 取最大;规则命中 HIGH 时不得被模型复核降级。

- [ ] **Step 1: 构造语料集 `risk_corpus.json`**:每条 `{"text": ..., "expected": "HIGH|MEDIUM|LOW"}`,至少 60 条(HIGH 25、MEDIUM 20、LOW 15),覆盖:直接表达、委婉表达、英文、否定句、过去时、他人话题("我朋友想自杀"→ MEDIUM,提示协助朋友)、无关日常(含易误判词如"累死了""笑死我了""烦死了"应为 LOW)。**语料由人审阅**。
- [ ] **Step 2: 写失败测试**
  - `test_high_corpus_never_missed`:全部 HIGH 条目必须判为 HIGH(漏判 = 失败)。
  - `test_medium_corpus_at_least_medium`:MEDIUM 条目判为 ≥ MEDIUM。
  - `test_low_corpus_false_positive_rate`:LOW 条目判为非 LOW 的比例 ≤ 10%,并输出被误判条目。
  - `test_combine_takes_max`、`test_phq9_item9_mapping`。
  - `test_crisis_message_contains_hotline`:包含 `12356`、`120`;已授权版本包含"将通知你的紧急联系人"字样,未授权版本包含"请联系身边信任的人"字样。
  - `test_outbound_blocks_method_details`:模型输出含具体自伤方法细节关键词时,`check_outbound` 返回 `blocked=True`,并提供替换文本。
  - `test_reasons_do_not_leak_text`:`RiskResult.reasons` 不含用户原文。
- [ ] **Step 3: 运行确认失败**
- [ ] **Step 4: 实现规则与话术**(关键词表放 `mhagent/data/risk_rules.json`,便于审阅与维护;正则做简单否定窗口检测)
- [ ] **Step 5: 运行确认通过;语料回归失败时只能改规则,禁止删语料**
- [ ] **Step 6: 提交** `git commit -m "feat: add safety layer with risk corpus regression"`

## Chunk 2: 本地存储与工具(M4)

### Task 5: 加密(TDD)

**Files:** Create `mhagent/store/crypto.py`;Test `tests/store/test_crypto.py`

- [ ] **Step 1: 写失败测试**:
  - `derive_key(passphrase, salt)` 同输入同输出,不同 salt 输出不同;
  - `encrypt/decrypt` 往返一致;密文每次不同;
  - 错误口令解密抛 `DecryptError`;篡改密文抛 `DecryptError`;
  - 空口令抛 `ValueError`。
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**:scrypt(`n=2**15, r=8, p=1`)派生 32 字节 → Fernet 密钥;salt 随机 16 字节,存在数据目录 `meta.json`(不是秘密)。
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `git commit -m "feat: add passphrase-based encryption"`

### Task 6: 本地加密库

**Files:** Create `mhagent/store/db.py`;Test `tests/store/test_db.py`

表结构(SQLite):`kv(key TEXT PRIMARY KEY, value BLOB)`、`records(id INTEGER PRIMARY KEY, kind TEXT, created_at TEXT, payload BLOB)`。`payload` 与 `value` 都是密文;只有 `kind` 与 `created_at` 为明文用于过滤。

- [ ] **Step 1: 写失败测试**:
  1. 写入记录后,直接读取 SQLite 文件原始字节,搜索唯一标记串 `PRIVATE-MARKER-xyz` 必须找不到;
  2. 正确口令可读回;错误口令打开时抛 `DecryptError` 且不修改文件;
  3. `add_record/list_records(kind, since, until)` 按时间过滤;
  4. `kv_set/kv_get` 往返;
  5. 数据目录首次创建权限为 `0700`,文件 `0600`。
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `git commit -m "feat: add encrypted local store"`

### Task 7: 情绪日记

**Files:** Create `mhagent/tools/journal.py`;Test `tests/tools/test_journal.py`

数据:`{date, event, emotions:[{name, intensity(0-10)}], thoughts, note}`。消极情绪名单放配置(焦虑、悲伤、愤怒、内疚、恐惧、孤独、无助等)。

- [ ] **Step 1: 写失败测试**:
  - `add_entry` 校验强度范围与必填字段,非法抛 `ValueError`;
  - `recent_negative_intensities(days=14, now=...)` 只返回窗口内且属于消极情绪的强度(为 `stress_index` 提供输入);
  - `weekly_review(week_start)` 返回条数、情绪频次 Top3、平均强度、与上周的强度变化;无数据时返回 `None`;
  - 注入时钟,不依赖系统时间。
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `git commit -m "feat: add emotion journal and weekly review"`

### Task 8: 练习与 CBT 模板数据

**Files:** Create `mhagent/tools/data/practices.json`、`cbt_templates.json`、`knowledge.json`、`mhagent/tools/practices.py`;Test `tests/tools/test_practices.py`

- [ ] **Step 1: 写失败测试**:
  - `get_practice("box_breathing")` 返回 `steps`(每步含 `instruction` 与 `seconds`)、`duration_seconds`、`stop_hint`;四个练习 id:`breathing_478`、`box_breathing`、`body_scan`、`grounding_54321` 都存在;
  - `get_cbt_template("thought_record")` 返回有序字段列表;四个模板 id:`thought_record`、`distortion_check`、`behavioral_activation`、`problem_solving`;
  - 未知 id 抛 `KeyError`;
  - `pick_knowledge(topic)` 按话题返回条目;未知话题返回空列表;每条含 `title`、`body`、`source`(来源字段不能为空)。
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 编写数据与加载**:内容由人审阅;`knowledge.json` 每条标注来源,首批 15–20 条覆盖睡眠、焦虑、压力、情绪调节、拖延与自我关怀。
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `git commit -m "feat: add practice scripts, cbt templates and knowledge base"`

### Task 9: 加密导出/导入

**Files:** Create `mhagent/store/export.py`;Test `tests/store/test_export.py`

- [ ] **Step 1: 写失败测试**:导出为单文件(含版本号、校验和,全部密文);新数据目录导入后记录一致;口令错误失败;文件被篡改失败;导入不覆盖已有数据(冲突时需 `overwrite=True`)。
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `git commit -m "feat: add encrypted export and import"`

## Chunk 3: LLM 层与技能(M5 前半)

### Task 10: LLM 抽象与 mock

**Files:** Create `mhagent/llm/base.py`、`mock.py`;Test `tests/llm/test_mock.py`

```python
class LLMError(Exception): ...
class InsufficientCredits(LLMError): ...
class GatewayUnavailable(LLMError): ...
class AuthExpired(LLMError): ...

@dataclass
class ChatResult:
    content: str
    input_hit: int
    input_miss: int
    output: int
    cost: int
    balance: int
    low_balance: bool = False

class LLMClient(Protocol):
    def chat(self, messages: list[dict], *, max_tokens: int = 1024) -> ChatResult: ...
    def chat_stream(self, messages, *, max_tokens=1024) -> Iterator[str]: ...
```

- [ ] **Step 1: 写失败测试**:mock 按脚本返回内容/抛指定异常,记录收到的 messages 供断言。
- [ ] **Step 2: 运行确认失败 → Step 3: 实现 → Step 4: 通过**
- [ ] **Step 5: 提交** `git commit -m "feat: add llm client protocol and mock"`

### Task 11: 网关客户端

**Files:** Create `mhagent/llm/gateway.py`、`mhagent/auth_session.py`;Test `tests/llm/test_gateway.py`(使用 `respx` 模拟)

- [ ] **Step 1: 写失败测试**:
  0. 登录:`send_code(phone)` 调 `/auth/sms/send`;`login(phone, code)` 调 `/auth/login`,保存令牌与 `is_new`;验证码错误(`40102`)抛 `CodeInvalid`;发送过频(429)抛 `TooFrequent` 并带出剩余等待秒数(若响应提供);手机号在本地先做格式校验,不合法不发请求;
  1. 成功:请求带 `Authorization` 与 `X-Request-Id`,解析 `content/usage(input_hit,input_miss,output)/cost/balance/low_balance`;请求体不包含 `thinking` 等后端专属字段;
  2. 402 `40201` → `InsufficientCredits`;
  3. 401 → 先 refresh 再重试一次;refresh 也失败 → `AuthExpired`;
  4. 502/超时/连接错误 → 重试 1 次(**同一个** `X-Request-Id`),仍失败 → `GatewayUnavailable`;
  5. 409(已结算)→ 视为成功语义的重复,返回特定异常 `DuplicateRequest` 由上层处理;
  6. 流式:解析 SSE 的 `delta/done/error`;中途 `error` 抛 `GatewayUnavailable`;
  7. 令牌保存在加密库 kv 中,不写入日志与明文文件。
- [ ] **Step 2: 运行确认失败 → Step 3: 实现 → Step 4: 通过**
- [ ] **Step 5: 提交** `git commit -m "feat: add gateway llm client"`

### Task 12: 技能文件与加载器

**Files:** Create `skills/*/SKILL.md`、`mhagent/skill_loader.py`;Test `tests/test_skill_loader.py`

SKILL.md 格式:YAML frontmatter(`name`、`description`、`triggers`)+ 正文(何时用、流程、边界、固定声明)。

- [ ] **Step 1: 写失败测试**:
  - `list_skills()` 返回三个技能的 name/description;
  - `load_skill("assessment")` 返回正文;未知名抛 `KeyError`;
  - `route(text)` 对"我想做个焦虑测试"返回 `assessment`,"教我呼吸放松"返回 `mental-health`,"帮我看看适合什么专业"返回 `gene-guidance`,闲聊返回 `None`(MVP 用关键词匹配,保留可替换为模型路由的接口);
  - `gene-guidance` 在无 `ReportProvider` 实现时,技能正文包含"暂未启用"说明,且 `route` 命中后返回说明文案而不是调用工具。
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 编写三个 SKILL.md**
  - `mental-health`:四个子能力的流程与边界(见设计文档 4.1);
  - `assessment`:评估前声明"筛查提示,非诊断";逐题提问、一次一题、允许中途退出;分数由工具给出,**禁止模型自行计算或改写等级**;
  - `gene-guidance`:框架 + 三条原则 + "暂未启用"状态说明。
- [ ] **Step 4: 实现加载器 → 运行确认通过**
- [ ] **Step 5: 提交** `git commit -m "feat: add skills and skill loader"`

### Task 13: 技能 3 预留接口

**Files:** Create `mhagent/insight/provider.py`;Test `tests/test_insight_provider.py`

```python
class ReportProvider(Protocol):
    def import_report(self, path: str) -> str: ...        # 返回本地 report_id
    def get_dimensions(self, report_id: str) -> dict: ... # 兴趣/特长维度
    def guidance(self, report_id: str, context: dict) -> dict: ...

class NotEnabled(ReportProvider): ...   # 所有方法抛 FeatureNotEnabled
```

- [ ] **Step 1: 写失败测试**:`NotEnabled` 的三个方法都抛 `FeatureNotEnabled`;主循环在此状态下对基因话题返回固定说明。
- [ ] **Step 2: 运行确认失败 → Step 3: 实现 → Step 4: 通过**
- [ ] **Step 5: 提交** `git commit -m "feat: add report provider interface placeholder"`

## Chunk 4: 对话循环与集成(M5 后半、M6)

### Task 14: 提示词

**Files:** Create `mhagent/prompts.py`;Test `tests/test_prompts.py`

- [ ] **Step 1: 写失败测试**:系统提示词包含:角色边界(非医生、不诊断、不开药)、"不替代专业帮助"、禁止自行计算量表分数、危机时的行为约束;根据当前已加载技能拼接其正文;总长度不超过设定上限。
- [ ] **Step 2: 运行确认失败 → Step 3: 实现 → Step 4: 通过**
- [ ] **Step 5: 提交** `git commit -m "feat: add system prompts"`

### Task 15: 对话循环

**Files:** Create `mhagent/loop.py`、`mhagent/consent.py`、`mhagent/notifier.py`;Test `tests/test_loop.py`

状态机:`NORMAL` / `ASSESSING(scale, index, answers)` / `PRACTICING(id, step)` / `CRISIS`。

每轮流程:
1. 规则安全检查(`classify_rules`);HIGH → 立即输出 `crisis_message` 并进入 `CRISIS`,**不调用网关**;
2. 技能路由与工具调用(评估状态下收集答案并确定性处理);
3. 调用 LLM(带系统提示词 + 技能正文 + 近期上下文,上下文窗口按字符预算裁剪);
4. 对模型回复做 `check_outbound`;
5. 模型分类复核(仅在规则为 LOW/MEDIUM 时异步或同步进行一次,结果取最大值;复核失败不影响主流程);
6. 写本地会话记录(加密)。

- [ ] **Step 1: 写失败测试**(全部使用 mock LLM):
  1. 普通对话:消息进入 LLM,回复返回;
  2. HIGH 输入:LLM mock 调用次数为 0,输出含 `12356`;之后状态为 `CRISIS`;`CRISIS` 状态下不再启动评估/练习;
  3. 已授权联系人:HIGH 时调用 `notifier.send` 一次且只调用一次;未授权:不调用,话术为"联系身边的人"版本;
  4. 通知失败:话术附"可复制的求助文字";
  5. 评估流程:"做个抑郁测试" → 逐题提问 → 9 题答完 → 结果由 `scale` 工具给出,回复中的分数与等级与工具一致(mock LLM 即使胡乱输出,最终展示的等级以工具为准);第 9 题非 0 触发风险处理;
  6. 评估中用户说"不想继续"可退出,不保存半成品;
  7. 余额不足(`InsufficientCredits`):普通对话给出"积分不足,可购买套餐获取积分"的提示(Agent 不提供购买入口,只提示去哪里购买,入口由运营告知);危机流程**不受影响**;响应 `low_balance=true` 时在回复末尾附一次余额提醒(同一会话只提醒一次);
  8. 网关不可用:提示稍后重试,安全检查仍然生效;
  9. 模型输出被 `check_outbound` 拦截:用户看到替换文本;
  10. 日记引导:完成后落库,可由 `weekly_review` 读到;
  11. 基因话题:返回"暂未启用"说明,不调用工具;
  12. 隐私:会话落盘后用标记串检查原始文件无明文。
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**;`notifier.py` 调 `/notify/emergency`,仅在 `consent.emergency_authorized` 为真时可用;授权状态存加密库并带授权时间。
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `git commit -m "feat: add conversation loop with safety-first flow"`

### Task 16: 命令行入口与首次引导

**Files:** Create `main.py`、`config.yaml`、`mhagent/cli_setup.py`;Test `tests/test_cli.py`

首次运行引导:设置本地口令(提示"口令丢失数据无法找回")→ 输入手机号并获取验证码登录(新用户提示获赠 100 积分)→ 展示并确认同意书(调 `/consent`,同意书需说明对话内容会经网关发送给第三方模型服务)→ 可选:填写紧急联系人(手机号或邮箱)并单独确认"高风险时通知该联系人"授权。

本地口令与手机号登录是两件事:登录令牌用于访问后端,本地口令用于加密本机数据;令牌存放在本地加密库里,过期后用验证码重新登录即可,**不影响本地数据**。

- [ ] **Step 1: 写失败测试**:用 `subprocess` 或函数级调用传入脚本化输入,验证:首次引导顺序;验证码错误可重试,连续失败提示稍后再试;拒绝同意书则退出且不保存数据;不填紧急联系人则授权为假;再次启动要求本地口令,错误口令不删除数据;令牌过期时只触发重新登录,本地数据完好;换手机号登录不会清除或混用本机数据(提示用户该设备上的本地数据属于原账号,是否继续使用)。
- [ ] **Step 2: 运行确认失败 → Step 3: 实现 → Step 4: 通过**
- [ ] **Step 5: 提交** `git commit -m "feat: add cli entry and first-run onboarding"`

### Task 17: 端到端与隐私验收

**Files:** Create `tests/e2e/test_e2e.py`

- [ ] **Step 1: 写测试**(mock 网关用 `respx`):完整会话:引导 → 对话 → 日记 → 评估 → 高风险 → 导出/导入。
- [ ] **Step 2: 隐私断言**:跑完后搜索数据目录所有文件与捕获日志,标记串 `PRIVATE-MARKER-xyz`(用户消息、日记、联系人)均不出现明文;发给 mock 网关的请求中**不包含**联系人信息与日记之外的本地数据(只含当前对话上下文)。
- [ ] **Step 3: 运行全部**

Run: `pytest -q`
Expected: 全部 PASS

- [ ] **Step 4: 提交** `git commit -m "test: add e2e and privacy acceptance"`

## Chunk 5: 联调与后续

### Task 18: 与后端联调(M3 之后)

- [ ] **Step 1:** 启动后端(mock upstream),Agent 配置 `gateway.base_url` 指向本地。
- [ ] **Step 2:** 手工走通:注册 → 对话 → 看余额下降 → 余额耗尽后提示购买套餐 → 危机话术仍可输出。
- [ ] **Step 3:** 对照账本核对每次 `cost` 与 `balance`。
- [ ] **Step 4:** 修复发现的契约偏差,更新 `00-overview-and-contracts.md`。

### Task 19: 技能 3 接入(阻塞于用户提供报告)

- [ ] **Step 1:** 收到报告样例后确认格式(PDF/文本/JSON),写入 `gene-guidance` 的格式说明。
- [ ] **Step 2:** 为 `ReportProvider` 写具体实现的失败测试:导入、维度提取、方向建议(含"倾向性参考"声明、不出现"天赋不足"类断言——用关键词黑名单断言)。
- [ ] **Step 3:** 报告文件加密存本地;导入过程不联网。
- [ ] **Step 4:** 补充维度到方向的映射资料,标注来源与适用范围,由人审阅。
- [ ] **Step 5:** 更新 `SKILL.md` 状态为启用,替换主循环中的"暂未启用"分支。

### Task 20: 上线前内容与合规审阅(非代码)

- [ ] 危机话术、热线号码、风险规则与语料集由具备资质的人审阅并签字
- [ ] 知识库与 CBT 模板内容审阅,来源可查
- [ ] PSS-10 授权确认后填充题目文本
- [ ] 同意书文本由法务审阅
- [ ] 未成年人策略与应用分发渠道的合规要求确认

## Agent 验收清单

- [ ] `pytest -q` 全部通过,安全语料回归 HIGH 漏判为 0
- [ ] 本地数据文件无明文(标记串检查)
- [ ] 危机话术在断网、余额为零、令牌过期时仍可输出
- [ ] 量表分数与等级在任何情况下以工具结果为准
- [ ] 技能 3 在未启用时只返回说明,不产生建议

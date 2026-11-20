# 心理健康 Agent 开发总览与接口约定

> 本文档只规划,不进入开发。设计依据:`docs/superpowers/specs/2026-11-06-mental-health-agent-design.md`
> 实施时使用 superpowers:subagent-driven-development(有子 agent 时)或 superpowers:executing-plans。

## 1. 计划拆分

| 文件 | 内容 | 可独立产出 |
|---|---|---|
| `01-backend-plan.md` | Go (go-zero) 后端:用户、积分账本、模型网关、紧急通知、同意书、审计 | 是,可用 mock 上游单独联调 |
| `02-agent-plan.md` | Python Agent:量表、压力指数、日记、安全层、技能、本地加密存储、对话循环 | 是,可用 mock LLM 单独运行 |

两份计划通过本文档第 3 节的接口契约解耦。后端与 Agent 可并行开发。管理后台页面(`admin-web/`)属于后端计划的一部分(Task 14B)。

## 2. 里程碑与顺序

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| M0 | 确认待定项(第 5 节)、搭建两个仓库骨架与 CI | `go test ./...` 与 `pytest` 在空项目上通过 |
| M1 | Agent 纯逻辑:量表计分、压力指数、安全规则 | 单元测试全绿;安全语料回归集通过 |
| M2 | 后端积分核心:定价、账本、冻结/结算/释放 | 账本并发与幂等测试通过(真实 PostgreSQL) |
| M3 | 后端用户与网关:登录、`/llm/chat` 非流式 + mock 上游 | 用 curl 走通:登录(得 100 积分)→ 对话 → 扣费 |
| M4 | Agent 本地存储与工具:加密库、日记、练习数据、技能文件 | 数据落盘为密文;日记/回顾测试通过 |
| M5 | Agent 主循环 + 网关客户端 | 用 mock 网关完成端到端对话,含风险兜底与余额不足降级 |
| M6 | 流式、紧急通知、同意书、审计 | 隐私检查通过:后端日志与库中无正文/联系人 |
| M6A | 套餐与订单(Task 14A)、管理后台页面(Task 14B) | 浏览器冒烟:建套餐 → 下单 → 后台确认收款 → 积分到账 |
| M7 | 真实上游(DeepSeek)适配;阿里云短信/邮件只接 SDK 与配置 | DeepSeek 预发冒烟,usage 与扣费核对一致;阿里云 `go build`/`go vet` 通过(不测) |
| M8 | P1 项:真实支付渠道、余额提醒、内容库、量表版本、监控 | 按各自验收 |

关键路径:M1 与 M2 可并行;M5 依赖 M3、M4。

## 3. 接口契约(后端 ⇄ Agent)

通用:`Content-Type: application/json`;除发验证码/登录外都带 `Authorization: Bearer <access_token>`;错误统一为
`{"code": <int>, "message": "<string>"}`,HTTP 状态码见下表。

| code | HTTP | 含义 |
|---|---|---|
| 40001 | 400 | 参数错误 |
| 40101 | 401 | 未登录或令牌无效/过期 |
| 40102 | 401 | 验证码错误或已失效(不区分原因) |
| 40201 | 402 | 积分不足 |
| 40301 | 403 | 未签署最新同意书(紧急通知等需同意的接口) |
| 40901 | 409 | 重复的 `X-Request-Id`(已结算),响应体附带首次的 `cost` |
| 42901 | 429 | 触发限流 |
| 50201 | 502 | 上游模型平台错误或超时 |

### 3.1 认证
- `POST /auth/sms/send` `{phone}` → 204。限频:同号 60 秒 1 次、每天 5 次(超限 429)。
- `POST /auth/login` `{phone, code}` → `{access_token, refresh_token, expires_in, is_new}`。手机号即账号,首次登录自动注册并赠送 100 积分(配置项),无密码。
- `POST /auth/refresh` `{refresh_token}` → 同上(无 `is_new`)。
- `DELETE /account`:注销账号,删除账户行;账本流水保留但去标识(`user_id` 置 0)。同一手机号注销后 30 天内再登录不重复赠送。
- 手机号格式:中国大陆 11 位,服务端规范化为 `+86...`;库中只存 HMAC 哈希与脱敏串。

### 3.2 积分
- `GET /credits/balance` → `{balance, held, available}`(均为整数积分)。
- `GET /credits/ledger?cursor=&limit=` → `{items:[{type, amount, created_at}], next_cursor}`。

### 3.3 模型网关
`POST /llm/chat`,请求头必须带 `X-Request-Id`(Agent 生成 UUID,同一次请求重试使用同一 ID)。
```json
{
  "model": "deepseek-flash",
  "messages": [{"role": "system|user|assistant", "content": "string"}],
  "max_tokens": 1024,
  "stream": false
}
```
- `model` 必须是管理端已启用的模型(目前 `deepseek-flash`、`deepseek-v4-pro`);`max_tokens` 超过该模型上限时被截断。
- 是否开启思考模式由后端的模型配置决定,客户端不能传;后端会显式向上游传 `thinking`,并且不会把 `reasoning_content` 转发给客户端。

非流式响应:
```json
{
  "content": "string",
  "usage": {"input_hit": 0, "input_miss": 0, "output": 0},
  "cost": 0,
  "balance": 0,
  "low_balance": false
}
```
`input_hit/input_miss` 对应 DeepSeek 的缓存命中/未命中输入 token,两档价格不同。
流式(`stream: true`):`text/event-stream`,事件为
- `event: delta` `data: {"text": "..."}`
- `event: done` `data: {"usage": {...}, "cost": 0, "balance": 0}`
- `event: error` `data: {"code": 50201, "message": "..."}`

幂等:同一 `X-Request-Id` 重复提交,若已结算则返回 409 并带上次的 `cost`,不重复扣费。

### 3.4 紧急通知
`POST /notify/emergency`
```json
{"channel": "sms|email", "to": "string", "template_id": "crisis_contact_v1", "params": {"nickname": "string"}}
```
→ `{"status": "sent|failed", "notify_id": "string"}`。
后端要求:校验该用户已签署最新同意书;发送后不保存 `to` 与 `params`,只记 `channel`、`template_id`、`status`、时间。

- `sms` 通道的 `to` 为大陆手机号,`email` 通道的 `to` 为邮箱;均走阿里云。
- 同一用户 1 小时内最多 3 次,同一接收方每天最多 3 次。

### 3.5 同意书
- `GET /consent/latest` → `{version, text, url}`
- `POST /consent` `{version}` → 204;记录签署版本与时间。

### 3.6 套餐与订单
积分不与人民币挂钩:套餐的"售价"只用于展示与记录,"赠送积分"是独立配置,系统内没有元到积分的换算。
- `GET /packages` → `{items:[{id, name, description, price_cents, credits}]}`(仅已上架)
- `POST /orders` `{package_id}` → `{order_id, status, pay_params}`
- `GET /orders` → 自己的订单(含下单时的套餐快照)
- `POST /pay/callback/{channel}`:支付渠道回调(验签、幂等)
- 支付成功后一次性入账套餐积分,订单状态 `pending → paid → credited`。MVP 的渠道为 `mock` 与 `manual`(线下收款,管理员后台确认);真实渠道待定。

### 3.7 管理端(不对 Agent 开放)
`/admin/*`,独立的管理员账号与令牌(角色 `super`/`ops`):登录、模型定价的查询与修改(必填原因、留历史、立即生效)、套餐增改与上下架、订单查询与确认收款/取消、积分发放(幂等、有单笔上限)、用户查询(仅脱敏手机号)、用量汇总、通知记录。详见 `01-backend-plan.md` Task 14、14A。
管理后台前端为独立的 React + Ant Design 页面(`admin-web/`,Task 14B)。

## 4. 横切约定

- 积分用整数,单位"积分";单价单位"积分 / 百万 token"(整数运算,避免浮点)。
- 时间一律 UTC,ISO 8601。
- Agent 与后端的日志中禁止出现:消息正文、日记内容、联系人信息、口令、令牌。
- 提交粒度:每个 Task 的最后一步提交一次;提交信息用 `feat:`/`test:`/`chore:` 前缀。
- 所有新增逻辑先写失败测试(TDD)。

## 5. 开发前必须确认的待定项

**已确认**
| 事项 | 决定 |
|---|---|
| 上游模型接口 | 参考 DeepSeek(OpenAI 兼容 `/chat/completions`),模型 `deepseek-flash`、`deepseek-v4-pro` |
| 注册/登录 | 手机号 + 短信验证码,首次登录自动注册 |
| 短信/邮件 | 阿里云;只接入 SDK 并留配置文件,本阶段不为其写测试,开发与测试用 mock |
| 初始赠送 | 100 积分 |
| 积分与金额 | 不挂钩;通过购买套餐赠送积分,套餐的售价与积分数在管理端独立配置 |
| 定价 | 每个模型的价格(积分/百万 token)由管理端调整,留历史 |
| 管理后台 | 需要页面(React + Ant Design),MVP 必做 |
| 对话内容发送给 DeepSeek | 可以;同意书与隐私政策需明示 |
| PSS-10 授权 / 危机话术审阅 / 未成年人策略 | 本阶段先不考虑(见下方"暂缓项") |

**仍需确认**
| # | 事项 | 影响 | 默认假设 |
|---|---|---|---|
| 1 | 真实支付渠道(微信/支付宝等) | 套餐购买的线上支付 | MVP 先用 `manual`(线下收款,后台确认)与 `mock`;渠道定后做 P1 Task 20 |
| 2 | 套餐具体档位(名称、售价、赠送积分)与各模型初始单价 | 运营配置 | 上线前由运营在后台配置;模型与套餐默认下架,未配置则无法使用 |
| 3 | 阿里云短信签名与模板审核、邮件发信域名 | 上线时登录与紧急通知 | 审核耗时较长,建议提前提交;开发期用 mock |
| 4 | DeepSeek 默认是否开启思考模式 | 成本与延迟 | 默认关闭(`thinking: disabled`),可按模型调整 |
| 5 | Agent 的"用户界面" | `main.py` | MVP 为命令行;面向用户的 H5/前端不在本计划内 |
| 6 | 套餐赠送积分对应的上游成本 | 避免亏损 | 积分不挂钩人民币,运营需自行核算"赠送积分 × 模型单价"与 DeepSeek 实际成本;后台用量汇总页可辅助 |

**暂缓项(本阶段不考虑,上线前必须回头处理)**
- PSS-10 题目文本商用授权:题库留空,PHQ-9、GAD-7 先行。
- 危机话术、热线与风险语料的专业审阅:先用公开热线占位。心理类产品的安全话术未经审阅不应对外发布。
- 未成年人使用策略:同意书中先声明年龄要求。

## 6. 完成定义(MVP)

1. 用户可用手机号验证码登录,首次获赠 100 积分,每次对话按真实 token 扣费且幂等;用户可购买套餐获得赠送积分(MVP 为线下收款 + 后台确认);管理员可在后台页面调整模型价格、管理套餐与订单并立即生效。
2. Agent 能完成:知识推送、日记记录与周回顾、四种练习引导、CBT 模板引导、PHQ-9/GAD-7/PSS-10 评估(PSS-10 视授权)与压力指数。
3. 高风险语料集 100% 命中;危机流程不依赖网关,余额为零也能输出。
4. 已授权时可发出紧急通知,未授权时仅引导;任何情况下后端不保存正文与联系人。
5. 本地数据文件为密文;导出/导入可用。
6. 技能 3 仅有框架与 `ReportProvider` 接口,不含业务逻辑。

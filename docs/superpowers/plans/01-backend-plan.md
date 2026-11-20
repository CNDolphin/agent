# 后端(Go / go-zero)开发计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供手机号登录、积分账本、DeepSeek 模型网关计费、套餐与订单(购买套餐赠送积分)、管理后台(API + 页面)、紧急通知(阿里云短信/邮件)、同意书与审计,不存任何用户隐私正文。

**Architecture:** go-zero REST 服务。积分一致性全部由 PostgreSQL 事务 + 行锁保证,Redis 只做限流与短信验证码。上游模型平台通过 `Upstream` 接口隔离(先 mock,再接 DeepSeek);短信/邮件通过 `Sender`/`Notifier` 接口隔离,阿里云 SDK 只接入并留配置,开发期用 mock;支付通过 `PaymentProvider` 接口隔离。管理后台是独立的 React 前端,调用 `/admin/*`。

**Tech Stack:** Go 1.22+、go-zero、goctl、PostgreSQL 15、Redis 7、golang-migrate、bcrypt(管理员密码)、JWT、testify、miniredis、阿里云 SDK(短信 `dysmsapi`、邮件推送 `dm`)、docker compose(测试库);管理后台:React + TypeScript + Ant Design 6、Vite、Vitest、Testing Library、msw。

契约见 `00-overview-and-contracts.md` 第 3 节。

---

## 已确认的决定

| 项 | 决定 |
|---|---|
| 上游模型平台 | 接口参考 DeepSeek(OpenAI 兼容 `/chat/completions`),模型名 `deepseek-flash`、`deepseek-v4-pro` |
| 注册/登录 | 手机号 + 短信验证码,首次登录自动注册,不设密码 |
| 短信与邮件 | 阿里云(短信服务 + 邮件推送)。**只接入 SDK 并留配置文件,本阶段不为阿里云调用写测试**,开发与测试一律走 mock |
| 初始赠送 | 新用户 100 积分(配置项 `Credits.SignupGrant`) |
| 积分与金额 | **积分不与人民币挂钩**,没有"元→积分"换算。积分只通过两种方式获得:注册赠送、购买套餐时随套餐赠送(以及运营手动发放) |
| 定价 | 每个模型的价格(积分/百万 token)可在管理端调整,即时审计,历史可查 |
| 套餐 | 管理端配置:名称、售价(仅记录与展示)、赠送积分数、是否上架。购买成功后一次性入账 |
| 管理后台 | 需要页面(React + Ant Design),属于 MVP |

## 文件结构

```
backend/
├── agent.api                       # goctl 的 API 定义
├── mhagent.go                      # 入口(goctl 生成)
├── docker-compose.yml              # postgres + redis,仅测试/开发
├── etc/mhagent.yaml                # 配置(密钥只从环境变量读)
├── migrations/                     # *.up.sql / *.down.sql
├── cmd/adminctl/                   # 创建管理员账号的命令行工具
└── internal/
    ├── config/config.go
    ├── svc/servicecontext.go
    ├── handler/ logic/             # goctl 生成,logic 只做编排
    ├── middleware/                 # auth、adminauth、request_id、ratelimit
    ├── credits/
    │   ├── pricing.go              # Cost / EstimateHold 纯函数
    │   ├── ledger.go               # Ledger 接口与 PG 实现
    │   └── priceprovider.go        # 读取 model_prices,带缓存
    ├── upstream/{upstream,mock,deepseek}.go
    ├── sms/{sender,aliyun,mock}.go # 验证码短信发送
    ├── smscode/service.go          # 验证码生成/校验/限频(Redis)
    ├── notify/{notifier,aliyun,mock}.go   # 紧急通知(短信/邮件)
    ├── auth/{token,phone}.go       # JWT、手机号规范化与哈希
    ├── packages/service.go         # 套餐与订单
    ├── payment/{provider,mock}.go  # PaymentProvider 接口(真实渠道待定)
    ├── audit/audit.go
    └── model/                      # 数据访问
admin-web/                          # 管理后台前端(Task 14B)
├── package.json  vite.config.ts  tsconfig.json
└── src/{main.tsx, api/, pages/, components/, auth/}
```

## Chunk 1: 骨架、数据库与定价

### Task 1: 项目骨架与健康检查

**Files:**
- Create: `backend/` 全部骨架、`backend/docker-compose.yml`、`backend/etc/mhagent.yaml`
- Create: `backend/internal/handler/health_test.go`

- [ ] **Step 1: 初始化模块与依赖**

```bash
mkdir -p backend && cd backend
go mod init mhagent
go install github.com/zeromicro/go-zero/tools/goctl@latest
```

- [ ] **Step 2: 写 API 定义(只含 health)并生成**

`agent.api`:
```
syntax = "v1"
type HealthResp { Status string `json:"status"` }
service mhagent {
    @handler Health
    get /health returns (HealthResp)
}
```
```bash
goctl api go -api agent.api -dir . --style go_zero
go mod tidy
```

- [ ] **Step 3: 写失败测试** — `health_test.go` 用 `httptest` 请求 `/health`,断言 200 且 body 含 `"status":"ok"`。

- [ ] **Step 4: 运行确认失败**

Run: `go test ./internal/handler/... -run TestHealth -v`
Expected: FAIL

- [ ] **Step 5: 在 `healthlogic.go` 返回 `Status: "ok"`,再运行**

Run: `go test ./internal/handler/... -run TestHealth -v`
Expected: PASS

- [ ] **Step 6: 写 `docker-compose.yml`(postgres:15、redis:7,端口 54329/63799,仅本地)并启动**

Run: `docker compose up -d && docker compose ps`
Expected: 两个服务 `running`

- [ ] **Step 7: 提交**

```bash
git add backend && git commit -m "chore(backend): scaffold go-zero project with health check"
```

### Task 2: 数据库迁移

**Files:**
- Create: `backend/migrations/0001_init.up.sql`、`0001_init.down.sql`
- Create: `backend/internal/model/migrate_test.go`

- [ ] **Step 1: 写迁移 SQL**

```sql
-- 手机号只存 HMAC 哈希(登录查找用)和脱敏展示串,不存明文
CREATE TABLE users (
  id          BIGSERIAL PRIMARY KEY,
  phone_hash  TEXT NOT NULL UNIQUE,
  phone_mask  TEXT NOT NULL,                 -- 138****1234
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at  TIMESTAMPTZ
);

CREATE TABLE credit_accounts (
  user_id    BIGINT PRIMARY KEY REFERENCES users(id),
  balance    BIGINT NOT NULL DEFAULT 0 CHECK (balance >= 0),
  held       BIGINT NOT NULL DEFAULT 0 CHECK (held >= 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (held <= balance)
);

CREATE TABLE credit_ledger (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT NOT NULL,             -- 注销后置为 0
  type          TEXT NOT NULL CHECK (type IN ('grant','recharge','hold','release','consume','refund')),
  amount        BIGINT NOT NULL CHECK (amount > 0),
  request_id    TEXT NOT NULL,
  ref           TEXT,
  balance_after BIGINT NOT NULL,
  held_after    BIGINT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, request_id, type)
);
CREATE INDEX idx_ledger_user_time ON credit_ledger(user_id, id DESC);

-- 价格单位:积分 / 百万 token(整数)。DeepSeek 输入分缓存命中/未命中两档
CREATE TABLE model_prices (
  model           TEXT PRIMARY KEY,
  in_hit_per_m    BIGINT NOT NULL CHECK (in_hit_per_m  >= 0),
  in_miss_per_m   BIGINT NOT NULL CHECK (in_miss_per_m >= 0),
  out_per_m       BIGINT NOT NULL CHECK (out_per_m     >= 0),
  thinking        TEXT   NOT NULL DEFAULT 'disabled' CHECK (thinking IN ('enabled','disabled')),
  max_tokens_cap  INT    NOT NULL DEFAULT 2048,
  enabled         BOOLEAN NOT NULL DEFAULT true,
  version         INT    NOT NULL DEFAULT 1,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE model_price_history (
  id           BIGSERIAL PRIMARY KEY,
  model        TEXT NOT NULL,
  version      INT  NOT NULL,
  in_hit_per_m BIGINT NOT NULL, in_miss_per_m BIGINT NOT NULL, out_per_m BIGINT NOT NULL,
  enabled      BOOLEAN NOT NULL,
  admin_id     BIGINT NOT NULL,
  reason       TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 只记 token 数,不记正文
CREATE TABLE usage_logs (
  id           BIGSERIAL PRIMARY KEY,
  user_id      BIGINT NOT NULL,
  request_id   TEXT NOT NULL,
  model        TEXT NOT NULL,
  in_hit       BIGINT NOT NULL,
  in_miss      BIGINT NOT NULL,
  out_tokens   BIGINT NOT NULL,
  cost         BIGINT NOT NULL,
  partial      BOOLEAN NOT NULL DEFAULT false,
  latency_ms   INT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, request_id)
);

CREATE TABLE consents (
  id         BIGSERIAL PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id),
  version    TEXT NOT NULL,
  signed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, version)
);

-- 套餐:price_cents 仅记录与展示,与积分数量没有换算关系
CREATE TABLE packages (
  id          BIGSERIAL PRIMARY KEY,
  name        TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  price_cents BIGINT NOT NULL CHECK (price_cents >= 0),
  credits     BIGINT NOT NULL CHECK (credits > 0),
  enabled     BOOLEAN NOT NULL DEFAULT false,
  sort_order  INT NOT NULL DEFAULT 0,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 订单保存下单时的套餐快照,之后改套餐不影响已有订单
CREATE TABLE orders (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT NOT NULL,
  package_id    BIGINT NOT NULL REFERENCES packages(id),
  package_name  TEXT   NOT NULL,
  price_cents   BIGINT NOT NULL,
  credits       BIGINT NOT NULL,
  status        TEXT   NOT NULL CHECK (status IN ('pending','paid','credited','cancelled')),
  channel       TEXT   NOT NULL,                 -- mock | manual | (真实渠道待定)
  trade_no      TEXT,                            -- 渠道流水号
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  paid_at       TIMESTAMPTZ,
  UNIQUE (channel, trade_no)
);
CREATE INDEX idx_orders_user ON orders(user_id, id DESC);

CREATE TABLE notify_logs (
  id          BIGSERIAL PRIMARY KEY,
  user_id     BIGINT NOT NULL,
  channel     TEXT NOT NULL,
  template_id TEXT NOT NULL,
  status      TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE admin_users (
  id            BIGSERIAL PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL CHECK (role IN ('super','ops')),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_logs (
  id         BIGSERIAL PRIMARY KEY,
  actor_type TEXT NOT NULL CHECK (actor_type IN ('user','admin','system')),
  actor_id   BIGINT,
  event      TEXT NOT NULL,                 -- 枚举常量,见 Task 17
  detail     JSONB NOT NULL DEFAULT '{}',   -- 仅数值/枚举
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```
`down.sql` 按反向顺序 `DROP TABLE`。

- [ ] **Step 2: 写迁移测试** — 连接 `TEST_DATABASE_URL`,执行 up,断言 12 张表存在(`users`、`credit_accounts`、`credit_ledger`、`model_prices`、`model_price_history`、`usage_logs`、`consents`、`packages`、`orders`、`notify_logs`、`admin_users`、`audit_logs`);执行 down 再 up 无错;`packages.credits <= 0`、`price_cents < 0` 的插入被约束拒绝。

- [ ] **Step 3: 运行并确认通过**

Run: `TEST_DATABASE_URL='postgres://postgres:postgres@localhost:54329/postgres?sslmode=disable' go test ./internal/model/... -run TestMigrate -v`
Expected: PASS

- [ ] **Step 4: 提交** `git commit -m "feat(backend): add initial schema migration"`

### Task 3: 定价纯函数(TDD)

**Files:**
- Create: `backend/internal/credits/pricing.go`
- Test: `backend/internal/credits/pricing_test.go`

公式:`cost = ceil((hit×InHitPerM + miss×InMissPerM + out×OutPerM) / 1,000,000)`,全整数。

- [ ] **Step 1: 写失败测试**

```go
package credits

import "testing"

func TestCost(t *testing.T) {
	p := Price{InHitPerM: 200, InMissPerM: 2000, OutPerM: 8000}
	cases := []struct {
		name            string
		hit, miss, out  int64
		want            int64
	}{
		{"zero tokens", 0, 0, 0, 0},
		{"one miss token rounds up", 0, 1, 0, 1},
		{"exact million miss", 0, 1_000_000, 0, 2000},
		{"exact million hit", 1_000_000, 0, 0, 200},
		{"exact total", 0, 1000, 500, 6},        // 2,000,000 + 4,000,000 = 6,000,000
		{"mixed rounds up", 1000, 1000, 500, 7}, // 6,200,000 -> 7
	}
	for _, c := range cases {
		if got := Cost(p, c.hit, c.miss, c.out); got != c.want {
			t.Errorf("%s: got %d want %d", c.name, got, c.want)
		}
	}
}

func TestEstimateHoldUsesHigherInputPrice(t *testing.T) {
	p := Price{InHitPerM: 200, InMissPerM: 2000, OutPerM: 8000}
	// 输入字符数当作 token,按命中/未命中中较高价;输出按 max_tokens
	if got := EstimateHold(p, 1000, 500); got != 6 {
		t.Errorf("got %d want 6", got)
	}
	p2 := Price{InHitPerM: 3000, InMissPerM: 2000, OutPerM: 8000}
	if got := EstimateHold(p2, 1000, 500); got != 7 { // 3,000,000+4,000,000
		t.Errorf("got %d want 7", got)
	}
}
```

- [ ] **Step 2: 运行确认失败**

Run: `go test ./internal/credits/ -run 'TestCost|TestEstimateHold' -v`
Expected: FAIL(`undefined: Price`)

- [ ] **Step 3: 最小实现**

```go
package credits

// Price 单位:积分 / 百万 token,整数。
type Price struct {
	InHitPerM  int64
	InMissPerM int64
	OutPerM    int64
}

const million = 1_000_000

// Cost 向上取整。
func Cost(p Price, hit, miss, out int64) int64 {
	n := hit*p.InHitPerM + miss*p.InMissPerM + out*p.OutPerM
	return (n + million - 1) / million
}

// EstimateHold 保守估算,用于冻结。
func EstimateHold(p Price, inputChars, maxTokens int64) int64 {
	in := p.InMissPerM
	if p.InHitPerM > in {
		in = p.InHitPerM
	}
	return (inputChars*in + maxTokens*p.OutPerM + million - 1) / million
}
```

- [ ] **Step 4: 运行确认通过** — 同 Step 2 命令,Expected: PASS
- [ ] **Step 5: 提交** `git commit -m "feat(backend): add integer pricing functions"`

## Chunk 2: 积分账本与价格读取

### Task 4: Ledger 接口与 PostgreSQL 实现(TDD)

**Files:**
- Create: `backend/internal/credits/ledger.go`
- Test: `backend/internal/credits/ledger_test.go`

```go
var ErrInsufficient = errors.New("insufficient credits")
var ErrNoHold = errors.New("hold not found")

type Balance struct{ Balance, Held int64 }
func (b Balance) Available() int64 { return b.Balance - b.Held }

type Ledger interface {
	// kind: "grant" | "recharge" | "refund"。同 (user, requestID, kind) 重复调用不重复入账。
	Credit(ctx context.Context, userID, amount int64, kind, requestID string) error
	Hold(ctx context.Context, userID, amount int64, requestID string) error
	// Settle 将 hold 转为 consume(actual,封顶为 hold 额),差额写 release。重复调用返回首次结果。
	Settle(ctx context.Context, userID int64, requestID string, actual int64) (consumed int64, err error)
	// Release 全额释放(上游失败时)。已 settle 的请求不可再 release。
	Release(ctx context.Context, userID int64, requestID string) error
	Balance(ctx context.Context, userID int64) (Balance, error)
}
```

- [ ] **Step 1: 写失败测试**(真实 PostgreSQL,每个测试前清表),覆盖:
  1. `TestCreditIncreasesBalance`:Credit 100 后 Balance=100。
  2. `TestCreditIdempotent`:相同 requestID 调用两次,余额仍为 100,账本 1 行。
  3. `TestHoldReducesAvailable`:Hold 30 → Balance 100、Held 30、Available 70。
  4. `TestHoldInsufficient`:Available 不足返回 `ErrInsufficient`,余额与 held 不变。
  5. `TestHoldIdempotent`:同 requestID 再次 Hold,held 仍为 30。
  6. `TestSettleConsumesActualAndReleasesRest`:Hold 30,Settle actual=12 → Balance 88、Held 0,账本含 consume=12、release=18。
  7. `TestSettleCapsAtHold`:Hold 30,Settle actual=50 → consumed=30,`ref` 记 `capped`。
  8. `TestSettleIdempotent`:连续两次 Settle,第二次返回相同 consumed,余额不再变化。
  9. `TestReleaseRestoresAvailable`:Hold 30 后 Release → Held 0、Balance 不变。
  10. `TestReleaseAfterSettleIsNoop`
  11. `TestSettleWithoutHold`:返回 `ErrNoHold`。
  12. `TestConcurrentHoldsNeverOverdraw`:余额 100,50 个 goroutine 各 Hold 10(不同 requestID),成功数恰好 10,最终 Held=100。
  13. `TestZeroActualSettle`:actual=0 时只写 release,不写 consume(`amount > 0` 约束)。

- [ ] **Step 2: 运行确认失败**

Run: `TEST_DATABASE_URL=... go test ./internal/credits/ -run 'Test(Credit|Hold|Settle|Release|Concurrent|Zero)' -v`
Expected: FAIL(`undefined: NewPGLedger`)

- [ ] **Step 3: 实现 `PGLedger`**,要点:
  - 每个方法一个事务:`SELECT ... FROM credit_accounts WHERE user_id=$1 FOR UPDATE`,账户行不存在则先 `INSERT ... ON CONFLICT DO NOTHING` 再锁。
  - 幂等:先查 `credit_ledger` 是否已有 `(user_id, request_id, type)`,有则返回既有结果;`UNIQUE` 约束兜底(冲突则回滚重读)。
  - `Hold`:`balance - held >= amount` 才写;`held += amount`。
  - `Settle`:读 `hold` 行得 `H`;`consumed = min(actual, H)`;`balance -= consumed`;`held -= H`;consumed>0 写 `consume`;`H-consumed>0` 写 `release`。
  - `Release`:已有 `consume` 或 `release` 行则 no-op;否则 `held -= H` 并写 `release`。
  - 每行记录 `balance_after`、`held_after`。

- [ ] **Step 4: 运行确认通过;再带 `-race` 跑并发用例**

Run: `go test ./internal/credits/ -race -count=3 -v`
Expected: PASS

- [ ] **Step 5: 提交** `git commit -m "feat(backend): add transactional credit ledger"`

### Task 5: 价格读取(带缓存)

**Files:** Create `backend/internal/credits/priceprovider.go`;Test `priceprovider_test.go`

```go
type ModelConfig struct {
	Model        string
	Price        Price
	Thinking     string // enabled|disabled
	MaxTokensCap int
}
type PriceProvider interface {
	Get(ctx context.Context, model string) (ModelConfig, error) // 未知或 disabled 返回 ErrUnknownModel
	Invalidate()                                                // 管理端修改后立即清缓存(本进程)
}
```

- [ ] **Step 1: 写失败测试**:返回表中价格;未知或 `enabled=false` → `ErrUnknownModel`;直接改表后,在 TTL(测试注入 50ms)之后读到新值;`Invalidate()` 后立即读到新值。
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**(内存缓存 + TTL 默认 30 秒;多实例依靠 TTL 收敛)
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `git commit -m "feat(backend): add price provider with cache"`

## Chunk 3: 手机号登录

### Task 6: 手机号处理与令牌

**Files:** Create `internal/auth/phone.go`、`token.go`;Test `phone_test.go`、`token_test.go`

- [ ] **Step 1: 写失败测试**:
  - `NormalizePhone`:接受 `13812345678`、`+8613812345678`、`138 1234 5678`,统一为 `+8613812345678`;拒绝非 `1[3-9]\d{9}`、空串、字母;MVP 仅支持中国大陆号码。
  - `HashPhone(pepper, phone)`:同输入同输出,不同 pepper 不同输出,输出不含明文;pepper 为空时返回错误。
  - `MaskPhone` → `138****5678`。
  - `IssueTokens(userID)` 得 access(15 分钟)和 refresh(30 天);`ParseAccess` 往返得 userID;篡改签名失败;过期失败(注入时钟);refresh 不能当 access 用,反之亦然。
- [ ] **Step 2: 运行确认失败** `go test ./internal/auth/... -v`
- [ ] **Step 3: 实现**(HMAC-SHA256;HS256 JWT,`typ` 声明区分 access/refresh;密钥与 pepper 来自环境变量)
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `git commit -m "feat(backend): add phone normalization and jwt tokens"`

### Task 7: 短信发送(阿里云)与验证码服务

**Files:** Create `internal/sms/sender.go`、`mock.go`、`aliyun.go`;`internal/smscode/service.go`;测试 `smscode/service_test.go`、`sms/aliyun_test.go`

```go
type Sender interface {
	// templateCode 为阿里云已审核通过的模板;params 序列化为 TemplateParam
	Send(ctx context.Context, phone, templateCode string, params map[string]string) error
}
```

验证码规则:6 位数字;有效期 5 分钟;Redis 只存 `HMAC(code)`,不存明文;校验成功立即删除;同一验证码最多错误 5 次后作废;发送限频——同一手机号 60 秒 1 次、每天 5 次;同一 IP 每天 20 次。阿里云对同一号码同一签名/模板默认有 1 条/分钟、5 条/小时、10 条/天的限制,服务端限频必须不高于该值。

- [ ] **Step 1: 写失败测试**(miniredis + mock Sender):
  1. 发送 → 校验成功;校验成功后同一验证码再次校验失败。
  2. 错误验证码计数,第 5 次错误后正确验证码也失败(作废)。
  3. 超过 5 分钟失效(注入时钟)。
  4. 60 秒内再次发送 → `ErrTooFrequent`;每日第 6 次 → `ErrDailyLimit`;IP 限频。
  5. Redis 中不存在明文验证码;日志输出不含手机号与验证码(捕获日志断言)。
  6. 发送失败(Sender 报错)时不计入成功次数,且已写入的验证码被删除。
  7. 开发模式(`Env=dev`)下 mock Sender 把验证码放入内存,供测试读取;`Env=prod` 时配置选择 mock 则启动失败。
- [ ] **Step 2: 运行确认失败(验证码服务与 mock,不含阿里云)**
- [ ] **Step 3: 实现验证码服务与 mock Sender**
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 接入阿里云短信 SDK(`sms/aliyun.go`),本阶段不写测试、不做联网调用**
  - 实现 `Sender` 接口;凭证只读环境变量 `ALIBABA_CLOUD_ACCESS_KEY_ID` / `ALIBABA_CLOUD_ACCESS_KEY_SECRET`;
  - 配置项写入 `etc/mhagent.yaml`:`Sms.Provider`(`mock|aliyun`)、`Sms.Aliyun.Endpoint`、`Sms.Aliyun.SignName`、`Sms.Aliyun.Templates.Login`、`Sms.Aliyun.Templates.Emergency`(模板代码);
  - 阿里云返回 `Code != "OK"` 时返回错误并保留 `Code` 供日志排查(日志不含手机号);
  - 实现前对照阿里云官方文档核对 SDK 包名与字段;只要求 `go build ./...` 与 `go vet ./...` 通过。
- [ ] **Step 6: 提交** `git commit -m "feat(backend): add sms verification code service and aliyun sender (untested, config-driven)"`

### Task 8: 发码/登录/刷新/注销接口

**Files:** 修改 `agent.api`;生成 handler/logic;Test `internal/logic/auth_test.go`

接口:`POST /auth/sms/send {phone}`、`POST /auth/login {phone, code}`(首次自动注册,响应含 `is_new`)、`POST /auth/refresh`、`DELETE /account`。

- [ ] **Step 1: 在 `agent.api` 增加路由**并重新 `goctl api go`。
- [ ] **Step 2: 写失败测试**(真实 PG + 真 Ledger + mock Sender):
  1. 新手机号登录:创建用户(只存 `phone_hash`、`phone_mask`)、创建账户、入账 `grant` 100(requestID=`signup:<userID>`),返回令牌与 `is_new=true`。
  2. 老用户再次登录:不再赠送,`is_new=false`。
  3. 并发:同一新手机号同时登录两次 → 只创建一个用户、只赠送一次。
  4. 验证码错误 → 40102;格式非法手机号 → 40001。
  5. 登录错误不泄露"该手机号是否已注册"。
  6. refresh 成功/失败;已注销用户 refresh 失败。
  7. 注销:`users.deleted_at` 置位,`credit_ledger.user_id` 置 0,账户行删除;旧令牌访问返回 40101;同一手机号再次登录视为新用户并**重新赠送**——为防刷赠送,注销后同一 `phone_hash` 在 30 天内再登录不重复赠送(`users` 保留 `phone_hash` 并标记 `deleted_at`,配置项 `Credits.ReSignupCooldownDays`)。
- [ ] **Step 3: 运行确认失败**
- [ ] **Step 4: 实现 logic**;注册、账户创建、赠送在同一事务。
- [ ] **Step 5: 运行确认通过**
- [ ] **Step 6: 提交** `git commit -m "feat(backend): add sms login, refresh and account deletion"`

### Task 9: 中间件

**Files:** Create `internal/middleware/auth.go`、`requestid.go`、`ratelimit.go` 与测试

- [ ] **Step 1: 写失败测试**:
  - auth:无头 / 非法 / 过期令牌 → 401 `40101`;合法令牌把 userID 注入 context。
  - requestid:`/llm/chat` 缺 `X-Request-Id` → 400 `40001`;格式要求 UUID。
  - ratelimit:同一用户每分钟超过配置阈值 → 429 `42901`(Redis 固定窗口,miniredis)。
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现并挂载到路由**
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `git commit -m "feat(backend): add auth, request-id and rate-limit middleware"`

## Chunk 4: 模型网关

### Task 10: Upstream 接口与 mock

**Files:** Create `internal/upstream/upstream.go`、`mock.go`、`mock_test.go`

```go
type Message struct{ Role, Content string }

type ChatRequest struct {
	Model     string
	Messages  []Message
	MaxTokens int
	Thinking  string // enabled|disabled,由模型配置决定
	UserTag   string // 用户伪名(HMAC),用于上游缓存/调度隔离,不是手机号或用户 ID 明文
}

type Usage struct {
	InputHit, InputMiss, Output int64
}

// 上游错误分类,供网关映射
var (
	ErrUpstreamAuth      = errors.New("upstream auth failed")      // 401:我方密钥问题,告警
	ErrUpstreamBalance   = errors.New("upstream out of balance")   // 402:我方上游账户欠费,告警,对用户表现为 502
	ErrUpstreamRateLimit = errors.New("upstream rate limited")     // 429
	ErrUpstreamBusy      = errors.New("upstream unavailable")      // 500/503/超时
	ErrUpstreamBadReq    = errors.New("upstream rejected request") // 400/422
)

type Upstream interface {
	Chat(ctx context.Context, req ChatRequest) (content string, usage Usage, err error)
	// ChatStream 每个增量调用 onDelta;返回已产生的 usage(出错时也返回已知部分)。
	ChatStream(ctx context.Context, req ChatRequest, onDelta func(string) error) (Usage, error)
}
```

- [ ] **Step 1: 写失败测试**:mock 可配置内容、usage、延迟、错误;`ChatStream` 按配置分片回调;ctx 取消返回 `ctx.Err()`。
- [ ] **Step 2: 运行确认失败 → Step 3: 实现 mock → Step 4: 通过**
- [ ] **Step 5: 提交** `git commit -m "feat(backend): define upstream interface with mock"`

### Task 11: `/llm/chat` 非流式

**Files:** 修改 `agent.api`;Create `internal/logic/chat_logic.go`;Test `chat_logic_test.go`

流程:`PriceProvider.Get`(**请求内只取一次**,hold 与 settle 使用同一份价格)→ `max_tokens` 截断到模型上限 → 估算 hold → `Ledger.Hold` → `Upstream.Chat` → 成功则 `Settle(Cost(...))` 并写 `usage_logs` → 返回;失败则 `Release` 并映射错误。

- [ ] **Step 1: 写失败测试**(真实 PG ledger + mock upstream):
  1. 成功:余额 100、usage(hit 0, miss 1000, out 500)、单价(200,2000,8000) → cost=6,响应 `balance=94`,账本含 hold/consume/release 且 held=0,`usage_logs` 一行。
  2. 余额不足:402 `40201`,**不调用** upstream。
  3. 上游 `ErrUpstreamBusy`/`ErrUpstreamRateLimit`:502 `50201`,held 恢复为 0,余额不变。
  4. 上游 `ErrUpstreamBalance`/`ErrUpstreamAuth`:对用户同样返回 502(不暴露原因),并产生告警事件(审计 `upstream.fatal`)。
  5. 未知或 disabled 模型:400。
  6. 同一 `X-Request-Id` 重复提交:409 `40901`,响应带首次 `cost`,余额不再变化。
  7. `max_tokens` 缺省取模型配置的上限,超过则截断。
  8. 请求中途管理端改价:本次请求仍按开始时取到的价格结算。
  9. 隐私:捕获日志输出,断言不含请求中的消息正文(唯一标记串)。
  10. 传给 upstream 的 `UserTag` 是伪名,不含用户 ID 明文;`Thinking` 取自模型配置。
- [ ] **Step 2: 运行确认失败 → Step 3: 实现 → Step 4: 通过**
- [ ] **Step 5: 提交** `git commit -m "feat(backend): add non-streaming chat gateway with billing"`

### Task 12: 流式

**Files:** 修改 handler(SSE);修改 `chat_logic.go`;Test `chat_stream_test.go`

- [ ] **Step 1: 写失败测试**:
  1. 正常:多个 `delta` + 末尾 `done`(含 cost、balance),账本结算正确。
  2. 客户端中途断开(取消 ctx):按已产生 usage 结算,held 归零;usage 不可得时按已输出字符数保守折算并标 `partial`。
  3. 上游中途报错:发 `event: error`,已产生部分结算,其余释放。
  4. 响应头 `Content-Type: text/event-stream`,每个事件即时 flush。
  5. 上游在**尚未输出任何内容**时失败(429/503):允许一次透明重试,不重复扣费。
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**(`http.Flusher`;结算放在 `defer`,保证任何路径都执行)
- [ ] **Step 4: 运行确认通过(加 `-race`)**
- [ ] **Step 5: 提交** `git commit -m "feat(backend): add streaming chat with partial settlement"`

### Task 13: 用户侧积分查询

- [ ] **Step 1: 写失败测试**:`GET /credits/balance` 返回 `balance/held/available`;`GET /credits/ledger` 游标分页、倒序、不含他人数据。
- [ ] **Step 2: 运行确认失败 → Step 3: 实现 → Step 4: 通过**
- [ ] **Step 5: 提交** `git commit -m "feat(backend): add credit queries"`

## Chunk 5: 管理端、同意书、通知、审计

### Task 14: 管理端 API(定价、发放、查询)

**Files:** Create `cmd/adminctl/main.go`、`internal/middleware/adminauth.go`;修改 `agent.api`;Test 对应 logic

管理员认证独立于用户:`admin_users` + bcrypt + 单独的 JWT 密钥,令牌带 `role`。管理员账号用 `adminctl create --username --role` 创建,不开放注册接口。

接口:
- `POST /admin/auth/login`
- `GET /admin/prices`;`PUT /admin/prices/{model}`(upsert,必须带 `reason`)
- `POST /admin/credits/grant`(`phone` 或 `user_id`、`amount`、`reason`、`request_id`)
- `GET /admin/users?phone=`(返回脱敏手机号与余额)、`GET /admin/users/{id}/ledger`
- `GET /admin/usage/summary?from=&to=`(按模型汇总 token 与积分)
- `GET /admin/notify-logs`
- 套餐与订单接口见 Task 14A

- [ ] **Step 1: 写失败测试**:
  1. 未登录/用户令牌访问 `/admin/*` → 401;`ops` 角色调用 `grant` → 403;`super` 可以。
  2. `PUT /admin/prices/deepseek-flash`:价格为负、缺 `reason`、超过上限(配置 `Admin.MaxPricePerM`)→ 400;成功时 `version` +1,写 `model_price_history` 与审计,并调用 `PriceProvider.Invalidate()`。
  3. 改价后下一次对话按新价结算(与 Task 11 用例 8 联动)。
  4. 把模型设为 `enabled=false` 后,对话返回 400。
  5. `grant`:缺 `request_id`/`reason`、单笔超过上限(配置 `Admin.MaxGrant`)→ 400;同一 `request_id` 重复提交幂等;记审计。
  6. 用户查询只返回 `phone_mask`,响应里没有 `phone_hash`。
  7. 首次上线种子:迁移或启动时写入 `deepseek-flash`、`deepseek-v4-pro` 两行(默认 `enabled=false`,价格为 0,必须由管理员设置并启用后才可用,防止未定价就开放)。
- [ ] **Step 2: 运行确认失败 → Step 3: 实现 → Step 4: 通过**
- [ ] **Step 5: 提交** `git commit -m "feat(backend): add admin api for pricing, grants and queries"`

### Task 14A: 套餐与订单(购买套餐赠送积分)

**Files:** Create `internal/packages/service.go`、`internal/payment/provider.go`、`mock.go`;修改 `agent.api`;Test `packages/service_test.go`

**规则**
- 积分与人民币**不挂钩**:套餐只有"售价(分,仅展示与记录)"和"赠送积分数"两个独立字段,系统里没有任何元到积分的换算。
- 购买成功 = 订单变为 `credited` 并一次性入账 `credits` 个积分,入账走 `Ledger.Credit(kind="recharge", requestID="order:<orderID>")`,天然幂等。
- 订单保存下单时的套餐快照(名称、售价、积分数);之后改套餐不影响已有订单。
- 状态机:`pending → paid → credited`;`pending → cancelled`;不允许回退或跳转。

**支付渠道**:真实渠道(微信/支付宝等)尚未确定。定义 `PaymentProvider` 接口,MVP 实现两个:
- `mock`:开发/测试,下单后可调用测试回调模拟支付成功;
- `manual`:线下收款后由管理员在后台"确认收款",触发入账。这样在渠道未定之前,上线即可运营。

```go
type PaymentProvider interface {
	// 返回前端/客户端用于发起支付的参数(mock/manual 返回提示信息)
	CreatePayment(ctx context.Context, o Order) (PayParams, error)
	// 验证渠道回调,返回订单号与渠道流水号;验签失败返回错误
	VerifyCallback(ctx context.Context, r *http.Request) (orderID, tradeNo string, err error)
}
```

**接口**
- 用户侧:`GET /packages`(仅 `enabled`,按 `sort_order`)、`POST /orders {package_id}` → `{order_id, status, pay_params}`、`GET /orders`(自己的)。
- 渠道回调:`POST /pay/callback/{channel}`(mock/真实渠道)。
- 管理侧:`GET/POST /admin/packages`、`PUT /admin/packages/{id}`(含上下架)、`GET /admin/orders?status=&phone=`、`POST /admin/orders/{id}/confirm`(manual 渠道确认收款)、`POST /admin/orders/{id}/cancel`。

- [ ] **Step 1: 写失败测试**(真实 PG + 真 Ledger + mock Provider):
  1. 管理员创建套餐:`credits <= 0`、`price_cents < 0`、缺名称 → 400;默认 `enabled=false`;上架后用户 `GET /packages` 才可见。
  2. 下单:创建 `pending` 订单,快照与下单时套餐一致;已下架套餐下单 → 400。
  3. 回调成功:订单 `pending → paid → credited`,账本新增一笔 `recharge`(金额 = 快照积分),余额增加;写审计。
  4. 回调幂等:同一 `trade_no` 重复回调,不重复入账;同一订单被两个不同回调并发处理,只入账一次(并发测试,`-race`)。
  5. 下单后管理员修改套餐积分数,已有订单仍按快照入账。
  6. 回调验签失败 → 拒绝,订单状态不变。
  7. 已 `cancelled` 或 `credited` 订单再收到回调 → 不改状态、不入账。
  8. `manual` 渠道:管理员 `confirm` 后入账;`ops` 角色可确认还是只有 `super`——按配置 `Admin.ConfirmRoles`,默认仅 `super`;重复确认幂等。
  9. 用户只能看到自己的订单。
  10. 隐私:订单、审计中不含手机号明文。
- [ ] **Step 2: 运行确认失败 → Step 3: 实现 → Step 4: 通过(加 `-race`)**
- [ ] **Step 5: 提交** `git commit -m "feat(backend): add packages and orders with credit grant on purchase"`

### Task 14B: 管理后台页面(admin-web)

**Files:** Create `admin-web/` 全部;测试 `admin-web/src/**/*.test.tsx`

**技术**:React + TypeScript + Vite + Ant Design 6 + React Router;请求层用 `fetch` 封装;测试用 Vitest + Testing Library + msw(模拟后端接口)。开始实现前加载 `ant-design` 与 `vercel-react-best-practices` 技能。

**页面**
| 路由 | 内容 |
|---|---|
| `/login` | 管理员登录(用户名 + 密码) |
| `/prices` | 模型价格表:模型名、命中输入/未命中输入/输出单价、思考模式、`max_tokens` 上限、启用开关、版本;行内编辑,保存时弹窗**必填修改原因**;展开可看该模型的价格历史 |
| `/packages` | 套餐列表与新建/编辑:名称、描述、售价(元,展示用)、赠送积分、排序、上下架;页面文案明确提示"积分与售价无换算关系" |
| `/orders` | 订单列表(状态/手机号尾号筛选);`manual` 渠道的 pending 订单有"确认收款""取消"操作,二次确认 |
| `/users` | 按手机号搜索(只显示脱敏号)、余额、冻结、流水分页 |
| `/credits/grant` | 手动发放积分:用户、数量、原因,自动生成 `request_id`;超过单笔上限的提示 |
| `/usage` | 按模型与时间段的 token 与积分消耗汇总 |
| `/notify-logs` | 紧急通知发送记录(渠道、模板、状态、时间) |

**约束**
- 令牌存 `sessionStorage`,过期或 401 时跳转登录;
- 角色为 `ops` 时,隐藏或禁用仅 `super` 可用的操作(与后端权限一致,后端仍是最终判定);
- 页面不展示、不请求任何对话内容与联系人信息(后端本就没有);
- 生产构建产物可由 Go 服务以静态文件方式挂载在 `/admin-ui/`,或独立部署。

- [ ] **Step 1: 初始化工程** `npm create vite@latest admin-web -- --template react-ts`,安装 `antd react-router-dom` 与测试依赖(`vitest @testing-library/react @testing-library/user-event msw jsdom`),配置 Vitest。
- [ ] **Step 2: 写失败测试 + 实现,按页面逐个推进**,每个页面至少覆盖:
  1. `login`:登录成功保存令牌并跳转;失败显示错误;未登录访问受保护路由跳转 `/login`。
  2. `prices`:渲染列表;编辑后点保存会弹出原因输入,**原因为空时不能提交**;提交调用 `PUT /admin/prices/{model}`;负数价格被表单拒绝;历史展开显示记录。
  3. `packages`:新建时 `credits <= 0` 被拒;上下架开关调用接口;页面含"积分与售价无换算关系"提示。
  4. `orders`:`manual` 渠道 pending 订单点"确认收款"出现二次确认,确认后调用接口并刷新;已入账订单没有操作按钮。
  5. `users` / `grant`:手机号只显示脱敏;发放时原因必填;提交使用生成的 `request_id`;后端返回超限错误时显示提示。
  6. 权限:`ops` 角色看不到 `super` 专属操作。
  7. 通用:接口返回 401 时清除令牌并跳转登录;网络错误显示可重试提示。
- [ ] **Step 3: 运行测试与类型检查**

Run: `cd admin-web && npx vitest run && npx tsc --noEmit && npm run build`
Expected: 测试全部通过,类型检查无错误,构建成功

- [ ] **Step 4: 手工冒烟** 启动后端(mock 上游)与 `npm run dev`,在浏览器里走一遍:登录 → 创建并上架套餐 → 设价并启用模型 → 查看订单与用户。界面类的验证必须在浏览器中实际操作,不能只看测试通过。
- [ ] **Step 5: 提交** `git commit -m "feat(admin-web): add admin console for pricing, packages, orders and users"`

### Task 15: 同意书

- [ ] **Step 1: 写失败测试**:`GET /consent/latest` 返回配置中的版本与文本;`POST /consent` 写入 `consents`;重复签同一版本幂等 204;签不存在的版本 400。
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**;同意书文本放配置文件,必须明确:日记、量表结果、基因报告仅存本机;对话内容经网关转发至第三方模型服务(DeepSeek),服务端不保存;紧急联系人信息仅在用户授权的高风险时刻用于发送通知,发送后不保存。
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `git commit -m "feat(backend): add consent versioning"`

### Task 16: 紧急通知(阿里云短信/邮件)

**Files:** Create `internal/notify/notifier.go`、`aliyun.go`、`mock.go`;Create 对应 logic;测试

```go
type Notifier interface {
	Send(ctx context.Context, channel, to, templateID string, params map[string]string) error
}
```
`channel=sms` 走阿里云短信(`templateID` 映射到已审核的模板代码);`channel=email` 走阿里云邮件推送(`SingleSendMail`,发信地址需在控制台验证)。模板白名单与映射在配置中(`Notify.Templates`、`Notify.Email.AccountName`、`Notify.Provider: mock|aliyun`)。**阿里云实现只接 SDK、留配置,不写测试**;下面的测试全部使用 mock Notifier。

- [ ] **Step 1: 写失败测试**:
  1. 未签最新同意书 → 403 `40301`。
  2. 已签 → 调用 Notifier,返回 `sent`,`notify_logs` 新增一行,只含 `channel/template_id/status`。
  3. Notifier 报错 → 返回 `failed`(HTTP 200),日志状态 `failed`。
  4. `template_id` 不在白名单 → 400,防止被当作任意短信发送器。
  5. 频率限制:同一用户 1 小时内超过 3 次 → 429;同一接收方(哈希)每天最多 3 次,防骚扰。
  6. 隐私:`notify_logs`、`audit_logs` 与捕获日志中都没有 `to` 和 `params` 的值。
- [ ] **Step 2: 运行确认失败 → Step 3: 用 mock Notifier 实现业务逻辑 → Step 4: 通过**
- [ ] **Step 5: 接入阿里云邮件推送与短信 SDK(`notify/aliyun.go`)**,不写测试;只要求 `go build ./...`、`go vet ./...` 通过;日志不含收件人与参数。
- [ ] **Step 6: 提交** `git commit -m "feat(backend): add emergency notification with aliyun sdk (untested, config-driven)"`

### Task 17: 审计日志

**Files:** Create `internal/audit/audit.go`;Test `audit_test.go`

- [ ] **Step 1: 写失败测试**:`audit.Log(ctx, actor, event, detail)` 的 `detail` 类型为自定义 `Detail`,只提供 `Int(key, v)`、`Enum(key, v)`,没有任意字符串入口;`event` 必须来自常量集合(`credit.grant`、`credit.consume`、`price.update`、`admin.grant`、`notify.emergency`、`upstream.fatal`、`account.delete` 等),非法事件拒绝写入。
- [ ] **Step 2: 运行确认失败 → Step 3: 实现并在 Ledger、改价、发放、通知、注销处接入 → Step 4: 通过**
- [ ] **Step 5: 提交** `git commit -m "feat(backend): add structured audit log"`

### Task 18: 全链路集成与隐私验证

**Files:** Create `backend/test/e2e_test.go`

- [ ] **Step 1: 写测试**:启动服务(mock upstream、mock Sender/Notifier/Payment),走通:管理员设价并启用模型 → 创建并上架套餐 → 手机号登录(得 100 积分)→ 签同意书 → 对话(扣费)→ 流式对话 → 管理员改价后再次对话按新价 → 余额不足被拒 → 下单并支付(mock 回调)→ 积分按套餐入账 → 紧急通知 → 查流水 → 注销。
- [ ] **Step 2: 隐私断言**:请求中放入唯一标记串 `PRIVATE-MARKER-xyz`(消息正文、联系人、通知参数),测试结束后逐表查询与搜索服务日志,必须为 0 处;`users` 表中不出现明文手机号。
- [ ] **Step 3: 运行**

Run: `go test ./test/... -race -v`
Expected: PASS

- [ ] **Step 4: 提交** `git commit -m "test(backend): add e2e flow and privacy marker check"`

## Chunk 6: 真实上游与 P1

### Task 19: DeepSeek 适配器

**Files:** Create `internal/upstream/deepseek.go`、`deepseek_test.go`

已核对的接口事实(DeepSeek 官方文档):
- `POST {base_url}/chat/completions`,`Authorization: Bearer <key>`,`base_url` 默认 `https://api.deepseek.com`。
- 模型名 `deepseek-flash`、`deepseek-v4-pro`;不传 `thinking` 时默认开启思考模式,所以必须**显式传** `"thinking": {"type": "disabled"|"enabled"}`(取自模型配置);默认关闭以降低延迟与成本。
- `max_tokens` 取值 1 – 393216;网关用模型配置的 `max_tokens_cap` 约束。
- 非流式 `usage`:`prompt_cache_hit_tokens`、`prompt_cache_miss_tokens`、`completion_tokens`(已含思考 token);`prompt_tokens = hit + miss`。
- 流式:请求加 `"stream": true, "stream_options": {"include_usage": true}`;SSE 每行 `data: {...}`,以 `data: [DONE]` 结束;**usage 在 `[DONE]` 之前最后一个 chunk 里**;`delta.content` 为增量,思考模式下还有 `delta.reasoning_content`(网关不转发给用户端)。
- `finish_reason` 取值 `stop|length|content_filter|tool_calls|insufficient_system_resource|aborted`;后两者按失败/部分结算处理。
- 错误码:400/422 参数错、401 密钥错、**402 上游账户余额不足(我方问题)**、429 限流、500/503 服务端问题。
- 请求体 `user_id` 可用于缓存隔离与调度隔离,要求 ASCII、≤512 字节、不得含隐私信息——传 `UserTag` 伪名。

- [ ] **Step 1: 用 `httptest.Server` 模拟上述响应,写失败测试**:
  1. 非流式成功:正确解析内容与 usage;请求体含 `thinking`、`max_tokens`、`user_id`,不含任何其他字段。
  2. 流式成功:分片拼接、末尾 usage 取自 `[DONE]` 之前的 chunk;`reasoning_content` 被丢弃。
  3. 流式中断(连接断开、无 usage):返回已输出部分,`Usage` 标记未知,由网关折算。
  4. 状态码映射:401→`ErrUpstreamAuth`,402→`ErrUpstreamBalance`,429→`ErrUpstreamRateLimit`,500/503/超时→`ErrUpstreamBusy`,400/422→`ErrUpstreamBadReq`。
  5. 重试:只对 429/500/503 且**尚未收到任何内容**时重试,最多 2 次,指数退避;其他不重试。
  6. `finish_reason=insufficient_system_resource|aborted` 视为失败并返回已产生 usage。
  7. 日志中不出现消息正文、API 密钥。
- [ ] **Step 2: 运行确认失败 → Step 3: 实现 → Step 4: 通过**
- [ ] **Step 5: 配置切换** `upstream.kind: mock|deepseek`;API 密钥只读环境变量 `DEEPSEEK_API_KEY`。
- [ ] **Step 6: 预发冒烟** 用真实密钥各发一次非流式与流式请求,核对 `usage` 与扣费:按管理端当前价格表手算一遍积分,与响应的 `cost` 一致。积分与人民币不挂钩,不需要对照 DeepSeek 的人民币定价;但运营应自行关注"套餐赠送积分 × 模型单价"对应的实际上游成本,避免亏损(见总览待确认项)。
- [ ] **Step 7: 提交** `git commit -m "feat(backend): add deepseek upstream adapter"`

### Task 20–24: P1 项(每项一个独立小计划,TDD 执行)

套餐与订单、管理后台页面已提升为 MVP(Task 14A、14B)。

| Task | 内容 | 要点与测试 |
|---|---|---|
| 20 | 真实支付渠道 | 渠道待定(微信/支付宝等)。实现 `PaymentProvider` 的真实版本:下单、回调验签、对账;复用 Task 14A 的订单状态机与幂等入账 |
| 21 | 余额不足提醒 | 结算后若 `available < 阈值`,响应附带 `low_balance: true`(契约已含该字段);Agent 据此提示 |
| 22 | 内容库 | `articles` 表与管理接口及后台页面;`GET /content/articles?since=`;仅含科普文章 |
| 23 | 量表版本 | `GET /scales/versions`;Agent 本地保存版本号 |
| 24 | 监控告警 | 指标:网关错误率、上游延迟 P95、**上游 401/402 次数(出现即告警)**、hold 超时未结算数、账本对账差异(账户与流水汇总)、订单 paid 但未 credited 的数量;短信发送失败率;每日对账任务 |

### 运维补充(随 Task 11 起纳入)
- [ ] 悬挂 hold 回收:定时任务扫描超过 10 分钟未 settle/release 的 hold,按 Release 处理并记审计。测试:构造悬挂 hold,任务运行后 `held` 归零。
- [ ] 配置:数据库/Redis 连接、JWT 密钥、手机号 pepper、DeepSeek 与阿里云密钥、管理端 JWT 密钥只从环境变量读取,仓库内不存密钥;启动时校验必填项缺失即退出。
- [ ] 前置事务(非代码,需尽早启动,审核需要时间):阿里云短信的企业签名与两个模板(验证码模板、紧急联系人通知模板)提交审核;邮件推送验证发信域名与发信地址。紧急通知模板措辞需克制,不得出现对话内容或诊断性词汇。阿里云 SDK 的联网联调不在本阶段,等审核通过后由你自行在预发环境验证。

## 后端验收清单

- [ ] `go vet ./...` 与 `go test ./... -race` 全部通过
- [ ] 账本并发测试连续 3 次通过
- [ ] 隐私标记串检查为 0;库中无明文手机号
- [ ] `cd admin-web && npx vitest run && npx tsc --noEmit && npm run build` 全部通过
- [ ] 手工冒烟(浏览器):管理员创建并上架套餐 → 设价并启用模型 → 手机号登录得 100 积分 → 下单(manual)→ 后台确认收款 → 积分到账 → 对话 → 余额下降 → 管理员改价 → 下一次按新价扣费

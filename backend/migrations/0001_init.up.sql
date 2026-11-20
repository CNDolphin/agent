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

-- 种子模型:默认不可用、价格为 0,必须由管理员设价并启用后才可调用
INSERT INTO model_prices (model, in_hit_per_m, in_miss_per_m, out_per_m, thinking, max_tokens_cap, enabled, version)
VALUES ('deepseek-flash', 0, 0, 0, 'disabled', 2048, false, 1),
       ('deepseek-v4-pro', 0, 0, 0, 'disabled', 2048, false, 1);

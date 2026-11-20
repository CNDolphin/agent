// Package testenv 组装带 mock 依赖与隔离数据库的服务上下文。
package testenv

import (
	"context"
	"database/sql"
	"fmt"
	"net"
	"net/http"
	"sync"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/zeromicro/go-zero/rest"

	"mhagent/internal/config"
	"mhagent/internal/handler"
	"mhagent/internal/model"
	"mhagent/internal/notify"
	"mhagent/internal/sms"
	"mhagent/internal/svc"
	"mhagent/internal/testdb"
	"mhagent/internal/upstream"
)

// Clock 可推进的测试时钟。
type Clock struct {
	mu sync.Mutex
	t  time.Time
}

// NewClock 创建固定时钟。
func NewClock() *Clock { return &Clock{t: time.Now().UTC()} }

// Now 返回当前时钟。
func (c *Clock) Now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.t
}

// Advance 推进时钟。
func (c *Clock) Advance(d time.Duration) {
	c.mu.Lock()
	c.t = c.t.Add(d)
	c.mu.Unlock()
}

// Env 测试环境。
type Env struct {
	SC       *svc.ServiceContext
	DB       *sql.DB
	Upstream *upstream.Mock
	Sender   *sms.MockSender
	Notifier *notify.MockNotifier
	Redis    *miniredis.Miniredis
	Clock    *Clock
	Cfg      config.Config
	Secrets  config.Secrets
}

// Option 修改测试配置。
type Option func(*config.Config)

// WithConfig 自定义配置。
func WithConfig(fn func(*config.Config)) Option { return fn }

// New 构建测试环境:隔离 schema + miniredis + mock 上游/短信/通知。
func New(t *testing.T, opts ...Option) *Env {
	t.Helper()
	db := testdb.New(t)
	if err := model.MigrateUp(context.Background(), db); err != nil {
		t.Fatalf("执行迁移失败: %v", err)
	}
	mr, rdb := testdb.Redis(t)
	clock := NewClock()

	cfg := baseConfig()
	for _, opt := range opts {
		opt(&cfg)
	}
	if cfg.Reports.Dir == "" {
		cfg.Reports.Dir = t.TempDir()
	}
	if cfg.Reports.MaxSizeMB <= 0 {
		cfg.Reports.MaxSizeMB = 20
	}
	if cfg.Content.Dir == "" {
		cfg.Content.Dir = t.TempDir()
	}
	if cfg.Content.MaxSizeMB <= 0 {
		cfg.Content.MaxSizeMB = 50
	}
	secrets := config.Secrets{
		JWTSecret:          "test-jwt-secret",
		AdminJWTSecret:     "test-admin-secret",
		PhonePepper:        "test-phone-pepper",
		DeepSeekAPIKey:     "test-deepseek-key",
		AliyunAccessKey:    "test-ak",
		AliyunAccessSecret: "test-sk",
	}
	up := upstream.NewMock()
	sender := sms.NewMockSender()
	notifier := notify.NewMockNotifier()

	sc, err := svc.New(cfg, secrets, svc.Options{
		DB: db, RDB: rdb, Upstream: up, Sender: sender, Notifier: notifier, Now: clock.Now,
	})
	if err != nil {
		t.Fatalf("组装服务上下文失败: %v", err)
	}
	t.Cleanup(sc.Close)
	return &Env{SC: sc, DB: db, Upstream: up, Sender: sender, Notifier: notifier, Redis: mr, Clock: clock, Cfg: cfg, Secrets: secrets}
}

func baseConfig() config.Config {
	cfg := config.Config{
		Env:       "test",
		Redis:     config.RedisConf{Addr: "localhost:6379"},
		Auth:      config.AuthConf{AccessTTLMinutes: 15, RefreshTTLHours: 720, AdminTTLHours: 12},
		Credits:   config.CreditsConf{SignupGrant: 100, LowBalanceThreshold: 10, ReSignupCooldownDays: 30, HoldReclaimMinutes: 10},
		Pricing:   config.PricingConf{CacheTTLSeconds: 30},
		RateLimit: config.RateLimitConf{PerMinute: 30},
		Admin:     config.AdminConf{MaxGrant: 100000, MaxPricePerM: 100000, ConfirmRoles: []string{"super"}},
		Payment:   config.PaymentConf{DefaultChannel: "mock", MaxOrdersPerUserPerDay: 20},
		Upstream:  config.UpstreamConf{Kind: "mock", BaseURL: "https://api.deepseek.com", TimeoutSeconds: 60, MaxRetries: 2},
		Consent:   config.ConsentConf{Version: "v1", Text: "同意书正文"},
	}
	cfg.Sms.Provider = "mock"
	cfg.Sms.CodeTTLSeconds = 300
	cfg.Sms.ResendSeconds = 60
	cfg.Sms.PhoneDailyLimit = 5
	cfg.Sms.IPDailyLimit = 20
	cfg.Sms.Templates.Login = "SMS_LOGIN_CODE"
	cfg.Notify.Provider = "mock"
	cfg.Notify.Templates = map[string]string{"crisis_contact_v1": "SMS_CRISIS_CONTACT"}
	return cfg
}

// StartServer 在随机端口启动 go-zero 服务,返回 baseURL。
func StartServer(t *testing.T, env *Env) string {
	t.Helper()
	port := freePort(t)
	conf := rest.RestConf{Host: "127.0.0.1", Port: port}
	server := rest.MustNewServer(conf)
	handler.RegisterRoutes(server, env.SC)
	go server.Start()
	t.Cleanup(server.Stop)

	base := fmt.Sprintf("http://127.0.0.1:%d", port)
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		resp, err := http.Get(base + "/health")
		if err == nil {
			_ = resp.Body.Close()
			if resp.StatusCode == http.StatusOK {
				return base
			}
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("服务未在 3 秒内启动")
	return ""
}

func freePort(t *testing.T) int {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("分配端口失败: %v", err)
	}
	defer l.Close()
	return l.Addr().(*net.TCPAddr).Port
}

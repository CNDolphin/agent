// Package svc 组装服务依赖。
package svc

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"time"

	"github.com/redis/go-redis/v9"

	"mhagent/internal/audit"
	"mhagent/internal/auth"
	"mhagent/internal/config"
	"mhagent/internal/credits"
	"mhagent/internal/model"
	"mhagent/internal/notify"
	"mhagent/internal/packages"
	"mhagent/internal/payment"
	"mhagent/internal/sms"
	"mhagent/internal/smscode"
	"mhagent/internal/sse"
	"mhagent/internal/upstream"
)

// ServiceContext 持有全局依赖。
type ServiceContext struct {
	Config          config.Config
	Secrets         config.Secrets
	DB              *sql.DB
	RDB             *redis.Client
	Ledger          *credits.PGLedger
	Prices          *credits.PGPriceProvider
	Upstream        upstream.Upstream
	Sender          sms.Sender
	SMSCode         *smscode.Service
	Notifier        notify.Notifier
	NotifyTemplates map[string]string
	Tokens          *auth.TokenIssuer
	AdminTokens     *auth.AdminTokenIssuer
	Audit           *audit.Logger
	Packages        *packages.Service
	ReportHub       *sse.Hub
	Now             func() time.Time
}

// Options 允许测试注入替代实现。
type Options struct {
	DB       *sql.DB
	RDB      *redis.Client
	Upstream upstream.Upstream
	Sender   sms.Sender
	Notifier notify.Notifier
	Now      func() time.Time
}

// New 组装依赖。未提供 Options 时按配置创建真实实现。
func New(cfg config.Config, secrets config.Secrets, opts Options) (*ServiceContext, error) {
	now := opts.Now
	if now == nil {
		now = time.Now
	}
	dsn := cfg.DataSource
	if v := os.Getenv("DATABASE_URL"); v != "" {
		dsn = v
	}
	db := opts.DB
	var err error
	if db == nil {
		db, err = model.Open(dsn, 20)
		if err != nil {
			return nil, err
		}
	}
	if err := model.EnsureUp(context.Background(), db); err != nil {
		return nil, fmt.Errorf("初始化数据库: %w", err)
	}

	rdb := opts.RDB
	if rdb == nil {
		addr := cfg.Redis.Addr
		if v := os.Getenv("REDIS_ADDR"); v != "" {
			addr = v
		}
		rdb = redis.NewClient(&redis.Options{Addr: addr, Password: cfg.Redis.Password, DB: cfg.Redis.DB})
		if err := rdb.Ping(context.Background()).Err(); err != nil {
			return nil, fmt.Errorf("连接 Redis 失败: %w", err)
		}
	}

	auditor := audit.New(db)
	auditor.Now = now
	ledger := credits.NewPGLedger(db)
	ledger.Audit = auditor
	ledger.Now = now
	prices := credits.NewPGPriceProvider(db, cfg.CacheTTL())
	prices.Now = now

	sender := opts.Sender
	if sender == nil {
		switch cfg.Sms.Provider {
		case "mock":
			sender = sms.NewMockSender()
		case "aliyun":
			sender, err = sms.NewAliyunSender(cfg.Sms.Aliyun.Endpoint, cfg.Sms.Aliyun.SignName, secrets.AliyunAccessKey, secrets.AliyunAccessSecret)
			if err != nil {
				return nil, err
			}
		default:
			return nil, fmt.Errorf("未知的短信发送器: %s", cfg.Sms.Provider)
		}
	}

	notifier := opts.Notifier
	if notifier == nil {
		switch cfg.Notify.Provider {
		case "mock":
			notifier = notify.NewMockNotifier()
		case "aliyun":
			templateCodes := cfg.Notify.Templates
			notifier, err = notify.NewAliyunNotifier(secrets.AliyunAccessKey, secrets.AliyunAccessSecret, sender, templateCodes, cfg.Notify.Email.AccountName, cfg.Notify.Email.FromAlias)
			if err != nil {
				return nil, err
			}
		default:
			return nil, fmt.Errorf("未知的通知发送器: %s", cfg.Notify.Provider)
		}
	}

	templates := cfg.Notify.Templates
	if len(templates) == 0 {
		templates = map[string]string{"crisis_contact_v1": "SMS_CRISIS_CONTACT"}
	}

	loginTemplate := cfg.Sms.Templates.Login
	if cfg.Sms.Provider == "aliyun" {
		loginTemplate = cfg.Sms.Aliyun.Templates.Login
	}
	if loginTemplate == "" {
		loginTemplate = "SMS_LOGIN_CODE"
	}

	codeSvc := &smscode.Service{
		RDB:         rdb,
		Sender:      sender,
		Pepper:      secrets.PhonePepper,
		Template:    loginTemplate,
		CodeTTL:     time.Duration(cfg.Sms.CodeTTLSeconds) * time.Second,
		ResendEvery: time.Duration(cfg.Sms.ResendSeconds) * time.Second,
		PhoneDaily:  cfg.Sms.PhoneDailyLimit,
		IPDaily:     cfg.Sms.IPDailyLimit,
		Now:         now,
	}
	if cfg.Sms.Provider == "mock" {
		// 本地联调使用的万能验证码,生产(aliyun)环境不生效。
		codeSvc.UniversalCode = "888888"
	}

	up := opts.Upstream
	if up == nil {
		switch cfg.Upstream.Kind {
		case "mock":
			m := upstream.NewMock()
			m.Content = "开发环境模拟回复"
			m.Usage = upstream.Usage{InputHit: 0, InputMiss: 10, Output: 10}
			up = m
		case "deepseek":
			up = upstream.NewDeepSeek(cfg.Upstream.BaseURL, secrets.DeepSeekAPIKey,
				time.Duration(cfg.Upstream.TimeoutSeconds)*time.Second, cfg.Upstream.MaxRetries)
		default:
			return nil, fmt.Errorf("未知的上游实现: %s", cfg.Upstream.Kind)
		}
	}

	tokens := auth.NewTokenIssuer(secrets.JWTSecret,
		time.Duration(cfg.Auth.AccessTTLMinutes)*time.Minute,
		time.Duration(cfg.Auth.RefreshTTLHours)*time.Hour)
	tokens.Now = now
	adminTokens := auth.NewAdminTokenIssuer(secrets.AdminJWTSecret, time.Duration(cfg.Auth.AdminTTLHours)*time.Hour)
	adminTokens.Now = now

	providers := map[string]payment.Provider{
		payment.ChannelMock:   payment.NewMockProvider(),
		payment.ChannelManual: payment.NewManualProvider(),
	}
	packageSvc := packages.New(db, ledger, auditor, providers, cfg.Payment.DefaultChannel, cfg.Payment.MaxOrdersPerUserPerDay)
	packageSvc.Now = now

	return &ServiceContext{
		Config: cfg, Secrets: secrets, DB: db, RDB: rdb,
		Ledger: ledger, Prices: prices, Upstream: up,
		Sender: sender, SMSCode: codeSvc, Notifier: notifier, NotifyTemplates: templates,
		Tokens: tokens, AdminTokens: adminTokens, Audit: auditor, Packages: packageSvc,
		ReportHub: sse.NewHub(),
		Now:       now,
	}, nil
}

// Close 释放资源。
func (s *ServiceContext) Close() {
	if s.RDB != nil {
		_ = s.RDB.Close()
	}
	if s.DB != nil {
		_ = s.DB.Close()
	}
}

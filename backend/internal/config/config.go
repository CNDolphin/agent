// Package config 定义服务配置。密钥一律来自环境变量,不写入 yaml。
package config

import (
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/zeromicro/go-zero/core/conf"
	"github.com/zeromicro/go-zero/rest"
)

// RedisConf Redis 连接配置。
type RedisConf struct {
	Addr     string
	Password string `json:",optional"`
	DB       int    `json:",default=0"`
}

// AuthConf 令牌配置。
type AuthConf struct {
	AccessTTLMinutes int `json:",default=15"`
	RefreshTTLHours  int `json:",default=720"`
	AdminTTLHours    int `json:",default=12"`
}

// CreditsConf 积分配置。
type CreditsConf struct {
	SignupGrant          int64 `json:",default=100"`
	LowBalanceThreshold  int64 `json:",default=10"`
	ReSignupCooldownDays int   `json:",default=30"`
	HoldReclaimMinutes   int   `json:",default=10"`
}

// PricingConf 价格缓存配置。
type PricingConf struct {
	CacheTTLSeconds int `json:",default=30"`
}

// RateLimitConf 用户接口限流配置。
type RateLimitConf struct {
	PerMinute int `json:",default=30"`
}

// AdminConf 管理端约束。
type AdminConf struct {
	MaxGrant     int64    `json:",default=100000"`
	MaxPricePerM int64    `json:",default=100000"`
	ConfirmRoles []string `json:",optional"`
}

// SmsAliyunConf 阿里云短信配置(仅接 SDK,测试走 mock)。
type SmsAliyunConf struct {
	Endpoint  string
	SignName  string
	Templates struct {
		Login     string
		Emergency string
	}
}

// SmsConf 短信验证码配置。
type SmsConf struct {
	Provider        string `json:",default=mock"`
	CodeTTLSeconds  int    `json:",default=300"`
	ResendSeconds   int    `json:",default=60"`
	PhoneDailyLimit int    `json:",default=5"`
	IPDailyLimit    int    `json:",default=20"`
	Templates       struct {
		Login string
	}
	Aliyun SmsAliyunConf
}

// NotifyEmailConf 阿里云邮件推送配置。
type NotifyEmailConf struct {
	AccountName string
	FromAlias   string
}

// NotifyConf 紧急通知配置。
type NotifyConf struct {
	Provider  string            `json:",default=mock"`
	Templates map[string]string `json:",optional"`
	Email     NotifyEmailConf
}

// PaymentConf 支付配置。
type PaymentConf struct {
	DefaultChannel         string `json:",default=mock"`
	MaxOrdersPerUserPerDay int    `json:",default=20"`
}

// UpstreamConf 上游模型平台配置。
type UpstreamConf struct {
	Kind           string `json:",default=mock"`
	BaseURL        string `json:",default=https://api.deepseek.com"`
	TimeoutSeconds int    `json:",default=60"`
	MaxRetries     int    `json:",default=2"`
}

// ConsentConf 同意书配置。
type ConsentConf struct {
	Version string
	Text    string
	URL     string `json:",optional"`
}

// ReportsConf 检测报告存储配置。
type ReportsConf struct {
	Dir       string `json:",default=./data/reports"`
	MaxSizeMB int64  `json:",default=20"`
}

// ContentConf 在线更新内容包存储配置。
type ContentConf struct {
	Dir          string `json:",default=./data/content"`
	MaxSizeMB    int64  `json:",default=50"`
	AppMaxSizeMB int64  `json:",default=200"`
}

// Config 服务总配置。
type Config struct {
	rest.RestConf
	Env        string `json:",default=dev"`
	DataSource string `json:",optional"`
	Redis      RedisConf
	Auth       AuthConf
	Credits    CreditsConf
	Pricing    PricingConf
	RateLimit  RateLimitConf
	Admin      AdminConf
	Sms        SmsConf
	Notify     NotifyConf
	Payment    PaymentConf
	Upstream   UpstreamConf
	Consent    ConsentConf
	Reports    ReportsConf
	Content    ContentConf
}

// Secrets 只从环境变量读取的密钥。
type Secrets struct {
	JWTSecret          string
	AdminJWTSecret     string
	PhonePepper        string
	DeepSeekAPIKey     string
	AliyunAccessKey    string
	AliyunAccessSecret string
}

// Load 读取配置文件并补齐环境变量中的密钥。
func Load(path string) (Config, Secrets, error) {
	var c Config
	if err := conf.Load(path, &c, conf.UseEnv()); err != nil {
		return c, Secrets{}, err
	}
	c.applyDefaults()
	s := LoadSecrets()
	if err := c.Validate(s); err != nil {
		return c, s, err
	}
	return c, s, nil
}

// LoadSecrets 从环境变量读取密钥;调用方按上游/短信渠道校验必填项。
func LoadSecrets() Secrets {
	return Secrets{
		JWTSecret:          os.Getenv("JWT_SECRET"),
		AdminJWTSecret:     os.Getenv("ADMIN_JWT_SECRET"),
		PhonePepper:        os.Getenv("PHONE_HASH_PEPPER"),
		DeepSeekAPIKey:     os.Getenv("DEEPSEEK_API_KEY"),
		AliyunAccessKey:    os.Getenv("ALIBABA_CLOUD_ACCESS_KEY_ID"),
		AliyunAccessSecret: os.Getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET"),
	}
}

func (c *Config) applyDefaults() {
	if c.Auth.AccessTTLMinutes <= 0 {
		c.Auth.AccessTTLMinutes = 15
	}
	if c.Auth.RefreshTTLHours <= 0 {
		c.Auth.RefreshTTLHours = 720
	}
	if c.Auth.AdminTTLHours <= 0 {
		c.Auth.AdminTTLHours = 12
	}
	if c.Credits.SignupGrant <= 0 {
		c.Credits.SignupGrant = 100
	}
	if c.Credits.ReSignupCooldownDays <= 0 {
		c.Credits.ReSignupCooldownDays = 30
	}
	if c.Credits.HoldReclaimMinutes <= 0 {
		c.Credits.HoldReclaimMinutes = 10
	}
	if c.Pricing.CacheTTLSeconds <= 0 {
		c.Pricing.CacheTTLSeconds = 30
	}
	if c.RateLimit.PerMinute <= 0 {
		c.RateLimit.PerMinute = 30
	}
	if c.Admin.MaxGrant <= 0 {
		c.Admin.MaxGrant = 100000
	}
	if c.Admin.MaxPricePerM <= 0 {
		c.Admin.MaxPricePerM = 100000
	}
	if len(c.Admin.ConfirmRoles) == 0 {
		c.Admin.ConfirmRoles = []string{"super"}
	}
	if c.Sms.Provider == "" {
		c.Sms.Provider = "mock"
	}
	if c.Sms.CodeTTLSeconds <= 0 {
		c.Sms.CodeTTLSeconds = 300
	}
	if c.Sms.ResendSeconds <= 0 {
		c.Sms.ResendSeconds = 60
	}
	if c.Sms.PhoneDailyLimit <= 0 {
		c.Sms.PhoneDailyLimit = 5
	}
	if c.Sms.IPDailyLimit <= 0 {
		c.Sms.IPDailyLimit = 20
	}
	if c.Notify.Provider == "" {
		c.Notify.Provider = "mock"
	}
	if c.Payment.DefaultChannel == "" {
		c.Payment.DefaultChannel = "mock"
	}
	if c.Payment.MaxOrdersPerUserPerDay <= 0 {
		c.Payment.MaxOrdersPerUserPerDay = 20
	}
	if c.Upstream.Kind == "" {
		c.Upstream.Kind = "mock"
	}
	if c.Upstream.BaseURL == "" {
		c.Upstream.BaseURL = "https://api.deepseek.com"
	}
	if c.Upstream.TimeoutSeconds <= 0 {
		c.Upstream.TimeoutSeconds = 60
	}
	if strings.TrimSpace(c.Reports.Dir) == "" {
		c.Reports.Dir = "./data/reports"
	}
	if c.Reports.MaxSizeMB <= 0 {
		c.Reports.MaxSizeMB = 20
	}
	if strings.TrimSpace(c.Content.Dir) == "" {
		c.Content.Dir = "./data/content"
	}
	if c.Content.MaxSizeMB <= 0 {
		c.Content.MaxSizeMB = 50
	}
	if c.Content.AppMaxSizeMB <= 0 {
		c.Content.AppMaxSizeMB = 200
	}
	if c.Env == "" {
		c.Env = "dev"
	}
}

// Validate 校验必填配置。缺少密钥时返回错误,由入口直接退出。
func (c *Config) Validate(s Secrets) error {
	if strings.TrimSpace(s.JWTSecret) == "" {
		return errors.New("缺少环境变量 JWT_SECRET")
	}
	if strings.TrimSpace(s.AdminJWTSecret) == "" {
		return errors.New("缺少环境变量 ADMIN_JWT_SECRET")
	}
	if strings.TrimSpace(s.PhonePepper) == "" {
		return errors.New("缺少环境变量 PHONE_HASH_PEPPER")
	}
	if c.Env == "prod" {
		if c.Sms.Provider == "mock" {
			return errors.New("prod 环境不允许使用 mock 短信发送器")
		}
		if c.Notify.Provider == "mock" {
			return errors.New("prod 环境不允许使用 mock 通知发送器")
		}
	}
	switch c.Sms.Provider {
	case "mock":
	case "aliyun":
		if s.AliyunAccessKey == "" || s.AliyunAccessSecret == "" {
			return errors.New("短信使用 aliyun 时必须配置 ALIBABA_CLOUD_ACCESS_KEY_ID/SECRET")
		}
		if c.Sms.Aliyun.SignName == "" || c.Sms.Aliyun.Templates.Login == "" {
			return errors.New("短信使用 aliyun 时必须配置签名与登录模板")
		}
	default:
		return fmt.Errorf("未知的 Sms.Provider: %s", c.Sms.Provider)
	}
	switch c.Notify.Provider {
	case "mock":
	case "aliyun":
		if s.AliyunAccessKey == "" || s.AliyunAccessSecret == "" {
			return errors.New("通知使用 aliyun 时必须配置 ALIBABA_CLOUD_ACCESS_KEY_ID/SECRET")
		}
		if c.Notify.Email.AccountName == "" {
			return errors.New("邮件通知缺少 Notify.Email.AccountName")
		}
	default:
		return fmt.Errorf("未知的 Notify.Provider: %s", c.Notify.Provider)
	}
	switch c.Upstream.Kind {
	case "mock":
	case "deepseek":
		if s.DeepSeekAPIKey == "" {
			return errors.New("上游使用 deepseek 时必须配置 DEEPSEEK_API_KEY")
		}
	default:
		return fmt.Errorf("未知的 Upstream.Kind: %s", c.Upstream.Kind)
	}
	if c.Consent.Version == "" || strings.TrimSpace(c.Consent.Text) == "" {
		return errors.New("缺少 Consent.Version 或 Consent.Text")
	}
	if _, err := time.ParseDuration(fmt.Sprintf("%dm", c.Credits.HoldReclaimMinutes)); err != nil {
		return err
	}
	if strings.TrimSpace(c.Reports.Dir) != "" {
		if err := os.MkdirAll(c.Reports.Dir, 0o700); err != nil {
			return fmt.Errorf("创建报告存储目录失败: %w", err)
		}
	}
	if strings.TrimSpace(c.Content.Dir) != "" {
		if err := os.MkdirAll(c.Content.Dir, 0o700); err != nil {
			return fmt.Errorf("创建内容包存储目录失败: %w", err)
		}
	}
	return nil
}

// CacheTTL 价格缓存有效期。
func (c *Config) CacheTTL() time.Duration {
	return time.Duration(c.Pricing.CacheTTLSeconds) * time.Second
}

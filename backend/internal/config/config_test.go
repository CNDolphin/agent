package config

import (
	"strings"
	"testing"
)

func validConfig() Config {
	c := Config{}
	c.Env = "dev"
	c.Sms.Provider = "mock"
	c.Notify.Provider = "mock"
	c.Upstream.Kind = "mock"
	c.Consent.Version = "v1"
	c.Consent.Text = "同意书"
	return c
}

func validSecrets() Secrets {
	return Secrets{
		JWTSecret:      "jwt",
		AdminJWTSecret: "admin",
		PhonePepper:    "pepper",
	}
}

func TestValidateOK(t *testing.T) {
	c := validConfig()
	if err := c.Validate(validSecrets()); err != nil {
		t.Fatalf("合法配置不应报错: %v", err)
	}
}

func TestValidateRequiresSecrets(t *testing.T) {
	c := validConfig()
	cases := []struct {
		name string
		mod  func(*Secrets)
		want string
	}{
		{"JWT", func(s *Secrets) { s.JWTSecret = "" }, "JWT_SECRET"},
		{"AdminJWT", func(s *Secrets) { s.AdminJWTSecret = "" }, "ADMIN_JWT_SECRET"},
		{"Pepper", func(s *Secrets) { s.PhonePepper = "" }, "PHONE_HASH_PEPPER"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			s := validSecrets()
			tc.mod(&s)
			err := c.Validate(s)
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("期望缺少 %s 的错误,实际 %v", tc.want, err)
			}
		})
	}
}

func TestValidateProdRejectsMockProviders(t *testing.T) {
	c := validConfig()
	c.Env = "prod"
	if err := c.Validate(validSecrets()); err == nil || !strings.Contains(err.Error(), "mock 短信") {
		t.Fatalf("prod + mock 短信应启动失败,实际 %v", err)
	}

	c.Sms.Provider = "aliyun"
	c.Sms.Aliyun.SignName = "签名"
	c.Sms.Aliyun.Templates.Login = "SMS_LOGIN"
	if err := c.Validate(validSecrets()); err == nil || !strings.Contains(err.Error(), "mock 通知") {
		t.Fatalf("prod + mock 通知应启动失败,实际 %v", err)
	}
}

func TestValidateAliyunRequiresCredentials(t *testing.T) {
	c := validConfig()
	c.Sms.Provider = "aliyun"
	c.Sms.Aliyun.SignName = "签名"
	c.Sms.Aliyun.Templates.Login = "SMS_LOGIN"
	if err := c.Validate(validSecrets()); err == nil || !strings.Contains(err.Error(), "ALIBABA_CLOUD_ACCESS_KEY_ID") {
		t.Fatalf("aliyun 短信缺少密钥应报错,实际 %v", err)
	}
	withKeys := validSecrets()
	withKeys.AliyunAccessKey = "ak"
	withKeys.AliyunAccessSecret = "sk"
	if err := c.Validate(withKeys); err != nil {
		t.Fatalf("补齐密钥后应通过: %v", err)
	}
}

func TestValidateDeepSeekRequiresKey(t *testing.T) {
	c := validConfig()
	c.Upstream.Kind = "deepseek"
	if err := c.Validate(validSecrets()); err == nil || !strings.Contains(err.Error(), "DEEPSEEK_API_KEY") {
		t.Fatalf("deepseek 缺少密钥应报错,实际 %v", err)
	}
	s := validSecrets()
	s.DeepSeekAPIKey = "k"
	if err := c.Validate(s); err != nil {
		t.Fatalf("补齐 DeepSeek 密钥后应通过: %v", err)
	}
}

func TestValidateRequiresConsent(t *testing.T) {
	c := validConfig()
	c.Consent.Version = ""
	if err := c.Validate(validSecrets()); err == nil || !strings.Contains(err.Error(), "Consent") {
		t.Fatalf("缺少同意书应报错,实际 %v", err)
	}
}

func TestValidateUnknownProviders(t *testing.T) {
	c := validConfig()
	c.Sms.Provider = "unknown"
	if err := c.Validate(validSecrets()); err == nil {
		t.Fatalf("未知短信渠道应报错")
	}
	c = validConfig()
	c.Notify.Provider = "unknown"
	if err := c.Validate(validSecrets()); err == nil {
		t.Fatalf("未知通知渠道应报错")
	}
	c = validConfig()
	c.Upstream.Kind = "unknown"
	if err := c.Validate(validSecrets()); err == nil {
		t.Fatalf("未知上游应报错")
	}
}

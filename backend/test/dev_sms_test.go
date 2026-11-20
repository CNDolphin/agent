package test

import (
	"net/http"
	"net/url"
	"testing"

	"mhagent/internal/config"
	"mhagent/internal/testenv"
)

// TestDevSMSLastCodeDev 开发环境可读取 mock 验证码。
func TestDevSMSLastCodeDev(t *testing.T) {
	env := testenv.New(t, testenv.WithConfig(func(c *config.Config) { c.Env = "dev" }))
	base := testenv.StartServer(t, env)

	phone := "13800001234"
	resp := do(t, http.MethodPost, base+"/auth/sms/send", map[string]string{"phone": phone}, "", nil)
	resp.expect(t, http.StatusNoContent)

	got := do(t, http.MethodGet, base+"/dev/sms/last?phone="+url.QueryEscape(phone), nil, "", nil)
	got.expect(t, http.StatusOK)
	if code := got.mapBody(t)["code"]; code != env.Sender.LastCodeAny() {
		t.Fatalf("取码接口返回 %v,期望 %s", code, env.Sender.LastCodeAny())
	}

	// 未发送过验证码的号码返回 404。
	other := do(t, http.MethodGet, base+"/dev/sms/last?phone=13900009999", nil, "", nil)
	other.expect(t, http.StatusNotFound)

	// 非法号码返回 40001。
	bad := do(t, http.MethodGet, base+"/dev/sms/last?phone=123", nil, "", nil)
	bad.expect(t, http.StatusBadRequest)
	if bad.errorCode(t) != 40001 {
		t.Fatalf("期望错误码 40001,实际 %d", bad.errorCode(t))
	}
}

// TestDevSMSLastCodeNonDev 非开发环境不暴露取码接口。
func TestDevSMSLastCodeNonDev(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)

	phone := "13800001234"
	do(t, http.MethodPost, base+"/auth/sms/send", map[string]string{"phone": phone}, "", nil).
		expect(t, http.StatusNoContent)

	got := do(t, http.MethodGet, base+"/dev/sms/last?phone="+phone, nil, "", nil)
	got.expect(t, http.StatusNotFound)
}

package smscode_test

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"

	"mhagent/internal/sms"
	"mhagent/internal/smscode"
	"mhagent/internal/testdb"
)

// fixedNow 固定时钟,便于控制"每天"的维度。
var fixedNow = time.Date(2026, 11, 6, 10, 0, 0, 0, time.UTC)

func newService(t *testing.T, phoneDaily, ipDaily int) (*smscode.Service, *sms.MockSender, *miniredis.Miniredis) {
	t.Helper()
	mr, rdb := testdb.Redis(t)
	sender := sms.NewMockSender()
	svc := &smscode.Service{
		RDB:         rdb,
		Sender:      sender,
		Pepper:      "test-pepper",
		Template:    "SMS_LOGIN_CODE",
		CodeTTL:     5 * time.Minute,
		ResendEvery: time.Minute,
		PhoneDaily:  phoneDaily,
		IPDaily:     ipDaily,
		Now:         func() time.Time { return fixedNow },
	}
	return svc, sender, mr
}

func TestSendAndVerify(t *testing.T) {
	svc, sender, mr := newService(t, 5, 20)
	ctx := context.Background()

	if err := svc.Send(ctx, "138 0000 1234", "1.2.3.4"); err != nil {
		t.Fatalf("发送验证码失败: %v", err)
	}
	if got := len(sender.Calls()); got != 1 {
		t.Fatalf("期望 1 次发送,实际 %d", got)
	}
	if phone := sender.Calls()[0].Phone; phone != "+8613800001234" {
		t.Fatalf("期望规范化手机号 +8613800001234,实际 %s", phone)
	}
	code := sender.LastCodeAny()
	if len(code) != 6 {
		t.Fatalf("验证码应为 6 位,实际 %q", code)
	}

	// Redis 中不得出现明文验证码或明文手机号。
	for _, key := range mr.Keys() {
		val, _ := mr.Get(key)
		if strings.Contains(key, "13800001234") {
			t.Fatalf("Redis 键包含明文手机号: %s", key)
		}
		if strings.Contains(val, code) {
			t.Fatalf("Redis 值包含明文验证码: %s=%s", key, val)
		}
	}
	stored, err := svc.PeekCodeHash(ctx, "13800001234")
	if err != nil {
		t.Fatalf("读取验证码哈希失败: %v", err)
	}
	if stored == code {
		t.Fatalf("Redis 中保存了明文验证码")
	}

	if err := svc.Verify(ctx, "13800001234", code); err != nil {
		t.Fatalf("校验正确验证码失败: %v", err)
	}
	// 验证成功后立即失效。
	if err := svc.Verify(ctx, "13800001234", code); !errors.Is(err, smscode.ErrInvalidCode) {
		t.Fatalf("期望验证码已失效,实际 %v", err)
	}
}

func TestVerifyWrongCodeLocksAfterFiveAttempts(t *testing.T) {
	svc, sender, _ := newService(t, 5, 20)
	ctx := context.Background()
	if err := svc.Send(ctx, "13800005678", "1.2.3.4"); err != nil {
		t.Fatalf("发送验证码失败: %v", err)
	}
	code := sender.LastCodeAny()
	for i := 0; i < 5; i++ {
		if err := svc.Verify(ctx, "13800005678", "000000"); !errors.Is(err, smscode.ErrInvalidCode) {
			t.Fatalf("第 %d 次错误验证码期望 ErrInvalidCode,实际 %v", i+1, err)
		}
	}
	// 错误 5 次后,即使验证码正确也作废。
	if err := svc.Verify(ctx, "13800005678", code); !errors.Is(err, smscode.ErrInvalidCode) {
		t.Fatalf("5 次错误后验证码应作废,实际 %v", err)
	}
}

func TestCodeExpires(t *testing.T) {
	svc, sender, mr := newService(t, 5, 20)
	ctx := context.Background()
	if err := svc.Send(ctx, "13800009999", "1.2.3.4"); err != nil {
		t.Fatalf("发送验证码失败: %v", err)
	}
	mr.FastForward(6 * time.Minute)
	if err := svc.Verify(ctx, "13800009999", sender.LastCodeAny()); !errors.Is(err, smscode.ErrInvalidCode) {
		t.Fatalf("验证码过期后应失效,实际 %v", err)
	}
}

func TestResendCooldown(t *testing.T) {
	svc, sender, mr := newService(t, 100, 100)
	ctx := context.Background()
	if err := svc.Send(ctx, "13800001111", "1.2.3.4"); err != nil {
		t.Fatalf("首次发送失败: %v", err)
	}
	if err := svc.Send(ctx, "13800001111", "1.2.3.4"); !errors.Is(err, smscode.ErrTooFrequent) {
		t.Fatalf("60 秒内重复发送期望 ErrTooFrequent,实际 %v", err)
	}
	if len(sender.Calls()) != 1 {
		t.Fatalf("冷却期内不应重复发送,实际 %d 次", len(sender.Calls()))
	}
	mr.FastForward(61 * time.Second)
	if err := svc.Send(ctx, "13800001111", "1.2.3.4"); err != nil {
		t.Fatalf("冷却结束后应可重发: %v", err)
	}
}

func TestPhoneDailyLimit(t *testing.T) {
	svc, _, mr := newService(t, 2, 100)
	ctx := context.Background()
	for i := 0; i < 2; i++ {
		if err := svc.Send(ctx, "13800002222", "1.2.3.4"); err != nil {
			t.Fatalf("第 %d 次发送失败: %v", i+1, err)
		}
		mr.FastForward(61 * time.Second)
	}
	if err := svc.Send(ctx, "13800002222", "1.2.3.4"); !errors.Is(err, smscode.ErrDailyLimit) {
		t.Fatalf("超过每日上限期望 ErrDailyLimit,实际 %v", err)
	}
}

func TestIPDailyLimit(t *testing.T) {
	svc, _, _ := newService(t, 100, 2)
	ctx := context.Background()
	for _, phone := range []string{"13800003333", "13800004444"} {
		if err := svc.Send(ctx, phone, "9.9.9.9"); err != nil {
			t.Fatalf("发送到 %s 失败: %v", phone, err)
		}
	}
	if err := svc.Send(ctx, "13800005555", "9.9.9.9"); !errors.Is(err, smscode.ErrDailyLimit) {
		t.Fatalf("同 IP 超过每日上限期望 ErrDailyLimit,实际 %v", err)
	}
}

func TestUniversalCode(t *testing.T) {
	svc, sender, _ := newService(t, 5, 20)
	ctx := context.Background()

	// 未配置万能码时,888888 不可用。
	if err := svc.Verify(ctx, "13800007777", "888888"); !errors.Is(err, smscode.ErrInvalidCode) {
		t.Fatalf("未配置万能码时期望 ErrInvalidCode,实际 %v", err)
	}

	svc.UniversalCode = "888888"
	if err := svc.Send(ctx, "13800007777", "1.2.3.4"); err != nil {
		t.Fatalf("发送验证码失败: %v", err)
	}
	if err := svc.Verify(ctx, "13800007777", "888888"); err != nil {
		t.Fatalf("万能码应通过校验,实际 %v", err)
	}
	// 万能码不消耗真实验证码。
	if err := svc.Verify(ctx, "13800007777", sender.LastCodeAny()); err != nil {
		t.Fatalf("真实验证码仍应可用,实际 %v", err)
	}
}

func TestSenderFailureDoesNotCount(t *testing.T) {
	svc, sender, _ := newService(t, 2, 100)
	ctx := context.Background()
	sender.SetError(errors.New("sms gateway down"))
	if err := svc.Send(ctx, "13800006666", "1.2.3.4"); err == nil {
		t.Fatalf("期望发送失败")
	}
	// 发送失败不写验证码、不写冷却、不计数。
	if _, err := svc.PeekCodeHash(ctx, "13800006666"); !errors.Is(err, redis.Nil) {
		t.Fatalf("发送失败不应保存验证码,实际 %v", err)
	}
	sender.SetError(nil)
	if err := svc.Send(ctx, "13800006666", "1.2.3.4"); err != nil {
		t.Fatalf("发送恢复后应可立即重试: %v", err)
	}
	if got := len(sender.Calls()); got != 1 {
		t.Fatalf("期望 1 次成功发送,实际 %d", got)
	}
	if err := svc.Verify(ctx, "13800006666", sender.LastCodeAny()); err != nil {
		t.Fatalf("重试后的验证码应可用: %v", err)
	}
}

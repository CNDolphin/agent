package test

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"testing"
	"time"

	"mhagent/internal/apierr"
	"mhagent/internal/testenv"
)

func TestAuthLoginAndRefresh(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)

	access, refresh, isNew := mustLogin(t, env, base, "13800001234")
	if !isNew {
		t.Fatalf("首次登录 is_new 应为 true")
	}
	if got := balanceOf(t, base, access); got != 100 {
		t.Fatalf("首次登录应赠送 100 积分,实际 %d", got)
	}

	// 冷却结束后再次登录:不是新用户,不重复赠送。
	env.Redis.FastForward(61 * time.Second)
	code := mustSendCode(t, env, base, "13800001234")
	resp := do(t, http.MethodPost, base+"/auth/login",
		map[string]string{"phone": "13800001234", "code": code}, "", nil)
	resp.expect(t, http.StatusOK)
	m := resp.mapBody(t)
	if m["is_new"].(bool) {
		t.Fatalf("非首次登录 is_new 应为 false")
	}
	if got := balanceOf(t, base, m["access_token"].(string)); got != 100 {
		t.Fatalf("重复登录不应重复赠送,实际 %d", got)
	}

	// refresh token 可换取可用的 access token。
	resp = do(t, http.MethodPost, base+"/auth/refresh", map[string]string{"refresh_token": refresh}, "", nil)
	resp.expect(t, http.StatusOK)
	newAccess := resp.mapBody(t)["access_token"].(string)
	if got := balanceOf(t, base, newAccess); got != 100 {
		t.Fatalf("刷新后的令牌不可用")
	}
}

func TestAuthErrors(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)

	resp := do(t, http.MethodPost, base+"/auth/sms/send", map[string]string{"phone": "123"}, "", nil)
	resp.expect(t, http.StatusBadRequest)
	if resp.errorCode(t) != apierr.CodeBadRequest {
		t.Fatalf("非法手机号应 40001,实际 %d", resp.errorCode(t))
	}

	mustSendCode(t, env, base, "13800002345")
	resp = do(t, http.MethodPost, base+"/auth/login",
		map[string]string{"phone": "13800002345", "code": "000000"}, "", nil)
	resp.expect(t, http.StatusUnauthorized)
	if resp.errorCode(t) != apierr.CodeInvalidCode {
		t.Fatalf("错误验证码应 40102,实际 %d", resp.errorCode(t))
	}

	resp = do(t, http.MethodPost, base+"/auth/login", map[string]string{"phone": "13800002345"}, "", nil)
	resp.expect(t, http.StatusUnauthorized)
	if resp.errorCode(t) != apierr.CodeInvalidCode {
		t.Fatalf("缺少验证码应 40102,实际 %d", resp.errorCode(t))
	}

	resp = do(t, http.MethodPost, base+"/auth/refresh", map[string]string{"refresh_token": "bad"}, "", nil)
	resp.expect(t, http.StatusUnauthorized)
	if resp.errorCode(t) != apierr.CodeUnauthorized {
		t.Fatalf("非法 refresh token 应 40101,实际 %d", resp.errorCode(t))
	}

	resp = do(t, http.MethodGet, base+"/credits/balance", nil, "", nil)
	resp.expect(t, http.StatusUnauthorized)
	if resp.errorCode(t) != apierr.CodeUnauthorized {
		t.Fatalf("未登录应 40101,实际 %d", resp.errorCode(t))
	}
}

func TestDeleteAccountAndCooldown(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)

	access, _, _ := mustLogin(t, env, base, "13800006789")
	resp := do(t, http.MethodDelete, base+"/account", nil, access, nil)
	resp.expect(t, http.StatusNoContent)

	// 注销后旧令牌失效。
	resp = do(t, http.MethodGet, base+"/credits/balance", nil, access, nil)
	resp.expect(t, http.StatusUnauthorized)

	if n := countDB(t, env.DB, `SELECT count(*) FROM credit_accounts`); n != 0 {
		t.Fatalf("注销后积分账户应删除,实际 %d", n)
	}
	if n := countDB(t, env.DB, `SELECT count(*) FROM users WHERE deleted_at IS NOT NULL`); n != 1 {
		t.Fatalf("注销应为软删除")
	}
	if n := countDB(t, env.DB, `SELECT count(*) FROM credit_ledger WHERE user_id<>0`); n != 0 {
		t.Fatalf("注销后账本应去标识,实际 %d 条仍带 user_id", n)
	}

	// 30 天内重新登录:is_new 为 true,但不重复赠送。
	env.Redis.FastForward(61 * time.Second)
	access2, _, isNew := mustLogin(t, env, base, "13800006789")
	if !isNew {
		t.Fatalf("重新登录应标记 is_new")
	}
	if got := balanceOf(t, base, access2); got != 0 {
		t.Fatalf("30 天内重新登录不应赠送,实际 %d", got)
	}

	// 再次注销,推进 31 天后登录应重新赠送。
	resp = do(t, http.MethodDelete, base+"/account", nil, access2, nil)
	resp.expect(t, http.StatusNoContent)
	env.Clock.Advance(31 * 24 * time.Hour)
	env.Redis.FastForward(61 * time.Second)
	access3, _, isNew := mustLogin(t, env, base, "13800006789")
	if !isNew {
		t.Fatalf("冷却期后登录应标记 is_new")
	}
	if got := balanceOf(t, base, access3); got != 100 {
		t.Fatalf("冷却期后应重新赠送 100,实际 %d", got)
	}
}

func TestCreditsBalanceAndLedger(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)
	access, _, _ := mustLogin(t, env, base, "13800003456")

	resp := do(t, http.MethodGet, base+"/credits/balance", nil, access, nil)
	resp.expect(t, http.StatusOK)
	m := resp.mapBody(t)
	if m["balance"].(float64) != 100 || m["held"].(float64) != 0 || m["available"].(float64) != 100 {
		t.Fatalf("余额字段不符: %v", m)
	}

	resp = do(t, http.MethodGet, base+"/credits/ledger", nil, access, nil)
	resp.expect(t, http.StatusOK)
	m = resp.mapBody(t)
	items := m["items"].([]any)
	if len(items) != 1 {
		t.Fatalf("注册后应有 1 条流水,实际 %d", len(items))
	}
	first := items[0].(map[string]any)
	if first["type"].(string) != "grant" || first["amount"].(float64) != 100 {
		t.Fatalf("流水内容不符: %v", first)
	}
	if _, ok := first["created_at"].(string); !ok {
		t.Fatalf("流水缺少 created_at")
	}

	resp = do(t, http.MethodGet, base+"/credits/ledger?limit=0", nil, access, nil)
	resp.expect(t, http.StatusBadRequest)
}

func TestChatNonStreamAndIdempotency(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)
	access, _, _ := mustLogin(t, env, base, "13800004567")
	enableModel(t, env, "deepseek-flash", 1, 2, 3, 1024)
	env.Upstream.Content = "回复"
	env.Upstream.Usage = upstreamUsage(100, 200, 300)

	resp := do(t, http.MethodPost, base+"/llm/chat", chatBody("deepseek-flash", "你好世界", false), access,
		map[string]string{"X-Request-Id": reqIDA})
	resp.expect(t, http.StatusOK)
	m := resp.mapBody(t)
	if m["content"].(string) != "回复" {
		t.Fatalf("正文不符: %v", m["content"])
	}
	usage := m["usage"].(map[string]any)
	if usage["input_hit"].(float64) != 100 || usage["input_miss"].(float64) != 200 || usage["output"].(float64) != 300 {
		t.Fatalf("usage 不符: %v", usage)
	}
	// (100*1 + 200*2 + 300*3) / 1e6 = 0.0014 -> 向上取整 1。
	if m["cost"].(float64) != 1 || m["balance"].(float64) != 99 || m["low_balance"].(bool) {
		t.Fatalf("计费结果不符: %v", m)
	}
	if len(env.Upstream.Calls()) != 1 {
		t.Fatalf("上游应被调用 1 次")
	}
	call := env.Upstream.Calls()[0]
	if call.MaxTokens != 128 || call.Thinking != "disabled" || len(call.UserTag) != 24 {
		t.Fatalf("上游请求字段不符: %+v", call)
	}

	// 同一 X-Request-Id 重复提交:409 且带首次 cost,不重复扣费。
	resp = do(t, http.MethodPost, base+"/llm/chat", chatBody("deepseek-flash", "你好世界", false), access,
		map[string]string{"X-Request-Id": reqIDA})
	resp.expect(t, http.StatusConflict)
	if resp.errorCode(t) != apierr.CodeDuplicateRequest {
		t.Fatalf("重复请求应 40901,实际 %d", resp.errorCode(t))
	}
	if resp.mapBody(t)["cost"].(float64) != 1 {
		t.Fatalf("409 应附带首次 cost=1: %s", string(resp.body))
	}
	if got := balanceOf(t, base, access); got != 99 {
		t.Fatalf("重复请求不应重复扣费,余额 %d", got)
	}
	if n := countDB(t, env.DB, `SELECT count(*) FROM usage_logs`); n != 1 {
		t.Fatalf("usage_logs 应只有 1 条,实际 %d", n)
	}
}

func TestChatValidationAndFailures(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)
	access, _, _ := mustLogin(t, env, base, "13800005678")

	// 缺少 X-Request-Id。
	resp := do(t, http.MethodPost, base+"/llm/chat", chatBody("deepseek-flash", "hi", false), access, nil)
	resp.expect(t, http.StatusBadRequest)
	if resp.errorCode(t) != apierr.CodeBadRequest {
		t.Fatalf("缺少 X-Request-Id 应 40001,实际 %d", resp.errorCode(t))
	}

	// 模型未启用。
	resp = do(t, http.MethodPost, base+"/llm/chat", chatBody("deepseek-v4-pro", "hi", false), access,
		map[string]string{"X-Request-Id": reqIDB})
	resp.expect(t, http.StatusBadRequest)
	if resp.errorCode(t) != apierr.CodeBadRequest {
		t.Fatalf("未启用模型应 40001,实际 %d", resp.errorCode(t))
	}

	enableModel(t, env, "deepseek-flash", 1, 2, 3, 512)

	// max_tokens 超过上限被截断。
	body := chatBody("deepseek-flash", "hi", false)
	body["max_tokens"] = 9999
	resp = do(t, http.MethodPost, base+"/llm/chat", body, access, map[string]string{"X-Request-Id": reqIDC})
	resp.expect(t, http.StatusOK)
	if got := env.Upstream.Calls()[len(env.Upstream.Calls())-1].MaxTokens; got != 512 {
		t.Fatalf("max_tokens 应被截断为 512,实际 %d", got)
	}

	// 积分不足。
	enableModel(t, env, "deepseek-flash", 0, 0, 1_000_000, 4096)
	body = chatBody("deepseek-flash", "hi", false)
	body["max_tokens"] = 4096
	resp = do(t, http.MethodPost, base+"/llm/chat", body, access, map[string]string{"X-Request-Id": reqIDD})
	resp.expect(t, http.StatusPaymentRequired)
	if resp.errorCode(t) != apierr.CodeInsufficient {
		t.Fatalf("积分不足应 40201,实际 %d", resp.errorCode(t))
	}

	// 上游故障:502,冻结被释放。
	enableModel(t, env, "deepseek-flash", 1, 2, 3, 1024)
	env.Upstream.Err = errors.New("upstream down")
	resp = do(t, http.MethodPost, base+"/llm/chat", chatBody("deepseek-flash", "hi", false), access,
		map[string]string{"X-Request-Id": "eeeeeeee-5555-4555-8555-555555555555"})
	resp.expect(t, http.StatusBadGateway)
	if resp.errorCode(t) != apierr.CodeUpstream {
		t.Fatalf("上游故障应 50201,实际 %d", resp.errorCode(t))
	}
	resp = do(t, http.MethodGet, base+"/credits/balance", nil, access, nil)
	resp.expect(t, http.StatusOK)
	if m := resp.mapBody(t); m["held"].(float64) != 0 || m["balance"].(float64) != 100 {
		t.Fatalf("上游失败后应释放冻结: %v", m)
	}
}

func TestChatStream(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)
	access, _, _ := mustLogin(t, env, base, "13800007890")
	enableModel(t, env, "deepseek-flash", 1, 2, 3, 1024)
	env.Upstream.Chunks = []string{"你", "好"}
	env.Upstream.Usage = upstreamUsage(100, 200, 300)

	resp := do(t, http.MethodPost, base+"/llm/chat", chatBody("deepseek-flash", "你好世界", true), access,
		map[string]string{"X-Request-Id": reqIDA})
	resp.expect(t, http.StatusOK)
	if ct := resp.header.Get("Content-Type"); !strings.Contains(ct, "text/event-stream") {
		t.Fatalf("流式 Content-Type 错误: %s", ct)
	}
	events := sseEvents(string(resp.body))
	deltas := eventsByName(events, "delta")
	if len(deltas) != 2 {
		t.Fatalf("期望 2 个 delta 事件,实际 %d: %s", len(deltas), string(resp.body))
	}
	for i, want := range []string{"你", "好"} {
		var d map[string]any
		if err := jsonUnmarshal(deltas[i]["data"], &d); err != nil || d["text"] != want {
			t.Fatalf("delta[%d] 不符: %v %v", i, d, err)
		}
	}
	dones := eventsByName(events, "done")
	if len(dones) != 1 {
		t.Fatalf("应有 1 个 done 事件,实际 %d", len(dones))
	}
	var done map[string]any
	_ = jsonUnmarshal(dones[0]["data"], &done)
	if done["cost"].(float64) != 1 || done["balance"].(float64) != 99 {
		t.Fatalf("done 计费不符: %v", done)
	}
	usage := done["usage"].(map[string]any)
	if usage["output"].(float64) != 300 {
		t.Fatalf("done usage 不符: %v", usage)
	}

	if n := countDB(t, env.DB, `SELECT count(*) FROM usage_logs WHERE partial=false`); n != 1 {
		t.Fatalf("应写入 1 条非部分结算记录,实际 %d", n)
	}
}

func TestChatStreamPartialSettlement(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)
	access, _, _ := mustLogin(t, env, base, "13800008901")
	enableModel(t, env, "deepseek-flash", 0, 1_000_000, 0, 1024)
	env.Upstream.Chunks = []string{"部分"}
	env.Upstream.Usage = upstreamUsage(0, 0, 0)
	env.Upstream.StreamErr = errors.New("stream broke")
	env.Upstream.FailAfterChunks = 1

	resp := do(t, http.MethodPost, base+"/llm/chat", chatBody("deepseek-flash", "你好", true), access,
		map[string]string{"X-Request-Id": reqIDB})
	resp.expect(t, http.StatusOK)
	events := sseEvents(string(resp.body))
	if len(eventsByName(events, "delta")) != 1 {
		t.Fatalf("应输出 1 个 delta: %s", string(resp.body))
	}
	errEvents := eventsByName(events, "error")
	if len(errEvents) != 1 {
		t.Fatalf("应输出 error 事件: %s", string(resp.body))
	}
	var e map[string]any
	_ = jsonUnmarshal(errEvents[0]["data"], &e)
	if e["code"].(float64) != float64(apierr.CodeUpstream) {
		t.Fatalf("error 事件应为 50201: %v", e)
	}

	var partial bool
	var cost, out int64
	if err := env.DB.QueryRow(`SELECT partial, cost, out_tokens FROM usage_logs ORDER BY id DESC LIMIT 1`).
		Scan(&partial, &cost, &out); err != nil {
		t.Fatalf("读取 usage_logs 失败: %v", err)
	}
	if !partial || cost != 2 || out != 2 {
		t.Fatalf("部分结算应按估算记为 partial cost=2 out=2,实际 partial=%v cost=%d out=%d", partial, cost, out)
	}
	if got := balanceOf(t, base, access); got != 98 {
		t.Fatalf("部分结算后余额应为 98,实际 %d", got)
	}

	// 重复 X-Request-Id 返回 409 且带首次 cost。
	resp = do(t, http.MethodPost, base+"/llm/chat", chatBody("deepseek-flash", "你好", true), access,
		map[string]string{"X-Request-Id": reqIDB})
	resp.expect(t, http.StatusConflict)
	if resp.mapBody(t)["cost"].(float64) != 2 {
		t.Fatalf("重复流式请求 cost 应为 2: %s", string(resp.body))
	}
}

func TestConsentAndNotify(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)
	access, _, _ := mustLogin(t, env, base, "13800009012")

	resp := do(t, http.MethodGet, base+"/consent/latest", nil, access, nil)
	resp.expect(t, http.StatusOK)
	if m := resp.mapBody(t); m["version"].(string) != "v1" || m["text"].(string) == "" {
		t.Fatalf("同意书信息不符: %v", m)
	}

	// 未签署最新同意书:40301。
	resp = do(t, http.MethodPost, base+"/notify/emergency", map[string]any{
		"channel": "sms", "to": "13900002222", "template_id": "crisis_contact_v1",
		"params": map[string]string{"nickname": "联系人"},
	}, access, nil)
	resp.expect(t, http.StatusForbidden)
	if resp.errorCode(t) != apierr.CodeConsentRequired {
		t.Fatalf("未签署应 40301,实际 %d", resp.errorCode(t))
	}

	resp = do(t, http.MethodPost, base+"/consent", map[string]string{"version": "v0"}, access, nil)
	resp.expect(t, http.StatusBadRequest)
	resp = do(t, http.MethodPost, base+"/consent", map[string]string{"version": "v1"}, access, nil)
	resp.expect(t, http.StatusNoContent)

	// 发送成功,记录中不含接收人与参数。
	const marker = "NOTIFY-PRIVATE-MARKER"
	resp = do(t, http.MethodPost, base+"/notify/emergency", map[string]any{
		"channel": "sms", "to": "139 0000 2222", "template_id": "crisis_contact_v1",
		"params": map[string]string{"nickname": marker},
	}, access, nil)
	resp.expect(t, http.StatusOK)
	m := resp.mapBody(t)
	if m["status"].(string) != "sent" || m["notify_id"].(string) == "" {
		t.Fatalf("通知结果不符: %v", m)
	}
	if n := countDB(t, env.DB, `SELECT count(*) FROM notify_logs WHERE channel='sms' AND template_id='crisis_contact_v1' AND status='sent'`); n != 1 {
		t.Fatalf("notify_logs 应记录 1 条,实际 %d", n)
	}
	if dumpContains(t, env.DB, "notify_logs", marker) || dumpContains(t, env.DB, "notify_logs", "13900002222") {
		t.Fatalf("notify_logs 不应保存接收人或参数值")
	}
	for _, key := range env.Redis.Keys() {
		val, _ := env.Redis.Get(key)
		if strings.Contains(key, "13900002222") || strings.Contains(val, "13900002222") ||
			strings.Contains(key, marker) || strings.Contains(val, marker) {
			t.Fatalf("Redis 中出现明文接收人或参数: %s=%s", key, val)
		}
	}

	// 同一用户每小时最多 3 次:第 4 次 429。
	for i := 0; i < 2; i++ {
		resp = do(t, http.MethodPost, base+"/notify/emergency", map[string]any{
			"channel": "sms", "to": "13900003333", "template_id": "crisis_contact_v1",
			"params": map[string]string{"nickname": "联系人"},
		}, access, nil)
		resp.expect(t, http.StatusOK)
	}
	resp = do(t, http.MethodPost, base+"/notify/emergency", map[string]any{
		"channel": "sms", "to": "13900004444", "template_id": "crisis_contact_v1",
		"params": map[string]string{"nickname": "联系人"},
	}, access, nil)
	resp.expect(t, http.StatusTooManyRequests)
	if resp.errorCode(t) != apierr.CodeRateLimited {
		t.Fatalf("超频应 42901,实际 %d", resp.errorCode(t))
	}

	// 未授权模板与非法渠道。
	resp = do(t, http.MethodPost, base+"/notify/emergency", map[string]any{
		"channel": "sms", "to": "13900005555", "template_id": "evil_template",
	}, access, nil)
	resp.expect(t, http.StatusBadRequest)
	resp = do(t, http.MethodPost, base+"/notify/emergency", map[string]any{
		"channel": "carrier-pigeon", "to": "x", "template_id": "crisis_contact_v1",
	}, access, nil)
	resp.expect(t, http.StatusBadRequest)
}

func TestChatStreamClientCancelSettles(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)
	access, _, _ := mustLogin(t, env, base, "13800011111")
	enableModel(t, env, "deepseek-flash", 0, 1_000_000, 0, 1024)
	for i := 0; i < 100; i++ {
		env.Upstream.Chunks = append(env.Upstream.Chunks, "x")
	}
	env.Upstream.Delay = 20 * time.Millisecond

	payload, err := json.Marshal(chatBody("deepseek-flash", "你好", true))
	if err != nil {
		t.Fatalf("序列化失败: %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, base+"/llm/chat", bytes.NewReader(payload))
	if err != nil {
		t.Fatalf("构造请求失败: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+access)
	req.Header.Set("X-Request-Id", reqIDC)
	resp, err := (&http.Client{Timeout: 10 * time.Second}).Do(req)
	if err != nil {
		t.Fatalf("发起流式请求失败: %v", err)
	}
	// 等上游输出若干分片后模拟客户端断开。
	time.Sleep(60 * time.Millisecond)
	cancel()
	_ = resp.Body.Close()

	// 断开后必须用独立上下文完成部分结算。
	deadline := time.Now().Add(3 * time.Second)
	var partial bool
	var cost int64
	for {
		err = env.DB.QueryRow(`SELECT partial, cost FROM usage_logs WHERE request_id=$1`, reqIDC).Scan(&partial, &cost)
		if err == nil {
			break
		}
		if !errors.Is(err, sql.ErrNoRows) {
			t.Fatalf("查询 usage_logs 失败: %v", err)
		}
		if time.Now().After(deadline) {
			t.Fatalf("客户端断开后未完成结算")
		}
		time.Sleep(20 * time.Millisecond)
	}
	if !partial || cost <= 0 {
		t.Fatalf("断开后应按部分结算入账,实际 partial=%v cost=%d", partial, cost)
	}
	if got := balanceOf(t, base, access); got >= 100 {
		t.Fatalf("断开后应扣减积分,实际余额 %d", got)
	}
}

func TestNotifyRecipientDailyLimit(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)
	var last apiResp
	for i := 0; i < 3; i++ {
		access, _, _ := mustLogin(t, env, base, "1380002000"+string(rune('1'+i)))
		do(t, http.MethodPost, base+"/consent", map[string]string{"version": "v1"}, access, nil).expect(t, http.StatusNoContent)
		last = do(t, http.MethodPost, base+"/notify/emergency", map[string]any{
			"channel": "sms", "to": "13900009999", "template_id": "crisis_contact_v1",
			"params": map[string]string{"nickname": "联系人"},
		}, access, nil)
		last.expect(t, http.StatusOK)
	}
	// 第 4 个用户向同一接收方发送:触发接收方每日上限。
	access, _, _ := mustLogin(t, env, base, "13800020004")
	do(t, http.MethodPost, base+"/consent", map[string]string{"version": "v1"}, access, nil).expect(t, http.StatusNoContent)
	resp := do(t, http.MethodPost, base+"/notify/emergency", map[string]any{
		"channel": "sms", "to": "13900009999", "template_id": "crisis_contact_v1",
		"params": map[string]string{"nickname": "联系人"},
	}, access, nil)
	resp.expect(t, http.StatusTooManyRequests)
	if resp.errorCode(t) != apierr.CodeRateLimited {
		t.Fatalf("接收方超频应 42901,实际 %d", resp.errorCode(t))
	}
}

func TestNotifyEmailAndFailure(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)
	access, _, _ := mustLogin(t, env, base, "13800010123")
	do(t, http.MethodPost, base+"/consent", map[string]string{"version": "v1"}, access, nil).expect(t, http.StatusNoContent)

	env.Notifier.SetError(errors.New("mail down"))
	resp := do(t, http.MethodPost, base+"/notify/emergency", map[string]any{
		"channel": "email", "to": "Guardian@Example.com", "template_id": "crisis_contact_v1",
		"params": map[string]string{"nickname": "联系人"},
	}, access, nil)
	resp.expect(t, http.StatusOK)
	if m := resp.mapBody(t); m["status"].(string) != "failed" {
		t.Fatalf("发送失败应记录 failed: %v", m)
	}
	if n := countDB(t, env.DB, `SELECT count(*) FROM notify_logs WHERE status='failed'`); n != 1 {
		t.Fatalf("应记录 1 条失败通知,实际 %d", n)
	}

	env.Notifier.SetError(nil)
	resp = do(t, http.MethodPost, base+"/notify/emergency", map[string]any{
		"channel": "email", "to": "guardian@example.com", "template_id": "crisis_contact_v1",
		"params": map[string]string{"nickname": "联系人"},
	}, access, nil)
	resp.expect(t, http.StatusOK)
	if m := resp.mapBody(t); m["status"].(string) != "sent" {
		t.Fatalf("恢复后应发送成功: %v", m)
	}
}

func TestPasswordRegisterLoginAndReset(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)

	const phone = "13900001111"
	const password = "Passw0rd!"
	const newPassword = "NewPassw0rd!"

	// 注册:验证码 + 密码,首次赠送积分。
	code := mustSendCode(t, env, base, phone)
	resp := do(t, http.MethodPost, base+"/auth/register",
		map[string]string{"phone": phone, "code": code, "password": password}, "", nil)
	resp.expect(t, http.StatusOK)
	m := resp.mapBody(t)
	if !m["is_new"].(bool) {
		t.Fatalf("首次注册 is_new 应为 true")
	}
	if got := balanceOf(t, base, m["access_token"].(string)); got != 100 {
		t.Fatalf("首次注册应赠送 100 积分,实际 %d", got)
	}

	// 手机号 + 密码登录。
	resp = do(t, http.MethodPost, base+"/auth/login/password",
		map[string]string{"phone": phone, "password": password}, "", nil)
	resp.expect(t, http.StatusOK)
	if resp.mapBody(t)["access_token"].(string) == "" {
		t.Fatalf("密码登录应返回 access_token")
	}

	// 错误密码。
	resp = do(t, http.MethodPost, base+"/auth/login/password",
		map[string]string{"phone": phone, "password": "wrong-password"}, "", nil)
	resp.expect(t, http.StatusUnauthorized)
	if resp.errorCode(t) != apierr.CodeWrongPassword {
		t.Fatalf("错误密码应 40104,实际 %d", resp.errorCode(t))
	}

	// 弱密码。
	env.Redis.FastForward(61 * time.Second)
	code = mustSendCode(t, env, base, phone)
	resp = do(t, http.MethodPost, base+"/auth/register",
		map[string]string{"phone": phone, "code": code, "password": "123"}, "", nil)
	resp.expect(t, http.StatusBadRequest)

	// 重复注册。
	env.Redis.FastForward(61 * time.Second)
	code = mustSendCode(t, env, base, phone)
	resp = do(t, http.MethodPost, base+"/auth/register",
		map[string]string{"phone": phone, "code": code, "password": password}, "", nil)
	resp.expect(t, http.StatusConflict)
	if resp.errorCode(t) != apierr.CodeAlreadyRegister {
		t.Fatalf("重复注册应 40902,实际 %d", resp.errorCode(t))
	}

	// 历史账号(仅验证码登录,无密码)登录应提示补设密码。
	legacyPhone := "13900002222"
	mustLogin(t, env, base, legacyPhone)
	resp = do(t, http.MethodPost, base+"/auth/login/password",
		map[string]string{"phone": legacyPhone, "password": password}, "", nil)
	resp.expect(t, http.StatusConflict)
	if resp.errorCode(t) != apierr.CodePasswordRequired {
		t.Fatalf("未设密码应 40105,实际 %d", resp.errorCode(t))
	}

	// 验证码重置密码后,旧密码失效、新密码可用。
	env.Redis.FastForward(61 * time.Second)
	code = mustSendCode(t, env, base, phone)
	resp = do(t, http.MethodPost, base+"/auth/password/reset",
		map[string]string{"phone": phone, "code": code, "new_password": newPassword}, "", nil)
	resp.expect(t, http.StatusNoContent)

	resp = do(t, http.MethodPost, base+"/auth/login/password",
		map[string]string{"phone": phone, "password": password}, "", nil)
	resp.expect(t, http.StatusUnauthorized)
	resp = do(t, http.MethodPost, base+"/auth/login/password",
		map[string]string{"phone": phone, "password": newPassword}, "", nil)
	resp.expect(t, http.StatusOK)
}


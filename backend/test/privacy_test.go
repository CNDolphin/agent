package test

import (
	"bytes"
	"net/http"
	"strings"
	"sync"
	"testing"

	"github.com/zeromicro/go-zero/core/logx"

	"mhagent/internal/testenv"
)

const privateMarker = "PRIVATE-MARKER-xyz"

type syncBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (b *syncBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

func (b *syncBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.String()
}

// TestEndToEndAndPrivacy 跑通完整链路并逐表、逐日志断言无隐私数据。
func TestEndToEndAndPrivacy(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)

	// 捕获服务日志,断言其中不含正文/联系人。
	oldWriter := logx.Reset()
	logs := &syncBuffer{}
	logx.SetWriter(logx.NewWriter(logs))
	t.Cleanup(func() {
		logx.Reset()
		if oldWriter != nil {
			logx.SetWriter(oldWriter)
		}
	})

	insertAdmin(t, env.DB, "root", "super", "root-pass")
	superToken, _ := adminLogin(t, base, "root", "root-pass")
	pkgID := createPackage(t, base, superToken, 100, true)

	access, _, _ := mustLogin(t, env, base, "13800001111")
	enableModel(t, env, "deepseek-flash", 1, 2, 3, 1024)
	env.Upstream.Content = privateMarker
	env.Upstream.Usage = upstreamUsage(100, 200, 300)

	// 非流式对话(正文含私密标记)。
	resp := do(t, http.MethodPost, base+"/llm/chat",
		chatBody("deepseek-flash", privateMarker, false), access,
		map[string]string{"X-Request-Id": reqIDA})
	resp.expect(t, http.StatusOK)
	if !strings.Contains(string(resp.body), privateMarker) {
		t.Fatalf("响应应回传上游正文")
	}

	// 流式对话(分片含私密标记)。
	env.Upstream.Chunks = []string{privateMarker}
	env.Upstream.Usage = upstreamUsage(1, 2, 3)
	resp = do(t, http.MethodPost, base+"/llm/chat",
		chatBody("deepseek-flash", "流式"+privateMarker, true), access,
		map[string]string{"X-Request-Id": reqIDB})
	resp.expect(t, http.StatusOK)
	if !strings.Contains(string(resp.body), privateMarker) {
		t.Fatalf("流式响应应包含分片正文")
	}

	// 同意书 + 紧急通知(参数与接收人含隐私数据)。
	do(t, http.MethodPost, base+"/consent", map[string]string{"version": "v1"}, access, nil).expect(t, http.StatusNoContent)
	resp = do(t, http.MethodPost, base+"/notify/emergency", map[string]any{
		"channel": "sms", "to": "139 0000 1111", "template_id": "crisis_contact_v1",
		"params": map[string]string{"nickname": privateMarker},
	}, access, nil)
	resp.expect(t, http.StatusOK)

	// 套餐下单 + 支付回调。
	orderID := createOrder(t, base, access, pkgID, "mock")
	payMock(t, base, orderID, "trade-e2e").expect(t, http.StatusOK)
	if got := balanceOf(t, base, access); got != 198 {
		t.Fatalf("完整链路后余额应为 198,实际 %d", got)
	}

	// 用户注销后账本去标识,但隐私数据仍然不允许落库。
	do(t, http.MethodDelete, base+"/account", nil, access, nil).expect(t, http.StatusNoContent)

	// 1) 逐表断言:任何表都不包含正文标记或明文接收人手机号。
	rows, err := env.DB.Query(`SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_type='BASE TABLE'`)
	if err != nil {
		t.Fatalf("列出表失败: %v", err)
	}
	var tables []string
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			t.Fatalf("读取表名失败: %v", err)
		}
		tables = append(tables, name)
	}
	rows.Close()
	if len(tables) < 12 {
		t.Fatalf("迁移表数量异常: %d", len(tables))
	}
	for _, table := range tables {
		if dumpContains(t, env.DB, table, privateMarker) {
			t.Fatalf("表 %s 中出现消息正文标记", table)
		}
		if dumpContains(t, env.DB, table, "13900001111") {
			t.Fatalf("表 %s 中出现明文手机号", table)
		}
	}

	// 2) Redis 中不得出现明文标记或手机号。
	for _, key := range env.Redis.Keys() {
		val, _ := env.Redis.Get(key)
		if strings.Contains(key, privateMarker) || strings.Contains(val, privateMarker) {
			t.Fatalf("Redis 中出现正文标记: %s=%s", key, val)
		}
		if strings.Contains(key, "13900001111") || strings.Contains(val, "13900001111") {
			t.Fatalf("Redis 中出现明文手机号: %s=%s", key, val)
		}
	}

	// 3) 服务日志中不得出现正文标记或明文接收人。
	logText := logs.String()
	if strings.Contains(logText, privateMarker) {
		t.Fatalf("服务日志中出现消息正文标记: %s", logText)
	}
	if strings.Contains(logText, "13900001111") {
		t.Fatalf("服务日志中出现明文手机号")
	}

	// 4) 单独确认关键表结构:usage_logs 只有 token 计量,notify_logs 不含接收人/参数。
	var usageCols string
	if err := env.DB.QueryRow(`SELECT string_agg(column_name, ',' ORDER BY ordinal_position)
		FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='usage_logs'`).Scan(&usageCols); err != nil {
		t.Fatalf("读取 usage_logs 列失败: %v", err)
	}
	for _, forbidden := range []string{"content", "message", "prompt", "text", "body"} {
		if strings.Contains(usageCols, forbidden) {
			t.Fatalf("usage_logs 不应有字段 %q: %s", forbidden, usageCols)
		}
	}
	var notifyCols string
	if err := env.DB.QueryRow(`SELECT string_agg(column_name, ',' ORDER BY ordinal_position)
		FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='notify_logs'`).Scan(&notifyCols); err != nil {
		t.Fatalf("读取 notify_logs 列失败: %v", err)
	}
	for _, forbidden := range []string{"to", "params", "recipient"} {
		if strings.Contains(notifyCols, forbidden) {
			t.Fatalf("notify_logs 不应有字段 %q: %s", forbidden, notifyCols)
		}
	}

	// 5) 审计 detail 只能是整数/枚举,不含自由文本。
	var auditDetail string
	if err := env.DB.QueryRow(`SELECT COALESCE(string_agg(detail::text, ' '),'') FROM audit_logs`).Scan(&auditDetail); err != nil {
		t.Fatalf("读取审计失败: %v", err)
	}
	if strings.Contains(auditDetail, privateMarker) {
		t.Fatalf("审计中出现正文标记: %s", auditDetail)
	}
}

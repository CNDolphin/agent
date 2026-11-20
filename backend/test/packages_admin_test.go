package test

import (
	"net/http"
	"strconv"
	"strings"
	"sync"
	"testing"

	"mhagent/internal/apierr"
	"mhagent/internal/testenv"
)

func createPackage(t *testing.T, base, adminToken string, credits int64, enabled bool) int64 {
	t.Helper()
	resp := do(t, http.MethodPost, base+"/admin/packages", map[string]any{
		"name": "测试套餐", "description": "用于测试", "price_cents": 1000,
		"credits": credits, "enabled": enabled, "sort_order": 1,
	}, adminToken, nil)
	resp.expect(t, http.StatusOK)
	return int64(resp.mapBody(t)["id"].(float64))
}

func createOrder(t *testing.T, base, access string, packageID int64, channel string) int64 {
	t.Helper()
	resp := do(t, http.MethodPost, base+"/orders", map[string]any{
		"package_id": packageID, "channel": channel,
	}, access, nil)
	resp.expect(t, http.StatusOK)
	m := resp.mapBody(t)
	if m["status"].(string) != "pending" {
		t.Fatalf("新订单状态应为 pending: %v", m)
	}
	if _, ok := m["pay_params"].(map[string]any); !ok {
		t.Fatalf("下单应返回 pay_params: %v", m)
	}
	return int64(m["order_id"].(float64))
}

func payMock(t *testing.T, base string, orderID int64, tradeNo string) apiResp {
	t.Helper()
	return do(t, http.MethodPost, base+"/pay/callback/mock", map[string]any{
		"order_id": orderID, "trade_no": tradeNo, "status": "success",
	}, "", nil)
}

func TestPackagesAndOrders(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)
	insertAdmin(t, env.DB, "root", "super", "root-pass")
	superToken, _ := adminLogin(t, base, "root", "root-pass")

	pkgID := createPackage(t, base, superToken, 100, true)
	access, _, _ := mustLogin(t, env, base, "13800007654")

	resp := do(t, http.MethodGet, base+"/packages", nil, access, nil)
	resp.expect(t, http.StatusOK)
	items := resp.mapBody(t)["items"].([]any)
	if len(items) != 1 {
		t.Fatalf("应只返回 1 个已上架套餐,实际 %d", len(items))
	}
	p := items[0].(map[string]any)
	if int64(p["id"].(float64)) != pkgID || p["credits"].(float64) != 100 || p["price_cents"].(float64) != 1000 {
		t.Fatalf("套餐展示字段不符: %v", p)
	}
	if _, leaked := p["enabled"]; leaked {
		t.Fatalf("公开套餐不应暴露 enabled 字段")
	}

	orderID := createOrder(t, base, access, pkgID, "mock")
	resp = payMock(t, base, orderID, "trade-001")
	resp.expect(t, http.StatusOK)
	if got := balanceOf(t, base, access); got != 200 {
		t.Fatalf("支付成功后余额应为 200,实际 %d", got)
	}

	// 重复回调:幂等,不重复入账。
	resp = payMock(t, base, orderID, "trade-001")
	resp.expect(t, http.StatusOK)
	if got := balanceOf(t, base, access); got != 200 {
		t.Fatalf("重复回调不应重复入账,实际 %d", got)
	}
	if n := countDB(t, env.DB, `SELECT count(*) FROM credit_ledger WHERE request_id=$1`, "order:"+itoa(orderID)); n != 1 {
		t.Fatalf("订单入账流水应只有 1 条,实际 %d", n)
	}

	// 用户订单列表包含套餐快照与状态。
	resp = do(t, http.MethodGet, base+"/orders", nil, access, nil)
	resp.expect(t, http.StatusOK)
	orders := resp.mapBody(t)["items"].([]any)
	if len(orders) != 1 {
		t.Fatalf("应有 1 个订单,实际 %d", len(orders))
	}
	o := orders[0].(map[string]any)
	if o["status"].(string) != "credited" || o["package_name"].(string) != "测试套餐" || o["credits"].(float64) != 100 {
		t.Fatalf("订单快照不符: %v", o)
	}

	// 并发重复回调只入账一次。
	order2 := createOrder(t, base, access, pkgID, "mock")
	var wg sync.WaitGroup
	var mu sync.Mutex
	var okCount int
	for i := 0; i < 5; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			r := payMock(t, base, order2, "trade-00"+itoa(int64(i)))
			mu.Lock()
			if r.status == http.StatusOK {
				okCount++
			}
			mu.Unlock()
		}(i)
	}
	wg.Wait()
	if okCount == 0 {
		t.Fatalf("并发回调至少应有 1 次成功")
	}
	if got := balanceOf(t, base, access); got != 300 {
		t.Fatalf("并发回调应只入账一次,余额应为 300,实际 %d", got)
	}

	// 非法回调。
	resp = do(t, http.MethodPost, base+"/pay/callback/mock",
		map[string]any{"order_id": order2, "trade_no": "", "status": "success"}, "", nil)
	resp.expect(t, http.StatusBadRequest)
	resp = do(t, http.MethodPost, base+"/pay/callback/unknown",
		map[string]any{"order_id": order2, "trade_no": "x"}, "", nil)
	resp.expect(t, http.StatusBadRequest)

	// manual 渠道:管理员确认收款;ops 无权确认。
	manualOrder := createOrder(t, base, access, pkgID, "manual")
	insertAdmin(t, env.DB, "ops1", "ops", "ops-pass")
	opsToken, _ := adminLogin(t, base, "ops1", "ops-pass")
	resp = do(t, http.MethodPost, base+"/admin/orders/"+itoa(manualOrder)+"/confirm", nil, opsToken, nil)
	resp.expect(t, http.StatusForbidden)
	if resp.errorCode(t) != apierr.CodeConsentRequired {
		t.Fatalf("无权限应 40301,实际 %d", resp.errorCode(t))
	}
	resp = do(t, http.MethodPost, base+"/admin/orders/"+itoa(manualOrder)+"/confirm", nil, superToken, nil)
	resp.expect(t, http.StatusOK)
	if m := resp.mapBody(t); m["status"].(string) != "credited" {
		t.Fatalf("确认收款后应 credited: %v", m)
	}
	if got := balanceOf(t, base, access); got != 400 {
		t.Fatalf("manual 确认后余额应为 400,实际 %d", got)
	}
	// 重复确认幂等。
	resp = do(t, http.MethodPost, base+"/admin/orders/"+itoa(manualOrder)+"/confirm", nil, superToken, nil)
	resp.expect(t, http.StatusOK)
	if got := balanceOf(t, base, access); got != 400 {
		t.Fatalf("重复确认不应重复入账")
	}

	// 取消订单。
	cancelOrder := createOrder(t, base, access, pkgID, "mock")
	resp = do(t, http.MethodPost, base+"/admin/orders/"+itoa(cancelOrder)+"/cancel", nil, superToken, nil)
	resp.expect(t, http.StatusOK)
	if m := resp.mapBody(t); m["status"].(string) != "cancelled" {
		t.Fatalf("取消后状态应为 cancelled: %v", m)
	}
	resp = do(t, http.MethodPost, base+"/admin/orders/"+itoa(cancelOrder)+"/cancel", nil, superToken, nil)
	resp.expect(t, http.StatusOK)

	// 管理端订单查询支持状态过滤。
	resp = do(t, http.MethodGet, base+"/admin/orders?status=credited", nil, superToken, nil)
	resp.expect(t, http.StatusOK)
	if items := resp.mapBody(t)["items"].([]any); len(items) != 3 {
		t.Fatalf("credited 订单应有 3 个,实际 %d", len(items))
	}

	// 已取消订单不能确认收款。
	resp = do(t, http.MethodPost, base+"/admin/orders/"+itoa(cancelOrder)+"/confirm", nil, superToken, nil)
	resp.expect(t, http.StatusBadRequest)

	// 下架套餐不再出现在公开列表,新订单不可用。
	resp = do(t, http.MethodPut, base+"/admin/packages/"+itoa(pkgID), map[string]any{"enabled": false}, superToken, nil)
	resp.expect(t, http.StatusOK)
	resp = do(t, http.MethodGet, base+"/packages", nil, access, nil)
	resp.expect(t, http.StatusOK)
	if items := resp.mapBody(t)["items"].([]any); len(items) != 0 {
		t.Fatalf("下架后公开列表应为空,实际 %d", len(items))
	}
	resp = do(t, http.MethodPost, base+"/orders", map[string]any{"package_id": pkgID, "channel": "mock"}, access, nil)
	resp.expect(t, http.StatusBadRequest)
}

func TestAdminAPI(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)
	insertAdmin(t, env.DB, "root", "super", "root-pass")
	insertAdmin(t, env.DB, "ops1", "ops", "ops-pass")
	superToken, superRole := adminLogin(t, base, "root", "root-pass")
	if superRole != "super" {
		t.Fatalf("角色不符: %s", superRole)
	}
	opsToken, _ := adminLogin(t, base, "ops1", "ops-pass")

	resp := do(t, http.MethodPost, base+"/admin/auth/login",
		map[string]string{"username": "root", "password": "bad"}, "", nil)
	resp.expect(t, http.StatusUnauthorized)

	// 价格查询对 ops 开放。
	resp = do(t, http.MethodGet, base+"/admin/prices", nil, opsToken, nil)
	resp.expect(t, http.StatusOK)
	items := resp.mapBody(t)["items"].([]any)
	if len(items) != 2 {
		t.Fatalf("应有 2 个种子模型,实际 %d", len(items))
	}

	// ops 不能改价。
	resp = do(t, http.MethodPut, base+"/admin/prices/deepseek-flash",
		map[string]any{"out_per_m": 3, "reason": "测试"}, opsToken, nil)
	resp.expect(t, http.StatusForbidden)

	// 改价必须填写 reason。
	resp = do(t, http.MethodPut, base+"/admin/prices/deepseek-flash",
		map[string]any{"out_per_m": 3}, superToken, nil)
	resp.expect(t, http.StatusBadRequest)

	resp = do(t, http.MethodPut, base+"/admin/prices/deepseek-flash", map[string]any{
		"in_hit_per_m": 1, "in_miss_per_m": 2, "out_per_m": 3,
		"max_tokens_cap": 1024, "enabled": true, "reason": "初始化测试价格",
	}, superToken, nil)
	resp.expect(t, http.StatusOK)
	m := resp.mapBody(t)
	if m["version"].(float64) != 3 || m["enabled"].(bool) != true {
		t.Fatalf("改价结果不符: %v", m)
	}
	if n := countDB(t, env.DB, `SELECT count(*) FROM model_price_history WHERE model='deepseek-flash' AND version=3 AND reason='初始化测试价格'`); n != 1 {
		t.Fatalf("应写入 1 条改价历史,实际 %d", n)
	}
	if n := countDB(t, env.DB, `SELECT count(*) FROM audit_logs WHERE event='price.update'`); n != 1 {
		t.Fatalf("应写入 1 条改价审计,实际 %d", n)
	}

	// 改价立即生效:对话按新价扣费。
	access, _, _ := mustLogin(t, env, base, "13800008888")
	env.Upstream.Content = "回复"
	env.Upstream.Usage = upstreamUsage(100, 200, 300)
	resp = do(t, http.MethodPost, base+"/llm/chat", chatBody("deepseek-flash", "你好", false), access,
		map[string]string{"X-Request-Id": reqIDA})
	resp.expect(t, http.StatusOK)
	if m := resp.mapBody(t); m["cost"].(float64) != 1 || m["balance"].(float64) != 99 {
		t.Fatalf("按新价计费结果不符: %v", m)
	}

	// 积分发放:ops 禁止,super 允许且幂等。
	grantBody := map[string]any{
		"phone": "13800008888", "amount": 100, "reason": "测试发放", "request_id": "grant-1",
	}
	resp = do(t, http.MethodPost, base+"/admin/credits/grant", grantBody, opsToken, nil)
	resp.expect(t, http.StatusForbidden)
	resp = do(t, http.MethodPost, base+"/admin/credits/grant", grantBody, superToken, nil)
	resp.expect(t, http.StatusOK)
	if m := resp.mapBody(t); m["balance"].(float64) != 199 || m["held"].(float64) != 0 {
		t.Fatalf("发放后余额不符: %v", m)
	}
	resp = do(t, http.MethodPost, base+"/admin/credits/grant", grantBody, superToken, nil)
	resp.expect(t, http.StatusOK)
	if got := balanceOf(t, base, access); got != 199 {
		t.Fatalf("重复 request_id 发放应幂等,余额 %d", got)
	}
	grantBody["request_id"] = "grant-2"
	grantBody["amount"] = 50
	resp = do(t, http.MethodPost, base+"/admin/credits/grant", grantBody, superToken, nil)
	resp.expect(t, http.StatusOK)
	if got := balanceOf(t, base, access); got != 249 {
		t.Fatalf("第二次发放后余额应为 249,实际 %d", got)
	}

	// 发放参数校验。
	for _, bad := range []map[string]any{
		{"phone": "13800008888", "user_id": 1, "amount": 10, "reason": "x", "request_id": "g-bad1"},
		{"phone": "13800008888", "amount": 0, "reason": "x", "request_id": "g-bad2"},
		{"phone": "13800008888", "amount": 10, "reason": "", "request_id": "g-bad3"},
		{"phone": "13900000000", "amount": 10, "reason": "x", "request_id": "g-bad4"},
	} {
		resp = do(t, http.MethodPost, base+"/admin/credits/grant", bad, superToken, nil)
		resp.expect(t, http.StatusBadRequest)
	}

	// 用户查询只返回脱敏手机号。
	resp = do(t, http.MethodGet, base+"/admin/users?phone=13800008888", nil, superToken, nil)
	resp.expect(t, http.StatusOK)
	if strings.Contains(string(resp.body), "13800008888") {
		t.Fatalf("用户查询泄露明文手机号: %s", string(resp.body))
	}
	users := resp.mapBody(t)["items"].([]any)
	if len(users) != 1 {
		t.Fatalf("应查到 1 个用户,实际 %d", len(users))
	}
	u := users[0].(map[string]any)
	if u["phone_mask"].(string) != "138****8888" {
		t.Fatalf("脱敏手机号不符: %v", u)
	}
	uid := int64(u["id"].(float64))
	if u["balance"].(float64) != 249 {
		t.Fatalf("用户余额不符: %v", u)
	}

	// 用户流水。
	resp = do(t, http.MethodGet, base+"/admin/users/"+itoa(uid)+"/ledger", nil, superToken, nil)
	resp.expect(t, http.StatusOK)
	ledger := resp.mapBody(t)["items"].([]any)
	if len(ledger) < 1 {
		t.Fatalf("应返回用户流水")
	}

	// 用量汇总。
	resp = do(t, http.MethodGet, base+"/admin/usage/summary", nil, superToken, nil)
	resp.expect(t, http.StatusOK)
	rows := resp.mapBody(t)["items"].([]any)
	if len(rows) != 1 {
		t.Fatalf("应有 1 行用量汇总,实际 %d", len(rows))
	}
	row := rows[0].(map[string]any)
	if row["model"].(string) != "deepseek-flash" || row["requests"].(float64) != 1 ||
		row["out"].(float64) != 300 || row["cost"].(float64) != 1 {
		t.Fatalf("用量汇总不符: %v", row)
	}

	resp = do(t, http.MethodGet, base+"/admin/usage/summary?from=bad", nil, superToken, nil)
	resp.expect(t, http.StatusBadRequest)

	// 通知记录:签署同意书后发送一次。
	do(t, http.MethodPost, base+"/consent", map[string]string{"version": "v1"}, access, nil).expect(t, http.StatusNoContent)
	resp = do(t, http.MethodPost, base+"/notify/emergency", map[string]any{
		"channel": "sms", "to": "13900002222", "template_id": "crisis_contact_v1",
		"params": map[string]string{"nickname": "联系人"},
	}, access, nil)
	resp.expect(t, http.StatusOK)

	resp = do(t, http.MethodGet, base+"/admin/notify-logs", nil, superToken, nil)
	resp.expect(t, http.StatusOK)
	logs := resp.mapBody(t)["items"].([]any)
	if len(logs) != 1 {
		t.Fatalf("应有 1 条通知记录,实际 %d", len(logs))
	}
	if strings.Contains(string(resp.body), "13900002222") {
		t.Fatalf("通知记录泄露接收人: %s", string(resp.body))
	}
}

// itoa 转换 int64 为字符串。
func itoa(v int64) string { return strconv.FormatInt(v, 10) }

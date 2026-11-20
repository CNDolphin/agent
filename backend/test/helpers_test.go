package test

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"

	"golang.org/x/crypto/bcrypt"

	"mhagent/internal/testenv"
	"mhagent/internal/upstream"
)

const (
	reqIDA = "aaaaaaaa-1111-4111-8111-111111111111"
	reqIDB = "bbbbbbbb-2222-4222-8222-222222222222"
	reqIDC = "cccccccc-3333-4333-8333-333333333333"
	reqIDD = "dddddddd-4444-4444-8444-444444444444"
)

type apiResp struct {
	status int
	body   []byte
	header http.Header
}

func (r apiResp) mapBody(t *testing.T) map[string]any {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal(r.body, &m); err != nil {
		t.Fatalf("响应不是合法 JSON: %v (%s)", err, string(r.body))
	}
	return m
}

func (r apiResp) expect(t *testing.T, status int) {
	t.Helper()
	if r.status != status {
		t.Fatalf("期望 HTTP %d,实际 %d,响应: %s", status, r.status, string(r.body))
	}
}

func (r apiResp) errorCode(t *testing.T) int {
	t.Helper()
	return int(r.mapBody(t)["code"].(float64))
}

func do(t *testing.T, method, url string, payload any, token string, headers map[string]string) apiResp {
	t.Helper()
	var reader io.Reader
	if payload != nil {
		raw, err := json.Marshal(payload)
		if err != nil {
			t.Fatalf("序列化请求失败: %v", err)
		}
		reader = bytes.NewReader(raw)
	}
	req, err := http.NewRequest(method, url, reader)
	if err != nil {
		t.Fatalf("构造请求失败: %v", err)
	}
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	client := &http.Client{Timeout: 20 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		t.Fatalf("请求 %s %s 失败: %v", method, url, err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("读取响应失败: %v", err)
	}
	return apiResp{status: resp.StatusCode, body: raw, header: resp.Header}
}

// mustSendCode 发送验证码并返回 mock 收到的验证码。
func mustSendCode(t *testing.T, env *testenv.Env, base, phone string) string {
	t.Helper()
	resp := do(t, http.MethodPost, base+"/auth/sms/send", map[string]string{"phone": phone}, "", nil)
	resp.expect(t, http.StatusNoContent)
	return env.Sender.LastCodeAny()
}

// mustLogin 完成一次验证码登录,返回令牌对。
func mustLogin(t *testing.T, env *testenv.Env, base, phone string) (access, refresh string, isNew bool) {
	t.Helper()
	code := mustSendCode(t, env, base, phone)
	resp := do(t, http.MethodPost, base+"/auth/login", map[string]string{"phone": phone, "code": code}, "", nil)
	resp.expect(t, http.StatusOK)
	m := resp.mapBody(t)
	return m["access_token"].(string), m["refresh_token"].(string), m["is_new"].(bool)
}

func enableModel(t *testing.T, env *testenv.Env, model string, hit, miss, out int64, cap int) {
	t.Helper()
	if _, err := env.DB.Exec(
		`UPDATE model_prices SET in_hit_per_m=$2, in_miss_per_m=$3, out_per_m=$4, max_tokens_cap=$5,
		 enabled=true, thinking='disabled', updated_at=now() WHERE model=$1`,
		model, hit, miss, out, cap); err != nil {
		t.Fatalf("启用模型失败: %v", err)
	}
	env.SC.Prices.Invalidate()
}

func insertAdmin(t *testing.T, db *sql.DB, username, role, password string) int64 {
	t.Helper()
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.MinCost)
	if err != nil {
		t.Fatalf("生成密码哈希失败: %v", err)
	}
	var id int64
	if err := db.QueryRow(
		`INSERT INTO admin_users (username, password_hash, role) VALUES ($1,$2,$3) RETURNING id`,
		username, string(hash), role).Scan(&id); err != nil {
		t.Fatalf("插入管理员失败: %v", err)
	}
	return id
}

func adminLogin(t *testing.T, base, username, password string) (token, role string) {
	t.Helper()
	resp := do(t, http.MethodPost, base+"/admin/auth/login",
		map[string]string{"username": username, "password": password}, "", nil)
	resp.expect(t, http.StatusOK)
	m := resp.mapBody(t)
	return m["access_token"].(string), m["role"].(string)
}

func chatBody(model, content string, stream bool) map[string]any {
	return map[string]any{
		"model":      model,
		"messages":   []map[string]string{{"role": "user", "content": content}},
		"max_tokens": 128,
		"stream":     stream,
	}
}

func balanceOf(t *testing.T, base, access string) int64 {
	t.Helper()
	resp := do(t, http.MethodGet, base+"/credits/balance", nil, access, nil)
	resp.expect(t, http.StatusOK)
	return int64(resp.mapBody(t)["balance"].(float64))
}

// sseEvents 解析 SSE 响应中的 event/data 对。
func sseEvents(body string) []map[string]string {
	var out []map[string]string
	var cur map[string]string
	for _, line := range strings.Split(body, "\n") {
		switch {
		case strings.HasPrefix(line, "event: "):
			cur = map[string]string{"event": strings.TrimPrefix(line, "event: ")}
		case strings.HasPrefix(line, "data: "):
			if cur == nil {
				cur = map[string]string{}
			}
			cur["data"] = strings.TrimPrefix(line, "data: ")
			out = append(out, cur)
			cur = nil
		}
	}
	return out
}

func eventsByName(events []map[string]string, name string) []map[string]string {
	var out []map[string]string
	for _, e := range events {
		if e["event"] == name {
			out = append(out, e)
		}
	}
	return out
}

func countDB(t *testing.T, db *sql.DB, query string, args ...any) int {
	t.Helper()
	var n int
	if err := db.QueryRow(query, args...).Scan(&n); err != nil {
		t.Fatalf("统计失败: %v", err)
	}
	return n
}

func upstreamUsage(hit, miss, out int64) upstream.Usage {
	return upstream.Usage{InputHit: hit, InputMiss: miss, Output: out}
}

func jsonUnmarshal(raw string, v any) error {
	return json.Unmarshal([]byte(raw), v)
}

func dumpContains(t *testing.T, db *sql.DB, table, needle string) bool {
	t.Helper()
	var all string
	if err := db.QueryRow(
		fmt.Sprintf(`SELECT COALESCE(string_agg(row_to_json(t)::text, E'\n'),'') FROM %s t`, table),
	).Scan(&all); err != nil {
		t.Fatalf("导出表 %s 失败: %v", table, err)
	}
	return strings.Contains(all, needle)
}

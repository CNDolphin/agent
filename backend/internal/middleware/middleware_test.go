package middleware_test

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"mhagent/internal/apierr"
	"mhagent/internal/middleware"
	"mhagent/internal/testenv"
)

func insertUserRow(t *testing.T, env *testenv.Env, phoneHash string) int64 {
	t.Helper()
	var id int64
	if err := env.DB.QueryRow(
		`INSERT INTO users (phone_hash, phone_mask) VALUES ($1,'138****0000') RETURNING id`, phoneHash).Scan(&id); err != nil {
		t.Fatalf("插入用户失败: %v", err)
	}
	return id
}

func errorCode(t *testing.T, resp *httptest.ResponseRecorder) int {
	t.Helper()
	var body struct {
		Code int `json:"code"`
	}
	if err := json.Unmarshal(resp.Body.Bytes(), &body); err != nil {
		t.Fatalf("解析错误响应失败: %v (%s)", err, resp.Body.String())
	}
	return body.Code
}

func TestAuthMiddleware(t *testing.T) {
	env := testenv.New(t)
	uid := insertUserRow(t, env, "hash-mw")
	pair, err := env.SC.Tokens.IssueTokens(uid)
	if err != nil {
		t.Fatalf("签发令牌失败: %v", err)
	}
	next := func(w http.ResponseWriter, r *http.Request) {
		id, ok := apierr.UserID(r.Context())
		fmt.Fprintf(w, "%d:%v", id, ok)
	}
	handler := middleware.Auth(env.SC)(next)

	resp := httptest.NewRecorder()
	handler(resp, httptest.NewRequest(http.MethodGet, "/x", nil))
	if resp.Code != http.StatusUnauthorized || errorCode(t, resp) != apierr.CodeUnauthorized {
		t.Fatalf("缺少令牌应 40101,实际 %d %s", resp.Code, resp.Body.String())
	}

	resp = httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/x", nil)
	req.Header.Set("Authorization", "Bearer not-a-token")
	handler(resp, req)
	if resp.Code != http.StatusUnauthorized {
		t.Fatalf("非法令牌应 401,实际 %d", resp.Code)
	}

	resp = httptest.NewRecorder()
	req = httptest.NewRequest(http.MethodGet, "/x", nil)
	req.Header.Set("Authorization", "Bearer "+pair.AccessToken)
	handler(resp, req)
	if resp.Code != http.StatusOK || resp.Body.String() != fmt.Sprintf("%d:true", uid) {
		t.Fatalf("合法令牌应注入 userID,实际 %d %s", resp.Code, resp.Body.String())
	}

	// 已注销用户的旧令牌必须失效。
	if _, err := env.DB.Exec(`UPDATE users SET deleted_at=$2 WHERE id=$1`, uid, env.Clock.Now()); err != nil {
		t.Fatalf("注销失败: %v", err)
	}
	resp = httptest.NewRecorder()
	req = httptest.NewRequest(http.MethodGet, "/x", nil)
	req.Header.Set("Authorization", "Bearer "+pair.AccessToken)
	handler(resp, req)
	if resp.Code != http.StatusUnauthorized {
		t.Fatalf("已注销用户的令牌应 401,实际 %d", resp.Code)
	}
}

func TestRequestIDMiddleware(t *testing.T) {
	next := func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}
	required := middleware.RequestID(true)(next)

	resp := httptest.NewRecorder()
	required(resp, httptest.NewRequest(http.MethodPost, "/x", nil))
	if resp.Code != http.StatusBadRequest || errorCode(t, resp) != apierr.CodeBadRequest {
		t.Fatalf("缺少 X-Request-Id 应 40001,实际 %d %s", resp.Code, resp.Body.String())
	}

	resp = httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/x", nil)
	req.Header.Set("X-Request-Id", "not-a-uuid")
	required(resp, req)
	if resp.Code != http.StatusBadRequest {
		t.Fatalf("非 UUID 应 40001,实际 %d", resp.Code)
	}

	const valid = "11111111-2222-3333-4444-555555555555"
	resp = httptest.NewRecorder()
	req = httptest.NewRequest(http.MethodPost, "/x", nil)
	req.Header.Set("X-Request-Id", valid)
	required(resp, req)
	if resp.Code != http.StatusOK || resp.Header().Get("X-Request-Id") != valid {
		t.Fatalf("合法 UUID 应透传并回写,实际 %d %v", resp.Code, resp.Header())
	}

	// 非必填时自动生成。
	optional := middleware.RequestID(false)(next)
	resp = httptest.NewRecorder()
	optional(resp, httptest.NewRequest(http.MethodGet, "/x", nil))
	id := resp.Header().Get("X-Request-Id")
	if resp.Code != http.StatusOK || len(id) != 36 || strings.Count(id, "-") != 4 {
		t.Fatalf("非必填应生成 UUID,实际 %d %q", resp.Code, id)
	}
}

func TestRateLimitMiddleware(t *testing.T) {
	env := testenv.New(t)
	limit := middleware.RateLimit(env.SC.RDB, 2, func() time.Time { return env.Clock.Now() })(
		func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusOK) })

	withUser := func() *http.Request {
		r := httptest.NewRequest(http.MethodPost, "/x", nil)
		return r.WithContext(apierr.WithUserID(r.Context(), 42))
	}
	for i := 0; i < 2; i++ {
		resp := httptest.NewRecorder()
		limit(resp, withUser())
		if resp.Code != http.StatusOK {
			t.Fatalf("第 %d 次请求应放行,实际 %d", i+1, resp.Code)
		}
	}
	resp := httptest.NewRecorder()
	limit(resp, withUser())
	if resp.Code != http.StatusTooManyRequests || errorCode(t, resp) != apierr.CodeRateLimited {
		t.Fatalf("超过每分钟限制应 42901,实际 %d %s", resp.Code, resp.Body.String())
	}

	// 进入下一分钟窗口后恢复。
	env.Clock.Advance(time.Minute)
	resp = httptest.NewRecorder()
	limit(resp, withUser())
	if resp.Code != http.StatusOK {
		t.Fatalf("新窗口应放行,实际 %d", resp.Code)
	}
}

func TestAdminAuthMiddleware(t *testing.T) {
	env := testenv.New(t)
	token, _, err := env.SC.AdminTokens.Issue(9, "ops")
	if err != nil {
		t.Fatalf("签发管理员令牌失败: %v", err)
	}
	handler := middleware.AdminAuth(env.SC)(func(w http.ResponseWriter, r *http.Request) {
		admin, ok := apierr.GetAdmin(r.Context())
		fmt.Fprintf(w, "%d:%s:%v", admin.ID, admin.Role, ok)
	})

	resp := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/admin/x", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	handler(resp, req)
	if resp.Code != http.StatusOK || resp.Body.String() != "9:ops:true" {
		t.Fatalf("管理员令牌应注入角色,实际 %d %s", resp.Code, resp.Body.String())
	}

	// 用户令牌不能访问管理端。
	uid := insertUserRow(t, env, "hash-admin")
	pair, _ := env.SC.Tokens.IssueTokens(uid)
	resp = httptest.NewRecorder()
	req = httptest.NewRequest(http.MethodGet, "/admin/x", nil)
	req.Header.Set("Authorization", "Bearer "+pair.AccessToken)
	handler(resp, req)
	if resp.Code != http.StatusUnauthorized {
		t.Fatalf("用户令牌访问管理端应 401,实际 %d", resp.Code)
	}
}

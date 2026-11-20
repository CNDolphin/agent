// Package middleware 提供鉴权、请求 ID 与限流中间件。
package middleware

import (
	"database/sql"
	"errors"
	"net/http"
	"strings"

	"mhagent/internal/apierr"
	"mhagent/internal/svc"
)

// Auth 校验用户 access token,并把 userID 注入 context。
func Auth(sc *svc.ServiceContext) func(http.HandlerFunc) http.HandlerFunc {
	return func(next http.HandlerFunc) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			raw := bearer(r.Header.Get("Authorization"))
			if raw == "" {
				apierr.WriteError(w, apierr.Unauthorized("未登录或令牌无效"))
				return
			}
			userID, err := sc.Tokens.ParseAccess(raw)
			if err != nil {
				apierr.WriteError(w, apierr.Unauthorized("未登录或令牌无效"))
				return
			}
			// 已注销用户的旧令牌必须失效。
			var exists int
			if err := sc.DB.QueryRowContext(r.Context(),
				`SELECT 1 FROM users WHERE id=$1 AND deleted_at IS NULL`, userID).Scan(&exists); err != nil {
				if errors.Is(err, sql.ErrNoRows) {
					apierr.WriteError(w, apierr.Unauthorized("未登录或令牌无效"))
					return
				}
				apierr.WriteError(w, apierr.Internal())
				return
			}
			ctx := apierr.WithUserID(r.Context(), userID)
			next(w, r.WithContext(ctx))
		}
	}
}

func bearer(v string) string {
	parts := strings.SplitN(v, " ", 2)
	if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
		return ""
	}
	return strings.TrimSpace(parts[1])
}

// AdminAuth 校验管理员令牌,并把角色注入 context。
func AdminAuth(sc *svc.ServiceContext) func(http.HandlerFunc) http.HandlerFunc {
	return func(next http.HandlerFunc) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			raw := bearer(r.Header.Get("Authorization"))
			if raw == "" {
				apierr.WriteError(w, apierr.Unauthorized("未登录或令牌无效"))
				return
			}
			claims, err := sc.AdminTokens.Parse(raw)
			if err != nil {
				apierr.WriteError(w, apierr.Unauthorized("未登录或令牌无效"))
				return
			}
			ctx := apierr.WithAdmin(r.Context(), apierr.Admin{ID: claims.AdminID, Role: claims.Role})
			next(w, r.WithContext(ctx))
		}
	}
}

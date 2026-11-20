package middleware

import (
	"net/http"
	"regexp"

	"github.com/google/uuid"

	"mhagent/internal/apierr"
)

var uuidRe = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)

// RequestID 校验/生成 X-Request-Id。required=true 时缺失或格式非法返回 40001。
func RequestID(required bool) func(http.HandlerFunc) http.HandlerFunc {
	return func(next http.HandlerFunc) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			id := r.Header.Get("X-Request-Id")
			if id == "" {
				if required {
					apierr.WriteError(w, apierr.BadRequest("缺少 X-Request-Id"))
					return
				}
				id = uuid.NewString()
			} else if !uuidRe.MatchString(id) {
				if required {
					apierr.WriteError(w, apierr.BadRequest("X-Request-Id 必须是 UUID"))
					return
				}
			}
			w.Header().Set("X-Request-Id", id)
			r.Header.Set("X-Request-Id", id)
			next(w, r)
		}
	}
}

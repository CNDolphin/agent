// Package handler 实现 HTTP 编排,业务逻辑放在 logic 包。
package handler

import (
	"encoding/json"
	"net"
	"net/http"
	"strconv"

	"github.com/zeromicro/go-zero/rest/pathvar"

	"mhagent/internal/apierr"
	"mhagent/internal/svc"
)

// decode 解析 JSON 请求体,超过 2MB 或格式错误返回 40001。
func decode(w http.ResponseWriter, r *http.Request, dst any) bool {
	r.Body = http.MaxBytesReader(w, r.Body, 2<<20)
	dec := json.NewDecoder(r.Body)
	if err := dec.Decode(dst); err != nil {
		apierr.WriteError(w, apierr.BadRequest("请求体不是合法 JSON"))
		return false
	}
	return true
}

func pathVar(r *http.Request, key string) string {
	return pathvar.Vars(r)[key]
}

func userID(r *http.Request) (int64, bool) {
	return apierr.UserID(r.Context())
}

func clientIP(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

func queryInt(r *http.Request, key string, def, max int) (int, error) {
	raw := r.URL.Query().Get(key)
	if raw == "" {
		return def, nil
	}
	v, err := strconv.Atoi(raw)
	if err != nil || v <= 0 || v > max {
		return 0, err
	}
	return v, nil
}

// Health 健康检查。
func Health(_ *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		apierr.WriteJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	}
}

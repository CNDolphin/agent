package handler

import (
	"net/http"

	"mhagent/internal/apierr"
	"mhagent/internal/auth"
	"mhagent/internal/sms"
	"mhagent/internal/svc"
)

// DevSMSLast GET /dev/sms/last?phone=... 返回 mock 短信最近一次验证码。
// 仅当 Env=dev 且短信为 mock 时可用,其他情况一律 404,避免生产泄露。
func DevSMSLast(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if sc.Config.Env != "dev" || sc.Config.Sms.Provider != "mock" {
			http.NotFound(w, r)
			return
		}
		sender, ok := sc.Sender.(*sms.MockSender)
		if !ok {
			http.NotFound(w, r)
			return
		}
		normalized, err := auth.NormalizePhone(r.URL.Query().Get("phone"))
		if err != nil {
			apierr.WriteError(w, apierr.BadRequest("手机号格式不正确"))
			return
		}
		code, found := sender.LastCode(normalized)
		if !found {
			apierr.WriteJSON(w, http.StatusNotFound, map[string]any{
				"code":    40401,
				"message": "该号码尚未发送验证码",
			})
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]string{"code": code})
	}
}

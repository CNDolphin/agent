package handler

import (
	"fmt"
	"net/http"
	"time"

	"mhagent/internal/apierr"
	"mhagent/internal/svc"
)

// NotificationStream GET /notifications/stream
// SSE 长连接:推送报告创建/更新/删除事件,离线期间的变更由客户端重连后调用
// GET /reports/pending 补拉。
func NotificationStream(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		uid, ok := userID(r)
		if !ok {
			apierr.WriteError(w, apierr.Unauthorized("未登录或令牌无效"))
			return
		}
		flusher, ok := w.(http.Flusher)
		if !ok {
			apierr.WriteError(w, apierr.Internal())
			return
		}
		ch, cancel := sc.ReportHub.Subscribe(uid)
		defer cancel()

		h := w.Header()
		h.Set("Content-Type", "text/event-stream; charset=utf-8")
		h.Set("Cache-Control", "no-cache")
		h.Set("Connection", "keep-alive")
		h.Set("X-Accel-Buffering", "no")
		w.WriteHeader(http.StatusOK)
		flusher.Flush()

		heartbeat := time.NewTicker(20 * time.Second)
		defer heartbeat.Stop()

		for {
			select {
			case <-r.Context().Done():
				return
			case <-heartbeat.C:
				if _, err := fmt.Fprint(w, ": ping\n\n"); err != nil {
					return
				}
				flusher.Flush()
			case ev, ok := <-ch:
				if !ok {
					return
				}
				if _, err := fmt.Fprintf(w, "id: %s\nevent: %s\ndata: %s\n\n", ev.ID, ev.Type, ev.Data); err != nil {
					return
				}
				flusher.Flush()
			}
		}
	}
}

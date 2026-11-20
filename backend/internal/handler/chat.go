package handler

import (
	"net/http"

	"mhagent/internal/apierr"
	"mhagent/internal/logic"
	"mhagent/internal/svc"
)

// Chat POST /llm/chat
func Chat(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body logic.ChatRequest
		if !decode(w, r, &body) {
			return
		}
		id, ok := userID(r)
		if !ok {
			apierr.WriteError(w, apierr.Unauthorized("未登录"))
			return
		}
		requestID := r.Header.Get("X-Request-Id")
		chat := logic.NewChatLogic(sc)
		if body.Stream {
			chat.ChatStream(w, r, id, requestID, body)
			return
		}
		res, err := chat.Chat(r.Context(), id, requestID, body)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{
			"content": res.Content,
			"usage": map[string]int64{
				"input_hit":  res.Usage.InputHit,
				"input_miss": res.Usage.InputMiss,
				"output":     res.Usage.Output,
			},
			"cost":        res.Cost,
			"balance":     res.Balance,
			"low_balance": res.LowBalance,
		})
	}
}

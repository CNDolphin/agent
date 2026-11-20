package handler

import (
	"net/http"

	"mhagent/internal/apierr"
	"mhagent/internal/logic"
	"mhagent/internal/svc"
)

// Balance GET /credits/balance
func Balance(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := userID(r)
		if !ok {
			apierr.WriteError(w, apierr.Unauthorized("未登录"))
			return
		}
		b, err := logic.NewCreditsLogic(sc).Balance(r.Context(), id)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]int64{
			"balance":   b.Balance,
			"held":      b.Held,
			"available": b.Available(),
		})
	}
}

// Ledger GET /credits/ledger
func Ledger(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := userID(r)
		if !ok {
			apierr.WriteError(w, apierr.Unauthorized("未登录"))
			return
		}
		res, err := logic.NewCreditsLogic(sc).Ledger(r.Context(), id,
			r.URL.Query().Get("cursor"), r.URL.Query().Get("limit"))
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, res)
	}
}

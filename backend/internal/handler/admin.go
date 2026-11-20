package handler

import (
	"net/http"
	"strconv"

	"mhagent/internal/apierr"
	"mhagent/internal/logic"
	"mhagent/internal/svc"
)

// AdminListPrices GET /admin/prices
func AdminListPrices(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		list, err := logic.NewAdminLogic(sc).ListPrices(r.Context())
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{"items": list})
	}
}

// AdminUpdatePrice PUT /admin/prices/:model
func AdminUpdatePrice(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		model := pathVar(r, "model")
		var body logic.PriceUpdateInput
		if !decode(w, r, &body) {
			return
		}
		v, err := logic.NewAdminLogic(sc).UpdatePrice(r.Context(), model, body)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, v)
	}
}

// AdminPriceHistory GET /admin/prices/:model/history
func AdminPriceHistory(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		list, err := logic.NewAdminLogic(sc).ListPriceHistory(r.Context(), pathVar(r, "model"))
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{"items": list})
	}
}

// AdminGrant POST /admin/credits/grant
func AdminGrant(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body logic.GrantInput
		if !decode(w, r, &body) {
			return
		}
		res, err := logic.NewAdminLogic(sc).Grant(r.Context(), body)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, res)
	}
}

// AdminUsers GET /admin/users
func AdminUsers(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		list, err := logic.NewAdminLogic(sc).SearchUsers(r.Context(), r.URL.Query().Get("phone"))
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{"items": list})
	}
}

// AdminUserLedger GET /admin/users/:id/ledger
func AdminUserLedger(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(pathVar(r, "id"), 10, 64)
		if err != nil || id <= 0 {
			apierr.WriteError(w, apierr.BadRequest("用户 id 非法"))
			return
		}
		limit, err := queryInt(r, "limit", 50, 100)
		if err != nil {
			apierr.WriteError(w, apierr.BadRequest("limit 非法"))
			return
		}
		var beforeID int64
		if v := r.URL.Query().Get("cursor"); v != "" {
			beforeID, err = strconv.ParseInt(v, 10, 64)
			if err != nil || beforeID < 0 {
				apierr.WriteError(w, apierr.BadRequest("cursor 非法"))
				return
			}
		}
		list, next, lerr := logic.NewAdminLogic(sc).AdminLedger(r.Context(), id, beforeID, limit)
		if lerr != nil {
			apierr.WriteError(w, lerr)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{"items": list, "next_cursor": next})
	}
}

// AdminUsageSummary GET /admin/usage/summary
func AdminUsageSummary(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		now := sc.Now().UTC()
		from := now.AddDate(0, 0, -30)
		to := now
		var err error
		if v := r.URL.Query().Get("from"); v != "" {
			from, err = logic.ParseTime(v)
			if err != nil {
				apierr.WriteError(w, apierr.BadRequest("from 时间格式非法"))
				return
			}
		}
		if v := r.URL.Query().Get("to"); v != "" {
			to, err = logic.ParseTime(v)
			if err != nil {
				apierr.WriteError(w, apierr.BadRequest("to 时间格式非法"))
				return
			}
		}
		if to.Sub(from) < 0 {
			apierr.WriteError(w, apierr.BadRequest("时间范围非法"))
			return
		}
		list, err := logic.NewAdminLogic(sc).UsageSummary(r.Context(), from, to)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{"items": list})
	}
}

// AdminNotifyLogs GET /admin/notify-logs
func AdminNotifyLogs(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		list, err := logic.NewAdminLogic(sc).NotifyLogs(r.Context())
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{"items": list})
	}
}

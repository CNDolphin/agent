package handler

import (
	"net/http"
	"strconv"

	"mhagent/internal/apierr"
	"mhagent/internal/logic"
	pkgmgr "mhagent/internal/packages"
	"mhagent/internal/svc"
)

type publicPackage struct {
	ID          int64  `json:"id"`
	Name        string `json:"name"`
	Description string `json:"description"`
	PriceCents  int64  `json:"price_cents"`
	Credits     int64  `json:"credits"`
}

// ListPackages GET /packages
func ListPackages(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		list, err := logic.NewPackagesLogic(sc).ListPublic(r.Context())
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		items := make([]publicPackage, 0, len(list))
		for _, p := range list {
			items = append(items, publicPackage{ID: p.ID, Name: p.Name, Description: p.Description, PriceCents: p.PriceCents, Credits: p.Credits})
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{"items": items})
	}
}

// CreateOrder POST /orders
func CreateOrder(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			PackageID int64  `json:"package_id"`
			Channel   string `json:"channel"`
		}
		if !decode(w, r, &body) {
			return
		}
		id, ok := userID(r)
		if !ok {
			apierr.WriteError(w, apierr.Unauthorized("未登录"))
			return
		}
		o, params, err := logic.NewPackagesLogic(sc).CreateOrder(r.Context(), id, body.PackageID, body.Channel)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{
			"order_id":   o.ID,
			"status":     o.Status,
			"pay_params": params,
		})
	}
}

// ListOrders GET /orders
func ListOrders(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := userID(r)
		if !ok {
			apierr.WriteError(w, apierr.Unauthorized("未登录"))
			return
		}
		list, err := logic.NewPackagesLogic(sc).ListOrders(r.Context(), id)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{"items": list})
	}
}

// PayCallback POST /pay/callback/:channel
func PayCallback(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		channel := pathVar(r, "channel")
		o, err := logic.NewPackagesLogic(sc).Callback(r.Context(), channel, r)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{
			"status":   "ok",
			"order_id": o.ID,
		})
	}
}

// AdminListPackages GET /admin/packages
func AdminListPackages(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		list, err := logic.NewPackagesLogic(sc).ListAll(r.Context())
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{"items": list})
	}
}

// AdminCreatePackage POST /admin/packages
func AdminCreatePackage(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Name        string `json:"name"`
			Description string `json:"description"`
			PriceCents  int64  `json:"price_cents"`
			Credits     int64  `json:"credits"`
			Enabled     bool   `json:"enabled"`
			SortOrder   int    `json:"sort_order"`
		}
		if !decode(w, r, &body) {
			return
		}
		p, err := logic.NewPackagesLogic(sc).CreatePackage(r.Context(), pkgmgr.CreatePackageInput{
			Name:        body.Name,
			Description: body.Description,
			PriceCents:  body.PriceCents,
			Credits:     body.Credits,
			Enabled:     body.Enabled,
			SortOrder:   body.SortOrder,
		})
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, p)
	}
}

// AdminUpdatePackage PUT /admin/packages/:id
func AdminUpdatePackage(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(pathVar(r, "id"), 10, 64)
		if err != nil || id <= 0 {
			apierr.WriteError(w, apierr.BadRequest("套餐 id 非法"))
			return
		}
		var body struct {
			Name        *string `json:"name"`
			Description *string `json:"description"`
			PriceCents  *int64  `json:"price_cents"`
			Credits     *int64  `json:"credits"`
			Enabled     *bool   `json:"enabled"`
			SortOrder   *int    `json:"sort_order"`
		}
		if !decode(w, r, &body) {
			return
		}
		p, err := logic.NewPackagesLogic(sc).UpdatePackage(r.Context(), id, pkgmgr.UpdatePackageInput{
			Name:        body.Name,
			Description: body.Description,
			PriceCents:  body.PriceCents,
			Credits:     body.Credits,
			Enabled:     body.Enabled,
			SortOrder:   body.SortOrder,
		})
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, p)
	}
}

// AdminListOrders GET /admin/orders
func AdminListOrders(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		list, err := logic.NewPackagesLogic(sc).AdminListOrders(r.Context(),
			r.URL.Query().Get("status"), r.URL.Query().Get("phone"))
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{"items": list})
	}
}

// AdminConfirmOrder POST /admin/orders/:id/confirm
func AdminConfirmOrder(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(pathVar(r, "id"), 10, 64)
		if err != nil || id <= 0 {
			apierr.WriteError(w, apierr.BadRequest("订单 id 非法"))
			return
		}
		o, err := logic.NewPackagesLogic(sc).ConfirmOrder(r.Context(), id)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, o)
	}
}

// AdminCancelOrder POST /admin/orders/:id/cancel
func AdminCancelOrder(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(pathVar(r, "id"), 10, 64)
		if err != nil || id <= 0 {
			apierr.WriteError(w, apierr.BadRequest("订单 id 非法"))
			return
		}
		o, err := logic.NewPackagesLogic(sc).CancelOrder(r.Context(), id)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, o)
	}
}

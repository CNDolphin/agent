package handler

import (
	"net/http"

	"mhagent/internal/apierr"
	"mhagent/internal/logic"
	"mhagent/internal/svc"
)

// SendSMSCode POST /auth/sms/send
func SendSMSCode(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Phone string `json:"phone"`
		}
		if !decode(w, r, &body) {
			return
		}
		if err := logic.NewAuthLogic(sc).SendCode(r.Context(), body.Phone, clientIP(r)); err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteNoContent(w)
	}
}

// Login POST /auth/login
func Login(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Phone string `json:"phone"`
			Code  string `json:"code"`
		}
		if !decode(w, r, &body) {
			return
		}
		if body.Code == "" {
			apierr.WriteError(w, apierr.InvalidCode())
			return
		}
		res, err := logic.NewAuthLogic(sc).Login(r.Context(), body.Phone, body.Code)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{
			"access_token":  res.Pair.AccessToken,
			"refresh_token": res.Pair.RefreshToken,
			"expires_in":    res.Pair.ExpiresIn,
			"is_new":        res.IsNew,
		})
	}
}

// Register POST /auth/register
func Register(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Phone    string `json:"phone"`
			Code     string `json:"code"`
			Password string `json:"password"`
		}
		if !decode(w, r, &body) {
			return
		}
		res, err := logic.NewAuthLogic(sc).Register(r.Context(), body.Phone, body.Code, body.Password)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{
			"access_token":  res.Pair.AccessToken,
			"refresh_token": res.Pair.RefreshToken,
			"expires_in":    res.Pair.ExpiresIn,
			"is_new":        res.IsNew,
		})
	}
}

// LoginWithPassword POST /auth/login/password
func LoginWithPassword(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Phone    string `json:"phone"`
			Password string `json:"password"`
		}
		if !decode(w, r, &body) {
			return
		}
		res, err := logic.NewAuthLogic(sc).LoginWithPassword(r.Context(), body.Phone, body.Password)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{
			"access_token":  res.Pair.AccessToken,
			"refresh_token": res.Pair.RefreshToken,
			"expires_in":    res.Pair.ExpiresIn,
			"is_new":        res.IsNew,
		})
	}
}

// ResetPassword POST /auth/password/reset
func ResetPassword(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Phone       string `json:"phone"`
			Code        string `json:"code"`
			NewPassword string `json:"new_password"`
		}
		if !decode(w, r, &body) {
			return
		}
		if err := logic.NewAuthLogic(sc).ResetPassword(r.Context(), body.Phone, body.Code, body.NewPassword); err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteNoContent(w)
	}
}

// Refresh POST /auth/refresh
func Refresh(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			RefreshToken string `json:"refresh_token"`
		}
		if !decode(w, r, &body) {
			return
		}
		pair, err := logic.NewAuthLogic(sc).Refresh(r.Context(), body.RefreshToken)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{
			"access_token":  pair.AccessToken,
			"refresh_token": pair.RefreshToken,
			"expires_in":    pair.ExpiresIn,
		})
	}
}

// DeleteAccount DELETE /account
func DeleteAccount(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := userID(r)
		if !ok {
			apierr.WriteError(w, apierr.Unauthorized("未登录"))
			return
		}
		if err := logic.NewAuthLogic(sc).DeleteAccount(r.Context(), id); err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteNoContent(w)
	}
}

// AdminLogin POST /admin/auth/login
func AdminLogin(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Username string `json:"username"`
			Password string `json:"password"`
		}
		if !decode(w, r, &body) {
			return
		}
		res, err := logic.NewAdminLogic(sc).Login(r.Context(), body.Username, body.Password)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{
			"access_token": res.AccessToken,
			"expires_in":   res.ExpiresIn,
			"role":         res.Role,
		})
	}
}

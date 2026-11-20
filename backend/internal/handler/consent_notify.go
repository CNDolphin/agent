package handler

import (
	"net/http"

	"mhagent/internal/apierr"
	"mhagent/internal/logic"
	"mhagent/internal/svc"
)

// ConsentLatest GET /consent/latest
func ConsentLatest(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		apierr.WriteJSON(w, http.StatusOK, logic.NewConsentLogic(sc).Latest())
	}
}

// ConsentSign POST /consent
func ConsentSign(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Version string `json:"version"`
		}
		if !decode(w, r, &body) {
			return
		}
		id, ok := userID(r)
		if !ok {
			apierr.WriteError(w, apierr.Unauthorized("未登录"))
			return
		}
		if err := logic.NewConsentLogic(sc).Sign(r.Context(), id, body.Version); err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteNoContent(w)
	}
}

// NotifyEmergency POST /notify/emergency
func NotifyEmergency(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Channel    string            `json:"channel"`
			To         string            `json:"to"`
			TemplateID string            `json:"template_id"`
			Params     map[string]string `json:"params"`
		}
		if !decode(w, r, &body) {
			return
		}
		id, ok := userID(r)
		if !ok {
			apierr.WriteError(w, apierr.Unauthorized("未登录"))
			return
		}
		res, err := logic.NewNotifyLogic(sc).Emergency(r.Context(), id, body.Channel, body.To, body.TemplateID, body.Params)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]string{
			"status":    res.Status,
			"notify_id": res.NotifyID,
		})
	}
}

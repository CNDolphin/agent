// Package apierr 定义与接口契约一致的错误码、HTTP 状态码与 JSON 响应。
package apierr

import (
	"encoding/json"
	"net/http"
)

// 契约错误码(见 00-overview-and-contracts 第 3 节)。
const (
	CodeBadRequest       = 40001
	CodeUnauthorized     = 40101
	CodeInvalidCode      = 40102
	CodeWrongPassword    = 40104
	CodePasswordRequired = 40105
	CodeInsufficient     = 40201
	CodeConsentRequired  = 40301
	CodeDuplicateRequest = 40901
	CodeAlreadyRegister  = 40902
	CodeRateLimited      = 42901
	CodeUpstream         = 50201
	CodeInternal         = 50000
)

// Error 是可直接写入响应的业务错误。
type Error struct {
	Code    int
	Status  int
	Message string
	Extra   map[string]any
}

func (e *Error) Error() string { return e.Message }

// New 构造业务错误。
func New(code, status int, message string) *Error {
	return &Error{Code: code, Status: status, Message: message}
}

// BadRequest 40001。
func BadRequest(message string) *Error { return New(CodeBadRequest, http.StatusBadRequest, message) }

// Unauthorized 40101。
func Unauthorized(message string) *Error {
	return New(CodeUnauthorized, http.StatusUnauthorized, message)
}

// InvalidCode 40102,故意不区分"验证码错误"与"已失效"。
func InvalidCode() *Error {
	return New(CodeInvalidCode, http.StatusUnauthorized, "验证码错误或已失效")
}

// WrongPassword 40104,故意不区分"手机号不存在"与"密码错误"。
func WrongPassword() *Error {
	return New(CodeWrongPassword, http.StatusUnauthorized, "手机号或密码错误")
}

// PasswordRequired 40105,历史账号尚未设置密码。
func PasswordRequired() *Error {
	return New(CodePasswordRequired, http.StatusConflict, "该账号尚未设置密码,请先用手机验证码完成首次设置")
}

// AlreadyRegistered 40902,手机号已注册且已设置密码。
func AlreadyRegistered() *Error {
	return New(CodeAlreadyRegister, http.StatusConflict, "该手机号已注册,请直接登录")
}

// InsufficientCredits 40201。
func InsufficientCredits() *Error {
	return New(CodeInsufficient, http.StatusPaymentRequired, "积分不足")
}

// ConsentRequired 40301。
func ConsentRequired() *Error {
	return New(CodeConsentRequired, http.StatusForbidden, "未签署最新同意书")
}

// DuplicateRequest 40901,附带首次结算的 cost。
func DuplicateRequest(cost int64) *Error {
	return &Error{
		Code:    CodeDuplicateRequest,
		Status:  http.StatusConflict,
		Message: "重复的 X-Request-Id,该请求已结算",
		Extra:   map[string]any{"cost": cost},
	}
}

// RateLimited 42901。
func RateLimited(message string) *Error {
	return New(CodeRateLimited, http.StatusTooManyRequests, message)
}

// Upstream 50201。
func Upstream(message string) *Error { return New(CodeUpstream, http.StatusBadGateway, message) }

// Internal 500,不对外暴露细节。
func Internal() *Error {
	return New(CodeInternal, http.StatusInternalServerError, "服务器内部错误")
}

// WriteJSON 写出 JSON 响应。
func WriteJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

// WriteError 写出契约错误体;未知错误统一按 500 处理。
func WriteError(w http.ResponseWriter, err error) {
	e, ok := err.(*Error)
	if !ok {
		e = Internal()
	}
	body := map[string]any{"code": e.Code, "message": e.Message}
	for k, v := range e.Extra {
		body[k] = v
	}
	WriteJSON(w, e.Status, body)
}

// WriteNoContent 写出 204。
func WriteNoContent(w http.ResponseWriter) {
	w.WriteHeader(http.StatusNoContent)
}

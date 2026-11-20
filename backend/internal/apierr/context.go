package apierr

import "context"

type contextKey string

const (
	userIDKey contextKey = "ctx-user-id"
	adminKey  contextKey = "ctx-admin"
)

// Admin 管理员上下文信息。
type Admin struct {
	ID   int64
	Role string
}

// WithUserID 把已认证用户写入 context。
func WithUserID(ctx context.Context, userID int64) context.Context {
	return context.WithValue(ctx, userIDKey, userID)
}

// UserID 读取已认证用户;未认证返回 0,false。
func UserID(ctx context.Context) (int64, bool) {
	v, ok := ctx.Value(userIDKey).(int64)
	return v, ok
}

// WithAdmin 把已认证管理员写入 context。
func WithAdmin(ctx context.Context, a Admin) context.Context {
	return context.WithValue(ctx, adminKey, a)
}

// GetAdmin 读取管理员上下文。
func GetAdmin(ctx context.Context) (Admin, bool) {
	v, ok := ctx.Value(adminKey).(Admin)
	return v, ok
}

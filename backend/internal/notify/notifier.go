// Package notify 提供紧急通知发送。阿里云实现只接 SDK、留配置;测试全部使用 mock。
package notify

import "context"

// Notifier 发送紧急通知。
type Notifier interface {
	Send(ctx context.Context, channel, to, templateID string, params map[string]string) error
}

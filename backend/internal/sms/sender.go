// Package sms 定义验证码短信发送通道。阿里云实现只接 SDK、留配置;开发与测试使用 mock。
package sms

import "context"

// Sender 发送短信。templateCode 为阿里云已审核通过的模板,params 序列化为 TemplateParam。
type Sender interface {
	Send(ctx context.Context, phone, templateCode string, params map[string]string) error
}

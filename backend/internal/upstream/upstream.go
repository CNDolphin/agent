// Package upstream 隔离上游模型平台。开发/测试使用 mock,生产使用 DeepSeek 适配器。
package upstream

import (
	"context"
	"errors"
)

// Message 对话消息。
type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// ChatRequest 上游请求。Thinking 由模型配置决定,客户端不可传。
type ChatRequest struct {
	Model     string
	Messages  []Message
	MaxTokens int
	Thinking  string // enabled|disabled
	UserTag   string // 用户伪名,不得包含手机号或用户 ID 明文
}

// Usage 上游用量。InputHit/InputMiss 对应 DeepSeek 的缓存命中/未命中输入。
type Usage struct {
	InputHit  int64
	InputMiss int64
	Output    int64
}

// 上游错误分类。
var (
	ErrUpstreamAuth        = errors.New("upstream auth failed")
	ErrUpstreamBalance     = errors.New("upstream out of balance")
	ErrUpstreamRateLimit   = errors.New("upstream rate limited")
	ErrUpstreamBusy        = errors.New("upstream unavailable")
	ErrUpstreamBadReq      = errors.New("upstream rejected request")
	ErrUpstreamInterrupted = errors.New("upstream stream interrupted")
)

// Upstream 模型调用接口。
type Upstream interface {
	Chat(ctx context.Context, req ChatRequest) (content string, usage Usage, err error)
	// ChatStream 每个增量调用 onDelta;出错时也返回已产生的 usage。
	ChatStream(ctx context.Context, req ChatRequest, onDelta func(string) error) (Usage, error)
}

package upstream

import (
	"context"
	"sync"
	"time"
)

// Mock 可配置的假上游,用于单元/集成测试。
type Mock struct {
	mu sync.Mutex

	// 以下字段在调用前设置,调用期间只读。
	Content   string
	Usage     Usage
	Delay     time.Duration
	Err       error
	Chunks    []string
	StreamErr error
	// FailAfterChunks 在输出该数量的分片后返回 StreamErr;<0 表示不注入。
	FailAfterChunks int
	// IgnoreContext 为 true 时不响应 ctx 取消(用于特殊测试)。
	IgnoreContext bool

	calls []ChatRequest
}

// NewMock 创建 mock 上游。
func NewMock() *Mock {
	return &Mock{FailAfterChunks: -1}
}

func (m *Mock) record(req ChatRequest) {
	m.mu.Lock()
	m.calls = append(m.calls, req)
	m.mu.Unlock()
}

// Calls 返回收到的请求。
func (m *Mock) Calls() []ChatRequest {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]ChatRequest, len(m.calls))
	copy(out, m.calls)
	return out
}

func (m *Mock) sleep(ctx context.Context, d time.Duration) error {
	if d <= 0 || m.IgnoreContext {
		return nil
	}
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-time.After(d):
		return nil
	}
}

// Chat 非流式 mock。
func (m *Mock) Chat(ctx context.Context, req ChatRequest) (string, Usage, error) {
	m.record(req)
	if err := m.sleep(ctx, m.Delay); err != nil {
		return "", Usage{}, err
	}
	if m.Err != nil {
		return "", Usage{}, m.Err
	}
	return m.Content, m.Usage, nil
}

// ChatStream 按 Chunks 分片回调。
func (m *Mock) ChatStream(ctx context.Context, req ChatRequest, onDelta func(string) error) (Usage, error) {
	m.record(req)
	chunks := m.Chunks
	if len(chunks) == 0 && m.Content != "" {
		chunks = []string{m.Content}
	}
	var emitted Usage
	for i, chunk := range chunks {
		if err := m.sleep(ctx, m.Delay); err != nil {
			return emitted, err
		}
		if err := onDelta(chunk); err != nil {
			return emitted, err
		}
		emitted.Output += 1
		if m.FailAfterChunks >= 0 && i+1 >= m.FailAfterChunks {
			if m.StreamErr != nil {
				return m.Usage, m.StreamErr
			}
		}
	}
	if m.StreamErr != nil {
		return m.Usage, m.StreamErr
	}
	if m.Err != nil {
		return emitted, m.Err
	}
	return m.Usage, nil
}

package notify

import (
	"context"
	"sync"
)

// MockCall 记录一次 mock 通知调用。
type MockCall struct {
	Channel    string
	To         string
	TemplateID string
	ParamKeys  []string
}

// MockNotifier 测试用通知器。
type MockNotifier struct {
	mu    sync.Mutex
	calls []MockCall
	Err   error
}

// NewMockNotifier 创建 mock 通知器。
func NewMockNotifier() *MockNotifier { return &MockNotifier{} }

// SetError 设置后续调用返回的错误。
func (m *MockNotifier) SetError(err error) {
	m.mu.Lock()
	m.Err = err
	m.mu.Unlock()
}

// Send 记录渠道与模板,不保存参数值。
func (m *MockNotifier) Send(_ context.Context, channel, to, templateID string, params map[string]string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.Err != nil {
		return m.Err
	}
	keys := make([]string, 0, len(params))
	for k := range params {
		keys = append(keys, k)
	}
	m.calls = append(m.calls, MockCall{Channel: channel, To: to, TemplateID: templateID, ParamKeys: keys})
	return nil
}

// Calls 返回调用记录。
func (m *MockNotifier) Calls() []MockCall {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]MockCall, len(m.calls))
	copy(out, m.calls)
	return out
}

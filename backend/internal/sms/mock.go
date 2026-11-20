package sms

import (
	"context"
	"sync"
)

// Call 记录一次 mock 发送(仅测试使用)。
type Call struct {
	Phone        string
	TemplateCode string
	Params       map[string]string
}

// MockSender 开发/测试用发送器:把验证码保存在内存,便于测试读取。
type MockSender struct {
	mu      sync.Mutex
	calls   []Call
	codes   map[string]string
	failErr error
}

// NewMockSender 创建 mock 发送器。
func NewMockSender() *MockSender {
	return &MockSender{codes: map[string]string{}}
}

// SetError 让后续发送返回指定错误。
func (m *MockSender) SetError(err error) {
	m.mu.Lock()
	m.failErr = err
	m.mu.Unlock()
}

// Send 记录调用;成功时保存 params["code"]。
func (m *MockSender) Send(_ context.Context, phone, templateCode string, params map[string]string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.failErr != nil {
		return m.failErr
	}
	cp := make(map[string]string, len(params))
	for k, v := range params {
		cp[k] = v
	}
	m.calls = append(m.calls, Call{Phone: phone, TemplateCode: templateCode, Params: cp})
	if code, ok := params["code"]; ok {
		m.codes[phone] = code
	}
	return nil
}

// LastCode 返回指定号码最后一次收到的验证码;不存在时 ok 为 false。
// 仅测试与开发环境取码接口使用。
func (m *MockSender) LastCode(phone string) (code string, ok bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	code, ok = m.codes[phone]
	return code, ok
}

// LastCodeAny 返回最近一次发送的验证码,便于测试无需关心号码规范化。
func (m *MockSender) LastCodeAny() string {
	m.mu.Lock()
	defer m.mu.Unlock()
	var last string
	for _, c := range m.calls {
		if code, ok := c.Params["code"]; ok {
			last = code
		}
	}
	return last
}

// Calls 返回累计调用。
func (m *MockSender) Calls() []Call {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]Call, len(m.calls))
	copy(out, m.calls)
	return out
}

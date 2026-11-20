package upstream_test

import (
	"context"
	"errors"
	"testing"
	"time"

	"mhagent/internal/upstream"
)

func TestMockChat(t *testing.T) {
	m := upstream.NewMock()
	m.Content = "你好"
	m.Usage = upstream.Usage{InputHit: 3, InputMiss: 5, Output: 7}
	req := upstream.ChatRequest{Model: "deepseek-flash", Messages: []upstream.Message{{Role: "user", Content: "hi"}}}
	content, usage, err := m.Chat(context.Background(), req)
	if err != nil {
		t.Fatalf("mock chat 失败: %v", err)
	}
	if content != "你好" || usage != (upstream.Usage{InputHit: 3, InputMiss: 5, Output: 7}) {
		t.Fatalf("mock 返回值不符合预期: %q %+v", content, usage)
	}
	if len(m.Calls()) != 1 || m.Calls()[0].Model != "deepseek-flash" {
		t.Fatalf("未记录调用: %+v", m.Calls())
	}
}

func TestMockChatError(t *testing.T) {
	m := upstream.NewMock()
	m.Err = upstream.ErrUpstreamBusy
	if _, _, err := m.Chat(context.Background(), upstream.ChatRequest{}); !errors.Is(err, upstream.ErrUpstreamBusy) {
		t.Fatalf("期望 ErrUpstreamBusy,实际 %v", err)
	}
}

func TestMockChatStreamChunks(t *testing.T) {
	m := upstream.NewMock()
	m.Chunks = []string{"你", "好", "呀"}
	m.Usage = upstream.Usage{InputHit: 1, InputMiss: 2, Output: 3}
	var got []string
	usage, err := m.ChatStream(context.Background(), upstream.ChatRequest{}, func(s string) error {
		got = append(got, s)
		return nil
	})
	if err != nil {
		t.Fatalf("mock stream 失败: %v", err)
	}
	if len(got) != 3 || got[0] != "你" || got[2] != "呀" {
		t.Fatalf("分片顺序错误: %v", got)
	}
	if usage != (upstream.Usage{InputHit: 1, InputMiss: 2, Output: 3}) {
		t.Fatalf("usage 不符合预期: %+v", usage)
	}
}

func TestMockChatStreamCancel(t *testing.T) {
	m := upstream.NewMock()
	m.Chunks = []string{"a", "b"}
	m.Delay = time.Hour
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := m.ChatStream(ctx, upstream.ChatRequest{}, func(string) error { return nil }); !errors.Is(err, context.Canceled) {
		t.Fatalf("期望 context.Canceled,实际 %v", err)
	}
}

func TestMockChatStreamFailAfterChunks(t *testing.T) {
	m := upstream.NewMock()
	m.Chunks = []string{"a", "b", "c"}
	m.FailAfterChunks = 1
	m.StreamErr = upstream.ErrUpstreamInterrupted
	var got []string
	usage, err := m.ChatStream(context.Background(), upstream.ChatRequest{}, func(s string) error {
		got = append(got, s)
		return nil
	})
	if !errors.Is(err, upstream.ErrUpstreamInterrupted) {
		t.Fatalf("期望 ErrUpstreamInterrupted,实际 %v", err)
	}
	if len(got) != 1 {
		t.Fatalf("应只输出 1 个分片,实际 %v", got)
	}
	_ = usage
}

func TestMockChatStreamDeltaError(t *testing.T) {
	m := upstream.NewMock()
	m.Chunks = []string{"a", "b"}
	boom := errors.New("client gone")
	if _, err := m.ChatStream(context.Background(), upstream.ChatRequest{}, func(string) error { return boom }); !errors.Is(err, boom) {
		t.Fatalf("onDelta 错误应原样返回,实际 %v", err)
	}
}

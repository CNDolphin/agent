package upstream_test

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"mhagent/internal/upstream"
)

// capture 线程安全地记录 handler 收到的请求,避免 -race 报告。
type capture struct {
	mu   sync.Mutex
	path string
	auth string
	body map[string]any
}

func (c *capture) set(r *http.Request) {
	raw, _ := io.ReadAll(r.Body)
	var body map[string]any
	_ = json.Unmarshal(raw, &body)
	c.mu.Lock()
	c.path = r.URL.Path
	c.auth = r.Header.Get("Authorization")
	c.body = body
	c.mu.Unlock()
}

func (c *capture) get() (path, auth string, body map[string]any) {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.path, c.auth, c.body
}

func TestDeepSeekChatNonStream(t *testing.T) {
	var rec capture
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		rec.set(r)
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"choices":[{"message":{"content":"你好","reasoning_content":"内部思考"},"finish_reason":"stop"}],
			"usage":{"prompt_cache_hit_tokens":10,"prompt_cache_miss_tokens":20,"completion_tokens":5}}`)
	}))
	defer srv.Close()

	d := upstream.NewDeepSeek(srv.URL, "sk-test-secret", 5*time.Second, 0)
	content, usage, err := d.Chat(context.Background(), upstream.ChatRequest{
		Model:     "deepseek-flash",
		Messages:  []upstream.Message{{Role: "user", Content: "hi"}},
		MaxTokens: 128,
		Thinking:  "disabled",
		UserTag:   "pseudonym123",
	})
	if err != nil {
		t.Fatalf("非流式调用失败: %v", err)
	}
	if content != "你好" {
		t.Fatalf("正文不符: %q", content)
	}
	if strings.Contains(content, "内部思考") {
		t.Fatalf("reasoning_content 不应转发给客户端")
	}
	if usage != (upstream.Usage{InputHit: 10, InputMiss: 20, Output: 5}) {
		t.Fatalf("usage 映射错误: %+v", usage)
	}
	gotPath, gotAuth, gotBody := rec.get()
	if gotPath != "/chat/completions" {
		t.Fatalf("请求路径错误: %s", gotPath)
	}
	if gotAuth != "Bearer sk-test-secret" {
		t.Fatalf("Authorization 错误: %s", gotAuth)
	}
	if gotBody["model"] != "deepseek-flash" {
		t.Fatalf("model 字段错误: %v", gotBody["model"])
	}
	if gotBody["max_tokens"] != float64(128) {
		t.Fatalf("max_tokens 字段错误: %v", gotBody["max_tokens"])
	}
	if _, exists := gotBody["stream"]; exists {
		t.Fatalf("非流式请求不应带 stream 字段")
	}
	thinking, _ := gotBody["thinking"].(map[string]any)
	if thinking["type"] != "disabled" {
		t.Fatalf("thinking 字段错误: %v", gotBody["thinking"])
	}
	if gotBody["user_id"] != "pseudonym123" {
		t.Fatalf("user_id 伪名错误: %v", gotBody["user_id"])
	}
}

func TestDeepSeekThinkingEnabled(t *testing.T) {
	var rec capture
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		rec.set(r)
		_, _ = io.WriteString(w, `{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],"usage":{}}`)
	}))
	defer srv.Close()

	d := upstream.NewDeepSeek(srv.URL, "k", time.Second, 0)
	if _, _, err := d.Chat(context.Background(), upstream.ChatRequest{Thinking: "enabled"}); err != nil {
		t.Fatalf("调用失败: %v", err)
	}
	_, _, gotBody := rec.get()
	thinking, _ := gotBody["thinking"].(map[string]any)
	if thinking["type"] != "enabled" {
		t.Fatalf("thinking 应为 enabled: %v", gotBody["thinking"])
	}
}

func TestDeepSeekBalanceErrorNotRetried(t *testing.T) {
	var calls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		w.WriteHeader(http.StatusPaymentRequired)
	}))
	defer srv.Close()

	d := upstream.NewDeepSeek(srv.URL, "sk-secret", time.Second, 3)
	_, _, err := d.Chat(context.Background(), upstream.ChatRequest{})
	if !errors.Is(err, upstream.ErrUpstreamBalance) {
		t.Fatalf("期望 ErrUpstreamBalance,实际 %v", err)
	}
	if got := atomic.LoadInt32(&calls); got != 1 {
		t.Fatalf("402 不应重试,实际调用 %d 次", got)
	}
	if strings.Contains(err.Error(), "sk-secret") {
		t.Fatalf("错误信息泄露了 API Key")
	}
}

func TestDeepSeekAuthError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
	}))
	defer srv.Close()
	d := upstream.NewDeepSeek(srv.URL, "sk-secret", time.Second, 2)
	_, _, err := d.Chat(context.Background(), upstream.ChatRequest{})
	if !errors.Is(err, upstream.ErrUpstreamAuth) {
		t.Fatalf("期望 ErrUpstreamAuth,实际 %v", err)
	}
	if strings.Contains(err.Error(), "sk-secret") {
		t.Fatalf("错误信息泄露了 API Key")
	}
}

func TestDeepSeekRetriesRateLimit(t *testing.T) {
	var calls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := atomic.AddInt32(&calls, 1)
		if n == 1 {
			w.WriteHeader(http.StatusTooManyRequests)
			return
		}
		_, _ = io.WriteString(w, `{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],"usage":{"completion_tokens":1}}`)
	}))
	defer srv.Close()

	d := upstream.NewDeepSeek(srv.URL, "k", time.Second, 2)
	content, _, err := d.Chat(context.Background(), upstream.ChatRequest{})
	if err != nil || content != "ok" {
		t.Fatalf("重试后应成功,实际 %q %v", content, err)
	}
	if got := atomic.LoadInt32(&calls); got != 2 {
		t.Fatalf("期望调用 2 次,实际 %d", got)
	}
}

func TestDeepSeekRetryExhausted(t *testing.T) {
	var calls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer srv.Close()
	d := upstream.NewDeepSeek(srv.URL, "k", time.Second, 2)
	if _, _, err := d.Chat(context.Background(), upstream.ChatRequest{}); !errors.Is(err, upstream.ErrUpstreamBusy) {
		t.Fatalf("期望 ErrUpstreamBusy,实际 %v", err)
	}
	if got := atomic.LoadInt32(&calls); got != 3 {
		t.Fatalf("MaxRetries=2 应调用 3 次,实际 %d", got)
	}
}

func TestDeepSeekAbortedFinishNotRetried(t *testing.T) {
	var calls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		_, _ = io.WriteString(w, `{"choices":[{"message":{"content":"部分"},"finish_reason":"aborted"}],"usage":{"completion_tokens":2}}`)
	}))
	defer srv.Close()
	d := upstream.NewDeepSeek(srv.URL, "k", time.Second, 5)
	content, usage, err := d.Chat(context.Background(), upstream.ChatRequest{})
	if !errors.Is(err, upstream.ErrUpstreamBusy) {
		t.Fatalf("期望 ErrUpstreamBusy,实际 %v", err)
	}
	if content != "部分" || usage.Output != 2 {
		t.Fatalf("应返回已产生内容与 usage: %q %+v", content, usage)
	}
	if got := atomic.LoadInt32(&calls); got != 1 {
		t.Fatalf("finish aborted 不应重试,实际 %d 次", got)
	}
}

func TestDeepSeekChatStream(t *testing.T) {
	var rec capture
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		rec.set(r)
		w.Header().Set("Content-Type", "text/event-stream")
		fmt.Fprint(w,
			"data: {\"choices\":[{\"delta\":{\"reasoning_content\":\"思考中\"}}]}\n\n"+
				"data: {\"choices\":[{\"delta\":{\"content\":\"你\"}}]}\n\n"+
				"data: {\"choices\":[{\"delta\":{\"content\":\"好\"}}]}\n\n"+
				"data: {\"choices\":[],\"usage\":{\"prompt_cache_hit_tokens\":1,\"prompt_cache_miss_tokens\":2,\"completion_tokens\":3}}\n\n"+
				"data: [DONE]\n\n")
	}))
	defer srv.Close()

	d := upstream.NewDeepSeek(srv.URL, "k", 5*time.Second, 0)
	var got []string
	usage, err := d.ChatStream(context.Background(), upstream.ChatRequest{Model: "deepseek-flash"}, func(s string) error {
		got = append(got, s)
		return nil
	})
	if err != nil {
		t.Fatalf("流式调用失败: %v", err)
	}
	if len(got) != 2 || got[0] != "你" || got[1] != "好" {
		t.Fatalf("增量内容错误: %v", got)
	}
	if usage != (upstream.Usage{InputHit: 1, InputMiss: 2, Output: 3}) {
		t.Fatalf("usage 错误: %+v", usage)
	}
	_, _, gotBody := rec.get()
	if gotBody["stream"] != true {
		t.Fatalf("流式请求应带 stream=true")
	}
	opts, _ := gotBody["stream_options"].(map[string]any)
	if opts["include_usage"] != true {
		t.Fatalf("应请求 include_usage: %v", gotBody["stream_options"])
	}
}

func TestDeepSeekChatStreamRetryBeforeOutput(t *testing.T) {
	var calls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := atomic.AddInt32(&calls, 1)
		if n == 1 {
			w.WriteHeader(http.StatusTooManyRequests)
			return
		}
		fmt.Fprint(w,
			"data: {\"choices\":[{\"delta\":{\"content\":\"ok\"}}]}\n\n"+
				"data: {\"choices\":[],\"usage\":{\"completion_tokens\":1}}\n\n"+
				"data: [DONE]\n\n")
	}))
	defer srv.Close()

	d := upstream.NewDeepSeek(srv.URL, "k", 5*time.Second, 2)
	var got []string
	usage, err := d.ChatStream(context.Background(), upstream.ChatRequest{}, func(s string) error {
		got = append(got, s)
		return nil
	})
	if err != nil {
		t.Fatalf("重试后应成功: %v", err)
	}
	if len(got) != 1 || got[0] != "ok" {
		t.Fatalf("重试导致内容重复: %v", got)
	}
	if usage.Output != 1 {
		t.Fatalf("usage 错误: %+v", usage)
	}
	if got := atomic.LoadInt32(&calls); got != 2 {
		t.Fatalf("期望调用 2 次,实际 %d", got)
	}
}

func TestDeepSeekChatStreamInterrupted(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, "data: {\"choices\":[{\"delta\":{\"content\":\"a\"}}]}\n\n")
	}))
	defer srv.Close()
	d := upstream.NewDeepSeek(srv.URL, "k", 5*time.Second, 0)
	_, err := d.ChatStream(context.Background(), upstream.ChatRequest{}, func(string) error { return nil })
	if !errors.Is(err, upstream.ErrUpstreamInterrupted) {
		t.Fatalf("缺少 [DONE] 期望 ErrUpstreamInterrupted,实际 %v", err)
	}
}

func TestDeepSeekChatStreamMissingUsage(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w,
			"data: {\"choices\":[{\"delta\":{\"content\":\"a\"}}]}\n\n"+
				"data: [DONE]\n\n")
	}))
	defer srv.Close()
	d := upstream.NewDeepSeek(srv.URL, "k", 5*time.Second, 0)
	if _, err := d.ChatStream(context.Background(), upstream.ChatRequest{}, func(string) error { return nil }); !errors.Is(err, upstream.ErrUpstreamInterrupted) {
		t.Fatalf("缺少 usage 期望 ErrUpstreamInterrupted,实际 %v", err)
	}
}

func TestDeepSeekChatStreamFinishAborted(t *testing.T) {
	var calls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		fmt.Fprint(w,
			"data: {\"choices\":[{\"delta\":{\"content\":\"a\"},\"finish_reason\":\"insufficient_system_resource\"}]}\n\n"+
				"data: [DONE]\n\n")
	}))
	defer srv.Close()
	d := upstream.NewDeepSeek(srv.URL, "k", 5*time.Second, 5)
	var got []string
	_, err := d.ChatStream(context.Background(), upstream.ChatRequest{}, func(s string) error {
		got = append(got, s)
		return nil
	})
	if !errors.Is(err, upstream.ErrUpstreamBusy) {
		t.Fatalf("期望 ErrUpstreamBusy,实际 %v", err)
	}
	if len(got) != 1 {
		t.Fatalf("已输出内容应保留: %v", got)
	}
	if got := atomic.LoadInt32(&calls); got != 1 {
		t.Fatalf("已输出后不应重试,实际 %d 次", got)
	}
}

func TestDeepSeekChatStreamBalanceError(t *testing.T) {
	var calls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		w.WriteHeader(http.StatusPaymentRequired)
	}))
	defer srv.Close()
	d := upstream.NewDeepSeek(srv.URL, "k", 5*time.Second, 3)
	if _, err := d.ChatStream(context.Background(), upstream.ChatRequest{}, func(string) error { return nil }); !errors.Is(err, upstream.ErrUpstreamBalance) {
		t.Fatalf("期望 ErrUpstreamBalance,实际 %v", err)
	}
	if got := atomic.LoadInt32(&calls); got != 1 {
		t.Fatalf("402 不应重试,实际 %d", got)
	}
}

func TestDeepSeekChatStreamDeltaError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, "data: {\"choices\":[{\"delta\":{\"content\":\"a\"}}]}\n\n")
	}))
	defer srv.Close()
	d := upstream.NewDeepSeek(srv.URL, "k", 5*time.Second, 0)
	boom := errors.New("client disconnected")
	if _, err := d.ChatStream(context.Background(), upstream.ChatRequest{}, func(string) error { return boom }); !errors.Is(err, boom) {
		t.Fatalf("onDelta 错误应原样返回,实际 %v", err)
	}
}

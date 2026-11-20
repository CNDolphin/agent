package upstream

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// DeepSeek 是 OpenAI/DeepSeek 兼容 chat/completions 的适配器。
type DeepSeek struct {
	BaseURL    string
	APIKey     string
	Client     *http.Client
	MaxRetries int
	Backoff    time.Duration
}

// NewDeepSeek 创建 DeepSeek 适配器。密钥只从环境变量注入。
func NewDeepSeek(baseURL, apiKey string, timeout time.Duration, maxRetries int) *DeepSeek {
	if strings.TrimSpace(baseURL) == "" {
		baseURL = "https://api.deepseek.com"
	}
	baseURL = strings.TrimRight(baseURL, "/")
	if timeout <= 0 {
		timeout = 60 * time.Second
	}
	if maxRetries < 0 {
		maxRetries = 0
	}
	return &DeepSeek{
		BaseURL:    baseURL,
		APIKey:     apiKey,
		Client:     &http.Client{Timeout: timeout},
		MaxRetries: maxRetries,
		Backoff:    20 * time.Millisecond,
	}
}

type thinkingOption struct {
	Type string `json:"type"`
}

type streamOptions struct {
	IncludeUsage bool `json:"include_usage"`
}

type chatRequestBody struct {
	Model         string         `json:"model"`
	Messages      []Message      `json:"messages"`
	MaxTokens     int            `json:"max_tokens"`
	Stream        bool           `json:"stream,omitempty"`
	Thinking      thinkingOption `json:"thinking"`
	UserID        string         `json:"user_id,omitempty"`
	StreamOptions *streamOptions `json:"stream_options,omitempty"`
}

type usageBody struct {
	PromptCacheHitTokens  int64 `json:"prompt_cache_hit_tokens"`
	PromptCacheMissTokens int64 `json:"prompt_cache_miss_tokens"`
	CompletionTokens      int64 `json:"completion_tokens"`
}

func (u usageBody) toUsage() Usage {
	return Usage{InputHit: u.PromptCacheHitTokens, InputMiss: u.PromptCacheMissTokens, Output: u.CompletionTokens}
}

type chatResponseBody struct {
	Choices []struct {
		Message struct {
			Content          string `json:"content"`
			ReasoningContent string `json:"reasoning_content"`
		} `json:"message"`
		FinishReason string `json:"finish_reason"`
	} `json:"choices"`
	Usage usageBody `json:"usage"`
}

type streamChunkBody struct {
	Choices []struct {
		Delta struct {
			Content          string `json:"content"`
			ReasoningContent string `json:"reasoning_content"`
		} `json:"delta"`
		FinishReason string `json:"finish_reason"`
	} `json:"choices"`
	Usage *usageBody `json:"usage"`
}

func (d *DeepSeek) buildRequest(ctx context.Context, req ChatRequest, stream bool) (*http.Request, error) {
	body := chatRequestBody{
		Model:     req.Model,
		Messages:  req.Messages,
		MaxTokens: req.MaxTokens,
		Stream:    stream,
		Thinking:  thinkingOption{Type: "disabled"},
		UserID:    req.UserTag,
	}
	if req.Thinking == "enabled" {
		body.Thinking.Type = "enabled"
	}
	if stream {
		body.StreamOptions = &streamOptions{IncludeUsage: true}
	}
	raw, err := json.Marshal(body)
	if err != nil {
		return nil, fmt.Errorf("序列化上游请求失败: %w", err)
	}
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, d.BaseURL+"/chat/completions", bytes.NewReader(raw))
	if err != nil {
		return nil, fmt.Errorf("创建上游请求失败: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Authorization", "Bearer "+d.APIKey)
	return httpReq, nil
}

func errorForStatus(status int) error {
	switch status {
	case http.StatusUnauthorized:
		return ErrUpstreamAuth
	case http.StatusPaymentRequired:
		return ErrUpstreamBalance
	case http.StatusTooManyRequests:
		return ErrUpstreamRateLimit
	case http.StatusBadRequest, http.StatusUnprocessableEntity:
		return ErrUpstreamBadReq
	case http.StatusInternalServerError, http.StatusServiceUnavailable, http.StatusBadGateway, http.StatusGatewayTimeout:
		return ErrUpstreamBusy
	default:
		if status >= 500 {
			return ErrUpstreamBusy
		}
		return ErrUpstreamBadReq
	}
}

func retryable(err error) bool {
	if errors.Is(err, errFinishAborted) {
		return false
	}
	return errors.Is(err, ErrUpstreamRateLimit) || errors.Is(err, ErrUpstreamBusy)
}

// errFinishAborted 标记上游已返回内容但 finish_reason 为失败,不应重试。
var errFinishAborted = fmt.Errorf("%w: finish reason aborted", ErrUpstreamBusy)

func (d *DeepSeek) backoff(ctx context.Context, attempt int) error {
	if attempt <= 0 {
		return nil
	}
	wait := d.Backoff
	if wait <= 0 {
		wait = 20 * time.Millisecond
	}
	for i := 1; i < attempt; i++ {
		wait *= 2
	}
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-time.After(wait):
		return nil
	}
}

// Chat 非流式调用。只对 429/500/503 重试,最多 MaxRetries 次。
func (d *DeepSeek) Chat(ctx context.Context, req ChatRequest) (string, Usage, error) {
	var lastErr error
	for attempt := 0; attempt <= d.MaxRetries; attempt++ {
		if err := d.backoff(ctx, attempt); err != nil {
			return "", Usage{}, err
		}
		content, usage, err := d.chatOnce(ctx, req)
		if err == nil {
			return content, usage, nil
		}
		lastErr = err
		if !retryable(err) {
			// 已产生的内容与 usage 必须保留,便于上层按部分结果结算。
			return content, usage, err
		}
	}
	return "", Usage{}, lastErr
}

func (d *DeepSeek) chatOnce(ctx context.Context, req ChatRequest) (string, Usage, error) {
	httpReq, err := d.buildRequest(ctx, req, false)
	if err != nil {
		return "", Usage{}, err
	}
	resp, err := d.Client.Do(httpReq)
	if err != nil {
		if ctx.Err() != nil {
			return "", Usage{}, ctx.Err()
		}
		return "", Usage{}, ErrUpstreamBusy
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
		return "", Usage{}, errorForStatus(resp.StatusCode)
	}
	var parsed chatResponseBody
	if err := json.NewDecoder(resp.Body).Decode(&parsed); err != nil {
		return "", Usage{}, ErrUpstreamBusy
	}
	usage := parsed.Usage.toUsage()
	if len(parsed.Choices) == 0 {
		return "", usage, ErrUpstreamBusy
	}
	choice := parsed.Choices[0]
	if choice.FinishReason == "insufficient_system_resource" || choice.FinishReason == "aborted" {
		return choice.Message.Content, usage, errFinishAborted
	}
	return choice.Message.Content, usage, nil
}

// ChatStream 流式调用;reasoning_content 不转发。usage 取自 [DONE] 前的最后一个 chunk。
func (d *DeepSeek) ChatStream(ctx context.Context, req ChatRequest, onDelta func(string) error) (Usage, error) {
	var lastErr error
	for attempt := 0; attempt <= d.MaxRetries; attempt++ {
		if err := d.backoff(ctx, attempt); err != nil {
			return Usage{}, err
		}
		usage, emitted, err := d.streamOnce(ctx, req, onDelta)
		if err == nil {
			return usage, nil
		}
		lastErr = err
		// 仅在尚未输出任何内容时透明重试。
		if emitted || !retryable(err) {
			return usage, err
		}
	}
	return Usage{}, lastErr
}

func (d *DeepSeek) streamOnce(ctx context.Context, req ChatRequest, onDelta func(string) error) (Usage, bool, error) {
	httpReq, err := d.buildRequest(ctx, req, true)
	if err != nil {
		return Usage{}, false, err
	}
	resp, err := d.Client.Do(httpReq)
	if err != nil {
		if ctx.Err() != nil {
			return Usage{}, false, ctx.Err()
		}
		return Usage{}, false, ErrUpstreamBusy
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
		return Usage{}, false, errorForStatus(resp.StatusCode)
	}

	var usage Usage
	var hasUsage bool
	var emitted bool
	sawDone := false
	reader := bufio.NewReader(resp.Body)
	for {
		line, readErr := reader.ReadString('\n')
		if line != "" {
			trimmed := strings.TrimSpace(line)
			if strings.HasPrefix(trimmed, "data:") {
				payload := strings.TrimSpace(strings.TrimPrefix(trimmed, "data:"))
				if payload == "[DONE]" {
					sawDone = true
					break
				}
				if payload != "" {
					var chunk streamChunkBody
					if err := json.Unmarshal([]byte(payload), &chunk); err == nil {
						if chunk.Usage != nil {
							usage = chunk.Usage.toUsage()
							hasUsage = true
						}
						for _, c := range chunk.Choices {
							if c.Delta.Content != "" {
								if err := onDelta(c.Delta.Content); err != nil {
									return usage, emitted, err
								}
								emitted = true
							}
							if c.FinishReason == "insufficient_system_resource" || c.FinishReason == "aborted" {
								return usage, emitted, ErrUpstreamBusy
							}
						}
					}
				}
			}
		}
		if readErr != nil {
			if readErr == io.EOF {
				break
			}
			if ctx.Err() != nil {
				return usage, emitted, ctx.Err()
			}
			return usage, emitted, ErrUpstreamInterrupted
		}
		if ctx.Err() != nil {
			return usage, emitted, ctx.Err()
		}
	}
	if !sawDone {
		return usage, emitted, ErrUpstreamInterrupted
	}
	if !hasUsage {
		return Usage{}, emitted, ErrUpstreamInterrupted
	}
	return usage, emitted, nil
}

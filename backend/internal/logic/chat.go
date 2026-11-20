package logic

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"mhagent/internal/apierr"
	"mhagent/internal/audit"
	"mhagent/internal/credits"
	"mhagent/internal/svc"
	"mhagent/internal/upstream"
)

// ChatRequest 对话入参。消息正文只用于转发,绝不落库或写日志。
type ChatRequest struct {
	Model     string             `json:"model"`
	Messages  []upstream.Message `json:"messages"`
	MaxTokens int                `json:"max_tokens"`
	Stream    bool               `json:"stream"`
}

// ChatResult 非流式结果。
type ChatResult struct {
	Content    string
	Usage      upstream.Usage
	Cost       int64
	Balance    int64
	LowBalance bool
}

// ChatLogic 对话计费逻辑。
type ChatLogic struct {
	sc *svc.ServiceContext
}

// NewChatLogic 创建对话逻辑。
func NewChatLogic(sc *svc.ServiceContext) *ChatLogic { return &ChatLogic{sc: sc} }

type preparedChat struct {
	model       string
	price       credits.Price
	maxTokens   int
	inputChars  int64
	hold        int64
	upstreamReq upstream.ChatRequest
}

func (l *ChatLogic) prepare(ctx context.Context, userID int64, req ChatRequest) (preparedChat, error) {
	if strings.TrimSpace(req.Model) == "" {
		return preparedChat{}, apierr.BadRequest("model 不能为空")
	}
	if len(req.Messages) == 0 {
		return preparedChat{}, apierr.BadRequest("messages 不能为空")
	}
	if len(req.Messages) > 200 {
		return preparedChat{}, apierr.BadRequest("messages 过多")
	}
	var inputChars int64
	for _, m := range req.Messages {
		switch m.Role {
		case "system", "user", "assistant":
		default:
			return preparedChat{}, apierr.BadRequest("messages.role 非法")
		}
		if strings.TrimSpace(m.Content) == "" {
			return preparedChat{}, apierr.BadRequest("messages.content 不能为空")
		}
		inputChars += int64(len([]rune(m.Content)))
	}
	if req.MaxTokens < 0 {
		return preparedChat{}, apierr.BadRequest("max_tokens 非法")
	}
	cfg, err := l.sc.Prices.Get(ctx, req.Model)
	if err != nil {
		if errors.Is(err, credits.ErrUnknownModel) {
			return preparedChat{}, apierr.BadRequest("模型不存在或未启用")
		}
		return preparedChat{}, apierr.Internal()
	}
	maxTokens := req.MaxTokens
	if maxTokens <= 0 || maxTokens > cfg.MaxTokensCap {
		maxTokens = cfg.MaxTokensCap
	}
	hold := credits.EstimateHold(cfg.Price, inputChars, int64(maxTokens))
	upReq := upstream.ChatRequest{
		Model:     req.Model,
		Messages:  req.Messages,
		MaxTokens: maxTokens,
		Thinking:  cfg.Thinking,
		UserTag:   l.userTag(userID),
	}
	return preparedChat{
		model: req.Model, price: cfg.Price, maxTokens: maxTokens,
		inputChars: inputChars, hold: hold, upstreamReq: upReq,
	}, nil
}

// userTag 生成不含明文用户标识的稳定伪名。
func (l *ChatLogic) userTag(userID int64) string {
	mac := hmac.New(sha256.New, []byte(l.sc.Secrets.PhonePepper))
	mac.Write([]byte(fmt.Sprintf("user:%d", userID)))
	return hex.EncodeToString(mac.Sum(nil))[:24]
}

func (l *ChatLogic) existingCost(ctx context.Context, userID int64, requestID string) (int64, bool, error) {
	var cost int64
	err := l.sc.DB.QueryRowContext(ctx,
		`SELECT cost FROM usage_logs WHERE user_id=$1 AND request_id=$2`, userID, requestID).Scan(&cost)
	if errors.Is(err, sql.ErrNoRows) {
		return 0, false, nil
	}
	if err != nil {
		return 0, false, err
	}
	return cost, true, nil
}

// Chat 非流式对话,先冻结积分,成功后结算。
func (l *ChatLogic) Chat(ctx context.Context, userID int64, requestID string, req ChatRequest) (ChatResult, error) {
	start := time.Now()
	prep, err := l.prepare(ctx, userID, req)
	if err != nil {
		return ChatResult{}, err
	}
	if cost, ok, err := l.existingCost(ctx, userID, requestID); err != nil {
		return ChatResult{}, apierr.Internal()
	} else if ok {
		return ChatResult{}, apierr.DuplicateRequest(cost)
	}
	held := false
	if prep.hold > 0 {
		if err := l.sc.Ledger.Hold(ctx, userID, prep.hold, requestID); err != nil {
			switch {
			case errors.Is(err, credits.ErrInsufficient):
				return ChatResult{}, apierr.InsufficientCredits()
			case errors.Is(err, credits.ErrAlreadyFinalized):
				cost, _, _ := l.existingCost(ctx, userID, requestID)
				return ChatResult{}, apierr.DuplicateRequest(cost)
			default:
				return ChatResult{}, apierr.Internal()
			}
		}
		held = true
	}

	content, usage, upErr := l.sc.Upstream.Chat(ctx, prep.upstreamReq)
	if upErr != nil {
		if held {
			_ = l.sc.Ledger.Release(ctx, userID, requestID)
		}
		l.auditUpstreamFailure(ctx, upErr)
		return ChatResult{}, apierr.Upstream("上游模型服务暂时不可用")
	}

	cost := credits.Cost(prep.price, usage.InputHit, usage.InputMiss, usage.Output)
	consumed := int64(0)
	if held {
		consumed, err = l.sc.Ledger.Settle(ctx, userID, requestID, cost)
		if err != nil {
			return ChatResult{}, apierr.Internal()
		}
	}
	finalCost := cost
	if held {
		finalCost = consumed
	}

	partial := false
	latency := int(time.Since(start).Milliseconds())
	if err := l.insertUsage(ctx, userID, requestID, prep.model, usage, finalCost, partial, latency); err != nil {
		// 并发重复请求:唯一约束冲突时按契约返回首次 cost。
		if cost, ok, lookupErr := l.existingCost(ctx, userID, requestID); lookupErr == nil && ok {
			return ChatResult{}, apierr.DuplicateRequest(cost)
		}
		return ChatResult{}, apierr.Internal()
	}
	bal, err := l.sc.Ledger.Balance(ctx, userID)
	if err != nil {
		return ChatResult{}, apierr.Internal()
	}
	return ChatResult{
		Content:    content,
		Usage:      usage,
		Cost:       finalCost,
		Balance:    bal.Available(),
		LowBalance: bal.Available() < l.sc.Config.Credits.LowBalanceThreshold,
	}, nil
}

func (l *ChatLogic) insertUsage(ctx context.Context, userID int64, requestID, model string, u upstream.Usage, cost int64, partial bool, latencyMS int) error {
	_, err := l.sc.DB.ExecContext(ctx,
		`INSERT INTO usage_logs (user_id, request_id, model, in_hit, in_miss, out_tokens, cost, partial, latency_ms, created_at)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`,
		userID, requestID, model, u.InputHit, u.InputMiss, u.Output, cost, partial, latencyMS, l.sc.Now().UTC())
	return err
}

func (l *ChatLogic) auditUpstreamFailure(ctx context.Context, err error) {
	if l.sc.Audit == nil {
		return
	}
	reason := "other"
	switch {
	case errors.Is(err, upstream.ErrUpstreamAuth):
		reason = "auth"
	case errors.Is(err, upstream.ErrUpstreamBalance):
		reason = "balance"
	case errors.Is(err, upstream.ErrUpstreamRateLimit):
		reason = "rate_limit"
	case errors.Is(err, upstream.ErrUpstreamBusy):
		reason = "busy"
	case errors.Is(err, upstream.ErrUpstreamBadReq):
		reason = "bad_request"
	}
	l.sc.Audit.Quiet(ctx, audit.ActorSystem, 0, audit.EventUpstreamFatal,
		audit.NewDetail().Enum("reason", reason))
}

// streamState 保证结算与 usage_logs 只执行一次。
type streamState struct {
	settled bool
}

func (l *ChatLogic) finalizeStream(ctx context.Context, userID int64, requestID, model string, prep preparedChat, held bool,
	state *streamState, u upstream.Usage, partial bool, latencyMS int) (int64, int64, error) {
	if state.settled {
		_, err := l.sc.Ledger.Balance(ctx, userID)
		return 0, 0, err
	}
	state.settled = true
	cost := credits.Cost(prep.price, u.InputHit, u.InputMiss, u.Output)
	finalCost := cost
	if held {
		consumed, err := l.sc.Ledger.Settle(ctx, userID, requestID, cost)
		if err != nil {
			return 0, 0, err
		}
		finalCost = consumed
	}
	if err := l.insertUsage(ctx, userID, requestID, model, u, finalCost, partial, latencyMS); err != nil {
		// 已写过 usage 时保持幂等,不覆盖。
		if _, ok, lookupErr := l.existingCost(ctx, userID, requestID); lookupErr != nil || !ok {
			return 0, 0, err
		}
	}
	bal, err := l.sc.Ledger.Balance(ctx, userID)
	if err != nil {
		return 0, 0, err
	}
	return finalCost, bal.Available(), nil
}

// ChatStream 处理 SSE 流式对话。写头之前完成鉴权、校验、冻结与幂等检查。
func (l *ChatLogic) ChatStream(w http.ResponseWriter, r *http.Request, userID int64, requestID string, req ChatRequest) {
	start := time.Now()
	ctx := r.Context()
	prep, err := l.prepare(ctx, userID, req)
	if err != nil {
		apierr.WriteError(w, err)
		return
	}
	if cost, ok, err := l.existingCost(ctx, userID, requestID); err != nil {
		apierr.WriteError(w, apierr.Internal())
		return
	} else if ok {
		apierr.WriteError(w, apierr.DuplicateRequest(cost))
		return
	}
	held := false
	if prep.hold > 0 {
		if err := l.sc.Ledger.Hold(ctx, userID, prep.hold, requestID); err != nil {
			switch {
			case errors.Is(err, credits.ErrInsufficient):
				apierr.WriteError(w, apierr.InsufficientCredits())
			case errors.Is(err, credits.ErrAlreadyFinalized):
				cost, _, _ := l.existingCost(ctx, userID, requestID)
				apierr.WriteError(w, apierr.DuplicateRequest(cost))
			default:
				apierr.WriteError(w, apierr.Internal())
			}
			return
		}
		held = true
	}

	w.Header().Set("Content-Type", "text/event-stream; charset=utf-8")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)
	flusher, _ := w.(http.Flusher)
	if flusher != nil {
		flusher.Flush()
	}

	state := &streamState{}
	var emittedChars int64
	var usage upstream.Usage
	var streamErr error
	emit := func(text string) error {
		emittedChars += int64(len([]rune(text)))
		return writeSSE(w, flusher, "delta", map[string]any{"text": text})
	}

	upCtx := ctx
	usage, streamErr = l.sc.Upstream.ChatStream(upCtx, prep.upstreamReq, emit)

	// 上游在尚未输出任何内容时失败(429/503):透明重试一次,不重复扣费。
	if streamErr != nil && emittedChars == 0 &&
		(errors.Is(streamErr, upstream.ErrUpstreamBusy) || errors.Is(streamErr, upstream.ErrUpstreamRateLimit)) {
		usage, streamErr = l.sc.Upstream.ChatStream(upCtx, prep.upstreamReq, emit)
	}

	latency := int(time.Since(start).Milliseconds())
	usageKnown := usage.InputHit > 0 || usage.InputMiss > 0 || usage.Output > 0
	partial := streamErr != nil || !usageKnown
	if usageKnown {
		// 上游只回报部分用量时(如客户端断开),缺失的输入/输出按本地估算补齐,避免少计费。
		if usage.InputHit == 0 && usage.InputMiss == 0 {
			usage.InputMiss = prep.inputChars
		}
		if usage.Output == 0 {
			usage.Output = emittedChars
		}
	} else {
		usage = upstream.Usage{InputMiss: prep.inputChars, Output: emittedChars}
	}

	// 客户端断开时 request ctx 已取消,结算必须使用脱离取消的短超时上下文。
	settleCtx, cancelSettle := context.WithTimeout(context.WithoutCancel(ctx), 15*time.Second)
	defer cancelSettle()
	finalCost, balance, finErr := l.finalizeStream(settleCtx, userID, requestID, prep.model, prep, held, state, usage, partial, latency)
	if finErr != nil {
		l.sendSSEError(w, flusher, apierr.Internal())
		return
	}

	if streamErr != nil {
		l.auditUpstreamFailure(settleCtx, streamErr)
		// 客户端取消时不再写事件;其余情况返回契约 error 事件。
		if ctx.Err() == nil {
			l.sendSSEError(w, flusher, apierr.Upstream("上游模型服务中断,已按已产生用量结算"))
		}
		return
	}

	_ = writeSSE(w, flusher, "done", map[string]any{
		"usage": map[string]int64{
			"input_hit":  usage.InputHit,
			"input_miss": usage.InputMiss,
			"output":     usage.Output,
		},
		"cost":    finalCost,
		"balance": balance,
	})
}

func (l *ChatLogic) sendSSEError(w http.ResponseWriter, flusher http.Flusher, e *apierr.Error) {
	_ = writeSSE(w, flusher, "error", map[string]any{"code": e.Code, "message": e.Message})
}

func writeSSE(w http.ResponseWriter, flusher http.Flusher, event string, data any) error {
	raw, err := json.Marshal(data)
	if err != nil {
		return err
	}
	if _, err := fmt.Fprintf(w, "event: %s\ndata: %s\n\n", event, raw); err != nil {
		return err
	}
	if flusher != nil {
		flusher.Flush()
	}
	return nil
}

package logic

import (
	"context"
	"strconv"
	"time"

	"mhagent/internal/apierr"
	"mhagent/internal/credits"
	"mhagent/internal/svc"
)

// CreditsLogic 积分查询。
type CreditsLogic struct {
	sc *svc.ServiceContext
}

// NewCreditsLogic 创建积分逻辑。
func NewCreditsLogic(sc *svc.ServiceContext) *CreditsLogic { return &CreditsLogic{sc: sc} }

// Balance 读取余额。
func (l *CreditsLogic) Balance(ctx context.Context, userID int64) (credits.Balance, error) {
	b, err := l.sc.Ledger.Balance(ctx, userID)
	if err != nil {
		return credits.Balance{}, apierr.Internal()
	}
	return b, nil
}

// LedgerItem 流水响应项。
type LedgerItem struct {
	Type      string `json:"type"`
	Amount    int64  `json:"amount"`
	CreatedAt string `json:"created_at"`
}

// LedgerResult 分页结果。
type LedgerResult struct {
	Items      []LedgerItem `json:"items"`
	NextCursor int64        `json:"next_cursor"`
}

// Ledger 读取流水(倒序游标分页)。
func (l *CreditsLogic) Ledger(ctx context.Context, userID int64, cursorRaw string, limitRaw string) (LedgerResult, error) {
	var beforeID int64
	if cursorRaw != "" {
		v, err := strconv.ParseInt(cursorRaw, 10, 64)
		if err != nil || v < 0 {
			return LedgerResult{}, apierr.BadRequest("cursor 非法")
		}
		beforeID = v
	}
	limit := 20
	if limitRaw != "" {
		v, err := strconv.Atoi(limitRaw)
		if err != nil || v <= 0 || v > 100 {
			return LedgerResult{}, apierr.BadRequest("limit 非法")
		}
		limit = v
	}
	entries, err := credits.ListEntries(ctx, l.sc.DB, userID, beforeID, limit)
	if err != nil {
		return LedgerResult{}, apierr.Internal()
	}
	res := LedgerResult{Items: make([]LedgerItem, 0, len(entries))}
	for _, e := range entries {
		res.Items = append(res.Items, LedgerItem{
			Type:      e.Type,
			Amount:    e.Amount,
			CreatedAt: e.CreatedAt.UTC().Format(time.RFC3339),
		})
	}
	if len(entries) == limit {
		res.NextCursor = entries[len(entries)-1].ID
	}
	return res, nil
}

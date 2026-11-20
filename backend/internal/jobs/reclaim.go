// Package jobs 提供后台定时任务。
package jobs

import (
	"context"
	"database/sql"
	"time"

	"github.com/zeromicro/go-zero/core/logx"

	"mhagent/internal/audit"
	"mhagent/internal/credits"
)

// ReclaimHolds 回收超过 cutoff 未结算的 hold,按 Release 处理并写审计。
func ReclaimHolds(ctx context.Context, db *sql.DB, ledger credits.Ledger, auditor *audit.Logger, cutoff time.Duration, now func() time.Time) (int, error) {
	if now == nil {
		now = time.Now
	}
	deadline := now().Add(-cutoff).UTC()
	rows, err := db.QueryContext(ctx,
		`SELECT l.user_id, l.request_id
		 FROM credit_ledger l
		 WHERE l.type='hold' AND l.user_id > 0 AND l.created_at < $1
		   AND NOT EXISTS (
		     SELECT 1 FROM credit_ledger x
		     WHERE x.user_id=l.user_id AND x.request_id=l.request_id AND x.type IN ('consume','release')
		   )
		 ORDER BY l.id ASC LIMIT 500`, deadline)
	if err != nil {
		return 0, err
	}
	type pending struct {
		userID    int64
		requestID string
	}
	var items []pending
	for rows.Next() {
		var p pending
		if err := rows.Scan(&p.userID, &p.requestID); err != nil {
			rows.Close()
			return 0, err
		}
		items = append(items, p)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}

	reclaimed := 0
	for _, p := range items {
		if err := ledger.Release(ctx, p.userID, p.requestID); err != nil {
			logx.Errorf("回收悬挂 hold 失败: %v", err)
			continue
		}
		reclaimed++
		if auditor != nil {
			auditor.Quiet(ctx, audit.ActorSystem, 0, audit.EventHoldReclaim,
				audit.NewDetail().Int("user_id", p.userID).Int("count", 1))
		}
	}
	return reclaimed, nil
}

// StartHoldReclaimer 每秒触发一次的常驻任务,按间隔扫描。
func StartHoldReclaimer(ctx context.Context, db *sql.DB, ledger credits.Ledger, auditor *audit.Logger, cutoff, interval time.Duration) {
	if interval <= 0 {
		interval = 5 * time.Minute
	}
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				if n, err := ReclaimHolds(ctx, db, ledger, auditor, cutoff, time.Now); err != nil {
					logx.Errorf("悬挂 hold 回收任务失败: %v", err)
				} else if n > 0 {
					logx.Infof("悬挂 hold 回收完成: %d 条", n)
				}
			}
		}
	}()
}

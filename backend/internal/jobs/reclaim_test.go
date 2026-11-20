package jobs_test

import (
	"context"
	"database/sql"
	"testing"
	"time"

	"mhagent/internal/audit"
	"mhagent/internal/credits"
	"mhagent/internal/jobs"
	"mhagent/internal/model"
	"mhagent/internal/testdb"
)

var testNow = time.Date(2026, 11, 6, 12, 0, 0, 0, time.UTC)

func setupJobs(t *testing.T) (*sql.DB, *credits.PGLedger, *audit.Logger, int64) {
	t.Helper()
	db := testdb.New(t)
	if err := model.MigrateUp(context.Background(), db); err != nil {
		t.Fatalf("迁移失败: %v", err)
	}
	var uid int64
	if err := db.QueryRow(`INSERT INTO users (phone_hash, phone_mask) VALUES ('h1','138****0000') RETURNING id`).Scan(&uid); err != nil {
		t.Fatalf("插入用户失败: %v", err)
	}
	ledger := credits.NewPGLedger(db)
	ledger.Now = func() time.Time { return testNow }
	auditor := audit.New(db)
	auditor.Now = func() time.Time { return testNow }
	return db, ledger, auditor, uid
}

func TestReclaimStaleHolds(t *testing.T) {
	db, ledger, auditor, uid := setupJobs(t)
	ctx := context.Background()
	if err := ledger.Credit(ctx, uid, 100, "grant", "g1"); err != nil {
		t.Fatalf("入账失败: %v", err)
	}
	if err := ledger.Hold(ctx, uid, 30, "stale-req"); err != nil {
		t.Fatalf("冻结失败: %v", err)
	}
	// 把 hold 的时间回拨到 1 小时前,模拟悬挂。
	if _, err := db.Exec(`UPDATE credit_ledger SET created_at=$2 WHERE user_id=$1 AND request_id='stale-req' AND type='hold'`,
		uid, testNow.Add(-time.Hour)); err != nil {
		t.Fatalf("回拨时间失败: %v", err)
	}

	n, err := jobs.ReclaimHolds(ctx, db, ledger, auditor, 10*time.Minute, func() time.Time { return testNow })
	if err != nil {
		t.Fatalf("回收失败: %v", err)
	}
	if n != 1 {
		t.Fatalf("期望回收 1 条,实际 %d", n)
	}
	b, err := ledger.Balance(ctx, uid)
	if err != nil {
		t.Fatalf("读取余额失败: %v", err)
	}
	if b.Balance != 100 || b.Held != 0 {
		t.Fatalf("回收后 held 应归零: %+v", b)
	}

	// 重复回收不应再次产生流水。
	n, err = jobs.ReclaimHolds(ctx, db, ledger, auditor, 10*time.Minute, func() time.Time { return testNow })
	if err != nil || n != 0 {
		t.Fatalf("重复回收期望 0 条,实际 %d %v", n, err)
	}

	var holds int
	if err := db.QueryRow(`SELECT count(*) FROM audit_logs WHERE event='system.hold_reclaim'`).Scan(&holds); err != nil {
		t.Fatalf("统计审计失败: %v", err)
	}
	if holds != 1 {
		t.Fatalf("期望 1 条回收审计,实际 %d", holds)
	}
}

func TestReclaimSkipsFreshHolds(t *testing.T) {
	db, ledger, auditor, uid := setupJobs(t)
	ctx := context.Background()
	if err := ledger.Credit(ctx, uid, 100, "grant", "g1"); err != nil {
		t.Fatalf("入账失败: %v", err)
	}
	if err := ledger.Hold(ctx, uid, 30, "fresh-req"); err != nil {
		t.Fatalf("冻结失败: %v", err)
	}
	n, err := jobs.ReclaimHolds(ctx, db, ledger, auditor, 10*time.Minute, func() time.Time { return testNow })
	if err != nil {
		t.Fatalf("回收失败: %v", err)
	}
	if n != 0 {
		t.Fatalf("未超时的 hold 不应被回收,实际 %d", n)
	}
	b, _ := ledger.Balance(ctx, uid)
	if b.Held != 30 {
		t.Fatalf("未超时 hold 应保留: %+v", b)
	}
}

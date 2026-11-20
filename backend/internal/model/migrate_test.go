package model

import (
	"context"
	"database/sql"
	"testing"

	"mhagent/internal/testdb"
)

var expectedTables = []string{
	"users", "credit_accounts", "credit_ledger", "model_prices", "model_price_history",
	"usage_logs", "consents", "packages", "orders", "notify_logs", "admin_users", "audit_logs",
}

func tableReg(t *testing.T, db *sql.DB, name string) sql.NullString {
	t.Helper()
	var reg sql.NullString
	if err := db.QueryRow(`SELECT to_regclass($1)::text`, name).Scan(&reg); err != nil {
		t.Fatalf("查询表 %s 失败: %v", name, err)
	}
	return reg
}

func TestMigrateUpCreatesTables(t *testing.T) {
	db := testdb.New(t)
	ctx := context.Background()
	if err := MigrateUp(ctx, db); err != nil {
		t.Fatalf("向上迁移失败: %v", err)
	}
	for _, name := range expectedTables {
		if reg := tableReg(t, db, name); !reg.Valid {
			t.Fatalf("表 %s 不存在", name)
		}
	}

	// deepseek-flash 在增量迁移中被启用并写入默认价格;deepseek-v4-pro 保持下架。
	var enabled bool
	var inHit, inMiss, out int64
	if err := db.QueryRowContext(ctx,
		`SELECT enabled, in_hit_per_m, in_miss_per_m, out_per_m FROM model_prices WHERE model='deepseek-flash'`).
		Scan(&enabled, &inHit, &inMiss, &out); err != nil {
		t.Fatalf("读取种子模型失败: %v", err)
	}
	if !enabled || inHit != 100 || inMiss != 200 || out != 800 {
		t.Fatalf("deepseek-flash 应已启用并带默认价格: enabled=%v price=%d/%d/%d", enabled, inHit, inMiss, out)
	}
	var proEnabled bool
	if err := db.QueryRowContext(ctx,
		`SELECT enabled FROM model_prices WHERE model='deepseek-v4-pro'`).Scan(&proEnabled); err != nil {
		t.Fatalf("读取 deepseek-v4-pro 失败: %v", err)
	}
	if proEnabled {
		t.Fatal("deepseek-v4-pro 应保持下架")
	}
}

func TestMigrateDownThenUp(t *testing.T) {
	db := testdb.New(t)
	ctx := context.Background()
	if err := MigrateUp(ctx, db); err != nil {
		t.Fatalf("首次迁移失败: %v", err)
	}
	if err := MigrateDown(ctx, db); err != nil {
		t.Fatalf("向下迁移失败: %v", err)
	}
	if reg := tableReg(t, db, "users"); reg.Valid {
		t.Fatalf("向下迁移后 users 表仍存在")
	}
	if err := MigrateUp(ctx, db); err != nil {
		t.Fatalf("重新迁移失败: %v", err)
	}
}

func TestMigrateConstraints(t *testing.T) {
	db := testdb.New(t)
	ctx := context.Background()
	if err := MigrateUp(ctx, db); err != nil {
		t.Fatalf("迁移失败: %v", err)
	}
	if _, err := db.ExecContext(ctx,
		`INSERT INTO packages (name, price_cents, credits) VALUES ('bad', 100, 0)`); err == nil {
		t.Fatalf("credits<=0 的套餐应被约束拒绝")
	}
	if _, err := db.ExecContext(ctx,
		`INSERT INTO packages (name, price_cents, credits) VALUES ('bad2', -1, 10)`); err == nil {
		t.Fatalf("price_cents<0 的套餐应被约束拒绝")
	}
	if _, err := db.ExecContext(ctx,
		`INSERT INTO packages (name, price_cents, credits) VALUES ('ok', 100, 10)`); err != nil {
		t.Fatalf("合法套餐应可插入: %v", err)
	}
}

func TestEnsureUp(t *testing.T) {
	db := testdb.New(t)
	ctx := context.Background()
	if err := EnsureUp(ctx, db); err != nil {
		t.Fatalf("EnsureUp 首次失败: %v", err)
	}
	if err := EnsureUp(ctx, db); err != nil {
		t.Fatalf("EnsureUp 第二次应幂等: %v", err)
	}
	if reg := tableReg(t, db, "users"); !reg.Valid {
		t.Fatalf("EnsureUp 未创建表")
	}
}

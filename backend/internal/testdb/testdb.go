// Package testdb 为测试提供隔离 schema 的 PostgreSQL 与 miniredis。
package testdb

import (
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"net/url"
	"os"
	"testing"

	"github.com/alicebob/miniredis/v2"
	_ "github.com/lib/pq"
	"github.com/redis/go-redis/v9"
)

// DSN 返回测试数据库连接串;未设置 TEST_DATABASE_URL 时跳过测试。
func DSN(t *testing.T) string {
	t.Helper()
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("未设置 TEST_DATABASE_URL,跳过数据库测试")
	}
	return dsn
}

// New 为当前测试创建独立 schema 并返回连接池,测试结束自动删除 schema。
func New(t *testing.T) *sql.DB {
	t.Helper()
	base := DSN(t)
	admin, err := sql.Open("postgres", base)
	if err != nil {
		t.Fatalf("连接测试库失败: %v", err)
	}
	if err := admin.Ping(); err != nil {
		t.Fatalf("测试库不可用: %v", err)
	}
	schema := randomSchema()
	if _, err := admin.Exec(`CREATE SCHEMA ` + schema); err != nil {
		t.Fatalf("创建 schema 失败: %v", err)
	}

	db, err := sql.Open("postgres", withSearchPath(base, schema))
	if err != nil {
		t.Fatalf("连接隔离 schema 失败: %v", err)
	}
	db.SetMaxOpenConns(20)
	if err := db.Ping(); err != nil {
		t.Fatalf("隔离 schema 不可用: %v", err)
	}
	t.Cleanup(func() {
		_ = db.Close()
		_, _ = admin.Exec(`DROP SCHEMA ` + schema + ` CASCADE`)
		_ = admin.Close()
	})
	return db
}

// Redis 启动当前测试独占的 miniredis。
func Redis(t *testing.T) (*miniredis.Miniredis, *redis.Client) {
	t.Helper()
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	return mr, client
}

// Reset 清空业务数据并恢复价格种子。
func Reset(t *testing.T, db *sql.DB) {
	t.Helper()
	_, err := db.Exec(`TRUNCATE users, credit_accounts, credit_ledger, usage_logs, consents,
		orders, packages, notify_logs, admin_users, audit_logs, model_price_history, model_prices
		RESTART IDENTITY CASCADE`)
	if err != nil {
		t.Fatalf("清空测试数据失败: %v", err)
	}
	_, err = db.Exec(`INSERT INTO model_prices (model, in_hit_per_m, in_miss_per_m, out_per_m, thinking, max_tokens_cap, enabled, version)
		VALUES ('deepseek-flash',0,0,0,'disabled',2048,false,1),
		       ('deepseek-v4-pro',0,0,0,'disabled',2048,false,1)`)
	if err != nil {
		t.Fatalf("恢复价格种子失败: %v", err)
	}
}

func randomSchema() string {
	b := make([]byte, 6)
	_, _ = rand.Read(b)
	return "t_" + hex.EncodeToString(b)
}

func withSearchPath(base, schema string) string {
	u, err := url.Parse(base)
	if err != nil {
		return base
	}
	q := u.Query()
	q.Set("search_path", schema)
	u.RawQuery = q.Encode()
	return u.String()
}

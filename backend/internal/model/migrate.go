// Package model 提供数据访问与数据库迁移能力。
package model

import (
	"context"
	"database/sql"
	"fmt"

	_ "github.com/lib/pq"

	"mhagent/migrations"
)

// Open 打开 PostgreSQL 连接池。dsn 形如 postgres://user:pass@host:port/db?sslmode=disable。
func Open(dsn string, maxOpenConns int) (*sql.DB, error) {
	if dsn == "" {
		return nil, fmt.Errorf("database dsn is empty")
	}
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		return nil, fmt.Errorf("open database: %w", err)
	}
	if maxOpenConns <= 0 {
		maxOpenConns = 20
	}
	db.SetMaxOpenConns(maxOpenConns)
	db.SetMaxIdleConns(maxOpenConns / 2)
	if err := db.Ping(); err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("ping database: %w", err)
	}
	return db, nil
}

// MigrateUp 执行初始化 schema 与增量 schema(均为幂等语句)。
func MigrateUp(ctx context.Context, db *sql.DB) error {
	if _, err := db.ExecContext(ctx, migrations.InitUp); err != nil {
		return err
	}
	if _, err := db.ExecContext(ctx, migrations.AlterUp); err != nil {
		return err
	}
	if _, err := db.ExecContext(ctx, migrations.PriceUp); err != nil {
		return err
	}
	if _, err := db.ExecContext(ctx, migrations.ReportsUp); err != nil {
		return err
	}
	_, err := db.ExecContext(ctx, migrations.ContentUp)
	return err
}

// MigrateDown 删除全部表,仅用于测试。
func MigrateDown(ctx context.Context, db *sql.DB) error {
	if _, err := db.ExecContext(ctx, migrations.ContentDown); err != nil {
		return err
	}
	if _, err := db.ExecContext(ctx, migrations.ReportsDown); err != nil {
		return err
	}
	_, err := db.ExecContext(ctx, migrations.InitDown)
	return err
}

// EnsureUp 若 users 表不存在则执行初始化迁移;已存在时仅执行幂等的增量迁移。
func EnsureUp(ctx context.Context, db *sql.DB) error {
	var reg sql.NullString
	if err := db.QueryRowContext(ctx, `SELECT to_regclass('users')`).Scan(&reg); err != nil {
		return err
	}
	if reg.Valid && reg.String != "" {
		if _, err := db.ExecContext(ctx, migrations.AlterUp); err != nil {
			return err
		}
		if _, err := db.ExecContext(ctx, migrations.PriceUp); err != nil {
			return err
		}
		if _, err := db.ExecContext(ctx, migrations.ReportsUp); err != nil {
			return err
		}
		_, err := db.ExecContext(ctx, migrations.ContentUp)
		return err
	}
	return MigrateUp(ctx, db)
}

// Migrate 先 down 再 up,用于测试与本地重建。
func Migrate(ctx context.Context, db *sql.DB) error {
	if err := MigrateDown(ctx, db); err != nil {
		return err
	}
	return MigrateUp(ctx, db)
}

package credits

import (
	"context"
	"database/sql"
	"errors"
	"testing"
	"time"

	"mhagent/internal/model"
	"mhagent/internal/testdb"
)

func setupPrices(t *testing.T) *sql.DB {
	t.Helper()
	db := testdb.New(t)
	if err := model.MigrateUp(context.Background(), db); err != nil {
		t.Fatalf("执行迁移失败: %v", err)
	}
	return db
}

func enableFlash(t *testing.T, db *sql.DB) {
	t.Helper()
	if _, err := db.Exec(
		`UPDATE model_prices SET in_hit_per_m=100, in_miss_per_m=200, out_per_m=300,
		 thinking='enabled', max_tokens_cap=1024, enabled=true WHERE model='deepseek-flash'`); err != nil {
		t.Fatalf("启用模型失败: %v", err)
	}
}

func TestPriceProviderReturnsEnabledModel(t *testing.T) {
	db := setupPrices(t)
	enableFlash(t, db)
	p := NewPGPriceProvider(db, time.Minute)

	cfg, err := p.Get(context.Background(), "deepseek-flash")
	if err != nil {
		t.Fatalf("读取价格失败: %v", err)
	}
	if cfg.Price != (Price{InHitPerM: 100, InMissPerM: 200, OutPerM: 300}) {
		t.Fatalf("价格不符: %+v", cfg.Price)
	}
	if cfg.Thinking != "enabled" || cfg.MaxTokensCap != 1024 || !cfg.Enabled {
		t.Fatalf("模型配置不符: %+v", cfg)
	}
}

func TestPriceProviderDisabledAndUnknown(t *testing.T) {
	db := setupPrices(t)
	p := NewPGPriceProvider(db, time.Minute)
	ctx := context.Background()

	// 显式下架后应返回 ErrUnknownModel。
	if _, err := db.Exec(`UPDATE model_prices SET enabled=false WHERE model='deepseek-flash'`); err != nil {
		t.Fatalf("下架模型失败: %v", err)
	}
	if _, err := p.Get(ctx, "deepseek-flash"); !errors.Is(err, ErrUnknownModel) {
		t.Fatalf("disabled 模型期望 ErrUnknownModel,实际 %v", err)
	}
	if _, err := p.Get(ctx, "not-exist"); !errors.Is(err, ErrUnknownModel) {
		t.Fatalf("未知模型期望 ErrUnknownModel,实际 %v", err)
	}

	// disabled 不进入缓存:启用后立即可读。
	enableFlash(t, db)
	cfg, err := p.Get(ctx, "deepseek-flash")
	if err != nil {
		t.Fatalf("启用后应立即可读: %v", err)
	}
	if cfg.Price.OutPerM != 300 {
		t.Fatalf("价格不符: %+v", cfg)
	}
}

func TestPriceProviderCacheTTL(t *testing.T) {
	db := setupPrices(t)
	enableFlash(t, db)
	now := time.Now()
	p := NewPGPriceProvider(db, 50*time.Millisecond)
	p.Now = func() time.Time { return now }
	ctx := context.Background()

	if _, err := p.Get(ctx, "deepseek-flash"); err != nil {
		t.Fatalf("首次读取失败: %v", err)
	}
	if _, err := db.Exec(`UPDATE model_prices SET out_per_m=999 WHERE model='deepseek-flash'`); err != nil {
		t.Fatalf("改价失败: %v", err)
	}
	if cfg, err := p.Get(ctx, "deepseek-flash"); err != nil || cfg.Price.OutPerM != 300 {
		t.Fatalf("TTL 内应命中缓存(300),实际 %+v %v", cfg.Price, err)
	}
	now = now.Add(60 * time.Millisecond)
	if cfg, err := p.Get(ctx, "deepseek-flash"); err != nil || cfg.Price.OutPerM != 999 {
		t.Fatalf("TTL 过后应读到新价(999),实际 %+v %v", cfg.Price, err)
	}
}

func TestPriceProviderInvalidate(t *testing.T) {
	db := setupPrices(t)
	enableFlash(t, db)
	p := NewPGPriceProvider(db, time.Hour)
	ctx := context.Background()
	if _, err := p.Get(ctx, "deepseek-flash"); err != nil {
		t.Fatalf("首次读取失败: %v", err)
	}
	if _, err := db.Exec(`UPDATE model_prices SET out_per_m=777 WHERE model='deepseek-flash'`); err != nil {
		t.Fatalf("改价失败: %v", err)
	}
	if cfg, _ := p.Get(ctx, "deepseek-flash"); cfg.Price.OutPerM != 300 {
		t.Fatalf("应命中缓存: %+v", cfg.Price)
	}
	p.Invalidate()
	if cfg, err := p.Get(ctx, "deepseek-flash"); err != nil || cfg.Price.OutPerM != 777 {
		t.Fatalf("Invalidate 后应立即可见新价: %+v %v", cfg.Price, err)
	}
}

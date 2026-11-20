package credits

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"sync"
	"time"
)

// ErrUnknownModel 未配置或未启用的模型。
var ErrUnknownModel = errors.New("unknown model")

// ModelConfig 模型运行配置。
type ModelConfig struct {
	Model        string
	Price        Price
	Thinking     string // enabled|disabled
	MaxTokensCap int
	Enabled      bool
	Version      int
}

// PriceProvider 读取模型价格,带进程内缓存。
type PriceProvider interface {
	Get(ctx context.Context, model string) (ModelConfig, error)
	Invalidate()
}

type cachedPrice struct {
	cfg  ModelConfig
	seen time.Time
}

// PGPriceProvider 从 model_prices 读取,TTL 内复用缓存。
type PGPriceProvider struct {
	DB  *sql.DB
	TTL time.Duration
	Now func() time.Time

	mu    sync.RWMutex
	cache map[string]cachedPrice
}

// NewPGPriceProvider 创建价格读取器。
func NewPGPriceProvider(db *sql.DB, ttl time.Duration) *PGPriceProvider {
	if ttl <= 0 {
		ttl = 30 * time.Second
	}
	return &PGPriceProvider{DB: db, TTL: ttl, Now: time.Now, cache: map[string]cachedPrice{}}
}

func (p *PGPriceProvider) now() time.Time {
	if p.Now != nil {
		return p.Now()
	}
	return time.Now()
}

// Get 返回启用模型的配置;未知或 disabled 返回 ErrUnknownModel。
func (p *PGPriceProvider) Get(ctx context.Context, model string) (ModelConfig, error) {
	p.mu.RLock()
	if c, ok := p.cache[model]; ok && p.now().Sub(c.seen) < p.TTL {
		p.mu.RUnlock()
		if !c.cfg.Enabled {
			return ModelConfig{}, ErrUnknownModel
		}
		return c.cfg, nil
	}
	p.mu.RUnlock()

	var cfg ModelConfig
	var enabled bool
	err := p.DB.QueryRowContext(ctx,
		`SELECT model, in_hit_per_m, in_miss_per_m, out_per_m, thinking, max_tokens_cap, enabled, version
		 FROM model_prices WHERE model=$1`, model).
		Scan(&cfg.Model, &cfg.Price.InHitPerM, &cfg.Price.InMissPerM, &cfg.Price.OutPerM,
			&cfg.Thinking, &cfg.MaxTokensCap, &enabled, &cfg.Version)
	if errors.Is(err, sql.ErrNoRows) {
		return ModelConfig{}, ErrUnknownModel
	}
	if err != nil {
		return ModelConfig{}, fmt.Errorf("read model price: %w", err)
	}
	cfg.Enabled = enabled
	if !enabled {
		return ModelConfig{}, ErrUnknownModel
	}

	p.mu.Lock()
	p.cache[model] = cachedPrice{cfg: cfg, seen: p.now()}
	p.mu.Unlock()
	return cfg, nil
}

// Invalidate 清空缓存;管理端改价后调用。
func (p *PGPriceProvider) Invalidate() {
	p.mu.Lock()
	p.cache = map[string]cachedPrice{}
	p.mu.Unlock()
}

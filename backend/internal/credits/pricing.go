// Package credits 提供整数定价与只增不改的积分账本。
package credits

// Price 单位:积分 / 百万 token,整数。
type Price struct {
	InHitPerM  int64
	InMissPerM int64
	OutPerM    int64
}

// Million 公式分母。
const Million = 1_000_000

// Cost 计算实际消耗,向上取整。
func Cost(p Price, hit, miss, out int64) int64 {
	if hit < 0 {
		hit = 0
	}
	if miss < 0 {
		miss = 0
	}
	if out < 0 {
		out = 0
	}
	n := hit*p.InHitPerM + miss*p.InMissPerM + out*p.OutPerM
	return (n + Million - 1) / Million
}

// EstimateHold 保守估算冻结额:输入按命中/未命中中较高价,输出按 max_tokens。
func EstimateHold(p Price, inputChars, maxTokens int64) int64 {
	if inputChars < 0 {
		inputChars = 0
	}
	if maxTokens < 0 {
		maxTokens = 0
	}
	in := p.InMissPerM
	if p.InHitPerM > in {
		in = p.InHitPerM
	}
	return (inputChars*in + maxTokens*p.OutPerM + Million - 1) / Million
}

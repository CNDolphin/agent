package credits

import "testing"

func TestCostMatchesFormula(t *testing.T) {
	p := Price{InHitPerM: 100, InMissPerM: 200, OutPerM: 800}
	cases := []struct {
		name                   string
		hit, miss, out, expect int64
	}{
		{"全零", 0, 0, 0, 0},
		{"一百万命中", 1_000_000, 0, 0, 100},
		{"混合", 1000, 1000, 1000, 2},
		{"仅输出", 0, 0, 125_000, 100},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := Cost(p, c.hit, c.miss, c.out); got != c.expect {
				t.Fatalf("Cost=%d, 期望 %d", got, c.expect)
			}
		})
	}
}

func TestCostRoundsUp(t *testing.T) {
	p := Price{InMissPerM: 1}
	if got := Cost(p, 0, 1, 0); got != 1 {
		t.Fatalf("1 token × 1 积分/百万 应向上取整为 1,得到 %d", got)
	}
	if got := Cost(p, 0, 0, 0); got != 0 {
		t.Fatalf("0 token 应为 0,得到 %d", got)
	}
}

func TestCostNoFloatDrift(t *testing.T) {
	// 用整数公式计算大数,避免浮点误差。
	p := Price{InMissPerM: 3, OutPerM: 7}
	got := Cost(p, 0, 333_333, 142_857)
	want := int64((333_333*3 + 142_857*7 + Million - 1) / Million)
	if got != want {
		t.Fatalf("整数计算不一致: got=%d want=%d", got, want)
	}
}

func TestEstimateHoldConservative(t *testing.T) {
	p := Price{InHitPerM: 100, InMissPerM: 200, OutPerM: 800}
	got := EstimateHold(p, 1000, 1000)
	// 输入取较高价 200:1000*200 + 1000*800 = 1,000,000 → 1
	if got != 1 {
		t.Fatalf("EstimateHold=%d 期望 1", got)
	}
	// 输入命中价更高时应取命中价。
	p2 := Price{InHitPerM: 500, InMissPerM: 10, OutPerM: 0}
	if got := EstimateHold(p2, 1000, 0); got != 1 {
		t.Fatalf("EstimateHold 未取较高输入价: %d", got)
	}
	if got := EstimateHold(p, 0, 0); got != 0 {
		t.Fatalf("空输入估算应为 0,得到 %d", got)
	}
}

package auth

import "testing"

func TestNormalizePhone(t *testing.T) {
	ok := []struct{ in, want string }{
		{"13812345678", "+8613812345678"},
		{"+8613812345678", "+8613812345678"},
		{"138 1234 5678", "+8613812345678"},
		{"138-1234-5678", "+8613812345678"},
	}
	for _, c := range ok {
		if got, err := NormalizePhone(c.in); err != nil || got != c.want {
			t.Fatalf("NormalizePhone(%q)=%q,%v 期望 %q", c.in, got, err, c.want)
		}
	}
	for _, bad := range []string{"", "12345", "23812345678", "1381234567a", "+11234567890", "138123456789"} {
		if _, err := NormalizePhone(bad); err == nil {
			t.Fatalf("非法号码 %q 未被拒绝", bad)
		}
	}
}

func TestNormalizeIsIdempotent(t *testing.T) {
	first, err := NormalizePhone("13812345678")
	if err != nil {
		t.Fatal(err)
	}
	second, err := NormalizePhone(first)
	if err != nil || second != first {
		t.Fatalf("规范化不幂等: %q -> %q, %v", first, second, err)
	}
}

func TestHashPhone(t *testing.T) {
	pepper := "pepper-xyz"
	h1, err := HashPhone(pepper, "13812345678")
	if err != nil {
		t.Fatal(err)
	}
	h2, err := HashPhone(pepper, "+8613812345678")
	if err != nil {
		t.Fatal(err)
	}
	if h1 != h2 {
		t.Fatalf("等价号码应得到同一哈希: %s vs %s", h1, h2)
	}
	if h1 == "13812345678" || len(h1) != 64 {
		t.Fatalf("哈希必须为 HMAC hex,得到 %q", h1)
	}
	h3, _ := HashPhone(pepper, "13912345678")
	if h1 == h3 {
		t.Fatal("不同号码不应哈希相同")
	}
	if _, err := HashPhone("", "13812345678"); err == nil {
		t.Fatal("空 pepper 应报错")
	}
}

func TestMaskPhone(t *testing.T) {
	if got := MaskPhone("13812345678"); got != "138****5678" {
		t.Fatalf("MaskPhone=%q", got)
	}
	if got := MaskPhone("+8613812345678"); got != "138****5678" {
		t.Fatalf("MaskPhone 带前缀=%q", got)
	}
	if got := MaskPhone("bad"); got != "" {
		t.Fatalf("非法号码应为空串,得到 %q", got)
	}
}

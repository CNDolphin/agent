package auth_test

import (
	"strings"
	"testing"

	"mhagent/internal/auth"
)

func TestValidatePassword(t *testing.T) {
	cases := []struct {
		password string
		ok       bool
	}{
		{"short", false},
		{"12345678", true},
		{strings.Repeat("a", 64), true},
		{strings.Repeat("a", 65), false},
		{strings.Repeat("密", 30), false}, // 90 字节,超过 bcrypt 上限
	}
	for _, c := range cases {
		err := auth.ValidatePassword(c.password)
		if c.ok && err != nil {
			t.Fatalf("密码 %q 应合法,实际错误: %v", c.password, err)
		}
		if !c.ok && err == nil {
			t.Fatalf("密码 %q 应非法", c.password)
		}
	}
}

func TestHashAndVerifyPassword(t *testing.T) {
	hash, err := auth.HashPassword("Passw0rd!")
	if err != nil {
		t.Fatalf("生成哈希失败: %v", err)
	}
	if !auth.VerifyPassword(hash, "Passw0rd!") {
		t.Fatalf("正确密码校验应通过")
	}
	if auth.VerifyPassword(hash, "wrong-password") {
		t.Fatalf("错误密码校验应失败")
	}
	if hash == "Passw0rd!" {
		t.Fatalf("哈希不应是明文")
	}
}

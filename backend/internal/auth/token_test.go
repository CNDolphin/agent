package auth

import (
	"strings"
	"testing"
	"time"
)

func TestTokenIssueAndParse(t *testing.T) {
	now := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	issuer := NewTokenIssuer("secret", 15*time.Minute, 24*time.Hour)
	issuer.Now = func() time.Time { return now }
	pair, err := issuer.IssueTokens(42)
	if err != nil {
		t.Fatal(err)
	}
	if pair.ExpiresIn != 900 {
		t.Fatalf("ExpiresIn=%d", pair.ExpiresIn)
	}
	if id, err := issuer.ParseAccess(pair.AccessToken); err != nil || id != 42 {
		t.Fatalf("access 解析失败: %d %v", id, err)
	}
	if id, err := issuer.ParseRefresh(pair.RefreshToken); err != nil || id != 42 {
		t.Fatalf("refresh 解析失败: %d %v", id, err)
	}
}

func TestTokenTypeCannotBeSwapped(t *testing.T) {
	issuer := NewTokenIssuer("secret", 15*time.Minute, 24*time.Hour)
	pair, _ := issuer.IssueTokens(42)
	if _, err := issuer.ParseAccess(pair.RefreshToken); err == nil {
		t.Fatal("refresh token 不应能当 access 使用")
	}
	if _, err := issuer.ParseRefresh(pair.AccessToken); err == nil {
		t.Fatal("access token 不应能当 refresh 使用")
	}
}

func TestTokenTamperedOrExpired(t *testing.T) {
	now := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	issuer := NewTokenIssuer("secret", 15*time.Minute, 24*time.Hour)
	issuer.Now = func() time.Time { return now }
	pair, _ := issuer.IssueTokens(42)

	tampered := pair.AccessToken[:len(pair.AccessToken)-1] + "x"
	if _, err := issuer.ParseAccess(tampered); err == nil {
		t.Fatal("被篡改的 token 应失败")
	}

	other := NewTokenIssuer("other-secret", 15*time.Minute, 24*time.Hour)
	other.Now = issuer.Now
	if _, err := other.ParseAccess(pair.AccessToken); err == nil {
		t.Fatal("不同密钥签发的 token 应失败")
	}

	issuer.Now = func() time.Time { return now.Add(20 * time.Minute) }
	if _, err := issuer.ParseAccess(pair.AccessToken); err == nil {
		t.Fatal("过期 access token 应失败")
	}
}

func TestAdminToken(t *testing.T) {
	now := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	issuer := NewAdminTokenIssuer("admin-secret", time.Hour)
	issuer.Now = func() time.Time { return now }
	token, expires, err := issuer.Issue(7, "super")
	if err != nil || expires != 3600 {
		t.Fatalf("签发失败: %v expires=%d", err, expires)
	}
	claims, err := issuer.Parse(token)
	if err != nil || claims.AdminID != 7 || claims.Role != "super" {
		t.Fatalf("解析失败: %+v %v", claims, err)
	}
	userIssuer := NewTokenIssuer("secret", time.Minute, time.Hour)
	userIssuer.Now = issuer.Now
	userPair, _ := userIssuer.IssueTokens(1)
	if _, err := issuer.Parse(userPair.AccessToken); err == nil {
		t.Fatal("用户令牌不应通过管理员校验")
	}
	if strings.Contains(token, "admin-secret") {
		t.Fatal("令牌不得包含密钥明文")
	}
}

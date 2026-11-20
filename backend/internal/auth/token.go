package auth

import (
	"errors"
	"fmt"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// 令牌类型。
const (
	TokenTypeAccess  = "access"
	TokenTypeRefresh = "refresh"
	TokenTypeAdmin   = "admin_access"
)

// TokenPair 登录响应中的令牌对。
type TokenPair struct {
	AccessToken  string
	RefreshToken string
	ExpiresIn    int64
}

type userClaims struct {
	UserID int64  `json:"uid"`
	Type   string `json:"typ"`
	jwt.RegisteredClaims
}

// TokenIssuer 用户令牌签发与校验。
type TokenIssuer struct {
	Secret     []byte
	AccessTTL  time.Duration
	RefreshTTL time.Duration
	Now        func() time.Time
}

// NewTokenIssuer 创建用户令牌签发器。
func NewTokenIssuer(secret string, accessTTL, refreshTTL time.Duration) *TokenIssuer {
	return &TokenIssuer{Secret: []byte(secret), AccessTTL: accessTTL, RefreshTTL: refreshTTL, Now: time.Now}
}

func (t *TokenIssuer) now() time.Time {
	if t.Now != nil {
		return t.Now()
	}
	return time.Now()
}

func (t *TokenIssuer) issue(userID int64, typ string, ttl time.Duration) (string, error) {
	now := t.now()
	claims := userClaims{
		UserID: userID,
		Type:   typ,
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   fmt.Sprintf("%d", userID),
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(ttl)),
		},
	}
	return jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString(t.Secret)
}

// IssueTokens 签发 access + refresh。
func (t *TokenIssuer) IssueTokens(userID int64) (TokenPair, error) {
	access, err := t.issue(userID, TokenTypeAccess, t.AccessTTL)
	if err != nil {
		return TokenPair{}, err
	}
	refresh, err := t.issue(userID, TokenTypeRefresh, t.RefreshTTL)
	if err != nil {
		return TokenPair{}, err
	}
	return TokenPair{AccessToken: access, RefreshToken: refresh, ExpiresIn: int64(t.AccessTTL.Seconds())}, nil
}

func (t *TokenIssuer) parse(token string, want string) (int64, error) {
	var claims userClaims
	parsed, err := jwt.ParseWithClaims(token, &claims, func(tok *jwt.Token) (any, error) {
		if _, ok := tok.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("unexpected signing method")
		}
		return t.Secret, nil
	}, jwt.WithValidMethods([]string{"HS256"}), jwt.WithTimeFunc(t.now))
	if err != nil || !parsed.Valid {
		return 0, errors.New("invalid token")
	}
	if claims.Type != want || claims.UserID <= 0 {
		return 0, errors.New("invalid token type")
	}
	return claims.UserID, nil
}

// ParseAccess 校验 access 令牌。
func (t *TokenIssuer) ParseAccess(token string) (int64, error) {
	return t.parse(token, TokenTypeAccess)
}

// ParseRefresh 校验 refresh 令牌。
func (t *TokenIssuer) ParseRefresh(token string) (int64, error) {
	return t.parse(token, TokenTypeRefresh)
}

type adminClaims struct {
	AdminID int64  `json:"aid"`
	Role    string `json:"role"`
	Type    string `json:"typ"`
	jwt.RegisteredClaims
}

// AdminClaims 管理员令牌信息。
type AdminClaims struct {
	AdminID int64
	Role    string
}

// AdminTokenIssuer 管理员令牌签发器(独立密钥)。
type AdminTokenIssuer struct {
	Secret []byte
	TTL    time.Duration
	Now    func() time.Time
}

// NewAdminTokenIssuer 创建管理员令牌签发器。
func NewAdminTokenIssuer(secret string, ttl time.Duration) *AdminTokenIssuer {
	return &AdminTokenIssuer{Secret: []byte(secret), TTL: ttl, Now: time.Now}
}

func (a *AdminTokenIssuer) now() time.Time {
	if a.Now != nil {
		return a.Now()
	}
	return time.Now()
}

// Issue 签发管理员令牌。
func (a *AdminTokenIssuer) Issue(adminID int64, role string) (string, int64, error) {
	now := a.now()
	claims := adminClaims{
		AdminID: adminID,
		Role:    role,
		Type:    TokenTypeAdmin,
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   fmt.Sprintf("%d", adminID),
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(a.TTL)),
		},
	}
	token, err := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString(a.Secret)
	return token, int64(a.TTL.Seconds()), err
}

// Parse 校验管理员令牌。
func (a *AdminTokenIssuer) Parse(token string) (AdminClaims, error) {
	var claims adminClaims
	parsed, err := jwt.ParseWithClaims(token, &claims, func(tok *jwt.Token) (any, error) {
		if _, ok := tok.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("unexpected signing method")
		}
		return a.Secret, nil
	}, jwt.WithValidMethods([]string{"HS256"}), jwt.WithTimeFunc(a.now))
	if err != nil || !parsed.Valid {
		return AdminClaims{}, errors.New("invalid admin token")
	}
	if claims.Type != TokenTypeAdmin || claims.AdminID <= 0 {
		return AdminClaims{}, errors.New("invalid admin token type")
	}
	if claims.Role != "super" && claims.Role != "ops" {
		return AdminClaims{}, errors.New("invalid admin role")
	}
	return AdminClaims{AdminID: claims.AdminID, Role: claims.Role}, nil
}

// Package auth 提供手机号规范化/哈希与 JWT 令牌签发。
package auth

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"regexp"
	"strings"
)

var mainlandPhoneRe = regexp.MustCompile(`^1[3-9]\d{9}$`)

// NormalizePhone 将大陆手机号统一为 +86 形式;支持空格、短横线分隔。
func NormalizePhone(raw string) (string, error) {
	s := strings.TrimSpace(raw)
	if s == "" {
		return "", errors.New("手机号不能为空")
	}
	s = strings.ReplaceAll(s, " ", "")
	s = strings.ReplaceAll(s, "-", "")
	s = strings.ReplaceAll(s, "\t", "")
	if strings.HasPrefix(s, "+86") {
		s = strings.TrimPrefix(s, "+86")
	}
	if !mainlandPhoneRe.MatchString(s) {
		return "", errors.New("手机号格式不正确")
	}
	return "+86" + s, nil
}

// HashPhone 计算手机号 HMAC-SHA256;pepper 为空时报错。数据库中只存该哈希。
func HashPhone(pepper, phone string) (string, error) {
	if strings.TrimSpace(pepper) == "" {
		return "", errors.New("phone pepper 不能为空")
	}
	normalized, err := NormalizePhone(phone)
	if err != nil {
		return "", err
	}
	mac := hmac.New(sha256.New, []byte(pepper))
	mac.Write([]byte(normalized))
	return hex.EncodeToString(mac.Sum(nil)), nil
}

// MaskPhone 生成脱敏展示串,如 138****5678。
func MaskPhone(phone string) string {
	normalized, err := NormalizePhone(phone)
	if err != nil {
		return ""
	}
	digits := strings.TrimPrefix(normalized, "+86")
	return digits[:3] + "****" + digits[len(digits)-4:]
}

// PhoneHash 返回稳定伪名,用于上游 user_id 等非明文标识。
func PhoneNumeric(phone string) string {
	normalized, err := NormalizePhone(phone)
	if err != nil {
		return ""
	}
	return strings.TrimPrefix(normalized, "+86")
}

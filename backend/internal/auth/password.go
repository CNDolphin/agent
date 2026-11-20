// Package auth 提供密码哈希与校验。
package auth

import (
	"errors"
	"fmt"
	"unicode/utf8"

	"golang.org/x/crypto/bcrypt"
)

const (
	// MinPasswordLength 密码最小长度(字符)。
	MinPasswordLength = 8
	// MaxPasswordLength 密码最大长度(字符)。
	MaxPasswordLength = 64
	maxBcryptBytes    = 72
)

// ValidatePassword 校验密码长度:8-64 个字符,且不超过 bcrypt 的 72 字节上限。
func ValidatePassword(password string) error {
	n := utf8.RuneCountInString(password)
	if n < MinPasswordLength || n > MaxPasswordLength {
		return fmt.Errorf("密码长度需为 %d-%d 位", MinPasswordLength, MaxPasswordLength)
	}
	if len([]byte(password)) > maxBcryptBytes {
		return errors.New("密码过长,请缩短后重试")
	}
	return nil
}

// HashPassword 生成 bcrypt 哈希。
func HashPassword(password string) (string, error) {
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return "", err
	}
	return string(hash), nil
}

// VerifyPassword 校验密码与哈希是否匹配。
func VerifyPassword(hash, password string) bool {
	return bcrypt.CompareHashAndPassword([]byte(hash), []byte(password)) == nil
}

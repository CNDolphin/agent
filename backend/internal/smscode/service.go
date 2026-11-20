// Package smscode 提供短信验证码的生成、校验与限频。Redis 中只保存 HMAC 后的验证码。
package smscode

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"math/big"
	"time"

	"github.com/redis/go-redis/v9"

	"mhagent/internal/auth"
	"mhagent/internal/sms"
)

// 验证码服务错误。
var (
	ErrTooFrequent = errors.New("too frequent")
	ErrDailyLimit  = errors.New("daily limit reached")
	ErrInvalidCode = errors.New("invalid code")
)

const maxAttempts = 5

// Service 验证码服务。
type Service struct {
	RDB         *redis.Client
	Sender      sms.Sender
	Pepper      string
	Template    string
	CodeTTL     time.Duration
	ResendEvery time.Duration
	PhoneDaily  int
	IPDaily     int
	Now         func() time.Time
	// UniversalCode 非空时作为万能验证码,任何手机号都可直接通过校验。
	// 仅供本地联调(短信发送器为 mock)使用,生产环境必须留空。
	UniversalCode string
}

func (s *Service) now() time.Time {
	if s.Now != nil {
		return s.Now()
	}
	return time.Now()
}

func (s *Service) digest(v string) string {
	mac := hmac.New(sha256.New, []byte(s.Pepper))
	mac.Write([]byte(v))
	return hex.EncodeToString(mac.Sum(nil))
}

func (s *Service) phoneKey(phone string) (string, error) {
	normalized, err := auth.NormalizePhone(phone)
	if err != nil {
		return "", err
	}
	return s.digest(normalized), nil
}

func codeKey(h string) string     { return "sms:code:" + h }
func cooldownKey(h string) string { return "sms:cd:" + h }
func attemptKey(h string) string  { return "sms:try:" + h }

// Send 生成 6 位验证码并发送。限频:同号 60 秒 1 次、每天 5 次;同 IP 每天 20 次。
func (s *Service) Send(ctx context.Context, phone, ip string) error {
	normalized, err := auth.NormalizePhone(phone)
	if err != nil {
		return err
	}
	h, err := s.phoneKey(normalized)
	if err != nil {
		return err
	}
	ipHash := s.digest(ip)
	today := s.now().UTC().Format("20060102")
	dayKey := "sms:day:" + h + ":" + today
	ipKey := "sms:ipday:" + ipHash + ":" + today

	if exists, err := s.RDB.Exists(ctx, cooldownKey(h)).Result(); err != nil {
		return fmt.Errorf("检查发送冷却失败: %w", err)
	} else if exists > 0 {
		return ErrTooFrequent
	}
	if n, err := s.RDB.Get(ctx, dayKey).Int(); err != nil && !errors.Is(err, redis.Nil) {
		return fmt.Errorf("读取每日发送次数失败: %w", err)
	} else if n >= s.PhoneDaily {
		return ErrDailyLimit
	}
	if n, err := s.RDB.Get(ctx, ipKey).Int(); err != nil && !errors.Is(err, redis.Nil) {
		return fmt.Errorf("读取 IP 每日发送次数失败: %w", err)
	} else if n >= s.IPDaily {
		return ErrDailyLimit
	}

	code, err := randomCode()
	if err != nil {
		return err
	}
	if err := s.Sender.Send(ctx, normalized, s.Template, map[string]string{"code": code}); err != nil {
		// 发送失败:不写入验证码、不计数。
		_ = s.RDB.Del(ctx, codeKey(h)).Err()
		return err
	}

	if err := s.RDB.Set(ctx, codeKey(h), s.digest(code), s.CodeTTL).Err(); err != nil {
		return fmt.Errorf("保存验证码失败: %w", err)
	}
	_ = s.RDB.Del(ctx, attemptKey(h)).Err()
	if err := s.RDB.Set(ctx, cooldownKey(h), "1", s.ResendEvery).Err(); err != nil {
		return fmt.Errorf("记录发送冷却失败: %w", err)
	}
	if err := s.RDB.Incr(ctx, dayKey).Err(); err != nil {
		return fmt.Errorf("记录每日发送次数失败: %w", err)
	}
	_ = s.RDB.Expire(ctx, dayKey, 24*time.Hour).Err()
	if err := s.RDB.Incr(ctx, ipKey).Err(); err != nil {
		return fmt.Errorf("记录 IP 发送次数失败: %w", err)
	}
	_ = s.RDB.Expire(ctx, ipKey, 24*time.Hour).Err()
	return nil
}

// Verify 校验验证码。成功立即删除;同一验证码最多错误 5 次后作废。
func (s *Service) Verify(ctx context.Context, phone, code string) error {
	if s.UniversalCode != "" && code == s.UniversalCode {
		// 联调万能码:不消耗已发送的验证码,也不受错误次数限制。
		return nil
	}
	h, err := s.phoneKey(phone)
	if err != nil {
		return ErrInvalidCode
	}
	attempts, err := s.RDB.Get(ctx, attemptKey(h)).Int()
	if err != nil && !errors.Is(err, redis.Nil) {
		return fmt.Errorf("读取尝试次数失败: %w", err)
	}
	if attempts >= maxAttempts {
		_ = s.RDB.Del(ctx, codeKey(h)).Err()
		return ErrInvalidCode
	}
	stored, err := s.RDB.Get(ctx, codeKey(h)).Result()
	if errors.Is(err, redis.Nil) {
		return ErrInvalidCode
	}
	if err != nil {
		return fmt.Errorf("读取验证码失败: %w", err)
	}
	if !hmac.Equal([]byte(stored), []byte(s.digest(code))) {
		n, incrErr := s.RDB.Incr(ctx, attemptKey(h)).Result()
		if incrErr != nil {
			return fmt.Errorf("记录尝试次数失败: %w", incrErr)
		}
		_ = s.RDB.Expire(ctx, attemptKey(h), s.CodeTTL).Err()
		if n >= maxAttempts {
			_ = s.RDB.Del(ctx, codeKey(h)).Err()
		}
		return ErrInvalidCode
	}
	_ = s.RDB.Del(ctx, codeKey(h)).Err()
	_ = s.RDB.Del(ctx, attemptKey(h)).Err()
	return nil
}

// PeekCodeHash 仅供测试检查 Redis 中不存明文。
func (s *Service) PeekCodeHash(ctx context.Context, phone string) (string, error) {
	h, err := s.phoneKey(phone)
	if err != nil {
		return "", err
	}
	return s.RDB.Get(ctx, codeKey(h)).Result()
}

func randomCode() (string, error) {
	n, err := rand.Int(rand.Reader, big.NewInt(1_000_000))
	if err != nil {
		return "", fmt.Errorf("生成验证码失败: %w", err)
	}
	return fmt.Sprintf("%06d", n.Int64()), nil
}

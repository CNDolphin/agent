// Package logic 编排业务逻辑,handler 只负责协议解析。
package logic

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"

	"mhagent/internal/apierr"
	"mhagent/internal/audit"
	"mhagent/internal/auth"
	"mhagent/internal/credits"
	"mhagent/internal/smscode"
	"mhagent/internal/svc"
)

// AuthLogic 认证相关业务。
type AuthLogic struct {
	sc *svc.ServiceContext
}

// NewAuthLogic 创建认证逻辑。
func NewAuthLogic(sc *svc.ServiceContext) *AuthLogic { return &AuthLogic{sc: sc} }

// SendCode 发送验证码。
func (l *AuthLogic) SendCode(ctx context.Context, phone, ip string) error {
	if _, err := auth.NormalizePhone(phone); err != nil {
		return apierr.BadRequest("手机号格式不正确")
	}
	err := l.sc.SMSCode.Send(ctx, phone, ip)
	switch {
	case err == nil:
		return nil
	case errors.Is(err, smscode.ErrTooFrequent), errors.Is(err, smscode.ErrDailyLimit):
		return apierr.RateLimited("验证码发送过于频繁,请稍后重试")
	default:
		return apierr.Internal()
	}
}

// LoginResult 登录结果。
type LoginResult struct {
	Pair  auth.TokenPair
	IsNew bool
}

// Login 校验验证码并登录;首次登录自动注册并赠送积分。
func (l *AuthLogic) Login(ctx context.Context, phone, code string) (LoginResult, error) {
	normalized, err := auth.NormalizePhone(phone)
	if err != nil {
		return LoginResult{}, apierr.BadRequest("手机号格式不正确")
	}
	if err := l.sc.SMSCode.Verify(ctx, normalized, code); err != nil {
		if errors.Is(err, smscode.ErrInvalidCode) {
			return LoginResult{}, apierr.InvalidCode()
		}
		return LoginResult{}, apierr.Internal()
	}
	phoneHash, err := auth.HashPhone(l.sc.Secrets.PhonePepper, normalized)
	if err != nil {
		return LoginResult{}, apierr.Internal()
	}

	now := l.sc.Now().UTC()
	tx, err := l.sc.DB.BeginTx(ctx, nil)
	if err != nil {
		return LoginResult{}, apierr.Internal()
	}
	defer func() { _ = tx.Rollback() }()

	userID, isNew, err := l.ensureUserTx(ctx, tx, phoneHash, auth.MaskPhone(normalized), now)
	if err != nil {
		return LoginResult{}, err
	}
	if err := tx.Commit(); err != nil {
		return LoginResult{}, apierr.Internal()
	}

	if l.sc.Audit != nil {
		l.sc.Audit.Quiet(ctx, audit.ActorUser, userID, audit.EventAuthLogin,
			audit.NewDetail().Int("user_id", userID).Int("is_new", boolInt(isNew)))
	}

	return l.issue(userID, isNew)
}

// Register 校验验证码、设置密码并登录;已注册且已有密码的用户返回「已注册」。
func (l *AuthLogic) Register(ctx context.Context, phone, code, password string) (LoginResult, error) {
	normalized, err := auth.NormalizePhone(phone)
	if err != nil {
		return LoginResult{}, apierr.BadRequest("手机号格式不正确")
	}
	if err := auth.ValidatePassword(password); err != nil {
		return LoginResult{}, apierr.BadRequest(err.Error())
	}
	if err := l.sc.SMSCode.Verify(ctx, normalized, code); err != nil {
		if errors.Is(err, smscode.ErrInvalidCode) {
			return LoginResult{}, apierr.InvalidCode()
		}
		return LoginResult{}, apierr.Internal()
	}
	phoneHash, err := auth.HashPhone(l.sc.Secrets.PhonePepper, normalized)
	if err != nil {
		return LoginResult{}, apierr.Internal()
	}
	hash, err := auth.HashPassword(password)
	if err != nil {
		return LoginResult{}, apierr.Internal()
	}

	now := l.sc.Now().UTC()
	tx, err := l.sc.DB.BeginTx(ctx, nil)
	if err != nil {
		return LoginResult{}, apierr.Internal()
	}
	defer func() { _ = tx.Rollback() }()

	var existing sql.NullString
	err = tx.QueryRowContext(ctx, `SELECT password_hash FROM users WHERE phone_hash=$1`, phoneHash).Scan(&existing)
	switch {
	case errors.Is(err, sql.ErrNoRows):
	case err != nil:
		return LoginResult{}, apierr.Internal()
	case existing.Valid && existing.String != "":
		return LoginResult{}, apierr.AlreadyRegistered()
	}

	userID, isNew, err := l.ensureUserTx(ctx, tx, phoneHash, auth.MaskPhone(normalized), now)
	if err != nil {
		return LoginResult{}, err
	}
	if _, err := tx.ExecContext(ctx, `UPDATE users SET password_hash=$2 WHERE id=$1`, userID, hash); err != nil {
		return LoginResult{}, apierr.Internal()
	}
	if err := tx.Commit(); err != nil {
		return LoginResult{}, apierr.Internal()
	}

	if l.sc.Audit != nil {
		l.sc.Audit.Quiet(ctx, audit.ActorUser, userID, audit.EventAuthLogin,
			audit.NewDetail().Int("user_id", userID).Int("is_new", boolInt(isNew)).Enum("method", "password"))
	}
	return l.issue(userID, isNew)
}

// LoginWithPassword 用手机号与密码登录。
func (l *AuthLogic) LoginWithPassword(ctx context.Context, phone, password string) (LoginResult, error) {
	normalized, err := auth.NormalizePhone(phone)
	if err != nil {
		return LoginResult{}, apierr.BadRequest("手机号格式不正确")
	}
	if password == "" {
		return LoginResult{}, apierr.BadRequest("密码不能为空")
	}
	phoneHash, err := auth.HashPhone(l.sc.Secrets.PhonePepper, normalized)
	if err != nil {
		return LoginResult{}, apierr.Internal()
	}

	var userID int64
	var deletedAt sql.NullTime
	var hash sql.NullString
	err = l.sc.DB.QueryRowContext(ctx,
		`SELECT id, deleted_at, password_hash FROM users WHERE phone_hash=$1`, phoneHash).
		Scan(&userID, &deletedAt, &hash)
	if errors.Is(err, sql.ErrNoRows) {
		return LoginResult{}, apierr.WrongPassword()
	}
	if err != nil {
		return LoginResult{}, apierr.Internal()
	}
	if deletedAt.Valid {
		return LoginResult{}, apierr.WrongPassword()
	}
	if !hash.Valid || hash.String == "" {
		return LoginResult{}, apierr.PasswordRequired()
	}
	if !auth.VerifyPassword(hash.String, password) {
		return LoginResult{}, apierr.WrongPassword()
	}

	if l.sc.Audit != nil {
		l.sc.Audit.Quiet(ctx, audit.ActorUser, userID, audit.EventAuthLogin,
			audit.NewDetail().Int("user_id", userID).Int("is_new", 0).Enum("method", "password"))
	}
	return l.issue(userID, false)
}

// ResetPassword 校验验证码后重置密码;手机号不存在也返回成功,避免泄露账号是否存在。
func (l *AuthLogic) ResetPassword(ctx context.Context, phone, code, newPassword string) error {
	normalized, err := auth.NormalizePhone(phone)
	if err != nil {
		return apierr.BadRequest("手机号格式不正确")
	}
	if err := auth.ValidatePassword(newPassword); err != nil {
		return apierr.BadRequest(err.Error())
	}
	if err := l.sc.SMSCode.Verify(ctx, normalized, code); err != nil {
		if errors.Is(err, smscode.ErrInvalidCode) {
			return apierr.InvalidCode()
		}
		return apierr.Internal()
	}
	phoneHash, err := auth.HashPhone(l.sc.Secrets.PhonePepper, normalized)
	if err != nil {
		return apierr.Internal()
	}
	hash, err := auth.HashPassword(newPassword)
	if err != nil {
		return apierr.Internal()
	}
	if _, err := l.sc.DB.ExecContext(ctx,
		`UPDATE users SET password_hash=$2 WHERE phone_hash=$1 AND deleted_at IS NULL`, phoneHash, hash); err != nil {
		return apierr.Internal()
	}
	return nil
}

// ensureUserTx 查找或创建用户、保证积分账户存在,并在需要时发放注册赠送积分。
func (l *AuthLogic) ensureUserTx(ctx context.Context, tx *sql.Tx, phoneHash, mask string, now time.Time) (int64, bool, error) {
	var userID int64
	var deletedAt sql.NullTime
	isNew := false
	grant := false
	cooldown := time.Duration(l.sc.Config.Credits.ReSignupCooldownDays) * 24 * time.Hour

	err := tx.QueryRowContext(ctx, `SELECT id, deleted_at FROM users WHERE phone_hash=$1`, phoneHash).Scan(&userID, &deletedAt)
	if errors.Is(err, sql.ErrNoRows) {
		err = tx.QueryRowContext(ctx,
			`INSERT INTO users (phone_hash, phone_mask, created_at) VALUES ($1,$2,$3)
			 ON CONFLICT (phone_hash) DO NOTHING RETURNING id`, phoneHash, mask, now).Scan(&userID)
		if err == nil {
			isNew, grant = true, true
		} else if errors.Is(err, sql.ErrNoRows) {
			// 并发注册:另一个事务已插入,重新读取。
			if err := tx.QueryRowContext(ctx, `SELECT id, deleted_at FROM users WHERE phone_hash=$1`, phoneHash).Scan(&userID, &deletedAt); err != nil {
				return 0, false, apierr.Internal()
			}
			if deletedAt.Valid {
				if _, err := tx.ExecContext(ctx, `UPDATE users SET deleted_at=NULL WHERE id=$1`, userID); err != nil {
					return 0, false, apierr.Internal()
				}
				isNew = true
				grant = now.Sub(deletedAt.Time.UTC()) >= cooldown
				deletedAt = sql.NullTime{}
			}
		} else {
			return 0, false, apierr.Internal()
		}
	} else if err != nil {
		return 0, false, apierr.Internal()
	}

	if deletedAt.Valid {
		if _, err := tx.ExecContext(ctx, `UPDATE users SET deleted_at=NULL WHERE id=$1`, userID); err != nil {
			return 0, false, apierr.Internal()
		}
		isNew = true
		grant = now.Sub(deletedAt.Time.UTC()) >= cooldown
	}

	if _, err := tx.ExecContext(ctx,
		`INSERT INTO credit_accounts (user_id, balance, held) VALUES ($1,0,0) ON CONFLICT (user_id) DO NOTHING`, userID); err != nil {
		return 0, false, apierr.Internal()
	}
	if grant {
		if err := credits.CreditTx(ctx, tx, userID, l.sc.Config.Credits.SignupGrant, "grant",
			fmt.Sprintf("signup:%d", userID), now); err != nil {
			return 0, false, apierr.Internal()
		}
	}
	return userID, isNew, nil
}

// issue 发放令牌对。
func (l *AuthLogic) issue(userID int64, isNew bool) (LoginResult, error) {
	pair, err := l.sc.Tokens.IssueTokens(userID)
	if err != nil {
		return LoginResult{}, apierr.Internal()
	}
	return LoginResult{Pair: pair, IsNew: isNew}, nil
}

// Refresh 用 refresh token 换取新的令牌对。
func (l *AuthLogic) Refresh(ctx context.Context, refreshToken string) (auth.TokenPair, error) {
	userID, err := l.sc.Tokens.ParseRefresh(refreshToken)
	if err != nil {
		return auth.TokenPair{}, apierr.Unauthorized("令牌无效或已过期")
	}
	var exists int
	if err := l.sc.DB.QueryRowContext(ctx,
		`SELECT 1 FROM users WHERE id=$1 AND deleted_at IS NULL`, userID).Scan(&exists); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return auth.TokenPair{}, apierr.Unauthorized("令牌无效或已过期")
		}
		return auth.TokenPair{}, apierr.Internal()
	}
	pair, err := l.sc.Tokens.IssueTokens(userID)
	if err != nil {
		return auth.TokenPair{}, apierr.Internal()
	}
	return pair, nil
}

// DeleteAccount 注销账号:软删除用户、删除积分账户、账本去标识。
func (l *AuthLogic) DeleteAccount(ctx context.Context, userID int64) error {
	tx, err := l.sc.DB.BeginTx(ctx, nil)
	if err != nil {
		return apierr.Internal()
	}
	defer func() { _ = tx.Rollback() }()

	if _, err := tx.ExecContext(ctx, `UPDATE users SET deleted_at=$2 WHERE id=$1`, userID, l.sc.Now().UTC()); err != nil {
		return apierr.Internal()
	}
	if _, err := tx.ExecContext(ctx, `DELETE FROM credit_accounts WHERE user_id=$1`, userID); err != nil {
		return apierr.Internal()
	}
	if _, err := tx.ExecContext(ctx, `UPDATE credit_ledger SET user_id=0 WHERE user_id=$1`, userID); err != nil {
		return apierr.Internal()
	}
	if err := tx.Commit(); err != nil {
		return apierr.Internal()
	}
	if l.sc.Audit != nil {
		l.sc.Audit.Quiet(ctx, audit.ActorUser, 0, audit.EventAccountDelete, audit.NewDetail().Int("user_id", userID))
	}
	return nil
}

func boolInt(v bool) int64 {
	if v {
		return 1
	}
	return 0
}

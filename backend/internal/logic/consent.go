package logic

import (
	"context"
	"database/sql"
	"errors"

	"mhagent/internal/apierr"
	"mhagent/internal/audit"
	"mhagent/internal/svc"
)

// ConsentLogic 同意书。
type ConsentLogic struct {
	sc *svc.ServiceContext
}

// NewConsentLogic 创建同意书逻辑。
func NewConsentLogic(sc *svc.ServiceContext) *ConsentLogic { return &ConsentLogic{sc: sc} }

// ConsentInfo 当前版本信息。
type ConsentInfo struct {
	Version string `json:"version"`
	Text    string `json:"text"`
	URL     string `json:"url,omitempty"`
}

// Latest 返回最新同意书。
func (l *ConsentLogic) Latest() ConsentInfo {
	return ConsentInfo{
		Version: l.sc.Config.Consent.Version,
		Text:    l.sc.Config.Consent.Text,
		URL:     l.sc.Config.Consent.URL,
	}
}

// Sign 记录签署;版本必须与当前版本一致。
func (l *ConsentLogic) Sign(ctx context.Context, userID int64, version string) error {
	if version == "" || version != l.sc.Config.Consent.Version {
		return apierr.BadRequest("同意书版本不一致,请刷新后重试")
	}
	_, err := l.sc.DB.ExecContext(ctx,
		`INSERT INTO consents (user_id, version, signed_at) VALUES ($1,$2,$3)
		 ON CONFLICT (user_id, version) DO NOTHING`, userID, version, l.sc.Now().UTC())
	if err != nil {
		return apierr.Internal()
	}
	if l.sc.Audit != nil {
		l.sc.Audit.Quiet(ctx, audit.ActorUser, userID, audit.EventConsentSign,
			audit.NewDetail().Enum("version", version))
	}
	return nil
}

// SignedLatest 查询用户是否已签署当前版本。
func (l *ConsentLogic) SignedLatest(ctx context.Context, userID int64) (bool, error) {
	var one int
	err := l.sc.DB.QueryRowContext(ctx,
		`SELECT 1 FROM consents WHERE user_id=$1 AND version=$2`,
		userID, l.sc.Config.Consent.Version).Scan(&one)
	if errors.Is(err, sql.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	return true, nil
}

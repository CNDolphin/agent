package logic

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/google/uuid"

	"mhagent/internal/apierr"
	"mhagent/internal/audit"
	"mhagent/internal/auth"
	"mhagent/internal/svc"
)

var emailRe = regexp.MustCompile(`^[^@\s]+@[^@\s]+\.[^@\s]+$`)

// NotifyLogic 紧急联系人通知。
type NotifyLogic struct {
	sc *svc.ServiceContext
}

// NewNotifyLogic 创建通知逻辑。
func NewNotifyLogic(sc *svc.ServiceContext) *NotifyLogic { return &NotifyLogic{sc: sc} }

// NotifyResult 通知结果。
type NotifyResult struct {
	Status   string
	NotifyID string
}

// Emergency 发送紧急通知。同一用户每小时最多 3 次,同一接收人每天最多 3 次。
func (l *NotifyLogic) Emergency(ctx context.Context, userID int64, channel, to, templateID string, params map[string]string) (NotifyResult, error) {
	if templateID == "" {
		return NotifyResult{}, apierr.BadRequest("template_id 不能为空")
	}
	if _, ok := l.sc.NotifyTemplates[templateID]; !ok {
		return NotifyResult{}, apierr.BadRequest("未授权的通知模板")
	}
	normalizedTo := ""
	switch channel {
	case "sms":
		v, err := auth.NormalizePhone(to)
		if err != nil {
			return NotifyResult{}, apierr.BadRequest("接收手机号格式不正确")
		}
		normalizedTo = v
	case "email":
		v := strings.TrimSpace(strings.ToLower(to))
		if !emailRe.MatchString(v) {
			return NotifyResult{}, apierr.BadRequest("接收邮箱格式不正确")
		}
		normalizedTo = v
	default:
		return NotifyResult{}, apierr.BadRequest("channel 仅支持 sms 或 email")
	}

	signed, err := NewConsentLogic(l.sc).SignedLatest(ctx, userID)
	if err != nil {
		return NotifyResult{}, apierr.Internal()
	}
	if !signed {
		return NotifyResult{}, apierr.ConsentRequired()
	}

	now := l.sc.Now().UTC()
	if err := l.checkAndCount(ctx, fmt.Sprintf("notify:u:%d:%s", userID, now.Format("2006010215")), 3, time.Hour); err != nil {
		return NotifyResult{}, err
	}
	recipientHash := l.recipientHash(normalizedTo)
	if err := l.checkAndCount(ctx, fmt.Sprintf("notify:r:%s:%s", recipientHash, now.Format("20060102")), 3, 24*time.Hour); err != nil {
		return NotifyResult{}, err
	}

	notifyID := uuid.NewString()
	status := "sent"
	sendErr := l.sc.Notifier.Send(ctx, channel, normalizedTo, templateID, params)
	if sendErr != nil {
		status = "failed"
	}
	if _, err := l.sc.DB.ExecContext(ctx,
		`INSERT INTO notify_logs (user_id, channel, template_id, status, created_at) VALUES ($1,$2,$3,$4,$5)`,
		userID, channel, templateID, status, now); err != nil {
		return NotifyResult{}, apierr.Internal()
	}
	if l.sc.Audit != nil {
		l.sc.Audit.Quiet(ctx, audit.ActorUser, userID, audit.EventNotifyEmergency,
			audit.NewDetail().Enum("channel", channel).Enum("status", status).Enum("template", templateID))
	}
	return NotifyResult{Status: status, NotifyID: notifyID}, nil
}

func (l *NotifyLogic) checkAndCount(ctx context.Context, key string, limit int, ttl time.Duration) error {
	n, err := l.sc.RDB.Incr(ctx, key).Result()
	if err != nil {
		return apierr.Internal()
	}
	if n == 1 {
		_ = l.sc.RDB.Expire(ctx, key, ttl).Err()
	}
	if int(n) > limit {
		return apierr.RateLimited("通知发送过于频繁,请稍后重试")
	}
	return nil
}

// recipientHash 对接收人做 HMAC,Redis 中不出现明文号码/邮箱。
func (l *NotifyLogic) recipientHash(to string) string {
	mac := hmac.New(sha256.New, []byte(l.sc.Secrets.PhonePepper))
	mac.Write([]byte(to))
	return hex.EncodeToString(mac.Sum(nil))
}

// Package audit 提供只记录枚举与数值的结构化审计日志,禁止写入任何自由文本。
package audit

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/zeromicro/go-zero/core/logx"
)

// Actor 类型。
const (
	ActorUser   = "user"
	ActorAdmin  = "admin"
	ActorSystem = "system"
)

// Event 是审计事件枚举;不在集合内的事件会被拒绝写入。
type Event string

const (
	EventCreditGrant     Event = "credit.grant"
	EventCreditRecharge  Event = "credit.recharge"
	EventCreditRefund    Event = "credit.refund"
	EventCreditConsume   Event = "credit.consume"
	EventCreditHold      Event = "credit.hold"
	EventCreditRelease   Event = "credit.release"
	EventPriceUpdate     Event = "price.update"
	EventAdminGrant      Event = "admin.grant"
	EventNotifyEmergency Event = "notify.emergency"
	EventUpstreamFatal   Event = "upstream.fatal"
	EventAccountDelete   Event = "account.delete"
	EventOrderPaid       Event = "order.paid"
	EventOrderCredited   Event = "order.credited"
	EventOrderCancelled  Event = "order.cancelled"
	EventPackageUpdate   Event = "package.update"
	EventConsentSign     Event = "consent.sign"
	EventHoldReclaim     Event = "system.hold_reclaim"
	EventAuthLogin       Event = "auth.login"
	EventAdminLogin      Event = "admin.login"
	EventContentPublish  Event = "content.publish"
)

var validEvents = map[Event]bool{
	EventCreditGrant: true, EventCreditRecharge: true, EventCreditRefund: true,
	EventCreditConsume: true, EventCreditHold: true, EventCreditRelease: true,
	EventPriceUpdate: true, EventAdminGrant: true, EventNotifyEmergency: true,
	EventUpstreamFatal: true, EventAccountDelete: true, EventOrderPaid: true,
	EventOrderCredited: true, EventOrderCancelled: true, EventPackageUpdate: true,
	EventConsentSign: true, EventHoldReclaim: true, EventAuthLogin: true,
	EventAdminLogin: true, EventContentPublish: true,
}

var validActors = map[string]bool{
	ActorUser: true, ActorAdmin: true, ActorSystem: true,
}

// Detail 只允许 Int 与 Enum 两类值,从类型层面阻止写入自由文本。
type Detail struct {
	m map[string]any
}

// NewDetail 创建空 detail。
func NewDetail() Detail { return Detail{m: map[string]any{}} }

// Int 记录整数值。
func (d Detail) Int(key string, v int64) Detail {
	d.m[key] = v
	return d
}

// Enum 记录枚举值(业务上只传固定常量)。
func (d Detail) Enum(key, v string) Detail {
	d.m[key] = v
	return d
}

// Map 返回底层只读副本。
func (d Detail) Map() map[string]any {
	out := make(map[string]any, len(d.m))
	for k, v := range d.m {
		out[k] = v
	}
	return out
}

// Logger 审计写入器。
type Logger struct {
	DB  *sql.DB
	Now func() time.Time
}

// New 创建审计写入器。
func New(db *sql.DB) *Logger {
	return &Logger{DB: db, Now: time.Now}
}

func (l *Logger) now() time.Time {
	if l.Now != nil {
		return l.Now()
	}
	return time.Now()
}

// Log 校验事件与 actor 后写入 audit_logs。detail 只含 Int/Enum。
func (l *Logger) Log(ctx context.Context, actorType string, actorID int64, event Event, detail Detail) error {
	if !validActors[actorType] {
		return fmt.Errorf("非法审计 actor 类型: %s", actorType)
	}
	if !validEvents[event] {
		return fmt.Errorf("非法审计事件: %s", event)
	}
	if l == nil || l.DB == nil {
		return errors.New("审计日志未初始化")
	}
	payload, err := json.Marshal(detail.m)
	if err != nil {
		return fmt.Errorf("序列化审计 detail: %w", err)
	}
	_, err = l.DB.ExecContext(ctx,
		`INSERT INTO audit_logs (actor_type, actor_id, event, detail, created_at) VALUES ($1,$2,$3,$4,$5)`,
		actorType, actorID, string(event), payload, l.now().UTC())
	if err != nil {
		return fmt.Errorf("写入审计日志: %w", err)
	}
	return nil
}

// Quiet 写入审计但不让失败影响主流程;失败只记录不带隐私的错误摘要。
func (l *Logger) Quiet(ctx context.Context, actorType string, actorID int64, event Event, detail Detail) {
	if err := l.Log(ctx, actorType, actorID, event, detail); err != nil {
		logx.Errorf("audit write failed: %v", err)
	}
}

package audit_test

import (
	"context"
	"encoding/json"
	"testing"

	"mhagent/internal/audit"
	"mhagent/internal/model"
	"mhagent/internal/testdb"
)

func setupAudit(t *testing.T) *audit.Logger {
	t.Helper()
	db := testdb.New(t)
	if err := model.MigrateUp(context.Background(), db); err != nil {
		t.Fatalf("迁移失败: %v", err)
	}
	return audit.New(db)
}

func TestLogWritesDetail(t *testing.T) {
	logger := setupAudit(t)
	ctx := context.Background()
	if err := logger.Log(ctx, audit.ActorUser, 7, audit.EventCreditConsume,
		audit.NewDetail().Int("user_id", 7).Int("amount", 12).Enum("kind", "consume")); err != nil {
		t.Fatalf("写入审计失败: %v", err)
	}
	var event, actor string
	var detail string
	if err := logger.DB.QueryRowContext(ctx,
		`SELECT event, actor_type, detail::text FROM audit_logs ORDER BY id DESC LIMIT 1`).
		Scan(&event, &actor, &detail); err != nil {
		t.Fatalf("读取审计失败: %v", err)
	}
	if event != string(audit.EventCreditConsume) || actor != audit.ActorUser {
		t.Fatalf("审计内容不符: %s %s", event, actor)
	}
	var parsed map[string]any
	if err := json.Unmarshal([]byte(detail), &parsed); err != nil {
		t.Fatalf("detail 不是合法 JSON: %v", err)
	}
	if parsed["user_id"] != float64(7) || parsed["amount"] != float64(12) || parsed["kind"] != "consume" {
		t.Fatalf("审计 detail 不符: %s", detail)
	}
}

func TestLogRejectsUnknownEventAndActor(t *testing.T) {
	logger := setupAudit(t)
	ctx := context.Background()
	if err := logger.Log(ctx, audit.ActorUser, 1, audit.Event("evil.event"), audit.NewDetail()); err == nil {
		t.Fatalf("非法事件应被拒绝")
	}
	if err := logger.Log(ctx, "robot", 1, audit.EventCreditGrant, audit.NewDetail()); err == nil {
		t.Fatalf("非法 actor 应被拒绝")
	}
	if err := logger.Log(ctx, audit.ActorSystem, 0, audit.EventHoldReclaim, audit.NewDetail()); err != nil {
		t.Fatalf("合法事件应写入: %v", err)
	}
}

func TestQuietDoesNotFailOnUnknownEvent(t *testing.T) {
	logger := setupAudit(t)
	// Quiet 只记录错误,不 panic、不阻塞主流程。
	logger.Quiet(context.Background(), audit.ActorSystem, 0, audit.Event("evil.event"), audit.NewDetail())
}

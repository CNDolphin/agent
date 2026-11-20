package logic

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"
	"time"

	"golang.org/x/crypto/bcrypt"

	"mhagent/internal/apierr"
	"mhagent/internal/audit"
	"mhagent/internal/auth"
	"mhagent/internal/credits"
	"mhagent/internal/svc"
)

// AdminLogic 管理端业务。
type AdminLogic struct {
	sc *svc.ServiceContext
}

// NewAdminLogic 创建管理端逻辑。
func NewAdminLogic(sc *svc.ServiceContext) *AdminLogic { return &AdminLogic{sc: sc} }

func requireSuper(ctx context.Context) (apierr.Admin, error) {
	admin, ok := apierr.GetAdmin(ctx)
	if !ok {
		return apierr.Admin{}, apierr.Unauthorized("未登录")
	}
	if admin.Role != "super" {
		return apierr.Admin{}, apierr.New(40301, 403, "无权限执行该操作")
	}
	return admin, nil
}

// AdminLoginResult 管理员登录结果。
type AdminLoginResult struct {
	AccessToken string
	ExpiresIn   int64
	Role        string
}

// Login 管理员登录。账号由 cmd/adminctl 创建。
func (l *AdminLogic) Login(ctx context.Context, username, password string) (AdminLoginResult, error) {
	if strings.TrimSpace(username) == "" || password == "" {
		return AdminLoginResult{}, apierr.BadRequest("用户名或密码不能为空")
	}
	var id int64
	var hash, role string
	err := l.sc.DB.QueryRowContext(ctx,
		`SELECT id, password_hash, role FROM admin_users WHERE username=$1`, username).Scan(&id, &hash, &role)
	if errors.Is(err, sql.ErrNoRows) {
		return AdminLoginResult{}, apierr.Unauthorized("用户名或密码错误")
	}
	if err != nil {
		return AdminLoginResult{}, apierr.Internal()
	}
	if bcrypt.CompareHashAndPassword([]byte(hash), []byte(password)) != nil {
		return AdminLoginResult{}, apierr.Unauthorized("用户名或密码错误")
	}
	token, expiresIn, err := l.sc.AdminTokens.Issue(id, role)
	if err != nil {
		return AdminLoginResult{}, apierr.Internal()
	}
	if l.sc.Audit != nil {
		l.sc.Audit.Quiet(ctx, audit.ActorAdmin, id, audit.EventAdminLogin,
			audit.NewDetail().Enum("role", role))
	}
	return AdminLoginResult{AccessToken: token, ExpiresIn: expiresIn, Role: role}, nil
}

// PriceView 价格视图。
type PriceView struct {
	Model        string `json:"model"`
	InHitPerM    int64  `json:"in_hit_per_m"`
	InMissPerM   int64  `json:"in_miss_per_m"`
	OutPerM      int64  `json:"out_per_m"`
	Thinking     string `json:"thinking"`
	MaxTokensCap int    `json:"max_tokens_cap"`
	Enabled      bool   `json:"enabled"`
	Version      int    `json:"version"`
	UpdatedAt    string `json:"updated_at"`
}

// ListPrices 返回全部模型价格(含未启用)。
func (l *AdminLogic) ListPrices(ctx context.Context) ([]PriceView, error) {
	rows, err := l.sc.DB.QueryContext(ctx,
		`SELECT model, in_hit_per_m, in_miss_per_m, out_per_m, thinking, max_tokens_cap, enabled, version, updated_at
		 FROM model_prices ORDER BY model ASC`)
	if err != nil {
		return nil, apierr.Internal()
	}
	defer rows.Close()
	var out []PriceView
	for rows.Next() {
		var v PriceView
		var updated time.Time
		if err := rows.Scan(&v.Model, &v.InHitPerM, &v.InMissPerM, &v.OutPerM, &v.Thinking, &v.MaxTokensCap, &v.Enabled, &v.Version, &updated); err != nil {
			return nil, apierr.Internal()
		}
		v.UpdatedAt = updated.UTC().Format(time.RFC3339)
		out = append(out, v)
	}
	return out, nil
}

// PriceUpdateInput 改价入参;nil 表示沿用旧值。
type PriceUpdateInput struct {
	InHitPerM    *int64  `json:"in_hit_per_m"`
	InMissPerM   *int64  `json:"in_miss_per_m"`
	OutPerM      *int64  `json:"out_per_m"`
	Thinking     *string `json:"thinking"`
	MaxTokensCap *int    `json:"max_tokens_cap"`
	Enabled      *bool   `json:"enabled"`
	Reason       string  `json:"reason"`
}

// UpdatePrice 改价:必须带 reason,版本 +1,写历史与审计并清缓存。
func (l *AdminLogic) UpdatePrice(ctx context.Context, model string, in PriceUpdateInput) (PriceView, error) {
	admin, err := requireSuper(ctx)
	if err != nil {
		return PriceView{}, err
	}
	model = strings.TrimSpace(model)
	if model == "" {
		return PriceView{}, apierr.BadRequest("model 不能为空")
	}
	if strings.TrimSpace(in.Reason) == "" {
		return PriceView{}, apierr.BadRequest("改价必须填写 reason")
	}

	view := PriceView{Model: model, Thinking: "disabled", MaxTokensCap: 2048}
	err = l.sc.DB.QueryRowContext(ctx,
		`SELECT in_hit_per_m, in_miss_per_m, out_per_m, thinking, max_tokens_cap, enabled, version
		 FROM model_prices WHERE model=$1`, model).
		Scan(&view.InHitPerM, &view.InMissPerM, &view.OutPerM, &view.Thinking, &view.MaxTokensCap, &view.Enabled, &view.Version)
	found := true
	if errors.Is(err, sql.ErrNoRows) {
		found = false
	} else if err != nil {
		return PriceView{}, apierr.Internal()
	}

	if in.InHitPerM != nil {
		view.InHitPerM = *in.InHitPerM
	}
	if in.InMissPerM != nil {
		view.InMissPerM = *in.InMissPerM
	}
	if in.OutPerM != nil {
		view.OutPerM = *in.OutPerM
	}
	if in.Thinking != nil {
		view.Thinking = *in.Thinking
	}
	if in.MaxTokensCap != nil {
		view.MaxTokensCap = *in.MaxTokensCap
	}
	if in.Enabled != nil {
		view.Enabled = *in.Enabled
	}
	if !found {
		view.Version = 1
	} else {
		view.Version++
	}

	maxPrice := l.sc.Config.Admin.MaxPricePerM
	if view.InHitPerM < 0 || view.InMissPerM < 0 || view.OutPerM < 0 ||
		view.InHitPerM > maxPrice || view.InMissPerM > maxPrice || view.OutPerM > maxPrice {
		return PriceView{}, apierr.BadRequest("价格超出允许范围")
	}
	if view.Thinking != "enabled" && view.Thinking != "disabled" {
		return PriceView{}, apierr.BadRequest("thinking 取值非法")
	}
	if view.MaxTokensCap < 1 || view.MaxTokensCap > 393216 {
		return PriceView{}, apierr.BadRequest("max_tokens_cap 超出允许范围")
	}

	now := l.sc.Now().UTC()
	tx, err := l.sc.DB.BeginTx(ctx, nil)
	if err != nil {
		return PriceView{}, apierr.Internal()
	}
	defer func() { _ = tx.Rollback() }()

	_, err = tx.ExecContext(ctx,
		`INSERT INTO model_prices (model, in_hit_per_m, in_miss_per_m, out_per_m, thinking, max_tokens_cap, enabled, version, updated_at)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
		 ON CONFLICT (model) DO UPDATE SET
		   in_hit_per_m=EXCLUDED.in_hit_per_m, in_miss_per_m=EXCLUDED.in_miss_per_m, out_per_m=EXCLUDED.out_per_m,
		   thinking=EXCLUDED.thinking, max_tokens_cap=EXCLUDED.max_tokens_cap, enabled=EXCLUDED.enabled,
		   version=EXCLUDED.version, updated_at=EXCLUDED.updated_at`,
		model, view.InHitPerM, view.InMissPerM, view.OutPerM, view.Thinking, view.MaxTokensCap, view.Enabled, view.Version, now)
	if err != nil {
		return PriceView{}, apierr.Internal()
	}
	if _, err := tx.ExecContext(ctx,
		`INSERT INTO model_price_history (model, version, in_hit_per_m, in_miss_per_m, out_per_m, enabled, admin_id, reason, created_at)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)`,
		model, view.Version, view.InHitPerM, view.InMissPerM, view.OutPerM, view.Enabled, admin.ID, in.Reason, now); err != nil {
		return PriceView{}, apierr.Internal()
	}
	if err := tx.Commit(); err != nil {
		return PriceView{}, apierr.Internal()
	}
	l.sc.Prices.Invalidate()
	if l.sc.Audit != nil {
		l.sc.Audit.Quiet(ctx, audit.ActorAdmin, admin.ID, audit.EventPriceUpdate,
			audit.NewDetail().Enum("model", model).Int("version", int64(view.Version)).Enum("enabled", boolEnum(view.Enabled)))
	}
	view.UpdatedAt = now.Format(time.RFC3339)
	return view, nil
}

// PriceHistoryView 价格历史视图。
type PriceHistoryView struct {
	ID         int64  `json:"id"`
	Model      string `json:"model"`
	Version    int    `json:"version"`
	InHitPerM  int64  `json:"in_hit_per_m"`
	InMissPerM int64  `json:"in_miss_per_m"`
	OutPerM    int64  `json:"out_per_m"`
	Enabled    bool   `json:"enabled"`
	AdminID    int64  `json:"admin_id"`
	Reason     string `json:"reason"`
	CreatedAt  string `json:"created_at"`
}

// ListPriceHistory 返回指定模型的改价历史,按版本倒序。
func (l *AdminLogic) ListPriceHistory(ctx context.Context, model string) ([]PriceHistoryView, error) {
	rows, err := l.sc.DB.QueryContext(ctx,
		`SELECT id, model, version, in_hit_per_m, in_miss_per_m, out_per_m, enabled, admin_id, reason, created_at
		 FROM model_price_history WHERE model=$1 ORDER BY version DESC LIMIT 100`, model)
	if err != nil {
		return nil, apierr.Internal()
	}
	defer rows.Close()
	var out []PriceHistoryView
	for rows.Next() {
		var v PriceHistoryView
		var created time.Time
		if err := rows.Scan(&v.ID, &v.Model, &v.Version, &v.InHitPerM, &v.InMissPerM, &v.OutPerM, &v.Enabled, &v.AdminID, &v.Reason, &created); err != nil {
			return nil, apierr.Internal()
		}
		v.CreatedAt = created.UTC().Format(time.RFC3339)
		out = append(out, v)
	}
	return out, rows.Err()
}

func boolEnum(v bool) string {
	if v {
		return "true"
	}
	return "false"
}

// GrantInput 管理员发放积分入参。
type GrantInput struct {
	Phone     string `json:"phone,omitempty"`
	UserID    int64  `json:"user_id,omitempty"`
	Amount    int64  `json:"amount"`
	Reason    string `json:"reason"`
	RequestID string `json:"request_id"`
}

// GrantResult 发放结果。
type GrantResult struct {
	UserID  int64 `json:"user_id"`
	Balance int64 `json:"balance"`
	Held    int64 `json:"held"`
}

// Grant 管理员发放积分,request_id 保证幂等。
func (l *AdminLogic) Grant(ctx context.Context, in GrantInput) (GrantResult, error) {
	admin, err := requireSuper(ctx)
	if err != nil {
		return GrantResult{}, err
	}
	if in.Amount <= 0 || in.Amount > l.sc.Config.Admin.MaxGrant {
		return GrantResult{}, apierr.BadRequest("发放数量必须在 1 到上限之间")
	}
	if strings.TrimSpace(in.Reason) == "" || strings.TrimSpace(in.RequestID) == "" {
		return GrantResult{}, apierr.BadRequest("必须填写 reason 与 request_id")
	}
	if (in.Phone == "" && in.UserID == 0) || (in.Phone != "" && in.UserID != 0) {
		return GrantResult{}, apierr.BadRequest("phone 与 user_id 必须且只能提供一个")
	}
	var userID int64
	if in.Phone != "" {
		hash, err := auth.HashPhone(l.sc.Secrets.PhonePepper, in.Phone)
		if err != nil {
			return GrantResult{}, apierr.BadRequest("手机号格式不正确")
		}
		err = l.sc.DB.QueryRowContext(ctx,
			`SELECT id FROM users WHERE phone_hash=$1 AND deleted_at IS NULL`, hash).Scan(&userID)
		if errors.Is(err, sql.ErrNoRows) {
			return GrantResult{}, apierr.BadRequest("用户不存在")
		}
		if err != nil {
			return GrantResult{}, apierr.Internal()
		}
	} else {
		var one int
		err = l.sc.DB.QueryRowContext(ctx, `SELECT 1 FROM users WHERE id=$1 AND deleted_at IS NULL`, in.UserID).Scan(&one)
		if errors.Is(err, sql.ErrNoRows) {
			return GrantResult{}, apierr.BadRequest("用户不存在")
		}
		if err != nil {
			return GrantResult{}, apierr.Internal()
		}
		userID = in.UserID
	}

	if err := l.sc.Ledger.Credit(ctx, userID, in.Amount, "grant", in.RequestID); err != nil {
		return GrantResult{}, apierr.Internal()
	}
	bal, err := l.sc.Ledger.Balance(ctx, userID)
	if err != nil {
		return GrantResult{}, apierr.Internal()
	}
	if l.sc.Audit != nil {
		l.sc.Audit.Quiet(ctx, audit.ActorAdmin, admin.ID, audit.EventAdminGrant,
			audit.NewDetail().Int("user_id", userID).Int("amount", in.Amount))
	}
	return GrantResult{UserID: userID, Balance: bal.Balance, Held: bal.Held}, nil
}

// AdminUserView 管理端用户视图(手机号仅脱敏)。
type AdminUserView struct {
	ID        int64  `json:"id"`
	PhoneMask string `json:"phone_mask"`
	Balance   int64  `json:"balance"`
	Held      int64  `json:"held"`
	Available int64  `json:"available"`
	CreatedAt string `json:"created_at"`
}

// SearchUsers 按手机号精确查询,未提供时返回最近 50 个未注销用户。
func (l *AdminLogic) SearchUsers(ctx context.Context, phone string) ([]AdminUserView, error) {
	q := `SELECT u.id, u.phone_mask, COALESCE(a.balance,0), COALESCE(a.held,0), u.created_at
		  FROM users u LEFT JOIN credit_accounts a ON a.user_id=u.id
		  WHERE u.deleted_at IS NULL`
	args := []any{}
	if phone != "" {
		hash, err := auth.HashPhone(l.sc.Secrets.PhonePepper, phone)
		if err != nil {
			return nil, apierr.BadRequest("手机号格式不正确")
		}
		q += ` AND u.phone_hash=$1`
		args = append(args, hash)
	}
	q += ` ORDER BY u.id DESC LIMIT 50`
	rows, err := l.sc.DB.QueryContext(ctx, q, args...)
	if err != nil {
		return nil, apierr.Internal()
	}
	defer rows.Close()
	var out []AdminUserView
	for rows.Next() {
		var v AdminUserView
		var created time.Time
		if err := rows.Scan(&v.ID, &v.PhoneMask, &v.Balance, &v.Held, &created); err != nil {
			return nil, apierr.Internal()
		}
		v.Available = v.Balance - v.Held
		v.CreatedAt = created.UTC().Format(time.RFC3339)
		out = append(out, v)
	}
	return out, nil
}

// AdminLedgerItem 管理端流水项。
type AdminLedgerItem struct {
	ID           int64  `json:"id"`
	Type         string `json:"type"`
	Amount       int64  `json:"amount"`
	Ref          string `json:"ref"`
	BalanceAfter int64  `json:"balance_after"`
	HeldAfter    int64  `json:"held_after"`
	CreatedAt    string `json:"created_at"`
}

// AdminLedger 管理端查看用户流水,按 id 倒序游标分页。
func (l *AdminLogic) AdminLedger(ctx context.Context, userID int64, beforeID int64, limit int) ([]AdminLedgerItem, int64, error) {
	entries, err := credits.ListEntries(ctx, l.sc.DB, userID, beforeID, limit)
	if err != nil {
		return nil, 0, apierr.Internal()
	}
	out := make([]AdminLedgerItem, 0, len(entries))
	for _, e := range entries {
		out = append(out, AdminLedgerItem{
			ID: e.ID, Type: e.Type, Amount: e.Amount, Ref: e.Ref,
			BalanceAfter: e.BalanceAfter, HeldAfter: e.HeldAfter,
			CreatedAt: e.CreatedAt.UTC().Format(time.RFC3339),
		})
	}
	var next int64
	if len(entries) == limit {
		next = entries[len(entries)-1].ID
	}
	return out, next, nil
}

// UsageSummaryRow 用量汇总行。
type UsageSummaryRow struct {
	Model    string `json:"model"`
	Requests int64  `json:"requests"`
	InHit    int64  `json:"in_hit"`
	InMiss   int64  `json:"in_miss"`
	Out      int64  `json:"out"`
	Cost     int64  `json:"cost"`
}

// UsageSummary 按模型汇总用量。
func (l *AdminLogic) UsageSummary(ctx context.Context, from, to time.Time) ([]UsageSummaryRow, error) {
	rows, err := l.sc.DB.QueryContext(ctx,
		`SELECT model, count(*), COALESCE(sum(in_hit),0), COALESCE(sum(in_miss),0), COALESCE(sum(out_tokens),0), COALESCE(sum(cost),0)
		 FROM usage_logs WHERE created_at >= $1 AND created_at <= $2
		 GROUP BY model ORDER BY model`, from.UTC(), to.UTC())
	if err != nil {
		return nil, apierr.Internal()
	}
	defer rows.Close()
	var out []UsageSummaryRow
	for rows.Next() {
		var v UsageSummaryRow
		if err := rows.Scan(&v.Model, &v.Requests, &v.InHit, &v.InMiss, &v.Out, &v.Cost); err != nil {
			return nil, apierr.Internal()
		}
		out = append(out, v)
	}
	return out, nil
}

// NotifyLogView 通知记录(不含接收人与参数)。
type NotifyLogView struct {
	ID         int64  `json:"id"`
	UserID     int64  `json:"user_id"`
	Channel    string `json:"channel"`
	TemplateID string `json:"template_id"`
	Status     string `json:"status"`
	CreatedAt  string `json:"created_at"`
}

// NotifyLogs 最近通知记录。
func (l *AdminLogic) NotifyLogs(ctx context.Context) ([]NotifyLogView, error) {
	rows, err := l.sc.DB.QueryContext(ctx,
		`SELECT id, user_id, channel, template_id, status, created_at
		 FROM notify_logs ORDER BY id DESC LIMIT 100`)
	if err != nil {
		return nil, apierr.Internal()
	}
	defer rows.Close()
	var out []NotifyLogView
	for rows.Next() {
		var v NotifyLogView
		var created time.Time
		if err := rows.Scan(&v.ID, &v.UserID, &v.Channel, &v.TemplateID, &v.Status, &created); err != nil {
			return nil, apierr.Internal()
		}
		v.CreatedAt = created.UTC().Format(time.RFC3339)
		out = append(out, v)
	}
	return out, nil
}

// ParseTime 解析 RFC3339 或 YYYY-MM-DD。
func ParseTime(v string) (time.Time, error) {
	if v == "" {
		return time.Time{}, fmt.Errorf("空时间")
	}
	if t, err := time.Parse(time.RFC3339, v); err == nil {
		return t, nil
	}
	return time.Parse("2006-01-02", v)
}

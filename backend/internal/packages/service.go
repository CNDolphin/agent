// Package packages 实现套餐与订单,购买成功后一次性入账套餐积分。
package packages

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"mhagent/internal/audit"
	"mhagent/internal/credits"
	"mhagent/internal/payment"
)

// 业务错误。
var (
	ErrPackageNotFound = errors.New("package not found")
	ErrPackageDisabled = errors.New("package disabled")
	ErrOrderNotFound   = errors.New("order not found")
	ErrInvalidState    = errors.New("invalid order state")
	ErrInvalidInput    = errors.New("invalid input")
	ErrTooManyOrders   = errors.New("too many orders today")
)

// Package 套餐。
type Package struct {
	ID          int64     `json:"id"`
	Name        string    `json:"name"`
	Description string    `json:"description"`
	PriceCents  int64     `json:"price_cents"`
	Credits     int64     `json:"credits"`
	Enabled     bool      `json:"enabled"`
	SortOrder   int       `json:"sort_order"`
	UpdatedAt   time.Time `json:"updated_at"`
}

// CreatePackageInput 创建套餐入参。
type CreatePackageInput struct {
	Name        string
	Description string
	PriceCents  int64
	Credits     int64
	Enabled     bool
	SortOrder   int
}

// UpdatePackageInput 修改套餐入参(nil 表示不修改)。
type UpdatePackageInput struct {
	Name        *string
	Description *string
	PriceCents  *int64
	Credits     *int64
	Enabled     *bool
	SortOrder   *int
}

// AdminOrder 管理端订单(附带脱敏手机号)。
type AdminOrder struct {
	payment.Order
	PhoneMask string `json:"phone_mask"`
}

// Service 套餐与订单服务。
type Service struct {
	DB              *sql.DB
	Ledger          credits.Ledger
	Audit           *audit.Logger
	Providers       map[string]payment.Provider
	DefaultChannel  string
	MaxOrdersPerDay int
	Now             func() time.Time
}

// New 创建服务。
func New(db *sql.DB, ledger credits.Ledger, a *audit.Logger, providers map[string]payment.Provider, defaultChannel string, maxOrdersPerDay int) *Service {
	return &Service{
		DB: db, Ledger: ledger, Audit: a, Providers: providers,
		DefaultChannel: defaultChannel, MaxOrdersPerDay: maxOrdersPerDay, Now: time.Now,
	}
}

func (s *Service) now() time.Time {
	if s.Now != nil {
		return s.Now()
	}
	return time.Now()
}

// ListPackages 只返回已上架套餐。
func (s *Service) ListPackages(ctx context.Context) ([]Package, error) {
	return s.queryPackages(ctx, true)
}

// ListAllPackages 返回全部套餐(管理端)。
func (s *Service) ListAllPackages(ctx context.Context) ([]Package, error) {
	return s.queryPackages(ctx, false)
}

func (s *Service) queryPackages(ctx context.Context, onlyEnabled bool) ([]Package, error) {
	q := `SELECT id, name, description, price_cents, credits, enabled, sort_order, updated_at FROM packages`
	if onlyEnabled {
		q += ` WHERE enabled=true`
	}
	q += ` ORDER BY sort_order ASC, id ASC`
	rows, err := s.DB.QueryContext(ctx, q)
	if err != nil {
		return nil, fmt.Errorf("查询套餐: %w", err)
	}
	defer rows.Close()
	var out []Package
	for rows.Next() {
		var p Package
		if err := rows.Scan(&p.ID, &p.Name, &p.Description, &p.PriceCents, &p.Credits, &p.Enabled, &p.SortOrder, &p.UpdatedAt); err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, rows.Err()
}

// CreatePackage 创建套餐,默认不上架。
func (s *Service) CreatePackage(ctx context.Context, in CreatePackageInput) (Package, error) {
	if strings.TrimSpace(in.Name) == "" || in.Credits <= 0 || in.PriceCents < 0 {
		return Package{}, ErrInvalidInput
	}
	var p Package
	err := s.DB.QueryRowContext(ctx,
		`INSERT INTO packages (name, description, price_cents, credits, enabled, sort_order, updated_at)
		 VALUES ($1,$2,$3,$4,$5,$6,$7)
		 RETURNING id, name, description, price_cents, credits, enabled, sort_order, updated_at`,
		strings.TrimSpace(in.Name), in.Description, in.PriceCents, in.Credits, in.Enabled, in.SortOrder, s.now().UTC()).
		Scan(&p.ID, &p.Name, &p.Description, &p.PriceCents, &p.Credits, &p.Enabled, &p.SortOrder, &p.UpdatedAt)
	if err != nil {
		return Package{}, fmt.Errorf("创建套餐: %w", err)
	}
	s.audit(ctx, audit.EventPackageUpdate, audit.NewDetail().Int("package_id", p.ID).Enum("action", "create"))
	return p, nil
}

// UpdatePackage 修改套餐(含上下架)。
func (s *Service) UpdatePackage(ctx context.Context, id int64, in UpdatePackageInput, adminID int64) (Package, error) {
	current, err := s.getPackage(ctx, id)
	if err != nil {
		return Package{}, err
	}
	if in.Name != nil {
		if strings.TrimSpace(*in.Name) == "" {
			return Package{}, ErrInvalidInput
		}
		current.Name = strings.TrimSpace(*in.Name)
	}
	if in.Description != nil {
		current.Description = *in.Description
	}
	if in.PriceCents != nil {
		if *in.PriceCents < 0 {
			return Package{}, ErrInvalidInput
		}
		current.PriceCents = *in.PriceCents
	}
	if in.Credits != nil {
		if *in.Credits <= 0 {
			return Package{}, ErrInvalidInput
		}
		current.Credits = *in.Credits
	}
	if in.Enabled != nil {
		current.Enabled = *in.Enabled
	}
	if in.SortOrder != nil {
		current.SortOrder = *in.SortOrder
	}
	_, err = s.DB.ExecContext(ctx,
		`UPDATE packages SET name=$2, description=$3, price_cents=$4, credits=$5, enabled=$6, sort_order=$7, updated_at=$8 WHERE id=$1`,
		id, current.Name, current.Description, current.PriceCents, current.Credits, current.Enabled, current.SortOrder, s.now().UTC())
	if err != nil {
		return Package{}, fmt.Errorf("修改套餐: %w", err)
	}
	s.audit(ctx, audit.EventPackageUpdate, audit.NewDetail().Int("package_id", id).Enum("action", "update").Int("admin_id", adminID))
	return s.getPackage(ctx, id)
}

func (s *Service) getPackage(ctx context.Context, id int64) (Package, error) {
	var p Package
	err := s.DB.QueryRowContext(ctx,
		`SELECT id, name, description, price_cents, credits, enabled, sort_order, updated_at FROM packages WHERE id=$1`, id).
		Scan(&p.ID, &p.Name, &p.Description, &p.PriceCents, &p.Credits, &p.Enabled, &p.SortOrder, &p.UpdatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return Package{}, ErrPackageNotFound
	}
	if err != nil {
		return Package{}, fmt.Errorf("查询套餐: %w", err)
	}
	return p, nil
}

// CreateOrder 下单并返回支付参数。
func (s *Service) CreateOrder(ctx context.Context, userID, packageID int64, channel string) (payment.Order, payment.PayParams, error) {
	pkg, err := s.getPackage(ctx, packageID)
	if errors.Is(err, sql.ErrNoRows) {
		return payment.Order{}, payment.PayParams{}, ErrPackageNotFound
	}
	if err != nil {
		return payment.Order{}, payment.PayParams{}, err
	}
	if !pkg.Enabled {
		return payment.Order{}, payment.PayParams{}, ErrPackageDisabled
	}
	if channel == "" {
		channel = s.DefaultChannel
	}
	provider, ok := s.Providers[channel]
	if !ok {
		return payment.Order{}, payment.PayParams{}, payment.ErrUnsupportedChannel
	}
	if s.MaxOrdersPerDay > 0 {
		start := time.Date(s.now().Year(), s.now().Month(), s.now().Day(), 0, 0, 0, 0, time.UTC)
		var n int
		if err := s.DB.QueryRowContext(ctx,
			`SELECT count(*) FROM orders WHERE user_id=$1 AND created_at >= $2`, userID, start).Scan(&n); err != nil {
			return payment.Order{}, payment.PayParams{}, fmt.Errorf("统计订单: %w", err)
		}
		if n >= s.MaxOrdersPerDay {
			return payment.Order{}, payment.PayParams{}, ErrTooManyOrders
		}
	}

	var o payment.Order
	var createdAt time.Time
	err = s.DB.QueryRowContext(ctx,
		`INSERT INTO orders (user_id, package_id, package_name, price_cents, credits, status, channel)
		 VALUES ($1,$2,$3,$4,$5,$6,$7)
		 RETURNING id, user_id, package_id, package_name, price_cents, credits, status, channel, created_at`,
		userID, pkg.ID, pkg.Name, pkg.PriceCents, pkg.Credits, payment.StatusPending, channel).
		Scan(&o.ID, &o.UserID, &o.PackageID, &o.PackageName, &o.PriceCents, &o.Credits, &o.Status, &o.Channel, &createdAt)
	if err != nil {
		return payment.Order{}, payment.PayParams{}, fmt.Errorf("创建订单: %w", err)
	}
	o.CreatedAt = createdAt.UTC().Format(time.RFC3339)
	payParams, err := provider.CreatePayment(ctx, o)
	if err != nil {
		return payment.Order{}, payment.PayParams{}, err
	}
	return o, payParams, nil
}

// ListOrders 返回用户自己的订单。
func (s *Service) ListOrders(ctx context.Context, userID int64) ([]payment.Order, error) {
	rows, err := s.DB.QueryContext(ctx,
		`SELECT id, user_id, package_id, package_name, price_cents, credits, status, channel, COALESCE(trade_no,''), created_at, paid_at
		 FROM orders WHERE user_id=$1 ORDER BY id DESC LIMIT 100`, userID)
	if err != nil {
		return nil, fmt.Errorf("查询订单: %w", err)
	}
	defer rows.Close()
	var out []payment.Order
	for rows.Next() {
		var o payment.Order
		var createdAt time.Time
		var paidAt sql.NullTime
		if err := rows.Scan(&o.ID, &o.UserID, &o.PackageID, &o.PackageName, &o.PriceCents, &o.Credits, &o.Status, &o.Channel, &o.TradeNo, &createdAt, &paidAt); err != nil {
			return nil, err
		}
		o.CreatedAt = createdAt.UTC().Format(time.RFC3339)
		if paidAt.Valid {
			o.PaidAt = paidAt.Time.UTC().Format(time.RFC3339)
		}
		out = append(out, o)
	}
	return out, rows.Err()
}

// ListAllOrders 管理端订单列表,可按状态与手机号哈希过滤。
func (s *Service) ListAllOrders(ctx context.Context, status, phoneHash string) ([]AdminOrder, error) {
	q := `SELECT o.id, o.user_id, o.package_id, o.package_name, o.price_cents, o.credits, o.status, o.channel,
		 COALESCE(o.trade_no,''), o.created_at, o.paid_at, COALESCE(u.phone_mask,'')
		 FROM orders o LEFT JOIN users u ON u.id = o.user_id`
	args := []any{}
	conds := []string{}
	if status != "" {
		conds = append(conds, fmt.Sprintf("o.status=$%d", len(args)+1))
		args = append(args, status)
	}
	if phoneHash != "" {
		conds = append(conds, fmt.Sprintf("u.phone_hash=$%d", len(args)+1))
		args = append(args, phoneHash)
	}
	if len(conds) > 0 {
		q += ` WHERE ` + strings.Join(conds, " AND ")
	}
	q += ` ORDER BY o.id DESC LIMIT 200`
	rows, err := s.DB.QueryContext(ctx, q, args...)
	if err != nil {
		return nil, fmt.Errorf("查询订单: %w", err)
	}
	defer rows.Close()
	var out []AdminOrder
	for rows.Next() {
		var o AdminOrder
		var createdAt time.Time
		var paidAt sql.NullTime
		if err := rows.Scan(&o.ID, &o.UserID, &o.PackageID, &o.PackageName, &o.PriceCents, &o.Credits, &o.Status, &o.Channel, &o.TradeNo, &createdAt, &paidAt, &o.PhoneMask); err != nil {
			return nil, err
		}
		o.CreatedAt = createdAt.UTC().Format(time.RFC3339)
		if paidAt.Valid {
			o.PaidAt = paidAt.Time.UTC().Format(time.RFC3339)
		}
		out = append(out, o)
	}
	return out, rows.Err()
}

// GetOrder 读取订单。
func (s *Service) GetOrder(ctx context.Context, id int64) (payment.Order, error) {
	var o payment.Order
	var createdAt time.Time
	var paidAt sql.NullTime
	err := s.DB.QueryRowContext(ctx,
		`SELECT id, user_id, package_id, package_name, price_cents, credits, status, channel, COALESCE(trade_no,''), created_at, paid_at
		 FROM orders WHERE id=$1`, id).
		Scan(&o.ID, &o.UserID, &o.PackageID, &o.PackageName, &o.PriceCents, &o.Credits, &o.Status, &o.Channel, &o.TradeNo, &createdAt, &paidAt)
	if errors.Is(err, sql.ErrNoRows) {
		return payment.Order{}, ErrOrderNotFound
	}
	if err != nil {
		return payment.Order{}, fmt.Errorf("读取订单: %w", err)
	}
	o.CreatedAt = createdAt.UTC().Format(time.RFC3339)
	if paidAt.Valid {
		o.PaidAt = paidAt.Time.UTC().Format(time.RFC3339)
	}
	return o, nil
}

// HandleCallback 校验渠道回调并完成入账。
func (s *Service) HandleCallback(ctx context.Context, channel string, r *http.Request) (payment.Order, error) {
	provider, ok := s.Providers[channel]
	if !ok {
		return payment.Order{}, payment.ErrUnsupportedChannel
	}
	orderID, tradeNo, err := provider.VerifyCallback(ctx, r)
	if err != nil {
		return payment.Order{}, err
	}
	return s.markPaidAndCredit(ctx, orderID, channel, tradeNo, audit.ActorSystem, 0)
}

// ConfirmManual 管理员确认线下收款。
func (s *Service) ConfirmManual(ctx context.Context, orderID, adminID int64) (payment.Order, error) {
	o, err := s.GetOrder(ctx, orderID)
	if err != nil {
		return payment.Order{}, err
	}
	if o.Channel != payment.ChannelManual {
		return payment.Order{}, ErrInvalidState
	}
	return s.markPaidAndCredit(ctx, orderID, payment.ChannelManual, fmt.Sprintf("manual:%d", orderID), audit.ActorAdmin, adminID)
}

// Cancel 取消待支付订单。
func (s *Service) Cancel(ctx context.Context, orderID, adminID int64) (payment.Order, error) {
	o, err := s.GetOrder(ctx, orderID)
	if err != nil {
		return payment.Order{}, err
	}
	if o.Status == payment.StatusCancelled {
		return s.GetOrder(ctx, orderID)
	}
	if o.Status != payment.StatusPending {
		return payment.Order{}, ErrInvalidState
	}
	res, err := s.DB.ExecContext(ctx, `UPDATE orders SET status='cancelled' WHERE id=$1 AND status='pending'`, orderID)
	if err != nil {
		return payment.Order{}, fmt.Errorf("取消订单: %w", err)
	}
	if n, _ := res.RowsAffected(); n == 0 {
		return payment.Order{}, ErrInvalidState
	}
	s.audit(ctx, audit.EventOrderCancelled, audit.NewDetail().Int("order_id", orderID).Int("admin_id", adminID))
	return s.GetOrder(ctx, orderID)
}

// markPaidAndCredit 将订单推进到 credited 并幂等入账。
func (s *Service) markPaidAndCredit(ctx context.Context, orderID int64, channel, tradeNo, actorType string, actorID int64) (payment.Order, error) {
	o, err := s.GetOrder(ctx, orderID)
	if err != nil {
		return payment.Order{}, err
	}
	if o.Channel != channel {
		return payment.Order{}, ErrInvalidState
	}
	if o.Status == payment.StatusCancelled || o.Status == payment.StatusCredited {
		return o, nil
	}
	if o.Status == payment.StatusPending {
		res, execErr := s.DB.ExecContext(ctx,
			`UPDATE orders SET status='paid', trade_no=$2, paid_at=$3 WHERE id=$1 AND status='pending'`,
			orderID, nilIfEmpty(tradeNo), s.now().UTC())
		if execErr != nil {
			return payment.Order{}, fmt.Errorf("标记订单已支付: %w", execErr)
		}
		if n, _ := res.RowsAffected(); n == 0 {
			// 并发情况下另一个回调已推进,重新读取后再继续。
			return s.markPaidAndCredit(ctx, orderID, channel, tradeNo, actorType, actorID)
		}
		s.auditActor(ctx, actorType, actorID, audit.EventOrderPaid, audit.NewDetail().Int("order_id", orderID))
	} else if o.TradeNo != "" && tradeNo != "" && o.TradeNo != tradeNo {
		return payment.Order{}, ErrInvalidState
	}

	if err := s.Ledger.Credit(ctx, o.UserID, o.Credits, "recharge", fmt.Sprintf("order:%d", orderID)); err != nil {
		return payment.Order{}, fmt.Errorf("订单入账: %w", err)
	}
	if _, err := s.DB.ExecContext(ctx, `UPDATE orders SET status='credited' WHERE id=$1 AND status='paid'`, orderID); err != nil {
		return payment.Order{}, fmt.Errorf("标记订单已入账: %w", err)
	}
	s.auditActor(ctx, actorType, actorID, audit.EventOrderCredited, audit.NewDetail().Int("order_id", orderID).Int("credits", o.Credits))
	return s.GetOrder(ctx, orderID)
}

func nilIfEmpty(v string) any {
	if v == "" {
		return nil
	}
	return v
}

func (s *Service) audit(ctx context.Context, event audit.Event, d audit.Detail) {
	s.auditActor(ctx, audit.ActorAdmin, 0, event, d)
}

func (s *Service) auditActor(ctx context.Context, actorType string, actorID int64, event audit.Event, d audit.Detail) {
	if s.Audit != nil {
		s.Audit.Quiet(ctx, actorType, actorID, event, d)
	}
}

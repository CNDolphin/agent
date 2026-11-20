package credits

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"

	"mhagent/internal/audit"
)

// 账本错误。
var (
	ErrInsufficient     = errors.New("insufficient credits")
	ErrNoHold           = errors.New("hold not found")
	ErrAlreadyFinalized = errors.New("request already finalized")
	ErrInvalidKind      = errors.New("invalid ledger kind")
)

// Balance 账户余额与冻结额。
type Balance struct {
	Balance int64
	Held    int64
}

// Available 可用积分。
func (b Balance) Available() int64 { return b.Balance - b.Held }

// Ledger 积分账本接口。
type Ledger interface {
	// Credit kind 为 grant | recharge | refund。同 (user, requestID, kind) 重复调用不重复入账。
	Credit(ctx context.Context, userID, amount int64, kind, requestID string) error
	Hold(ctx context.Context, userID, amount int64, requestID string) error
	// Settle 将 hold 转为 consume(actual 封顶为 hold 额),差额写 release;重复调用返回首次结果。
	Settle(ctx context.Context, userID int64, requestID string, actual int64) (consumed int64, err error)
	// Release 全额释放(上游失败时)。已 settle 的请求不再变化。
	Release(ctx context.Context, userID int64, requestID string) error
	Balance(ctx context.Context, userID int64) (Balance, error)
}

// PGLedger 基于 PostgreSQL 事务 + 行锁的实现。
type PGLedger struct {
	DB    *sql.DB
	Audit *audit.Logger
	Now   func() time.Time
}

// NewPGLedger 创建账本实现。
func NewPGLedger(db *sql.DB) *PGLedger {
	return &PGLedger{DB: db, Now: time.Now}
}

func (l *PGLedger) now() time.Time {
	if l.Now != nil {
		return l.Now()
	}
	return time.Now()
}

func (l *PGLedger) audit(ctx context.Context, event audit.Event, detail audit.Detail) {
	if l.Audit != nil {
		l.Audit.Quiet(ctx, audit.ActorUser, 0, event, detail)
	}
}

// Credit 在独立事务内入账。
func (l *PGLedger) Credit(ctx context.Context, userID, amount int64, kind, requestID string) error {
	tx, err := l.DB.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	if err := CreditTx(ctx, tx, userID, amount, kind, requestID, l.now()); err != nil {
		return err
	}
	if err := tx.Commit(); err != nil {
		return fmt.Errorf("commit credit: %w", err)
	}
	event := audit.EventCreditGrant
	switch kind {
	case "recharge":
		event = audit.EventCreditRecharge
	case "refund":
		event = audit.EventCreditRefund
	}
	l.audit(ctx, event, audit.NewDetail().Int("user_id", userID).Int("amount", amount).Enum("kind", kind))
	return nil
}

// CreditTx 在调用方事务内入账,供注册赠送等需要原子性的场景使用。
func CreditTx(ctx context.Context, tx *sql.Tx, userID, amount int64, kind, requestID string, now time.Time) error {
	if amount <= 0 {
		return errors.New("credit amount must be positive")
	}
	switch kind {
	case "grant", "recharge", "refund":
	default:
		return ErrInvalidKind
	}
	balance, held, err := lockAccount(ctx, tx, userID)
	if err != nil {
		return err
	}
	exists, err := ledgerEntryExists(ctx, tx, userID, requestID, kind)
	if err != nil {
		return err
	}
	if exists {
		return nil
	}
	newBalance := balance + amount
	if _, err := tx.ExecContext(ctx,
		`UPDATE credit_accounts SET balance=$2, held=$3, updated_at=$4 WHERE user_id=$1`,
		userID, newBalance, held, now.UTC()); err != nil {
		return fmt.Errorf("update account: %w", err)
	}
	_, err = tx.ExecContext(ctx,
		`INSERT INTO credit_ledger (user_id, type, amount, request_id, balance_after, held_after, created_at)
		 VALUES ($1,$2,$3,$4,$5,$6,$7)`,
		userID, kind, amount, requestID, newBalance, held, now.UTC())
	if err != nil {
		return fmt.Errorf("insert ledger: %w", err)
	}
	return nil
}

// Hold 冻结积分。
func (l *PGLedger) Hold(ctx context.Context, userID, amount int64, requestID string) error {
	if amount <= 0 {
		return errors.New("hold amount must be positive")
	}
	tx, err := l.DB.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	balance, held, err := lockAccount(ctx, tx, userID)
	if err != nil {
		return err
	}
	exists, finalized, err := ledgerEntryState(ctx, tx, userID, requestID, "hold")
	if err != nil {
		return err
	}
	if exists {
		if finalized {
			return ErrAlreadyFinalized
		}
		return nil
	}
	if balance-held < amount {
		return ErrInsufficient
	}
	newHeld := held + amount
	if _, err := tx.ExecContext(ctx,
		`UPDATE credit_accounts SET held=$2, updated_at=$3 WHERE user_id=$1`,
		userID, newHeld, l.now().UTC()); err != nil {
		return fmt.Errorf("update held: %w", err)
	}
	if _, err := tx.ExecContext(ctx,
		`INSERT INTO credit_ledger (user_id, type, amount, request_id, balance_after, held_after, created_at)
		 VALUES ($1,'hold',$2,$3,$4,$5,$6)`,
		userID, amount, requestID, balance, newHeld, l.now().UTC()); err != nil {
		return fmt.Errorf("insert hold: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return fmt.Errorf("commit hold: %w", err)
	}
	l.audit(ctx, audit.EventCreditHold, audit.NewDetail().Int("user_id", userID).Int("amount", amount).Int("held_after", newHeld))
	return nil
}

// Settle 结算。
func (l *PGLedger) Settle(ctx context.Context, userID int64, requestID string, actual int64) (int64, error) {
	if actual < 0 {
		actual = 0
	}
	tx, err := l.DB.BeginTx(ctx, nil)
	if err != nil {
		return 0, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	balance, held, err := lockAccount(ctx, tx, userID)
	if err != nil {
		return 0, err
	}
	var holdAmount int64
	err = tx.QueryRowContext(ctx,
		`SELECT amount FROM credit_ledger WHERE user_id=$1 AND request_id=$2 AND type='hold'`,
		userID, requestID).Scan(&holdAmount)
	if errors.Is(err, sql.ErrNoRows) {
		return 0, ErrNoHold
	}
	if err != nil {
		return 0, fmt.Errorf("read hold: %w", err)
	}

	// 已结算:返回首次结果(consume 行金额;若已 release 则为 0)。
	var existing int64
	err = tx.QueryRowContext(ctx,
		`SELECT amount FROM credit_ledger WHERE user_id=$1 AND request_id=$2 AND type='consume'`,
		userID, requestID).Scan(&existing)
	if err == nil {
		return existing, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return 0, fmt.Errorf("read consume: %w", err)
	}
	var released int64
	err = tx.QueryRowContext(ctx,
		`SELECT amount FROM credit_ledger WHERE user_id=$1 AND request_id=$2 AND type='release'`,
		userID, requestID).Scan(&released)
	if err == nil {
		// 已经 release 的请求不会被再次结算。
		return 0, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return 0, fmt.Errorf("read release: %w", err)
	}

	consumed := actual
	capped := false
	if consumed > holdAmount {
		consumed = holdAmount
		capped = true
	}
	newBalance := balance - consumed
	newHeld := held - holdAmount
	if _, err := tx.ExecContext(ctx,
		`UPDATE credit_accounts SET balance=$2, held=$3, updated_at=$4 WHERE user_id=$1`,
		userID, newBalance, newHeld, l.now().UTC()); err != nil {
		return 0, fmt.Errorf("update settle: %w", err)
	}
	if consumed > 0 {
		ref := ""
		if capped {
			ref = "capped"
		}
		if err := insertLedgerRow(ctx, tx, userID, "consume", consumed, requestID, ref, newBalance, newHeld, l.now()); err != nil {
			return 0, err
		}
	}
	if rest := holdAmount - consumed; rest > 0 {
		if err := insertLedgerRow(ctx, tx, userID, "release", rest, requestID, "settle-rest", newBalance, newHeld, l.now()); err != nil {
			return 0, err
		}
	}
	if err := tx.Commit(); err != nil {
		return 0, fmt.Errorf("commit settle: %w", err)
	}
	if consumed > 0 {
		l.audit(ctx, audit.EventCreditConsume, audit.NewDetail().Int("user_id", userID).Int("amount", consumed).Int("balance_after", newBalance))
	}
	return consumed, nil
}

// Release 全额释放。
func (l *PGLedger) Release(ctx context.Context, userID int64, requestID string) error {
	tx, err := l.DB.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	balance, held, err := lockAccount(ctx, tx, userID)
	if err != nil {
		return err
	}
	var holdAmount int64
	err = tx.QueryRowContext(ctx,
		`SELECT amount FROM credit_ledger WHERE user_id=$1 AND request_id=$2 AND type='hold'`,
		userID, requestID).Scan(&holdAmount)
	if errors.Is(err, sql.ErrNoRows) {
		return ErrNoHold
	}
	if err != nil {
		return fmt.Errorf("read hold: %w", err)
	}
	exists, err := ledgerEntryExists(ctx, tx, userID, requestID, "release")
	if err != nil {
		return err
	}
	if exists {
		return nil
	}
	consumeExists, err := ledgerEntryExists(ctx, tx, userID, requestID, "consume")
	if err != nil {
		return err
	}
	if consumeExists {
		return nil
	}
	newHeld := held - holdAmount
	if _, err := tx.ExecContext(ctx,
		`UPDATE credit_accounts SET held=$2, updated_at=$3 WHERE user_id=$1`,
		userID, newHeld, l.now().UTC()); err != nil {
		return fmt.Errorf("update release: %w", err)
	}
	if err := insertLedgerRow(ctx, tx, userID, "release", holdAmount, requestID, "release", balance, newHeld, l.now()); err != nil {
		return err
	}
	if err := tx.Commit(); err != nil {
		return fmt.Errorf("commit release: %w", err)
	}
	l.audit(ctx, audit.EventCreditRelease, audit.NewDetail().Int("user_id", userID).Int("amount", holdAmount).Int("held_after", newHeld))
	return nil
}

// Balance 读取账户余额。
func (l *PGLedger) Balance(ctx context.Context, userID int64) (Balance, error) {
	var b Balance
	err := l.DB.QueryRowContext(ctx,
		`SELECT balance, held FROM credit_accounts WHERE user_id=$1`, userID).Scan(&b.Balance, &b.Held)
	if errors.Is(err, sql.ErrNoRows) {
		return Balance{}, nil
	}
	if err != nil {
		return Balance{}, fmt.Errorf("read balance: %w", err)
	}
	return b, nil
}

func insertLedgerRow(ctx context.Context, tx *sql.Tx, userID int64, typ string, amount int64, requestID, ref string, balanceAfter, heldAfter int64, now time.Time) error {
	var refArg any
	if ref != "" {
		refArg = ref
	}
	_, err := tx.ExecContext(ctx,
		`INSERT INTO credit_ledger (user_id, type, amount, request_id, ref, balance_after, held_after, created_at)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`,
		userID, typ, amount, requestID, refArg, balanceAfter, heldAfter, now.UTC())
	if err != nil {
		return fmt.Errorf("insert %s ledger: %w", typ, err)
	}
	return nil
}

// lockAccount 确保账户行存在并加行锁,返回余额与冻结额。
func lockAccount(ctx context.Context, tx *sql.Tx, userID int64) (int64, int64, error) {
	if userID <= 0 {
		return 0, 0, errors.New("invalid user id")
	}
	if _, err := tx.ExecContext(ctx,
		`INSERT INTO credit_accounts (user_id, balance, held) VALUES ($1,0,0) ON CONFLICT (user_id) DO NOTHING`,
		userID); err != nil {
		return 0, 0, fmt.Errorf("ensure account: %w", err)
	}
	var balance, held int64
	if err := tx.QueryRowContext(ctx,
		`SELECT balance, held FROM credit_accounts WHERE user_id=$1 FOR UPDATE`, userID).Scan(&balance, &held); err != nil {
		return 0, 0, fmt.Errorf("lock account: %w", err)
	}
	return balance, held, nil
}

func ledgerEntryExists(ctx context.Context, tx *sql.Tx, userID int64, requestID, typ string) (bool, error) {
	var one int
	err := tx.QueryRowContext(ctx,
		`SELECT 1 FROM credit_ledger WHERE user_id=$1 AND request_id=$2 AND type=$3`,
		userID, requestID, typ).Scan(&one)
	if errors.Is(err, sql.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("read ledger entry: %w", err)
	}
	return true, nil
}

// ledgerEntryState 查询 hold 是否存在,以及该 request 是否已有 consume/release(即已终结)。
func ledgerEntryState(ctx context.Context, tx *sql.Tx, userID int64, requestID, typ string) (exists, finalized bool, err error) {
	exists, err = ledgerEntryExists(ctx, tx, userID, requestID, typ)
	if err != nil || !exists {
		return exists, false, err
	}
	for _, t := range []string{"consume", "release"} {
		ok, e := ledgerEntryExists(ctx, tx, userID, requestID, t)
		if e != nil {
			return true, false, e
		}
		if ok {
			return true, true, nil
		}
	}
	return true, false, nil
}

// Entry 是账本流水的一行。
type Entry struct {
	ID           int64
	Type         string
	Amount       int64
	Ref          string
	BalanceAfter int64
	HeldAfter    int64
	CreatedAt    time.Time
}

// ListEntries 按 id 倒序读取流水;beforeID<=0 表示第一页。
func ListEntries(ctx context.Context, db *sql.DB, userID, beforeID int64, limit int) ([]Entry, error) {
	if limit <= 0 || limit > 100 {
		limit = 20
	}
	rows, err := db.QueryContext(ctx,
		`SELECT id, type, amount, COALESCE(ref,''), balance_after, held_after, created_at
		 FROM credit_ledger
		 WHERE user_id=$1 AND ($2=0 OR id < $2)
		 ORDER BY id DESC LIMIT $3`, userID, beforeID, limit)
	if err != nil {
		return nil, fmt.Errorf("list ledger: %w", err)
	}
	defer rows.Close()
	var out []Entry
	for rows.Next() {
		var e Entry
		if err := rows.Scan(&e.ID, &e.Type, &e.Amount, &e.Ref, &e.BalanceAfter, &e.HeldAfter, &e.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, rows.Err()
}

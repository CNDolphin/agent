package credits

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"sync"
	"sync/atomic"
	"testing"

	"mhagent/internal/model"
	"mhagent/internal/testdb"
)

func setupLedger(t *testing.T) (*sql.DB, *PGLedger, int64) {
	t.Helper()
	db := testdb.New(t)
	if err := model.MigrateUp(context.Background(), db); err != nil {
		t.Fatalf("执行迁移失败: %v", err)
	}
	ledger := NewPGLedger(db)
	return db, ledger, insertUser(t, db, "hash-a")
}

func insertUser(t *testing.T, db *sql.DB, phoneHash string) int64 {
	t.Helper()
	var id int64
	if err := db.QueryRow(
		`INSERT INTO users (phone_hash, phone_mask) VALUES ($1,'138****0000') RETURNING id`,
		phoneHash).Scan(&id); err != nil {
		t.Fatalf("插入用户失败: %v", err)
	}
	return id
}

func countRows(t *testing.T, db *sql.DB, query string, args ...any) int {
	t.Helper()
	var n int
	if err := db.QueryRow(query, args...).Scan(&n); err != nil {
		t.Fatalf("统计失败: %v", err)
	}
	return n
}

func mustBalance(t *testing.T, ledger *PGLedger, userID int64) Balance {
	t.Helper()
	b, err := ledger.Balance(context.Background(), userID)
	if err != nil {
		t.Fatalf("读取余额失败: %v", err)
	}
	return b
}

func TestCreditIsIdempotent(t *testing.T) {
	db, ledger, uid := setupLedger(t)
	ctx := context.Background()
	if err := ledger.Credit(ctx, uid, 100, "grant", "signup"); err != nil {
		t.Fatalf("入账失败: %v", err)
	}
	if err := ledger.Credit(ctx, uid, 100, "grant", "signup"); err != nil {
		t.Fatalf("重复入账不应报错: %v", err)
	}
	if b := mustBalance(t, ledger, uid); b.Balance != 100 {
		t.Fatalf("重复入账导致余额错误: %+v", b)
	}
	if n := countRows(t, db, `SELECT count(*) FROM credit_ledger WHERE user_id=$1`, uid); n != 1 {
		t.Fatalf("期望 1 条流水,实际 %d", n)
	}
}

func TestCreditRejectsInvalidInput(t *testing.T) {
	_, ledger, uid := setupLedger(t)
	ctx := context.Background()
	if err := ledger.Credit(ctx, uid, 0, "grant", "x"); err == nil {
		t.Fatalf("金额为 0 应报错")
	}
	if err := ledger.Credit(ctx, uid, 10, "hold", "x"); !errors.Is(err, ErrInvalidKind) {
		t.Fatalf("非法 kind 期望 ErrInvalidKind,实际 %v", err)
	}
}

func TestHoldSettleRelease(t *testing.T) {
	db, ledger, uid := setupLedger(t)
	ctx := context.Background()
	if err := ledger.Credit(ctx, uid, 100, "grant", "g1"); err != nil {
		t.Fatalf("入账失败: %v", err)
	}
	if err := ledger.Hold(ctx, uid, 30, "req-1"); err != nil {
		t.Fatalf("冻结失败: %v", err)
	}
	if b := mustBalance(t, ledger, uid); b.Held != 30 || b.Available() != 70 {
		t.Fatalf("冻结后余额错误: %+v", b)
	}
	// 重复冻结同一 request 不重复累计。
	if err := ledger.Hold(ctx, uid, 30, "req-1"); err != nil {
		t.Fatalf("重复冻结应幂等: %v", err)
	}
	if b := mustBalance(t, ledger, uid); b.Held != 30 {
		t.Fatalf("重复冻结导致 held 错误: %+v", b)
	}

	consumed, err := ledger.Settle(ctx, uid, "req-1", 20)
	if err != nil {
		t.Fatalf("结算失败: %v", err)
	}
	if consumed != 20 {
		t.Fatalf("期望消费 20,实际 %d", consumed)
	}
	b := mustBalance(t, ledger, uid)
	if b.Balance != 80 || b.Held != 0 {
		t.Fatalf("结算后余额错误: %+v", b)
	}
	if n := countRows(t, db, `SELECT count(*) FROM credit_ledger WHERE user_id=$1 AND type='consume' AND amount=20`, uid); n != 1 {
		t.Fatalf("期望 1 条 consume=20,实际 %d", n)
	}
	if n := countRows(t, db, `SELECT count(*) FROM credit_ledger WHERE user_id=$1 AND type='release' AND amount=10`, uid); n != 1 {
		t.Fatalf("期望 1 条 release=10,实际 %d", n)
	}

	// 重复结算返回首次结果,不再变化。
	again, err := ledger.Settle(ctx, uid, "req-1", 99)
	if err != nil || again != 20 {
		t.Fatalf("重复结算应返回首次结果 20,实际 %d %v", again, err)
	}
	if b := mustBalance(t, ledger, uid); b.Balance != 80 {
		t.Fatalf("重复结算改变了余额: %+v", b)
	}
}

func TestInsufficientCredits(t *testing.T) {
	db, ledger, uid := setupLedger(t)
	ctx := context.Background()
	if err := ledger.Credit(ctx, uid, 100, "grant", "g1"); err != nil {
		t.Fatalf("入账失败: %v", err)
	}
	if err := ledger.Hold(ctx, uid, 200, "req-big"); !errors.Is(err, ErrInsufficient) {
		t.Fatalf("期望 ErrInsufficient,实际 %v", err)
	}
	if b := mustBalance(t, ledger, uid); b.Balance != 100 || b.Held != 0 {
		t.Fatalf("失败冻结改变了账户: %+v", b)
	}
	if n := countRows(t, db, `SELECT count(*) FROM credit_ledger WHERE user_id=$1 AND type='hold'`, uid); n != 0 {
		t.Fatalf("失败冻结不应写入流水,实际 %d", n)
	}
}

func TestSettleCapsAtHoldAmount(t *testing.T) {
	_, ledger, uid := setupLedger(t)
	ctx := context.Background()
	if err := ledger.Credit(ctx, uid, 100, "grant", "g1"); err != nil {
		t.Fatalf("入账失败: %v", err)
	}
	if err := ledger.Hold(ctx, uid, 30, "req-1"); err != nil {
		t.Fatalf("冻结失败: %v", err)
	}
	consumed, err := ledger.Settle(ctx, uid, "req-1", 50)
	if err != nil {
		t.Fatalf("结算失败: %v", err)
	}
	if consumed != 30 {
		t.Fatalf("结算应封顶为 hold 额 30,实际 %d", consumed)
	}
	if b := mustBalance(t, ledger, uid); b.Balance != 70 || b.Held != 0 {
		t.Fatalf("封顶结算后余额错误: %+v", b)
	}
}

func TestReleaseThenSettle(t *testing.T) {
	db, ledger, uid := setupLedger(t)
	ctx := context.Background()
	if err := ledger.Credit(ctx, uid, 100, "grant", "g1"); err != nil {
		t.Fatalf("入账失败: %v", err)
	}
	if err := ledger.Hold(ctx, uid, 30, "req-1"); err != nil {
		t.Fatalf("冻结失败: %v", err)
	}
	if err := ledger.Release(ctx, uid, "req-1"); err != nil {
		t.Fatalf("释放失败: %v", err)
	}
	if err := ledger.Release(ctx, uid, "req-1"); err != nil {
		t.Fatalf("重复释放应幂等: %v", err)
	}
	if b := mustBalance(t, ledger, uid); b.Balance != 100 || b.Held != 0 {
		t.Fatalf("释放后余额错误: %+v", b)
	}
	consumed, err := ledger.Settle(ctx, uid, "req-1", 10)
	if err != nil || consumed != 0 {
		t.Fatalf("已释放请求再结算应返回 0,实际 %d %v", consumed, err)
	}
	if n := countRows(t, db, `SELECT count(*) FROM credit_ledger WHERE user_id=$1 AND type='consume'`, uid); n != 0 {
		t.Fatalf("已释放请求不应产生 consume,实际 %d", n)
	}
}

func TestHoldAfterFinalized(t *testing.T) {
	_, ledger, uid := setupLedger(t)
	ctx := context.Background()
	if err := ledger.Credit(ctx, uid, 100, "grant", "g1"); err != nil {
		t.Fatalf("入账失败: %v", err)
	}
	if err := ledger.Hold(ctx, uid, 10, "req-1"); err != nil {
		t.Fatalf("冻结失败: %v", err)
	}
	if _, err := ledger.Settle(ctx, uid, "req-1", 10); err != nil {
		t.Fatalf("结算失败: %v", err)
	}
	if err := ledger.Hold(ctx, uid, 10, "req-1"); !errors.Is(err, ErrAlreadyFinalized) {
		t.Fatalf("已结算的 request 再次冻结期望 ErrAlreadyFinalized,实际 %v", err)
	}
}

func TestSettleWithoutHold(t *testing.T) {
	_, ledger, uid := setupLedger(t)
	if _, err := ledger.Settle(context.Background(), uid, "none", 10); !errors.Is(err, ErrNoHold) {
		t.Fatalf("期望 ErrNoHold,实际 %v", err)
	}
}

func TestHoldConcurrency(t *testing.T) {
	_, ledger, uid := setupLedger(t)
	ctx := context.Background()
	if err := ledger.Credit(ctx, uid, 100, "grant", "g1"); err != nil {
		t.Fatalf("入账失败: %v", err)
	}

	const workers = 50
	var success int32
	var wg sync.WaitGroup
	errs := make(chan error, workers)
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			err := ledger.Hold(ctx, uid, 10, fmt.Sprintf("req-%d", i))
			switch {
			case err == nil:
				atomic.AddInt32(&success, 1)
			case errors.Is(err, ErrInsufficient):
			default:
				errs <- err
			}
		}(i)
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		t.Fatalf("并发冻结出现意外错误: %v", err)
	}
	if got := atomic.LoadInt32(&success); got != 10 {
		t.Fatalf("100 积分每次冻结 10,应恰好成功 10 次,实际 %d", got)
	}
	b := mustBalance(t, ledger, uid)
	if b.Balance != 100 || b.Held != 100 || b.Available() != 0 {
		t.Fatalf("并发冻结后账户不一致: %+v", b)
	}
}

func TestSettleConcurrency(t *testing.T) {
	db, ledger, uid := setupLedger(t)
	ctx := context.Background()
	if err := ledger.Credit(ctx, uid, 100, "grant", "g1"); err != nil {
		t.Fatalf("入账失败: %v", err)
	}
	if err := ledger.Hold(ctx, uid, 10, "req-concurrent"); err != nil {
		t.Fatalf("冻结失败: %v", err)
	}

	const workers = 20
	var wg sync.WaitGroup
	errs := make(chan error, workers)
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			consumed, err := ledger.Settle(ctx, uid, "req-concurrent", 10)
			if err != nil {
				errs <- err
				return
			}
			if consumed != 10 {
				errs <- fmt.Errorf("期望消费 10,实际 %d", consumed)
			}
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		t.Fatalf("并发结算错误: %v", err)
	}
	if n := countRows(t, db, `SELECT count(*) FROM credit_ledger WHERE user_id=$1 AND request_id='req-concurrent' AND type='consume'`, uid); n != 1 {
		t.Fatalf("并发结算应只写 1 条 consume,实际 %d", n)
	}
	if b := mustBalance(t, ledger, uid); b.Balance != 90 || b.Held != 0 {
		t.Fatalf("并发结算后余额错误: %+v", b)
	}
}

func TestBalanceForUnknownUser(t *testing.T) {
	_, ledger, _ := setupLedger(t)
	b, err := ledger.Balance(context.Background(), 999999)
	if err != nil {
		t.Fatalf("读取不存在用户余额不应报错: %v", err)
	}
	if b.Balance != 0 || b.Held != 0 {
		t.Fatalf("不存在用户余额应为 0: %+v", b)
	}
}

func TestListEntriesPagination(t *testing.T) {
	db, ledger, uid := setupLedger(t)
	ctx := context.Background()
	other := insertUser(t, db, "hash-b")
	if err := ledger.Credit(ctx, uid, 10, "grant", "r1"); err != nil {
		t.Fatalf("入账失败: %v", err)
	}
	if err := ledger.Credit(ctx, uid, 20, "grant", "r2"); err != nil {
		t.Fatalf("入账失败: %v", err)
	}
	if err := ledger.Credit(ctx, uid, 30, "grant", "r3"); err != nil {
		t.Fatalf("入账失败: %v", err)
	}
	if err := ledger.Credit(ctx, other, 99, "grant", "other"); err != nil {
		t.Fatalf("他人入账失败: %v", err)
	}

	page1, err := ListEntries(ctx, db, uid, 0, 2)
	if err != nil {
		t.Fatalf("读取流水失败: %v", err)
	}
	if len(page1) != 2 || page1[0].Amount != 30 || page1[1].Amount != 20 {
		t.Fatalf("第一页应按 id 倒序: %+v", page1)
	}
	page2, err := ListEntries(ctx, db, uid, page1[1].ID, 2)
	if err != nil {
		t.Fatalf("读取第二页失败: %v", err)
	}
	if len(page2) != 1 || page2[0].Amount != 10 {
		t.Fatalf("第二页应只有 1 条: %+v", page2)
	}
}

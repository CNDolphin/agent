package logic

import (
	"context"
	"errors"
	"net/http"

	"mhagent/internal/apierr"
	"mhagent/internal/auth"
	pkgmgr "mhagent/internal/packages"
	"mhagent/internal/payment"
	"mhagent/internal/svc"
)

// PackagesLogic 套餐与订单。
type PackagesLogic struct {
	sc *svc.ServiceContext
}

// NewPackagesLogic 创建套餐逻辑。
func NewPackagesLogic(sc *svc.ServiceContext) *PackagesLogic { return &PackagesLogic{sc: sc} }

// ListPublic 用户可见套餐。
func (l *PackagesLogic) ListPublic(ctx context.Context) ([]pkgmgr.Package, error) {
	out, err := l.sc.Packages.ListPackages(ctx)
	if err != nil {
		return nil, apierr.Internal()
	}
	return out, nil
}

// ListAll 管理端套餐列表。
func (l *PackagesLogic) ListAll(ctx context.Context) ([]pkgmgr.Package, error) {
	out, err := l.sc.Packages.ListAllPackages(ctx)
	if err != nil {
		return nil, apierr.Internal()
	}
	return out, nil
}

// CreatePackage 管理端创建套餐。
func (l *PackagesLogic) CreatePackage(ctx context.Context, in pkgmgr.CreatePackageInput) (pkgmgr.Package, error) {
	if _, err := requireSuper(ctx); err != nil {
		return pkgmgr.Package{}, err
	}
	p, err := l.sc.Packages.CreatePackage(ctx, in)
	if err != nil {
		if errors.Is(err, pkgmgr.ErrInvalidInput) {
			return pkgmgr.Package{}, apierr.BadRequest("套餐参数不合法")
		}
		return pkgmgr.Package{}, apierr.Internal()
	}
	return p, nil
}

// UpdatePackage 管理端修改套餐。
func (l *PackagesLogic) UpdatePackage(ctx context.Context, id int64, in pkgmgr.UpdatePackageInput) (pkgmgr.Package, error) {
	admin, err := requireSuper(ctx)
	if err != nil {
		return pkgmgr.Package{}, err
	}
	p, err := l.sc.Packages.UpdatePackage(ctx, id, in, admin.ID)
	switch {
	case err == nil:
		return p, nil
	case errors.Is(err, pkgmgr.ErrPackageNotFound), errors.Is(err, pkgmgr.ErrInvalidInput):
		return pkgmgr.Package{}, apierr.BadRequest("套餐不存在或参数不合法")
	default:
		return pkgmgr.Package{}, apierr.Internal()
	}
}

// CreateOrder 下单。
func (l *PackagesLogic) CreateOrder(ctx context.Context, userID, packageID int64, channel string) (payment.Order, payment.PayParams, error) {
	o, p, err := l.sc.Packages.CreateOrder(ctx, userID, packageID, channel)
	switch {
	case err == nil:
		return o, p, nil
	case errors.Is(err, pkgmgr.ErrPackageNotFound), errors.Is(err, pkgmgr.ErrPackageDisabled),
		errors.Is(err, pkgmgr.ErrTooManyOrders), errors.Is(err, payment.ErrUnsupportedChannel):
		return payment.Order{}, payment.PayParams{}, apierr.BadRequest("套餐不可用、渠道非法或下单过于频繁")
	default:
		return payment.Order{}, payment.PayParams{}, apierr.Internal()
	}
}

// ListOrders 用户订单。
func (l *PackagesLogic) ListOrders(ctx context.Context, userID int64) ([]payment.Order, error) {
	out, err := l.sc.Packages.ListOrders(ctx, userID)
	if err != nil {
		return nil, apierr.Internal()
	}
	return out, nil
}

// Callback 支付回调。
func (l *PackagesLogic) Callback(ctx context.Context, channel string, r *http.Request) (payment.Order, error) {
	o, err := l.sc.Packages.HandleCallback(ctx, channel, r)
	switch {
	case err == nil:
		return o, nil
	case errors.Is(err, payment.ErrInvalidCallback), errors.Is(err, payment.ErrUnsupportedCallback),
		errors.Is(err, payment.ErrUnsupportedChannel), errors.Is(err, pkgmgr.ErrOrderNotFound):
		return payment.Order{}, apierr.BadRequest("支付回调非法")
	case errors.Is(err, pkgmgr.ErrInvalidState):
		return payment.Order{}, apierr.BadRequest("订单状态不允许该操作")
	default:
		return payment.Order{}, apierr.Internal()
	}
}

// AdminListOrders 管理端订单列表。
func (l *PackagesLogic) AdminListOrders(ctx context.Context, status, phone string) ([]pkgmgr.AdminOrder, error) {
	hash := ""
	if phone != "" {
		var err error
		hash, err = auth.HashPhone(l.sc.Secrets.PhonePepper, phone)
		if err != nil {
			return nil, apierr.BadRequest("手机号格式不正确")
		}
	}
	out, err := l.sc.Packages.ListAllOrders(ctx, status, hash)
	if err != nil {
		return nil, apierr.Internal()
	}
	return out, nil
}

// ConfirmOrder 管理员确认线下收款。
func (l *PackagesLogic) ConfirmOrder(ctx context.Context, orderID int64) (payment.Order, error) {
	admin, err := requireSuper(ctx)
	if err != nil {
		return payment.Order{}, err
	}
	o, err := l.sc.Packages.ConfirmManual(ctx, orderID, admin.ID)
	switch {
	case err == nil:
		return o, nil
	case errors.Is(err, pkgmgr.ErrOrderNotFound):
		return payment.Order{}, apierr.BadRequest("订单不存在")
	case errors.Is(err, pkgmgr.ErrInvalidState):
		return payment.Order{}, apierr.BadRequest("订单状态不允许确认收款")
	default:
		return payment.Order{}, apierr.Internal()
	}
}

// CancelOrder 管理员取消订单。
func (l *PackagesLogic) CancelOrder(ctx context.Context, orderID int64) (payment.Order, error) {
	admin, err := requireSuper(ctx)
	if err != nil {
		return payment.Order{}, err
	}
	o, err := l.sc.Packages.Cancel(ctx, orderID, admin.ID)
	switch {
	case err == nil:
		return o, nil
	case errors.Is(err, pkgmgr.ErrOrderNotFound):
		return payment.Order{}, apierr.BadRequest("订单不存在")
	case errors.Is(err, pkgmgr.ErrInvalidState):
		return payment.Order{}, apierr.BadRequest("订单状态不允许取消")
	default:
		return payment.Order{}, apierr.Internal()
	}
}

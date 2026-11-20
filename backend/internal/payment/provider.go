// Package payment 隔离支付渠道。MVP 提供 mock 与 manual 两种实现。
package payment

import (
	"context"
	"errors"
	"net/http"
)

// 订单状态。
const (
	StatusPending   = "pending"
	StatusPaid      = "paid"
	StatusCredited  = "credited"
	StatusCancelled = "cancelled"
)

// 渠道。
const (
	ChannelMock   = "mock"
	ChannelManual = "manual"
)

// 支付错误。
var (
	ErrInvalidCallback     = errors.New("invalid payment callback")
	ErrUnsupportedChannel  = errors.New("unsupported payment channel")
	ErrUnsupportedCallback = errors.New("channel does not support callback")
)

// Order 订单(含套餐快照)。
type Order struct {
	ID          int64  `json:"id"`
	UserID      int64  `json:"user_id"`
	PackageID   int64  `json:"package_id"`
	PackageName string `json:"package_name"`
	PriceCents  int64  `json:"price_cents"`
	Credits     int64  `json:"credits"`
	Status      string `json:"status"`
	Channel     string `json:"channel"`
	TradeNo     string `json:"trade_no,omitempty"`
	CreatedAt   string `json:"created_at"`
	PaidAt      string `json:"paid_at,omitempty"`
}

// PayParams 返回给客户端用于发起支付的参数。
type PayParams struct {
	Channel string `json:"channel"`
	Message string `json:"message"`
}

// Provider 支付渠道接口。
type Provider interface {
	CreatePayment(ctx context.Context, o Order) (PayParams, error)
	VerifyCallback(ctx context.Context, r *http.Request) (orderID int64, tradeNo string, err error)
}

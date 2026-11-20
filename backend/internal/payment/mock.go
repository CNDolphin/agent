package payment

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

// MockProvider 开发/测试渠道:回调体为 {"order_id":1,"trade_no":"...","status":"success"}。
type MockProvider struct{}

// NewMockProvider 创建 mock 渠道。
func NewMockProvider() *MockProvider { return &MockProvider{} }

// CreatePayment 返回模拟支付参数。
func (m *MockProvider) CreatePayment(_ context.Context, o Order) (PayParams, error) {
	return PayParams{Channel: ChannelMock, Message: fmt.Sprintf("模拟支付:订单 %d", o.ID)}, nil
}

// VerifyCallback 校验并解析模拟回调。
func (m *MockProvider) VerifyCallback(_ context.Context, r *http.Request) (int64, string, error) {
	var body struct {
		OrderID int64  `json:"order_id"`
		TradeNo string `json:"trade_no"`
		Status  string `json:"status"`
	}
	raw, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	if err != nil {
		return 0, "", ErrInvalidCallback
	}
	if err := json.Unmarshal(raw, &body); err != nil {
		return 0, "", ErrInvalidCallback
	}
	if body.Status != "" && body.Status != "success" {
		return 0, "", ErrInvalidCallback
	}
	if body.OrderID <= 0 || body.TradeNo == "" {
		return 0, "", ErrInvalidCallback
	}
	return body.OrderID, body.TradeNo, nil
}

// ManualProvider 线下收款渠道:由管理员在后台确认收款,不接收回调。
type ManualProvider struct{}

// NewManualProvider 创建 manual 渠道。
func NewManualProvider() *ManualProvider { return &ManualProvider{} }

// CreatePayment 返回线下支付提示。
func (m *ManualProvider) CreatePayment(_ context.Context, o Order) (PayParams, error) {
	return PayParams{Channel: ChannelManual, Message: "请按客服提供的收款方式完成付款,到账后由管理员确认"}, nil
}

// VerifyCallback manual 不支持回调。
func (m *ManualProvider) VerifyCallback(_ context.Context, _ *http.Request) (int64, string, error) {
	return 0, "", ErrUnsupportedCallback
}

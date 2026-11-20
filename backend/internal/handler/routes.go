package handler

import (
	"net/http"

	"github.com/zeromicro/go-zero/rest"

	"mhagent/internal/middleware"
	"mhagent/internal/svc"
)

// RegisterRoutes 注册全部路由与中间件。
func RegisterRoutes(server *rest.Server, sc *svc.ServiceContext) {
	userAuth := middleware.Auth(sc)
	adminAuth := middleware.AdminAuth(sc)
	reqIDOptional := middleware.RequestID(false)
	reqIDRequired := middleware.RequestID(true)
	rateLimit := middleware.RateLimit(sc.RDB, sc.Config.RateLimit.PerMinute, sc.Now)

	// 公开路由:健康检查、验证码、登录、刷新、支付回调、管理端登录。
	public := []rest.Route{
		{Method: http.MethodGet, Path: "/health", Handler: Health(sc)},
		{Method: http.MethodPost, Path: "/auth/sms/send", Handler: SendSMSCode(sc)},
		{Method: http.MethodPost, Path: "/auth/register", Handler: Register(sc)},
		{Method: http.MethodPost, Path: "/auth/login/password", Handler: LoginWithPassword(sc)},
		{Method: http.MethodPost, Path: "/auth/password/reset", Handler: ResetPassword(sc)},
		{Method: http.MethodPost, Path: "/auth/login", Handler: Login(sc)},
		{Method: http.MethodPost, Path: "/auth/refresh", Handler: Refresh(sc)},
		{Method: http.MethodPost, Path: "/pay/callback/:channel", Handler: PayCallback(sc)},
		{Method: http.MethodGet, Path: "/dev/sms/last", Handler: DevSMSLast(sc)},
		{Method: http.MethodPost, Path: "/admin/auth/login", Handler: AdminLogin(sc)},
	}
	server.AddRoutes(rest.WithMiddlewares([]rest.Middleware{reqIDOptional}, public...))

	// 用户路由(需 access token)。
	user := []rest.Route{
		{Method: http.MethodDelete, Path: "/account", Handler: DeleteAccount(sc)},
		{Method: http.MethodGet, Path: "/credits/balance", Handler: Balance(sc)},
		{Method: http.MethodGet, Path: "/credits/ledger", Handler: Ledger(sc)},
		{Method: http.MethodPost, Path: "/notify/emergency", Handler: NotifyEmergency(sc)},
		{Method: http.MethodGet, Path: "/consent/latest", Handler: ConsentLatest(sc)},
		{Method: http.MethodPost, Path: "/consent", Handler: ConsentSign(sc)},
		{Method: http.MethodGet, Path: "/packages", Handler: ListPackages(sc)},
		{Method: http.MethodPost, Path: "/orders", Handler: CreateOrder(sc)},
		{Method: http.MethodGet, Path: "/orders", Handler: ListOrders(sc)},
		{Method: http.MethodGet, Path: "/reports/pending", Handler: ReportsPending(sc)},
		{Method: http.MethodGet, Path: "/reports/:id/download", Handler: ReportDownload(sc)},
		{Method: http.MethodPost, Path: "/reports/:id/read", Handler: ReportRead(sc)},
		{Method: http.MethodGet, Path: "/contents/latest", Handler: ContentsLatest(sc)},
		{Method: http.MethodGet, Path: "/contents/:id/download", Handler: ContentDownload(sc)},
		// SSE 长连接单独注册,不挂限流中间件。
		{Method: http.MethodGet, Path: "/notifications/stream", Handler: NotificationStream(sc)},
	}
	server.AddRoutes(rest.WithMiddlewares([]rest.Middleware{userAuth, reqIDOptional}, user...))

	// 对话路由:强制 X-Request-Id + 每用户每分钟限流。
	chat := []rest.Route{
		{Method: http.MethodPost, Path: "/llm/chat", Handler: Chat(sc)},
	}
	server.AddRoutes(rest.WithMiddlewares([]rest.Middleware{userAuth, reqIDRequired, rateLimit}, chat...))

	// 管理端路由。
	admin := []rest.Route{
		{Method: http.MethodGet, Path: "/admin/prices", Handler: AdminListPrices(sc)},
		{Method: http.MethodPut, Path: "/admin/prices/:model", Handler: AdminUpdatePrice(sc)},
		{Method: http.MethodGet, Path: "/admin/prices/:model/history", Handler: AdminPriceHistory(sc)},
		{Method: http.MethodPost, Path: "/admin/credits/grant", Handler: AdminGrant(sc)},
		{Method: http.MethodGet, Path: "/admin/users", Handler: AdminUsers(sc)},
		{Method: http.MethodGet, Path: "/admin/users/:id/ledger", Handler: AdminUserLedger(sc)},
		{Method: http.MethodGet, Path: "/admin/usage/summary", Handler: AdminUsageSummary(sc)},
		{Method: http.MethodGet, Path: "/admin/notify-logs", Handler: AdminNotifyLogs(sc)},
		{Method: http.MethodGet, Path: "/admin/packages", Handler: AdminListPackages(sc)},
		{Method: http.MethodPost, Path: "/admin/packages", Handler: AdminCreatePackage(sc)},
		{Method: http.MethodPut, Path: "/admin/packages/:id", Handler: AdminUpdatePackage(sc)},
		{Method: http.MethodGet, Path: "/admin/orders", Handler: AdminListOrders(sc)},
		{Method: http.MethodPost, Path: "/admin/orders/:id/confirm", Handler: AdminConfirmOrder(sc)},
		{Method: http.MethodPost, Path: "/admin/orders/:id/cancel", Handler: AdminCancelOrder(sc)},
		{Method: http.MethodPost, Path: "/admin/reports", Handler: AdminCreateReport(sc)},
		{Method: http.MethodGet, Path: "/admin/reports", Handler: AdminListReports(sc)},
		{Method: http.MethodGet, Path: "/admin/reports/:id", Handler: AdminGetReport(sc)},
		{Method: http.MethodGet, Path: "/admin/reports/:id/download", Handler: AdminDownloadReport(sc)},
		{Method: http.MethodPost, Path: "/admin/reports/:id/versions", Handler: AdminReplaceReportVersion(sc)},
		{Method: http.MethodPost, Path: "/admin/reports/:id/notify", Handler: AdminNotifyReport(sc)},
		{Method: http.MethodDelete, Path: "/admin/reports/:id", Handler: AdminDeleteReport(sc)},
		{Method: http.MethodPost, Path: "/admin/contents", Handler: AdminPublishContent(sc)},
		{Method: http.MethodGet, Path: "/admin/contents", Handler: AdminListContents(sc)},
		{Method: http.MethodGet, Path: "/admin/contents/:id/download", Handler: ContentDownload(sc)},
		{Method: http.MethodPost, Path: "/admin/contents/:id/notify", Handler: AdminNotifyContent(sc)},
		{Method: http.MethodDelete, Path: "/admin/contents/:id", Handler: AdminOfflineContent(sc)},
	}
	server.AddRoutes(rest.WithMiddlewares([]rest.Middleware{adminAuth, reqIDOptional}, admin...))
}

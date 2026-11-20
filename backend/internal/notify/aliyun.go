package notify

import (
	"context"
	"fmt"
	"strings"

	dm "github.com/aliyun/alibaba-cloud-sdk-go/services/dm"

	"mhagent/internal/sms"
)

// AliyunNotifier 阿里云短信 + 邮件推送实现。日志与错误不含收件人与参数。
type AliyunNotifier struct {
	SMS           sms.Sender
	TemplateCodes map[string]string // templateID -> 已审核短信模板代码
	EmailClient   *dm.Client
	EmailAccount  string
	EmailAlias    string
}

// NewAliyunNotifier 创建阿里云通知器。
func NewAliyunNotifier(accessKeyID, accessKeySecret string, sender sms.Sender, templateCodes map[string]string, emailAccount, emailAlias string) (*AliyunNotifier, error) {
	client, err := dm.NewClientWithAccessKey("cn-hangzhou", accessKeyID, accessKeySecret)
	if err != nil {
		return nil, fmt.Errorf("创建阿里云邮件客户端失败: %w", err)
	}
	return &AliyunNotifier{
		SMS:           sender,
		TemplateCodes: templateCodes,
		EmailClient:   client,
		EmailAccount:  emailAccount,
		EmailAlias:    emailAlias,
	}, nil
}

// Send 按渠道发送。模板必须已在配置白名单中映射。
func (a *AliyunNotifier) Send(ctx context.Context, channel, to, templateID string, params map[string]string) error {
	switch channel {
	case "sms":
		code, ok := a.TemplateCodes[templateID]
		if !ok || strings.TrimSpace(code) == "" {
			return fmt.Errorf("未知的短信通知模板: %s", templateID)
		}
		return a.SMS.Send(ctx, to, code, params)
	case "email":
		return a.sendEmail(to)
	default:
		return fmt.Errorf("未知的通知渠道: %s", channel)
	}
}

func (a *AliyunNotifier) sendEmail(to string) error {
	req := dm.CreateSingleSendMailRequest()
	req.AccountName = a.EmailAccount
	req.FromAlias = a.EmailAlias
	req.AddressType = "1"
	req.ToAddress = to
	req.Subject = "紧急联系人提醒"
	// 邮件正文为固定克制文案,不包含对话内容、诊断词汇或用户参数。
	req.TextBody = "您好,有一位用户在其心理健康助手中将您设为紧急联系人,并在高风险时刻授权我们向您发送此提醒。请尽快联系对方,给予支持。"
	_, err := a.EmailClient.SingleSendMail(req)
	if err != nil {
		return fmt.Errorf("阿里云邮件发送失败(未含收件人): %w", err)
	}
	return nil
}

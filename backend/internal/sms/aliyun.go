package sms

import (
	"context"
	"encoding/json"
	"fmt"

	dysmsapi "github.com/aliyun/alibaba-cloud-sdk-go/services/dysmsapi"
)

// AliyunSender 阿里云短信实现。凭证只从环境变量注入构造参数,不落配置文件。
type AliyunSender struct {
	Client   *dysmsapi.Client
	SignName string
	Endpoint string
}

// NewAliyunSender 创建阿里云短信发送器。
func NewAliyunSender(endpoint, signName, accessKeyID, accessKeySecret string) (*AliyunSender, error) {
	client, err := dysmsapi.NewClientWithAccessKey("cn-hangzhou", accessKeyID, accessKeySecret)
	if err != nil {
		return nil, fmt.Errorf("创建阿里云短信客户端失败: %w", err)
	}
	return &AliyunSender{Client: client, SignName: signName, Endpoint: endpoint}, nil
}

// Send 调用阿里云 SendSms。日志与错误中不包含手机号。
func (s *AliyunSender) Send(_ context.Context, phone, templateCode string, params map[string]string) error {
	paramJSON, err := json.Marshal(params)
	if err != nil {
		return fmt.Errorf("序列化短信模板参数失败: %w", err)
	}
	req := dysmsapi.CreateSendSmsRequest()
	if s.Endpoint != "" {
		req.Domain = s.Endpoint
	}
	req.SignName = s.SignName
	req.PhoneNumbers = phone
	req.TemplateCode = templateCode
	req.TemplateParam = string(paramJSON)
	resp, err := s.Client.SendSms(req)
	if err != nil {
		return fmt.Errorf("阿里云短信发送失败(未含号码): %w", err)
	}
	if resp.Code != "OK" {
		return fmt.Errorf("阿里云短信返回错误: Code=%s Message=%s", resp.Code, resp.Message)
	}
	return nil
}

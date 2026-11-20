package test

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"io"
	"mime/multipart"
	"net/http"
	"strings"
	"testing"
	"time"

	"mhagent/internal/testenv"
)

// uploadReport 构造 multipart 上传请求。
func uploadReport(t *testing.T, base, token, phone, userID, title, filename string, content []byte) apiResp {
	t.Helper()
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	if phone != "" {
		_ = mw.WriteField("phone", phone)
	}
	if userID != "" {
		_ = mw.WriteField("user_id", userID)
	}
	if title != "" {
		_ = mw.WriteField("title", title)
	}
	fw, err := mw.CreateFormFile("file", filename)
	if err != nil {
		t.Fatalf("构造文件字段失败: %v", err)
	}
	if _, err := fw.Write(content); err != nil {
		t.Fatalf("写入文件内容失败: %v", err)
	}
	if err := mw.Close(); err != nil {
		t.Fatalf("关闭 multipart 失败: %v", err)
	}

	req, err := http.NewRequest(http.MethodPost, base+"/admin/reports", &buf)
	if err != nil {
		t.Fatalf("构造请求失败: %v", err)
	}
	req.Header.Set("Content-Type", mw.FormDataContentType())
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	return sendReq(t, req)
}

// replaceReportVersion 上传报告新版本。
func replaceReportVersion(t *testing.T, base, token string, reportID int64, filename string, content []byte) apiResp {
	t.Helper()
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	fw, err := mw.CreateFormFile("file", filename)
	if err != nil {
		t.Fatalf("构造文件字段失败: %v", err)
	}
	_, _ = fw.Write(content)
	_ = mw.Close()

	req, err := http.NewRequest(http.MethodPost, base+"/admin/reports/"+itoa(reportID)+"/versions", &buf)
	if err != nil {
		t.Fatalf("构造请求失败: %v", err)
	}
	req.Header.Set("Content-Type", mw.FormDataContentType())
	req.Header.Set("Authorization", "Bearer "+token)
	return sendReq(t, req)
}

func sendReq(t *testing.T, req *http.Request) apiResp {
	t.Helper()
	client := &http.Client{Timeout: 20 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		t.Fatalf("请求失败: %v", err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("读取响应失败: %v", err)
	}
	return apiResp{status: resp.StatusCode, body: raw, header: resp.Header}
}

func TestReportUploadDeliveryAndManagement(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)
	insertAdmin(t, env.DB, "root", "super", "root-pass")
	insertAdmin(t, env.DB, "ops", "ops", "ops-pass")
	superToken, _ := adminLogin(t, base, "root", "root-pass")
	opsToken, role := adminLogin(t, base, "ops", "ops-pass")
	if role != "ops" {
		t.Fatalf("ops 账号角色应为 ops,实际 %s", role)
	}

	phone := "13800009001"
	access, _, _ := mustLogin(t, env, base, phone)

	// 运营角色无权限。
	resp := uploadReport(t, base, opsToken, phone, "", "报告", "r.pdf", []byte("no-auth"))
	resp.expect(t, http.StatusForbidden)
	resp = do(t, http.MethodGet, base+"/admin/reports", nil, opsToken, nil)
	resp.expect(t, http.StatusForbidden)

	// 上传并绑定用户。
	content := []byte("%PDF-1.4 mock report v1")
	resp = uploadReport(t, base, superToken, phone, "", "心理测评报告", "report.pdf", content)
	resp.expect(t, http.StatusOK)
	m := resp.mapBody(t)
	reportID := int64(m["id"].(float64))
	if m["status"].(string) != "pending" {
		t.Fatalf("新上传报告状态应为 pending: %v", m)
	}
	if m["version"].(float64) != 1 || m["filename"].(string) != "report.pdf" {
		t.Fatalf("上传返回字段不符: %v", m)
	}
	if m["phone_mask"].(string) == "" {
		t.Fatalf("应返回脱敏手机号: %v", m)
	}

	// 管理端列表与筛选。
	resp = do(t, http.MethodGet, base+"/admin/reports?phone="+phone, nil, superToken, nil)
	resp.expect(t, http.StatusOK)
	list := resp.mapBody(t)
	if list["total"].(float64) != 1 {
		t.Fatalf("应有 1 份报告,实际 %v", list["total"])
	}
	item := list["items"].([]any)[0].(map[string]any)
	if item["status"].(string) != "pending" {
		t.Fatalf("列表状态应为 pending: %v", item)
	}

	// 用户拉取待下载列表:未下载前反复返回。
	for i := 0; i < 2; i++ {
		resp = do(t, http.MethodGet, base+"/reports/pending", nil, access, nil)
		resp.expect(t, http.StatusOK)
		items := resp.mapBody(t)["items"].([]any)
		if len(items) != 1 {
			t.Fatalf("第 %d 次 pending 应返回 1 份,实际 %d", i+1, len(items))
		}
	}
	// 拉取后状态应变为已通知。
	resp = do(t, http.MethodGet, base+"/admin/reports/"+itoa(reportID), nil, superToken, nil)
	resp.expect(t, http.StatusOK)
	if got := resp.mapBody(t)["status"].(string); got != "notified" {
		t.Fatalf("用户拉取后状态应为 notified,实际 %s", got)
	}

	// 用户下载内容与上传一致。
	resp = do(t, http.MethodGet, base+"/reports/"+itoa(reportID)+"/download", nil, access, nil)
	resp.expect(t, http.StatusOK)
	if !bytes.Equal(resp.body, content) {
		t.Fatalf("下载内容与上传不一致: %q", string(resp.body))
	}
	if cd := resp.header.Get("Content-Disposition"); !strings.Contains(cd, "report.pdf") {
		t.Fatalf("下载应带附件文件名: %s", cd)
	}
	resp = do(t, http.MethodGet, base+"/admin/reports/"+itoa(reportID), nil, superToken, nil)
	resp.expect(t, http.StatusOK)
	detail := resp.mapBody(t)
	if detail["status"].(string) != "downloaded" {
		t.Fatalf("下载后状态应为 downloaded: %v", detail)
	}

	// 标记已读。
	resp = do(t, http.MethodPost, base+"/reports/"+itoa(reportID)+"/read", nil, access, nil)
	resp.expect(t, http.StatusNoContent)
	if n := countDB(t, env.DB, `SELECT count(*) FROM report_deliveries WHERE report_id=$1 AND read_at IS NOT NULL`, reportID); n != 1 {
		t.Fatalf("应记录 read_at,实际 %d", n)
	}

	// 替换版本:重新出现 pending。
	newContent := []byte("%PDF-1.4 mock report v2")
	resp = replaceReportVersion(t, base, superToken, reportID, "report-v2.pdf", newContent)
	resp.expect(t, http.StatusOK)
	m = resp.mapBody(t)
	if m["version"].(float64) != 2 || m["status"].(string) != "pending" {
		t.Fatalf("新版本应为 v2 且重置为 pending: %v", m)
	}
	resp = do(t, http.MethodGet, base+"/reports/pending", nil, access, nil)
	resp.expect(t, http.StatusOK)
	items := resp.mapBody(t)["items"].([]any)
	if len(items) != 1 || items[0].(map[string]any)["version"].(float64) != 2 {
		t.Fatalf("pending 应返回 v2: %v", items)
	}

	// 下载新版本。
	resp = do(t, http.MethodGet, base+"/reports/"+itoa(reportID)+"/download", nil, access, nil)
	resp.expect(t, http.StatusOK)
	if !bytes.Equal(resp.body, newContent) {
		t.Fatalf("v2 下载内容不一致")
	}

	// 管理端仍可下载历史版本 v1。
	resp = do(t, http.MethodGet, base+"/admin/reports/"+itoa(reportID)+"/download?version=1", nil, superToken, nil)
	resp.expect(t, http.StatusOK)
	if !bytes.Equal(resp.body, content) {
		t.Fatalf("历史版本下载内容不一致")
	}

	// 重新通知。
	resp = do(t, http.MethodPost, base+"/admin/reports/"+itoa(reportID)+"/notify", nil, superToken, nil)
	resp.expect(t, http.StatusOK)
	if resp.mapBody(t)["notified_at"] == nil {
		t.Fatalf("重新通知后应有 notified_at")
	}

	// 删除后用户端不再返回,管理端列表也不可见。
	resp = do(t, http.MethodDelete, base+"/admin/reports/"+itoa(reportID), nil, superToken, nil)
	resp.expect(t, http.StatusNoContent)
	resp = do(t, http.MethodGet, base+"/reports/pending", nil, access, nil)
	resp.expect(t, http.StatusOK)
	if n := len(resp.mapBody(t)["items"].([]any)); n != 0 {
		t.Fatalf("删除后 pending 应为空,实际 %d", n)
	}
	resp = do(t, http.MethodGet, base+"/admin/reports", nil, superToken, nil)
	resp.expect(t, http.StatusOK)
	if n := resp.mapBody(t)["total"].(float64); n != 0 {
		t.Fatalf("删除后列表应为空,实际 %v", n)
	}
}

func TestReportValidationAndOwnership(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)
	insertAdmin(t, env.DB, "root", "super", "root-pass")
	superToken, _ := adminLogin(t, base, "root", "root-pass")

	// 用户不存在。
	resp := uploadReport(t, base, superToken, "13900000000", "", "报告", "r.pdf", []byte("x"))
	resp.expect(t, http.StatusNotFound)

	// 非法扩展名。
	resp = uploadReport(t, base, superToken, "", "", "报告", "r.exe", []byte("x"))
	resp.expect(t, http.StatusBadRequest)

	// 正常上传后,其他用户看不到、下不到。
	ownerPhone := "13800009010"
	ownerAccess, _, _ := mustLogin(t, env, base, ownerPhone)
	resp = uploadReport(t, base, superToken, ownerPhone, "", "报告", "r.pdf", []byte("owner-only"))
	resp.expect(t, http.StatusOK)
	reportID := int64(resp.mapBody(t)["id"].(float64))

	otherAccess, _, _ := mustLogin(t, env, base, "13800009011")
	resp = do(t, http.MethodGet, base+"/reports/pending", nil, otherAccess, nil)
	resp.expect(t, http.StatusOK)
	if n := len(resp.mapBody(t)["items"].([]any)); n != 0 {
		t.Fatalf("其他用户不应看到报告,实际 %d", n)
	}
	resp = do(t, http.MethodGet, base+"/reports/"+itoa(reportID)+"/download", nil, otherAccess, nil)
	resp.expect(t, http.StatusNotFound)
	resp = do(t, http.MethodGet, base+"/reports/"+itoa(reportID)+"/download", nil, ownerAccess, nil)
	resp.expect(t, http.StatusOK)
}

func TestReportSSE(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)
	insertAdmin(t, env.DB, "root", "super", "root-pass")
	superToken, _ := adminLogin(t, base, "root", "root-pass")

	phone := "13800009020"
	access, _, _ := mustLogin(t, env, base, phone)

	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, base+"/notifications/stream", nil)
	if err != nil {
		t.Fatalf("构造 SSE 请求失败: %v", err)
	}
	req.Header.Set("Authorization", "Bearer "+access)
	req.Header.Set("Accept", "text/event-stream")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("建立 SSE 连接失败: %v", err)
	}
	defer resp.Body.Close()
	if ct := resp.Header.Get("Content-Type"); !strings.HasPrefix(ct, "text/event-stream") {
		t.Fatalf("响应类型应为 text/event-stream,实际 %s", ct)
	}

	events := make(chan map[string]string, 8)
	go func() {
		scanner := bufio.NewScanner(resp.Body)
		cur := map[string]string{}
		for scanner.Scan() {
			line := scanner.Text()
			switch {
			case strings.HasPrefix(line, "event: "):
				cur["event"] = strings.TrimPrefix(line, "event: ")
			case strings.HasPrefix(line, "data: "):
				cur["data"] = strings.TrimPrefix(line, "data: ")
				select {
				case events <- cur:
				default:
				}
				cur = map[string]string{}
			}
		}
	}()

	// 等待订阅建立。
	time.Sleep(200 * time.Millisecond)

	respUpload := uploadReport(t, base, superToken, phone, "", "SSE 报告", "sse.pdf", []byte("sse"))
	respUpload.expect(t, http.StatusOK)
	reportID := int64(respUpload.mapBody(t)["id"].(float64))

	select {
	case ev := <-events:
		if ev["event"] != "report.created" {
			t.Fatalf("应收到 report.created,实际 %v", ev)
		}
		var payload map[string]any
		if err := json.Unmarshal([]byte(ev["data"]), &payload); err != nil {
			t.Fatalf("事件 data 不是合法 JSON: %v", err)
		}
		if int64(payload["report_id"].(float64)) != reportID {
			t.Fatalf("事件报告 id 不符: %v", payload)
		}
	case <-time.After(4 * time.Second):
		t.Fatalf("未在超时内收到 SSE 事件")
	}
}

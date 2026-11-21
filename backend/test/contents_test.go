package test

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"sort"
	"testing"
	"time"

	"mhagent/internal/testenv"
)

// buildContentZip 生成带 manifest.json 的内容包。
func buildContentZip(t *testing.T, kind, version string, files map[string][]byte) []byte {
	t.Helper()
	paths := make([]string, 0, len(files))
	for p := range files {
		paths = append(paths, p)
	}
	sort.Strings(paths)

	type manifestFile struct {
		Path   string `json:"path"`
		SHA256 string `json:"sha256"`
	}
	manifest := struct {
		Kind    string         `json:"kind"`
		Version string         `json:"version"`
		Files   []manifestFile `json:"files"`
	}{Kind: kind, Version: version}

	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	for _, p := range paths {
		sum := sha256.Sum256(files[p])
		manifest.Files = append(manifest.Files, manifestFile{
			Path: p, SHA256: hex.EncodeToString(sum[:]),
		})
		w, err := zw.Create(p)
		if err != nil {
			t.Fatalf("写入 zip 失败: %v", err)
		}
		if _, err := w.Write(files[p]); err != nil {
			t.Fatalf("写入 zip 失败: %v", err)
		}
	}
	raw, err := json.Marshal(manifest)
	if err != nil {
		t.Fatalf("序列化 manifest 失败: %v", err)
	}
	w, err := zw.Create("manifest.json")
	if err != nil {
		t.Fatalf("写入 manifest 失败: %v", err)
	}
	if _, err := w.Write(raw); err != nil {
		t.Fatalf("写入 manifest 失败: %v", err)
	}
	if err := zw.Close(); err != nil {
		t.Fatalf("关闭 zip 失败: %v", err)
	}
	return buf.Bytes()
}

func uploadContent(t *testing.T, base, token, kind, version, platform string, content []byte) apiResp {
	t.Helper()
	return uploadContentFile(t, base, token, kind, version, platform, kind+"-"+version+".zip", content)
}

func uploadContentFile(
	t *testing.T, base, token, kind, version, platform, filename string, content []byte,
) apiResp {
	t.Helper()
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	_ = mw.WriteField("kind", kind)
	_ = mw.WriteField("version", version)
	if platform != "" {
		_ = mw.WriteField("platform", platform)
	}
	_ = mw.WriteField("notes", "测试内容包")
	fw, err := mw.CreateFormFile("file", filename)
	if err != nil {
		t.Fatalf("构造文件字段失败: %v", err)
	}
	if _, err := fw.Write(content); err != nil {
		t.Fatalf("写入文件失败: %v", err)
	}
	if err := mw.Close(); err != nil {
		t.Fatalf("关闭 multipart 失败: %v", err)
	}

	req, err := http.NewRequest(http.MethodPost, base+"/admin/contents", &buf)
	if err != nil {
		t.Fatalf("构造请求失败: %v", err)
	}
	req.Header.Set("Content-Type", mw.FormDataContentType())
	req.Header.Set("Authorization", "Bearer "+token)
	return sendReq(t, req)
}

func TestContentPublishLatestDownload(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)

	insertAdmin(t, env.DB, "root", "super", "Passw0rd!x")
	adminToken, _ := adminLogin(t, base, "root", "Passw0rd!x")
	access, _, _ := mustLogin(t, env, base, "13800009901")

	// 发布前订阅全局事件。
	events, cancel := env.SC.ReportHub.Subscribe(1)
	defer cancel()

	skillsV1 := buildContentZip(t, "skills", "1.0.0", map[string][]byte{
		"skills/emotion/SKILL.md": []byte("# 情绪\n第一版"),
	})
	resp := uploadContent(t, base, adminToken, "skills", "1.0.0", "all", skillsV1)
	resp.expect(t, http.StatusOK)
	first := resp.mapBody(t)
	if first["sha256"].(string) == "" || int64(first["size_bytes"].(float64)) != int64(len(skillsV1)) {
		t.Fatalf("发布结果字段异常: %v", first)
	}
	if got := countDB(t, env.DB, `SELECT count(*) FROM content_releases WHERE kind='skills'`); got != 1 {
		t.Fatalf("应写入 1 条内容记录,实际 %d", got)
	}

	select {
	case ev := <-events:
		if ev.Type != "content.updated" {
			t.Fatalf("期望 content.updated,实际 %s", ev.Type)
		}
	case <-time.After(2 * time.Second):
		t.Fatalf("未收到 content.updated 广播")
	}

	skillsV2 := buildContentZip(t, "skills", "1.0.1", map[string][]byte{
		"skills/emotion/SKILL.md": []byte("# 情绪\n第二版"),
	})
	resp = uploadContent(t, base, adminToken, "skills", "1.0.1", "all", skillsV2)
	resp.expect(t, http.StatusOK)
	second := resp.mapBody(t)

	// 用户端获取最新版本。
	resp = do(t, http.MethodGet, base+"/contents/latest?platform=macos&kinds=skills", nil, access, nil)
	resp.expect(t, http.StatusOK)
	items, _ := resp.mapBody(t)["items"].([]any)
	if len(items) != 1 {
		t.Fatalf("应返回 1 个最新版本,实际 %d", len(items))
	}
	latest := items[0].(map[string]any)
	if latest["version"].(string) != "1.0.1" {
		t.Fatalf("最新版本应为 1.0.1,实际 %v", latest["version"])
	}

	// 下载并校验内容与响应头。
	resp = do(t, http.MethodGet, base+"/contents/"+itoa(int64(second["id"].(float64)))+"/download", nil, access, nil)
	resp.expect(t, http.StatusOK)
	if resp.header.Get("X-Content-SHA256") != second["sha256"].(string) {
		t.Fatalf("下载响应头 SHA256 不一致")
	}
	if !bytes.Equal(resp.body, skillsV2) {
		t.Fatalf("下载内容与上传内容不一致")
	}
}

func TestContentPublishAppExe(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)

	insertAdmin(t, env.DB, "root", "super", "Passw0rd!x")
	adminToken, _ := adminLogin(t, base, "root", "Passw0rd!x")

	exe := append([]byte("MZ\x90\x00"), bytes.Repeat([]byte{0}, 128)...)
	resp := uploadContentFile(
		t, base, adminToken, "app", "0.2.0", "windows", "agent-setup-0.2.0.exe", exe)
	resp.expect(t, http.StatusOK)
	item := resp.mapBody(t)
	if item["filename"].(string) != "agent-setup-0.2.0.exe" {
		t.Fatalf("应保留原始 exe 文件名,实际 %v", item["filename"])
	}
	if item["platform"].(string) != "windows" {
		t.Fatalf("平台应为 windows,实际 %v", item["platform"])
	}
	expectedType := "application/vnd.microsoft.portable-executable"
	if item["content_type"].(string) != expectedType {
		t.Fatalf("content_type 应为 %s,实际 %v", expectedType, item["content_type"])
	}
	sum := sha256.Sum256(exe)
	if item["sha256"].(string) != hex.EncodeToString(sum[:]) {
		t.Fatalf("SHA256 不一致")
	}
	if int64(item["size_bytes"].(float64)) != int64(len(exe)) {
		t.Fatalf("size_bytes 不一致")
	}

	id := int64(item["id"].(float64))
	resp = do(t, http.MethodGet, base+"/admin/contents/"+itoa(id)+"/download", nil, adminToken, nil)
	resp.expect(t, http.StatusOK)
	if resp.header.Get("Content-Type") != expectedType {
		t.Fatalf("下载 Content-Type 应为 %s,实际 %s", expectedType, resp.header.Get("Content-Type"))
	}
	if !bytes.Equal(resp.body, exe) {
		t.Fatalf("下载内容与上传 exe 不一致")
	}
}

func TestContentPublishRejects(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)

	insertAdmin(t, env.DB, "root", "super", "Passw0rd!x")
	insertAdmin(t, env.DB, "ops", "ops", "Passw0rd!x")
	superToken, _ := adminLogin(t, base, "root", "Passw0rd!x")
	opsToken, _ := adminLogin(t, base, "ops", "Passw0rd!x")

	content := buildContentZip(t, "skills", "2.0.0", map[string][]byte{
		"skills/a/SKILL.md": []byte("# A"),
	})
	resp := uploadContent(t, base, opsToken, "skills", "2.0.0", "all", content)
	resp.expect(t, http.StatusForbidden)

	resp = uploadContent(t, base, superToken, "skills", "2.0.0", "all", content)
	resp.expect(t, http.StatusOK)

	// 重复版本。
	resp = uploadContent(t, base, superToken, "skills", "2.0.0", "all", content)
	resp.expect(t, http.StatusConflict)

	// 缺少 manifest。
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	w, _ := zw.Create("skills/a/SKILL.md")
	_, _ = w.Write([]byte("# A"))
	_ = zw.Close()
	resp = uploadContent(t, base, superToken, "skills", "2.0.1", "all", buf.Bytes())
	resp.expect(t, http.StatusBadRequest)

	// manifest 与参数不一致。
	mismatch := buildContentZip(t, "quiz", "2.0.2", map[string][]byte{"mi_quiz.json": []byte(`{}`)})
	resp = uploadContent(t, base, superToken, "skills", "2.0.2", "all", mismatch)
	resp.expect(t, http.StatusBadRequest)

	// 非法版本号。
	resp = uploadContent(t, base, superToken, "skills", "v2", "all", content)
	resp.expect(t, http.StatusBadRequest)

	// Windows 客户端程序只接受 exe 扩展名。
	resp = uploadContent(t, base, superToken, "app", "0.2.0", "windows", content)
	resp.expect(t, http.StatusBadRequest)

	// exe 扩展名但文件头不是 MZ。
	resp = uploadContentFile(
		t, base, superToken, "app", "0.3.0", "windows", "agent-setup.exe", []byte("PK\x03\x04"))
	resp.expect(t, http.StatusBadRequest)

	// app 不允许 all 平台。
	resp = uploadContentFile(
		t, base, superToken, "app", "0.4.0", "all", "agent-setup.exe", []byte("MZ\x90\x00"))
	resp.expect(t, http.StatusBadRequest)
}

func TestContentOfflineAndNotify(t *testing.T) {
	env := testenv.New(t)
	base := testenv.StartServer(t, env)

	insertAdmin(t, env.DB, "root", "super", "Passw0rd!x")
	adminToken, _ := adminLogin(t, base, "root", "Passw0rd!x")
	access, _, _ := mustLogin(t, env, base, "13800009902")

	v1 := buildContentZip(t, "rules", "1.0.0", map[string][]byte{"risk_rules.json": []byte(`{"rules":[]}`)})
	resp := uploadContent(t, base, adminToken, "rules", "1.0.0", "all", v1)
	resp.expect(t, http.StatusOK)
	firstID := int64(resp.mapBody(t)["id"].(float64))

	v2 := buildContentZip(t, "rules", "1.0.1", map[string][]byte{"risk_rules.json": []byte(`{"rules":[1]}`)})
	resp = uploadContent(t, base, adminToken, "rules", "1.0.1", "all", v2)
	resp.expect(t, http.StatusOK)
	secondID := int64(resp.mapBody(t)["id"].(float64))

	resp = do(t, http.MethodDelete, base+"/admin/contents/"+itoa(secondID), nil, adminToken, nil)
	resp.expect(t, http.StatusNoContent)

	resp = do(t, http.MethodGet, base+"/contents/latest?platform=macos&kinds=rules", nil, access, nil)
	resp.expect(t, http.StatusOK)
	items, _ := resp.mapBody(t)["items"].([]any)
	if len(items) != 1 || items[0].(map[string]any)["version"].(string) != "1.0.0" {
		t.Fatalf("下线后应回退到 1.0.0,实际 %v", items)
	}

	// 下线版本不可通知。
	resp = do(t, http.MethodPost, base+"/admin/contents/"+itoa(secondID)+"/notify", nil, adminToken, nil)
	resp.expect(t, http.StatusBadRequest)

	// 未登录不能获取最新版本。
	resp = do(t, http.MethodGet, base+"/contents/latest?platform=macos", nil, "", nil)
	resp.expect(t, http.StatusUnauthorized)

	// 上线中的版本可重新通知。
	resp = do(t, http.MethodPost, base+"/admin/contents/"+itoa(firstID)+"/notify", nil, adminToken, nil)
	resp.expect(t, http.StatusOK)

	// 列表返回全部记录。
	resp = do(t, http.MethodGet, base+"/admin/contents?page=1&page_size=10", nil, adminToken, nil)
	resp.expect(t, http.StatusOK)
	if total := int(resp.mapBody(t)["total"].(float64)); total != 2 {
		t.Fatalf("列表总数应为 2,实际 %d", total)
	}
}

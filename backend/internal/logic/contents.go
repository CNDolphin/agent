package logic

import (
	"archive/zip"
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/lib/pq"

	"mhagent/internal/apierr"
	"mhagent/internal/audit"
	"mhagent/internal/sse"
	"mhagent/internal/svc"
)

// ContentLogic 在线更新内容包的发布、查询与下载。
type ContentLogic struct {
	sc *svc.ServiceContext
}

// NewContentLogic 创建内容包逻辑。
func NewContentLogic(sc *svc.ServiceContext) *ContentLogic { return &ContentLogic{sc: sc} }

// 允许的内容类型。
const (
	KindSkills = "skills"
	KindQuiz   = "quiz"
	KindRules  = "rules"
	KindScales = "scales"
	KindApp    = "app"
)

var contentKinds = map[string]bool{
	KindSkills: true, KindQuiz: true, KindRules: true, KindScales: true, KindApp: true,
}

var contentPlatforms = map[string]bool{"all": true, "macos": true, "windows": true}

var contentVersionPattern = regexp.MustCompile(`^\d+\.\d+\.\d+$`)

const (
	codeContentNotFound   = 40404
	codeContentDuplicate  = 40901
	codeContentInvalidZip = 40006
)

func errContentNotFound() *apierr.Error {
	return apierr.New(codeContentNotFound, 404, "内容版本不存在")
}

// ContentItem 内容包版本项。
type ContentItem struct {
	ID          int64   `json:"id"`
	Kind        string  `json:"kind"`
	Platform    string  `json:"platform"`
	Version     string  `json:"version"`
	Filename    string  `json:"filename"`
	ContentType string  `json:"content_type"`
	SizeBytes   int64   `json:"size_bytes"`
	SHA256      string  `json:"sha256"`
	Notes       string  `json:"notes"`
	Forced      bool    `json:"forced"`
	Status      string  `json:"status"`
	PublishedAt *string `json:"published_at"`
	CreatedAt   string  `json:"created_at"`
}

// ContentListQuery 管理端列表查询条件。
type ContentListQuery struct {
	Kind     string
	Page     int
	PageSize int
}

// ContentListResult 列表结果。
type ContentListResult struct {
	Items []ContentItem `json:"items"`
	Total int           `json:"total"`
}

// ContentUploadInput 上传输入。
type ContentUploadInput struct {
	Kind        string
	Platform    string
	Version     string
	Notes       string
	Forced      bool
	Filename    string
	ContentType string
	Body        io.Reader
}

// ContentFile 待写出的内容包文件。
type ContentFile struct {
	Item ContentItem
	File *os.File
}

// contentManifest 内容包内的清单文件。
type contentManifest struct {
	Kind    string `json:"kind"`
	Version string `json:"version"`
	Files   []struct {
		Path   string `json:"path"`
		SHA256 string `json:"sha256"`
	} `json:"files"`
}

// PublishContent 校验并发布一个内容包,成功后向所有在线客户端广播。
func (l *ContentLogic) PublishContent(ctx context.Context, in ContentUploadInput) (ContentItem, error) {
	admin, err := requireSuper(ctx)
	if err != nil {
		return ContentItem{}, err
	}
	kind := strings.TrimSpace(in.Kind)
	if !contentKinds[kind] {
		return ContentItem{}, apierr.BadRequest("kind 非法,可选 skills/quiz/rules/scales/app")
	}
	platform := strings.TrimSpace(in.Platform)
	if platform == "" {
		platform = "all"
	}
	if !contentPlatforms[platform] {
		return ContentItem{}, apierr.BadRequest("platform 非法,可选 all/macos/windows")
	}
	if kind != KindApp {
		platform = "all"
	}
	version := strings.TrimSpace(in.Version)
	if !contentVersionPattern.MatchString(version) {
		return ContentItem{}, apierr.BadRequest("version 必须是 x.y.z 形式的版本号")
	}

	var exists int
	if err := l.sc.DB.QueryRowContext(ctx,
		`SELECT 1 FROM content_releases WHERE kind=$1 AND platform=$2 AND version=$3`,
		kind, platform, version).Scan(&exists); err == nil {
		return ContentItem{}, apierr.New(codeContentDuplicate, 409, "该版本已存在")
	} else if !errors.Is(err, sql.ErrNoRows) {
		return ContentItem{}, apierr.Internal()
	}

	relDir := filepath.Join(kind, platform)
	absDir := filepath.Join(l.sc.Config.Content.Dir, relDir)
	if err := os.MkdirAll(absDir, 0o700); err != nil {
		return ContentItem{}, apierr.Internal()
	}
	tmp, err := os.CreateTemp(absDir, ".upload-*.zip")
	if err != nil {
		return ContentItem{}, apierr.Internal()
	}
	tmpPath := tmp.Name()
	defer func() {
		_ = tmp.Close()
		_ = os.Remove(tmpPath)
	}()

	hasher := sha256.New()
	limit := l.maxBytes()
	n, copyErr := io.Copy(io.MultiWriter(tmp, hasher), io.LimitReader(in.Body, limit+1))
	if copyErr != nil {
		return ContentItem{}, apierr.Internal()
	}
	if n > limit {
		return ContentItem{}, apierr.BadRequest(fmt.Sprintf("内容包超过大小限制(%dMB)", l.sc.Config.Content.MaxSizeMB))
	}
	if err := tmp.Sync(); err != nil {
		return ContentItem{}, apierr.Internal()
	}

	if err := inspectManifest(tmpPath, n, kind, version); err != nil {
		return ContentItem{}, err
	}

	name := fmt.Sprintf("%s-%s.zip", version, uuid.NewString())
	relPath := filepath.Join(relDir, name)
	target := filepath.Join(l.sc.Config.Content.Dir, relPath)
	if err := os.Rename(tmpPath, target); err != nil {
		return ContentItem{}, apierr.Internal()
	}

	digest := hex.EncodeToString(hasher.Sum(nil))
	filename := strings.TrimSpace(in.Filename)
	if filename == "" {
		filename = name
	}
	now := l.sc.Now().UTC()
	contentType := strings.TrimSpace(in.ContentType)
	if contentType == "" {
		contentType = "application/zip"
	}

	var id int64
	err = l.sc.DB.QueryRowContext(ctx,
		`INSERT INTO content_releases
		 (kind, platform, version, filename, content_type, size_bytes, sha256, storage_path, notes, forced, status, published_at, created_by)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'published',$11,$12) RETURNING id`,
		kind, platform, version, filename, contentType, n, digest, relPath,
		strings.TrimSpace(in.Notes), in.Forced, now, admin.ID).Scan(&id)
	if err != nil {
		_ = os.Remove(target)
		var pqErr *pq.Error
		if errors.As(err, &pqErr) && pqErr.Code == "23505" {
			return ContentItem{}, apierr.New(codeContentDuplicate, 409, "该版本已存在")
		}
		return ContentItem{}, apierr.Internal()
	}

	if l.sc.Audit != nil {
		l.sc.Audit.Quiet(ctx, audit.ActorAdmin, admin.ID, audit.EventContentPublish,
			audit.NewDetail().Int("release_id", id))
	}
	l.broadcast(id, kind, platform, version, in.Forced)
	return l.contentItem(ctx, id)
}

// ListContents 管理端分页列表。
func (l *ContentLogic) ListContents(ctx context.Context, q ContentListQuery) (ContentListResult, error) {
	if _, err := requireSuper(ctx); err != nil {
		return ContentListResult{}, err
	}
	page, pageSize := q.Page, q.PageSize
	if page <= 0 {
		page = 1
	}
	if pageSize <= 0 {
		pageSize = 20
	}
	where := "WHERE 1=1"
	args := []any{}
	if kind := strings.TrimSpace(q.Kind); kind != "" {
		if !contentKinds[kind] {
			return ContentListResult{}, apierr.BadRequest("kind 非法")
		}
		args = append(args, kind)
		where += fmt.Sprintf(" AND kind=$%d", len(args))
	}

	var total int
	if err := l.sc.DB.QueryRowContext(ctx, "SELECT count(*) FROM content_releases "+where, args...).Scan(&total); err != nil {
		return ContentListResult{}, apierr.Internal()
	}
	args = append(args, pageSize, (page-1)*pageSize)
	rows, err := l.sc.DB.QueryContext(ctx,
		`SELECT id, kind, platform, version, filename, content_type, size_bytes, sha256, notes, forced, status, published_at, created_at
		 FROM content_releases `+where+` ORDER BY id DESC LIMIT $`+strconv.Itoa(len(args)-1)+` OFFSET $`+strconv.Itoa(len(args)), args...)
	if err != nil {
		return ContentListResult{}, apierr.Internal()
	}
	defer rows.Close()
	items := make([]ContentItem, 0, pageSize)
	for rows.Next() {
		item, scanErr := scanContentItem(rows)
		if scanErr != nil {
			return ContentListResult{}, apierr.Internal()
		}
		items = append(items, item)
	}
	if err := rows.Err(); err != nil {
		return ContentListResult{}, apierr.Internal()
	}
	return ContentListResult{Items: items, Total: total}, nil
}

// LatestContents 返回每个 kind 的最新已发布版本。
func (l *ContentLogic) LatestContents(ctx context.Context, platform string, kinds []string) ([]ContentItem, error) {
	if _, ok := apierr.UserID(ctx); !ok {
		return nil, apierr.Unauthorized("未登录")
	}
	platform = strings.TrimSpace(platform)
	if platform == "" {
		platform = "macos"
	}
	if !contentPlatforms[platform] {
		return nil, apierr.BadRequest("platform 非法")
	}
	rows, err := l.sc.DB.QueryContext(ctx,
		`SELECT id, kind, platform, version, filename, content_type, size_bytes, sha256, notes, forced, status, published_at, created_at
		 FROM content_releases
		 WHERE status='published' AND (platform=$1 OR platform='all')`, platform)
	if err != nil {
		return nil, apierr.Internal()
	}
	defer rows.Close()

	allowed := map[string]bool{}
	for _, k := range kinds {
		k = strings.TrimSpace(k)
		if k != "" {
			allowed[k] = true
		}
	}
	best := map[string]ContentItem{}
	for rows.Next() {
		item, scanErr := scanContentItem(rows)
		if scanErr != nil {
			return nil, apierr.Internal()
		}
		if len(allowed) > 0 && !allowed[item.Kind] {
			continue
		}
		prev, ok := best[item.Kind]
		if !ok || contentNewer(item, prev, platform) {
			best[item.Kind] = item
		}
	}
	if err := rows.Err(); err != nil {
		return nil, apierr.Internal()
	}
	out := make([]ContentItem, 0, len(best))
	for _, item := range best {
		out = append(out, item)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Kind < out[j].Kind })
	return out, nil
}

// NotifyContent 重新广播指定版本。
func (l *ContentLogic) NotifyContent(ctx context.Context, id int64) (ContentItem, error) {
	if _, err := requireSuper(ctx); err != nil {
		return ContentItem{}, err
	}
	item, err := l.contentItem(ctx, id)
	if err != nil {
		return ContentItem{}, err
	}
	if item.Status != "published" {
		return ContentItem{}, apierr.BadRequest("该版本已下线,无法通知")
	}
	l.broadcast(item.ID, item.Kind, item.Platform, item.Version, item.Forced)
	return item, nil
}

// OfflineContent 下线指定版本。
func (l *ContentLogic) OfflineContent(ctx context.Context, id int64) error {
	admin, err := requireSuper(ctx)
	if err != nil {
		return err
	}
	res, err := l.sc.DB.ExecContext(ctx,
		`UPDATE content_releases SET status='offline' WHERE id=$1 AND status<>'offline'`, id)
	if err != nil {
		return apierr.Internal()
	}
	if affected, _ := res.RowsAffected(); affected == 0 {
		return errContentNotFound()
	}
	if l.sc.Audit != nil {
		l.sc.Audit.Quiet(ctx, audit.ActorAdmin, admin.ID, audit.EventContentPublish,
			audit.NewDetail().Int("release_id", id))
	}
	return nil
}

// DownloadContent 打开指定版本的文件供下载。
func (l *ContentLogic) DownloadContent(ctx context.Context, id int64) (ContentFile, error) {
	if _, ok := apierr.UserID(ctx); !ok {
		if _, err := requireSuper(ctx); err != nil {
			return ContentFile{}, err
		}
	}
	item, err := l.contentItem(ctx, id)
	if err != nil {
		return ContentFile{}, err
	}
	if item.Status != "published" {
		return ContentFile{}, errContentNotFound()
	}
	var storagePath string
	if err := l.sc.DB.QueryRowContext(ctx,
		`SELECT storage_path FROM content_releases WHERE id=$1`, id).Scan(&storagePath); err != nil {
		return ContentFile{}, apierr.Internal()
	}
	abs := filepath.Join(l.sc.Config.Content.Dir, storagePath)
	if !strings.HasPrefix(filepath.Clean(abs), filepath.Clean(l.sc.Config.Content.Dir)) {
		return ContentFile{}, apierr.Internal()
	}
	f, err := os.Open(abs)
	if err != nil {
		return ContentFile{}, apierr.Internal()
	}
	return ContentFile{Item: item, File: f}, nil
}

// ---- 内部实现 ----

func (l *ContentLogic) maxBytes() int64 {
	return l.sc.Config.Content.MaxSizeMB << 20
}

func (l *ContentLogic) contentItem(ctx context.Context, id int64) (ContentItem, error) {
	row := l.sc.DB.QueryRowContext(ctx,
		`SELECT id, kind, platform, version, filename, content_type, size_bytes, sha256, notes, forced, status, published_at, created_at
		 FROM content_releases WHERE id=$1`, id)
	item, err := scanContentItem(row)
	if errors.Is(err, sql.ErrNoRows) {
		return ContentItem{}, errContentNotFound()
	}
	if err != nil {
		return ContentItem{}, apierr.Internal()
	}
	return item, nil
}

type contentScanner interface {
	Scan(dest ...any) error
}

func scanContentItem(s contentScanner) (ContentItem, error) {
	var item ContentItem
	var published sql.NullTime
	var created time.Time
	if err := s.Scan(&item.ID, &item.Kind, &item.Platform, &item.Version, &item.Filename,
		&item.ContentType, &item.SizeBytes, &item.SHA256, &item.Notes, &item.Forced,
		&item.Status, &published, &created); err != nil {
		return ContentItem{}, err
	}
	if published.Valid {
		v := published.Time.UTC().Format(time.RFC3339)
		item.PublishedAt = &v
	}
	item.CreatedAt = created.UTC().Format(time.RFC3339)
	return item, nil
}

func (l *ContentLogic) broadcast(id int64, kind, platform, version string, forced bool) {
	if l.sc.ReportHub == nil {
		return
	}
	data, err := json.Marshal(map[string]any{
		"kind": kind, "platform": platform, "version": version, "forced": forced,
	})
	if err != nil {
		return
	}
	l.sc.ReportHub.Broadcast(sse.Event{
		ID:   fmt.Sprintf("content:%d", id),
		Type: "content.updated",
		Data: data,
	})
}

// inspectManifest 校验 zip 内容包的清单、路径安全与文件哈希。
func inspectManifest(zipPath string, size int64, kind, version string) error {
	reader, err := zip.OpenReader(zipPath)
	if err != nil {
		return apierr.New(codeContentInvalidZip, 400, "内容包不是合法的 zip 文件")
	}
	defer reader.Close()
	if len(reader.File) > 500 {
		return apierr.BadRequest("内容包文件数超过限制(500)")
	}

	actual := map[string]string{}
	var manifest []byte
	for _, f := range reader.File {
		if f.FileInfo().IsDir() {
			continue
		}
		name := path.Clean(strings.ReplaceAll(f.Name, "\\", "/"))
		if !safeArchivePath(name) {
			return apierr.BadRequest("内容包包含非法路径: " + f.Name)
		}
		rc, openErr := f.Open()
		if openErr != nil {
			return apierr.New(codeContentInvalidZip, 400, "内容包无法读取")
		}
		digest := ""
		if name == "manifest.json" {
			data, readErr := io.ReadAll(io.LimitReader(rc, 1<<20))
			_ = rc.Close()
			if readErr != nil {
				return apierr.New(codeContentInvalidZip, 400, "内容包无法读取")
			}
			manifest = data
			sum := sha256.Sum256(data)
			digest = hex.EncodeToString(sum[:])
		} else {
			hasher := sha256.New()
			_, copyErr := io.Copy(hasher, io.LimitReader(rc, size+1))
			_ = rc.Close()
			if copyErr != nil {
				return apierr.New(codeContentInvalidZip, 400, "内容包无法读取")
			}
			digest = hex.EncodeToString(hasher.Sum(nil))
		}
		actual[name] = digest
	}
	if len(manifest) == 0 {
		return apierr.BadRequest("内容包缺少 manifest.json")
	}
	var m contentManifest
	if err := json.Unmarshal(manifest, &m); err != nil {
		return apierr.BadRequest("manifest.json 不是合法 JSON")
	}
	if m.Kind != kind || m.Version != version {
		return apierr.BadRequest("manifest.json 的 kind/version 与上传参数不一致")
	}
	if len(m.Files) == 0 {
		return apierr.BadRequest("manifest.json 未声明任何文件")
	}
	for _, entry := range m.Files {
		p := path.Clean(strings.ReplaceAll(strings.TrimSpace(entry.Path), "\\", "/"))
		if !safeArchivePath(p) {
			return apierr.BadRequest("manifest 包含非法路径: " + entry.Path)
		}
		digest, ok := actual[p]
		if !ok {
			return apierr.BadRequest("manifest 声明的文件不存在: " + entry.Path)
		}
		if !strings.EqualFold(digest, strings.TrimSpace(entry.SHA256)) {
			return apierr.BadRequest("文件哈希不一致: " + entry.Path)
		}
	}
	return nil
}

func safeArchivePath(name string) bool {
	if name == "" || name == "." || name == ".." {
		return false
	}
	if strings.HasPrefix(name, "/") || strings.HasPrefix(name, "../") || strings.Contains(name, "/../") {
		return false
	}
	return true
}

func contentNewer(a, b ContentItem, platform string) bool {
	c := compareVersion(a.Version, b.Version)
	if c != 0 {
		return c > 0
	}
	// 版本相同时,平台精确匹配优先于 all。
	return a.Platform == platform && b.Platform != platform
}

func compareVersion(a, b string) int {
	pa, pb := strings.Split(a, "."), strings.Split(b, ".")
	for i := 0; i < 3; i++ {
		var ai, bi int
		if i < len(pa) {
			ai, _ = strconv.Atoi(pa[i])
		}
		if i < len(pb) {
			bi, _ = strconv.Atoi(pb[i])
		}
		if ai != bi {
			if ai > bi {
				return 1
			}
			return -1
		}
	}
	return 0
}

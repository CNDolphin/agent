package logic

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"

	"mhagent/internal/apierr"
	"mhagent/internal/auth"
	"mhagent/internal/sse"
	"mhagent/internal/svc"
)

// ReportLogic 检测报告上传、投递与下载。
type ReportLogic struct {
	sc *svc.ServiceContext
}

// NewReportLogic 创建报告逻辑。
func NewReportLogic(sc *svc.ServiceContext) *ReportLogic { return &ReportLogic{sc: sc} }

// allowedReportExts 允许上传的报告扩展名。
var allowedReportExts = map[string]bool{
	".pdf": true, ".png": true, ".jpg": true, ".jpeg": true, ".webp": true, ".doc": true, ".docx": true,
}

// 报告相关错误码。
const (
	codeUserNotFound   = 40401
	codeReportNotFound = 40402
	codeVersionMissing = 40403
)

func errUserNotFound() *apierr.Error   { return apierr.New(codeUserNotFound, 404, "用户不存在") }
func errReportNotFound() *apierr.Error { return apierr.New(codeReportNotFound, 404, "检测报告不存在") }
func errVersionMissing() *apierr.Error { return apierr.New(codeVersionMissing, 404, "报告版本不存在") }

// ReportItem 管理端列表项。
type ReportItem struct {
	ID           int64   `json:"id"`
	UserID       int64   `json:"user_id"`
	PhoneMask    string  `json:"phone_mask"`
	Title        string  `json:"title"`
	Version      int     `json:"version"`
	Filename     string  `json:"filename"`
	SizeBytes    int64   `json:"size_bytes"`
	Status       string  `json:"status"`
	CreatedAt    string  `json:"created_at"`
	UpdatedAt    string  `json:"updated_at"`
	NotifiedAt   *string `json:"notified_at"`
	DownloadedAt *string `json:"downloaded_at"`
	ReadAt       *string `json:"read_at"`
}

// ReportVersionItem 报告版本项。
type ReportVersionItem struct {
	Version     int    `json:"version"`
	Filename    string `json:"filename"`
	ContentType string `json:"content_type"`
	SizeBytes   int64  `json:"size_bytes"`
	UploadedBy  int64  `json:"uploaded_by"`
	CreatedAt   string `json:"created_at"`
}

// ReportDetail 报告详情。
type ReportDetail struct {
	ReportItem
	Versions []ReportVersionItem `json:"versions"`
}

// ReportListQuery 管理端列表查询条件。
type ReportListQuery struct {
	Phone    string
	Keyword  string
	Status   string
	Page     int
	PageSize int
}

// ReportListResult 列表结果。
type ReportListResult struct {
	Items []ReportItem `json:"items"`
	Total int          `json:"total"`
}

// ReportUploadInput 上传输入。
type ReportUploadInput struct {
	UserID      int64
	Phone       string
	Title       string
	Filename    string
	ContentType string
	Body        io.Reader
}

// PendingReport 用户端待下载报告。
type PendingReport struct {
	ReportID    int64  `json:"report_id"`
	Version     int    `json:"version"`
	Title       string `json:"title"`
	Filename    string `json:"filename"`
	ContentType string `json:"content_type"`
	SizeBytes   int64  `json:"size_bytes"`
	CreatedAt   string `json:"created_at"`
}

// ReportFile 待写出的报告文件。
type ReportFile struct {
	Name        string
	ContentType string
	SizeBytes   int64
	Version     int
	Body        io.ReadCloser
}

func formatTime(t time.Time) string { return t.UTC().Format(time.RFC3339) }

func formatNullTime(t sql.NullTime) *string {
	if !t.Valid {
		return nil
	}
	v := formatTime(t.Time)
	return &v
}

func deriveStatus(notified, downloaded sql.NullTime) string {
	switch {
	case downloaded.Valid:
		return "downloaded"
	case notified.Valid:
		return "notified"
	default:
		return "pending"
	}
}

// resolveUserID 按 user_id 优先、否则按手机号定位未注销用户。
func (l *ReportLogic) resolveUserID(ctx context.Context, userID int64, phone string) (int64, error) {
	if userID > 0 {
		var id int64
		err := l.sc.DB.QueryRowContext(ctx,
			`SELECT id FROM users WHERE id=$1 AND deleted_at IS NULL`, userID).Scan(&id)
		if errors.Is(err, sql.ErrNoRows) {
			return 0, errUserNotFound()
		}
		if err != nil {
			return 0, apierr.Internal()
		}
		return id, nil
	}
	phone = strings.TrimSpace(phone)
	if phone == "" {
		return 0, apierr.BadRequest("必须提供手机号或用户 ID")
	}
	hash, err := auth.HashPhone(l.sc.Secrets.PhonePepper, phone)
	if err != nil {
		return 0, apierr.BadRequest("手机号格式不正确")
	}
	var id int64
	err = l.sc.DB.QueryRowContext(ctx,
		`SELECT id FROM users WHERE phone_hash=$1 AND deleted_at IS NULL`, hash).Scan(&id)
	if errors.Is(err, sql.ErrNoRows) {
		return 0, errUserNotFound()
	}
	if err != nil {
		return 0, apierr.Internal()
	}
	return id, nil
}

func normalizeFilename(name string) string {
	name = strings.TrimSpace(filepath.Base(strings.ReplaceAll(name, "\\", "/")))
	if name == "" || name == "." {
		return "report"
	}
	return name
}

func reportExt(filename string) (string, error) {
	ext := strings.ToLower(filepath.Ext(filename))
	if !allowedReportExts[ext] {
		return "", apierr.BadRequest("不支持的文件类型,仅允许 PDF/图片/Word")
	}
	return ext, nil
}

func defaultTitle(title, filename string) string {
	t := strings.TrimSpace(title)
	if t != "" {
		return t
	}
	base := strings.TrimSuffix(normalizeFilename(filename), filepath.Ext(filename))
	if strings.TrimSpace(base) == "" {
		return "检测报告"
	}
	return base
}

func contentTypeOf(declared, ext string) string {
	if v := strings.TrimSpace(declared); v != "" {
		return v
	}
	if v := mime.TypeByExtension(ext); v != "" {
		return v
	}
	return "application/octet-stream"
}

func (l *ReportLogic) maxBytes() int64 { return l.sc.Config.Reports.MaxSizeMB << 20 }

// storeFile 落盘并返回相对存储路径、sha256、实际大小。
func (l *ReportLogic) storeFile(userID, reportID int64, version int, ext string, body io.Reader) (string, string, int64, error) {
	relDir := filepath.Join(strconv.FormatInt(userID, 10), strconv.FormatInt(reportID, 10))
	absDir := filepath.Join(l.sc.Config.Reports.Dir, relDir)
	if err := os.MkdirAll(absDir, 0o700); err != nil {
		return "", "", 0, apierr.Internal()
	}
	name := fmt.Sprintf("v%d-%s%s", version, uuid.NewString(), ext)
	relPath := filepath.Join(relDir, name)
	tmpPath := filepath.Join(absDir, name+".part")

	f, err := os.OpenFile(tmpPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		return "", "", 0, apierr.Internal()
	}
	hasher := sha256.New()
	n, copyErr := io.Copy(io.MultiWriter(f, hasher), io.LimitReader(body, l.maxBytes()+1))
	closeErr := f.Close()
	if copyErr != nil || closeErr != nil {
		_ = os.Remove(tmpPath)
		return "", "", 0, apierr.Internal()
	}
	if n > l.maxBytes() {
		_ = os.Remove(tmpPath)
		return "", "", 0, apierr.BadRequest(fmt.Sprintf("文件超过大小限制(%dMB)", l.sc.Config.Reports.MaxSizeMB))
	}
	if err := os.Rename(tmpPath, filepath.Join(absDir, name)); err != nil {
		_ = os.Remove(tmpPath)
		return "", "", 0, apierr.Internal()
	}
	return relPath, hex.EncodeToString(hasher.Sum(nil)), n, nil
}

func (l *ReportLogic) publish(userID int64, eventType string, reportID int64, version int, title string) {
	if l.sc.ReportHub == nil {
		return
	}
	data, err := json.Marshal(map[string]any{
		"report_id": reportID,
		"version":   version,
		"title":     title,
	})
	if err != nil {
		return
	}
	l.sc.ReportHub.Publish(userID, sse.Event{
		ID:   fmt.Sprintf("%d:%d", reportID, version),
		Type: eventType,
		Data: data,
	})
}

// CreateReport 上传新报告(v1)并推送通知事件。
func (l *ReportLogic) CreateReport(ctx context.Context, in ReportUploadInput) (ReportItem, error) {
	admin, err := requireSuper(ctx)
	if err != nil {
		return ReportItem{}, err
	}
	uid, err := l.resolveUserID(ctx, in.UserID, in.Phone)
	if err != nil {
		return ReportItem{}, err
	}
	filename := normalizeFilename(in.Filename)
	ext, err := reportExt(filename)
	if err != nil {
		return ReportItem{}, err
	}
	title := defaultTitle(in.Title, filename)
	contentType := contentTypeOf(in.ContentType, ext)

	var reportID int64
	if err := l.sc.DB.QueryRowContext(ctx,
		`INSERT INTO reports (user_id, title, current_version, created_by) VALUES ($1,$2,1,$3) RETURNING id`,
		uid, title, admin.ID).Scan(&reportID); err != nil {
		return ReportItem{}, apierr.Internal()
	}

	relPath, digest, size, err := l.storeFile(uid, reportID, 1, ext, in.Body)
	if err != nil {
		_, _ = l.sc.DB.ExecContext(ctx, `DELETE FROM reports WHERE id=$1`, reportID)
		return ReportItem{}, err
	}

	tx, err := l.sc.DB.BeginTx(ctx, nil)
	if err != nil {
		_ = os.Remove(filepath.Join(l.sc.Config.Reports.Dir, relPath))
		_, _ = l.sc.DB.ExecContext(ctx, `DELETE FROM reports WHERE id=$1`, reportID)
		return ReportItem{}, apierr.Internal()
	}
	_, err = tx.ExecContext(ctx,
		`INSERT INTO report_versions (report_id, version, filename, content_type, size_bytes, sha256, storage_path, uploaded_by)
		 VALUES ($1,1,$2,$3,$4,$5,$6,$7)`,
		reportID, filename, contentType, size, digest, relPath, admin.ID)
	if err == nil {
		_, err = tx.ExecContext(ctx,
			`INSERT INTO report_deliveries (report_id, version, user_id) VALUES ($1,1,$2)`, reportID, uid)
	}
	if err != nil {
		_ = tx.Rollback()
		_ = os.Remove(filepath.Join(l.sc.Config.Reports.Dir, relPath))
		_, _ = l.sc.DB.ExecContext(ctx, `DELETE FROM reports WHERE id=$1`, reportID)
		return ReportItem{}, apierr.Internal()
	}
	if err := tx.Commit(); err != nil {
		return ReportItem{}, apierr.Internal()
	}

	l.publish(uid, "report.created", reportID, 1, title)
	return l.reportItem(ctx, reportID)
}

// ListReports 管理端分页列表。
func (l *ReportLogic) ListReports(ctx context.Context, q ReportListQuery) (ReportListResult, error) {
	if _, err := requireSuper(ctx); err != nil {
		return ReportListResult{}, err
	}
	if q.Page <= 0 {
		q.Page = 1
	}
	if q.PageSize <= 0 {
		q.PageSize = 20
	}
	if q.PageSize > 100 {
		q.PageSize = 100
	}

	where := []string{"r.deleted_at IS NULL"}
	args := []any{}
	if strings.TrimSpace(q.Phone) != "" {
		hash, err := auth.HashPhone(l.sc.Secrets.PhonePepper, strings.TrimSpace(q.Phone))
		if err != nil {
			return ReportListResult{}, apierr.BadRequest("手机号格式不正确")
		}
		var uid int64
		err = l.sc.DB.QueryRowContext(ctx,
			`SELECT id FROM users WHERE phone_hash=$1 AND deleted_at IS NULL`, hash).Scan(&uid)
		if errors.Is(err, sql.ErrNoRows) {
			return ReportListResult{Items: []ReportItem{}, Total: 0}, nil
		}
		if err != nil {
			return ReportListResult{}, apierr.Internal()
		}
		args = append(args, uid)
		where = append(where, fmt.Sprintf("r.user_id=$%d", len(args)))
	}
	if kw := strings.TrimSpace(q.Keyword); kw != "" {
		args = append(args, "%"+kw+"%")
		n := len(args)
		where = append(where, fmt.Sprintf("(r.title ILIKE $%d OR COALESCE(v.filename,'') ILIKE $%d)", n, n))
	}
	switch strings.ToLower(strings.TrimSpace(q.Status)) {
	case "pending":
		where = append(where, "d.notified_at IS NULL AND d.downloaded_at IS NULL")
	case "notified":
		where = append(where, "d.notified_at IS NOT NULL AND d.downloaded_at IS NULL")
	case "downloaded":
		where = append(where, "d.downloaded_at IS NOT NULL")
	}

	from := ` FROM reports r
		 JOIN users u ON u.id=r.user_id
		 LEFT JOIN report_versions v ON v.report_id=r.id AND v.version=r.current_version
		 LEFT JOIN report_deliveries d ON d.report_id=r.id AND d.version=r.current_version`
	cond := " WHERE " + strings.Join(where, " AND ")

	var total int
	if err := l.sc.DB.QueryRowContext(ctx, `SELECT count(*)`+from+cond, args...).Scan(&total); err != nil {
		return ReportListResult{}, apierr.Internal()
	}
	if total == 0 {
		return ReportListResult{Items: []ReportItem{}, Total: 0}, nil
	}

	pageArgs := append(append([]any{}, args...), q.PageSize, (q.Page-1)*q.PageSize)
	rows, err := l.sc.DB.QueryContext(ctx,
		`SELECT r.id, r.user_id, u.phone_mask, r.title, r.current_version,
		        COALESCE(v.filename,''), COALESCE(v.size_bytes,0),
		        d.notified_at, d.downloaded_at, d.read_at,
		        r.created_at, r.updated_at`+from+cond+
			fmt.Sprintf(" ORDER BY r.id DESC LIMIT $%d OFFSET $%d", len(pageArgs)-1, len(pageArgs)),
		pageArgs...)
	if err != nil {
		return ReportListResult{}, apierr.Internal()
	}
	defer rows.Close()

	items := make([]ReportItem, 0, q.PageSize)
	for rows.Next() {
		item, err := scanReportItem(rows)
		if err != nil {
			return ReportListResult{}, apierr.Internal()
		}
		items = append(items, item)
	}
	if err := rows.Err(); err != nil {
		return ReportListResult{}, apierr.Internal()
	}
	return ReportListResult{Items: items, Total: total}, nil
}

type rowScanner interface {
	Scan(dest ...any) error
}

func scanReportItem(row rowScanner) (ReportItem, error) {
	var v ReportItem
	var notified, downloaded, read sql.NullTime
	var createdAt, updatedAt time.Time
	if err := row.Scan(&v.ID, &v.UserID, &v.PhoneMask, &v.Title, &v.Version,
		&v.Filename, &v.SizeBytes, &notified, &downloaded, &read, &createdAt, &updatedAt); err != nil {
		return ReportItem{}, err
	}
	v.Status = deriveStatus(notified, downloaded)
	v.NotifiedAt = formatNullTime(notified)
	v.DownloadedAt = formatNullTime(downloaded)
	v.ReadAt = formatNullTime(read)
	v.CreatedAt = formatTime(createdAt)
	v.UpdatedAt = formatTime(updatedAt)
	return v, nil
}

func (l *ReportLogic) reportItem(ctx context.Context, reportID int64) (ReportItem, error) {
	row := l.sc.DB.QueryRowContext(ctx,
		`SELECT r.id, r.user_id, u.phone_mask, r.title, r.current_version,
		        COALESCE(v.filename,''), COALESCE(v.size_bytes,0),
		        d.notified_at, d.downloaded_at, d.read_at,
		        r.created_at, r.updated_at
		 FROM reports r
		 JOIN users u ON u.id=r.user_id
		 LEFT JOIN report_versions v ON v.report_id=r.id AND v.version=r.current_version
		 LEFT JOIN report_deliveries d ON d.report_id=r.id AND d.version=r.current_version
		 WHERE r.id=$1 AND r.deleted_at IS NULL`, reportID)
	item, err := scanReportItem(row)
	if errors.Is(err, sql.ErrNoRows) {
		return ReportItem{}, errReportNotFound()
	}
	if err != nil {
		return ReportItem{}, apierr.Internal()
	}
	return item, nil
}

// GetReport 管理端详情:报告 + 全部版本。
func (l *ReportLogic) GetReport(ctx context.Context, reportID int64) (ReportDetail, error) {
	if _, err := requireSuper(ctx); err != nil {
		return ReportDetail{}, err
	}
	item, err := l.reportItem(ctx, reportID)
	if err != nil {
		return ReportDetail{}, err
	}
	rows, err := l.sc.DB.QueryContext(ctx,
		`SELECT version, filename, content_type, size_bytes, uploaded_by, created_at
		 FROM report_versions WHERE report_id=$1 ORDER BY version DESC`, reportID)
	if err != nil {
		return ReportDetail{}, apierr.Internal()
	}
	defer rows.Close()
	versions := []ReportVersionItem{}
	for rows.Next() {
		var v ReportVersionItem
		var created time.Time
		if err := rows.Scan(&v.Version, &v.Filename, &v.ContentType, &v.SizeBytes, &v.UploadedBy, &created); err != nil {
			return ReportDetail{}, apierr.Internal()
		}
		v.CreatedAt = formatTime(created)
		versions = append(versions, v)
	}
	return ReportDetail{ReportItem: item, Versions: versions}, nil
}

// ReplaceVersion 上传新版本并重置投递状态。
func (l *ReportLogic) ReplaceVersion(ctx context.Context, reportID int64, filename, contentType string, body io.Reader) (ReportItem, error) {
	admin, err := requireSuper(ctx)
	if err != nil {
		return ReportItem{}, err
	}
	filename = normalizeFilename(filename)
	ext, err := reportExt(filename)
	if err != nil {
		return ReportItem{}, err
	}
	contentType = contentTypeOf(contentType, ext)

	tx, err := l.sc.DB.BeginTx(ctx, nil)
	if err != nil {
		return ReportItem{}, apierr.Internal()
	}
	defer func() { _ = tx.Rollback() }()

	var uid int64
	var current int
	err = tx.QueryRowContext(ctx,
		`SELECT user_id, current_version FROM reports WHERE id=$1 AND deleted_at IS NULL FOR UPDATE`,
		reportID).Scan(&uid, &current)
	if errors.Is(err, sql.ErrNoRows) {
		return ReportItem{}, errReportNotFound()
	}
	if err != nil {
		return ReportItem{}, apierr.Internal()
	}

	next := current + 1
	relPath, digest, size, err := l.storeFile(uid, reportID, next, ext, body)
	if err != nil {
		return ReportItem{}, err
	}
	if _, err := tx.ExecContext(ctx,
		`INSERT INTO report_versions (report_id, version, filename, content_type, size_bytes, sha256, storage_path, uploaded_by)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`,
		reportID, next, filename, contentType, size, digest, relPath, admin.ID); err != nil {
		_ = os.Remove(filepath.Join(l.sc.Config.Reports.Dir, relPath))
		return ReportItem{}, apierr.Internal()
	}
	if _, err := tx.ExecContext(ctx,
		`UPDATE reports SET current_version=$2, updated_at=now() WHERE id=$1`, reportID, next); err != nil {
		return ReportItem{}, apierr.Internal()
	}
	if _, err := tx.ExecContext(ctx,
		`INSERT INTO report_deliveries (report_id, version, user_id) VALUES ($1,$2,$3)
		 ON CONFLICT (report_id, version) DO UPDATE SET notified_at=NULL, downloaded_at=NULL, read_at=NULL`,
		reportID, next, uid); err != nil {
		return ReportItem{}, apierr.Internal()
	}
	if err := tx.Commit(); err != nil {
		return ReportItem{}, apierr.Internal()
	}

	item, err := l.reportItem(ctx, reportID)
	if err != nil {
		return ReportItem{}, err
	}
	l.publish(uid, "report.updated", reportID, next, item.Title)
	return item, nil
}

// NotifyReport 重新通知:刷新当前版本的 notified_at 并推送事件。
func (l *ReportLogic) NotifyReport(ctx context.Context, reportID int64) (ReportItem, error) {
	if _, err := requireSuper(ctx); err != nil {
		return ReportItem{}, err
	}
	item, err := l.reportItem(ctx, reportID)
	if err != nil {
		return ReportItem{}, err
	}
	if _, err := l.sc.DB.ExecContext(ctx,
		`INSERT INTO report_deliveries (report_id, version, user_id, notified_at) VALUES ($1,$2,$3,now())
		 ON CONFLICT (report_id, version) DO UPDATE SET notified_at=now()`,
		reportID, item.Version, item.UserID); err != nil {
		return ReportItem{}, apierr.Internal()
	}
	updated, err := l.reportItem(ctx, reportID)
	if err != nil {
		return ReportItem{}, err
	}
	l.publish(item.UserID, "report.updated", reportID, item.Version, item.Title)
	return updated, nil
}

// DeleteReport 软删报告并推送删除事件,磁盘文件保留。
func (l *ReportLogic) DeleteReport(ctx context.Context, reportID int64) error {
	if _, err := requireSuper(ctx); err != nil {
		return err
	}
	var uid int64
	var version int
	var title string
	err := l.sc.DB.QueryRowContext(ctx,
		`SELECT user_id, current_version, title FROM reports WHERE id=$1 AND deleted_at IS NULL`,
		reportID).Scan(&uid, &version, &title)
	if errors.Is(err, sql.ErrNoRows) {
		return errReportNotFound()
	}
	if err != nil {
		return apierr.Internal()
	}
	if _, err := l.sc.DB.ExecContext(ctx,
		`UPDATE reports SET deleted_at=now(), updated_at=now() WHERE id=$1`, reportID); err != nil {
		return apierr.Internal()
	}
	l.publish(uid, "report.deleted", reportID, version, title)
	return nil
}

// openVersion 打开指定版本的存储文件;version<=0 表示当前版本。
func (l *ReportLogic) openVersion(ctx context.Context, reportID int64, version int) (ReportFile, error) {
	query := `SELECT v.version, v.filename, v.content_type, v.size_bytes, v.storage_path
		 FROM reports r JOIN report_versions v ON v.report_id=r.id AND v.version=r.current_version
		 WHERE r.id=$1 AND r.deleted_at IS NULL`
	args := []any{reportID}
	if version > 0 {
		query = `SELECT v.version, v.filename, v.content_type, v.size_bytes, v.storage_path
		 FROM reports r JOIN report_versions v ON v.report_id=r.id
		 WHERE r.id=$1 AND r.deleted_at IS NULL AND v.version=$2`
		args = append(args, version)
	}
	var f ReportFile
	var relPath string
	err := l.sc.DB.QueryRowContext(ctx, query, args...).
		Scan(&f.Version, &f.Name, &f.ContentType, &f.SizeBytes, &relPath)
	if errors.Is(err, sql.ErrNoRows) {
		if version > 0 {
			return ReportFile{}, errVersionMissing()
		}
		return ReportFile{}, errReportNotFound()
	}
	if err != nil {
		return ReportFile{}, apierr.Internal()
	}
	abs := filepath.Join(l.sc.Config.Reports.Dir, relPath)
	body, err := os.Open(abs)
	if err != nil {
		return ReportFile{}, apierr.Internal()
	}
	f.Body = body
	return f, nil
}

// AdminDownload 管理端下载指定版本(默认当前版本)。
func (l *ReportLogic) AdminDownload(ctx context.Context, reportID int64, version int) (ReportFile, error) {
	if _, err := requireSuper(ctx); err != nil {
		return ReportFile{}, err
	}
	return l.openVersion(ctx, reportID, version)
}

// PendingReports 返回当前用户尚未下载的最新版本,并把 notified_at 置为当前时间。
func (l *ReportLogic) PendingReports(ctx context.Context) ([]PendingReport, error) {
	uid, ok := apierr.UserID(ctx)
	if !ok {
		return nil, apierr.Unauthorized("未登录或令牌无效")
	}
	rows, err := l.sc.DB.QueryContext(ctx,
		`SELECT r.id, r.current_version, r.title, v.filename, v.content_type, v.size_bytes, v.created_at
		 FROM reports r
		 JOIN report_versions v ON v.report_id=r.id AND v.version=r.current_version
		 LEFT JOIN report_deliveries d ON d.report_id=r.id AND d.version=r.current_version
		 WHERE r.user_id=$1 AND r.deleted_at IS NULL AND d.downloaded_at IS NULL
		 ORDER BY r.id DESC`, uid)
	if err != nil {
		return nil, apierr.Internal()
	}
	defer rows.Close()

	items := []PendingReport{}
	for rows.Next() {
		var v PendingReport
		var created time.Time
		if err := rows.Scan(&v.ReportID, &v.Version, &v.Title, &v.Filename, &v.ContentType, &v.SizeBytes, &created); err != nil {
			return nil, apierr.Internal()
		}
		v.CreatedAt = formatTime(created)
		items = append(items, v)
	}
	if err := rows.Err(); err != nil {
		return nil, apierr.Internal()
	}
	for _, v := range items {
		if _, err := l.sc.DB.ExecContext(ctx,
			`INSERT INTO report_deliveries (report_id, version, user_id, notified_at) VALUES ($1,$2,$3,now())
			 ON CONFLICT (report_id, version) DO UPDATE SET notified_at=COALESCE(report_deliveries.notified_at, now())`,
			v.ReportID, v.Version, uid); err != nil {
			return nil, apierr.Internal()
		}
	}
	return items, nil
}

// UserDownload 用户下载自己报告的当前版本,并记录 downloaded_at。
func (l *ReportLogic) UserDownload(ctx context.Context, reportID int64) (ReportFile, error) {
	uid, ok := apierr.UserID(ctx)
	if !ok {
		return ReportFile{}, apierr.Unauthorized("未登录或令牌无效")
	}
	f, err := l.openVersion(ctx, reportID, 0)
	if err != nil {
		return ReportFile{}, err
	}
	var owner int64
	if err := l.sc.DB.QueryRowContext(ctx,
		`SELECT user_id FROM reports WHERE id=$1 AND deleted_at IS NULL`, reportID).Scan(&owner); err != nil {
		_ = f.Body.Close()
		return ReportFile{}, apierr.Internal()
	}
	if owner != uid {
		_ = f.Body.Close()
		return ReportFile{}, errReportNotFound()
	}
	if _, err := l.sc.DB.ExecContext(ctx,
		`INSERT INTO report_deliveries (report_id, version, user_id, notified_at, downloaded_at)
		 VALUES ($1,$2,$3,now(),now())
		 ON CONFLICT (report_id, version) DO UPDATE
		 SET notified_at=COALESCE(report_deliveries.notified_at, now()), downloaded_at=now()`,
		reportID, f.Version, uid); err != nil {
		_ = f.Body.Close()
		return ReportFile{}, apierr.Internal()
	}
	return f, nil
}

// MarkRead 标记当前版本已读(幂等)。
func (l *ReportLogic) MarkRead(ctx context.Context, reportID int64) error {
	uid, ok := apierr.UserID(ctx)
	if !ok {
		return apierr.Unauthorized("未登录或令牌无效")
	}
	res, err := l.sc.DB.ExecContext(ctx,
		`UPDATE report_deliveries d SET read_at=COALESCE(d.read_at, now())
		 FROM reports r
		 WHERE d.report_id=r.id AND d.version=r.current_version
		   AND r.id=$1 AND r.user_id=$2 AND r.deleted_at IS NULL`, reportID, uid)
	if err != nil {
		return apierr.Internal()
	}
	if n, _ := res.RowsAffected(); n == 0 {
		return errReportNotFound()
	}
	return nil
}

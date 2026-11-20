package handler

import (
	"io"
	"net/http"
	"net/url"
	"strconv"

	"mhagent/internal/apierr"
	"mhagent/internal/logic"
	"mhagent/internal/svc"
)

func parseReportID(r *http.Request) (int64, error) {
	id, err := strconv.ParseInt(pathVar(r, "id"), 10, 64)
	if err != nil || id <= 0 {
		return 0, apierr.BadRequest("报告 id 非法")
	}
	return id, nil
}

func writeReportFile(w http.ResponseWriter, f logic.ReportFile) {
	defer f.Body.Close()
	w.Header().Set("Content-Type", f.ContentType)
	w.Header().Set("Content-Length", strconv.FormatInt(f.SizeBytes, 10))
	w.Header().Set("Content-Disposition",
		"attachment; filename*=UTF-8''"+url.PathEscape(f.Name))
	w.WriteHeader(http.StatusOK)
	_, _ = io.Copy(w, f.Body)
}

// AdminCreateReport POST /admin/reports
func AdminCreateReport(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if err := r.ParseMultipartForm(8 << 20); err != nil {
			apierr.WriteError(w, apierr.BadRequest("请求体不是合法的 multipart/form-data"))
			return
		}
		file, header, err := r.FormFile("file")
		if err != nil {
			apierr.WriteError(w, apierr.BadRequest("缺少报告文件"))
			return
		}
		defer file.Close()
		var userID int64
		if v := r.FormValue("user_id"); v != "" {
			userID, err = strconv.ParseInt(v, 10, 64)
			if err != nil || userID <= 0 {
				apierr.WriteError(w, apierr.BadRequest("用户 id 非法"))
				return
			}
		}
		item, err := logic.NewReportLogic(sc).CreateReport(r.Context(), logic.ReportUploadInput{
			UserID:      userID,
			Phone:       r.FormValue("phone"),
			Title:       r.FormValue("title"),
			Filename:    header.Filename,
			ContentType: header.Header.Get("Content-Type"),
			Body:        file,
		})
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, item)
	}
}

// AdminListReports GET /admin/reports
func AdminListReports(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		page, err := queryInt(r, "page", 1, 100000)
		if err != nil {
			apierr.WriteError(w, apierr.BadRequest("page 非法"))
			return
		}
		pageSize, err := queryInt(r, "page_size", 20, 100)
		if err != nil {
			apierr.WriteError(w, apierr.BadRequest("page_size 非法"))
			return
		}
		q := r.URL.Query()
		res, lerr := logic.NewReportLogic(sc).ListReports(r.Context(), logic.ReportListQuery{
			Phone:    q.Get("phone"),
			Keyword:  q.Get("keyword"),
			Status:   q.Get("status"),
			Page:     page,
			PageSize: pageSize,
		})
		if lerr != nil {
			apierr.WriteError(w, lerr)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, res)
	}
}

// AdminGetReport GET /admin/reports/:id
func AdminGetReport(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := parseReportID(r)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		detail, lerr := logic.NewReportLogic(sc).GetReport(r.Context(), id)
		if lerr != nil {
			apierr.WriteError(w, lerr)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, detail)
	}
}

// AdminDownloadReport GET /admin/reports/:id/download?version=
func AdminDownloadReport(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := parseReportID(r)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		var version int
		if v := r.URL.Query().Get("version"); v != "" {
			version, err = strconv.Atoi(v)
			if err != nil || version <= 0 {
				apierr.WriteError(w, apierr.BadRequest("version 非法"))
				return
			}
		}
		f, lerr := logic.NewReportLogic(sc).AdminDownload(r.Context(), id, version)
		if lerr != nil {
			apierr.WriteError(w, lerr)
			return
		}
		writeReportFile(w, f)
	}
}

// AdminReplaceReportVersion POST /admin/reports/:id/versions
func AdminReplaceReportVersion(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := parseReportID(r)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		if err := r.ParseMultipartForm(8 << 20); err != nil {
			apierr.WriteError(w, apierr.BadRequest("请求体不是合法的 multipart/form-data"))
			return
		}
		file, header, err := r.FormFile("file")
		if err != nil {
			apierr.WriteError(w, apierr.BadRequest("缺少报告文件"))
			return
		}
		defer file.Close()
		item, lerr := logic.NewReportLogic(sc).ReplaceVersion(r.Context(), id,
			header.Filename, header.Header.Get("Content-Type"), file)
		if lerr != nil {
			apierr.WriteError(w, lerr)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, item)
	}
}

// AdminNotifyReport POST /admin/reports/:id/notify
func AdminNotifyReport(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := parseReportID(r)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		item, lerr := logic.NewReportLogic(sc).NotifyReport(r.Context(), id)
		if lerr != nil {
			apierr.WriteError(w, lerr)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, item)
	}
}

// AdminDeleteReport DELETE /admin/reports/:id
func AdminDeleteReport(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := parseReportID(r)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		if lerr := logic.NewReportLogic(sc).DeleteReport(r.Context(), id); lerr != nil {
			apierr.WriteError(w, lerr)
			return
		}
		apierr.WriteNoContent(w)
	}
}

// ReportsPending GET /reports/pending
func ReportsPending(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		items, err := logic.NewReportLogic(sc).PendingReports(r.Context())
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{"items": items})
	}
}

// ReportDownload GET /reports/:id/download
func ReportDownload(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := parseReportID(r)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		f, lerr := logic.NewReportLogic(sc).UserDownload(r.Context(), id)
		if lerr != nil {
			apierr.WriteError(w, lerr)
			return
		}
		writeReportFile(w, f)
	}
}

// ReportRead POST /reports/:id/read
func ReportRead(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := parseReportID(r)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		if lerr := logic.NewReportLogic(sc).MarkRead(r.Context(), id); lerr != nil {
			apierr.WriteError(w, lerr)
			return
		}
		apierr.WriteNoContent(w)
	}
}

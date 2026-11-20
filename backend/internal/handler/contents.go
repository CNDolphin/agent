package handler

import (
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"

	"mhagent/internal/apierr"
	"mhagent/internal/logic"
	"mhagent/internal/svc"
)

func parseContentID(r *http.Request) (int64, error) {
	id, err := strconv.ParseInt(pathVar(r, "id"), 10, 64)
	if err != nil || id <= 0 {
		return 0, apierr.BadRequest("内容版本 id 非法")
	}
	return id, nil
}

// AdminPublishContent POST /admin/contents
func AdminPublishContent(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if err := r.ParseMultipartForm(8 << 20); err != nil {
			apierr.WriteError(w, apierr.BadRequest("请求体不是合法的 multipart/form-data"))
			return
		}
		file, header, err := r.FormFile("file")
		if err != nil {
			apierr.WriteError(w, apierr.BadRequest("缺少内容包文件"))
			return
		}
		defer file.Close()
		forced := r.FormValue("forced") == "true" || r.FormValue("forced") == "1"
		item, lerr := logic.NewContentLogic(sc).PublishContent(r.Context(), logic.ContentUploadInput{
			Kind:        r.FormValue("kind"),
			Platform:    r.FormValue("platform"),
			Version:     r.FormValue("version"),
			Notes:       r.FormValue("notes"),
			Forced:      forced,
			Filename:    header.Filename,
			ContentType: header.Header.Get("Content-Type"),
			Body:        file,
		})
		if lerr != nil {
			apierr.WriteError(w, lerr)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, item)
	}
}

// AdminListContents GET /admin/contents
func AdminListContents(sc *svc.ServiceContext) http.HandlerFunc {
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
		res, lerr := logic.NewContentLogic(sc).ListContents(r.Context(), logic.ContentListQuery{
			Kind:     r.URL.Query().Get("kind"),
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

// AdminNotifyContent POST /admin/contents/:id/notify
func AdminNotifyContent(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := parseContentID(r)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		item, lerr := logic.NewContentLogic(sc).NotifyContent(r.Context(), id)
		if lerr != nil {
			apierr.WriteError(w, lerr)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, item)
	}
}

// AdminOfflineContent DELETE /admin/contents/:id
func AdminOfflineContent(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := parseContentID(r)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		if lerr := logic.NewContentLogic(sc).OfflineContent(r.Context(), id); lerr != nil {
			apierr.WriteError(w, lerr)
			return
		}
		apierr.WriteNoContent(w)
	}
}

// ContentsLatest GET /contents/latest
func ContentsLatest(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var kinds []string
		for _, raw := range strings.Split(r.URL.Query().Get("kinds"), ",") {
			if v := strings.TrimSpace(raw); v != "" {
				kinds = append(kinds, v)
			}
		}
		items, err := logic.NewContentLogic(sc).LatestContents(
			r.Context(), r.URL.Query().Get("platform"), kinds)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		apierr.WriteJSON(w, http.StatusOK, map[string]any{"items": items})
	}
}

// ContentDownload GET /contents/:id/download
func ContentDownload(sc *svc.ServiceContext) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := parseContentID(r)
		if err != nil {
			apierr.WriteError(w, err)
			return
		}
		f, lerr := logic.NewContentLogic(sc).DownloadContent(r.Context(), id)
		if lerr != nil {
			apierr.WriteError(w, lerr)
			return
		}
		defer f.File.Close()
		w.Header().Set("Content-Type", "application/zip")
		w.Header().Set("Content-Length", strconv.FormatInt(f.Item.SizeBytes, 10))
		w.Header().Set("Content-Disposition",
			"attachment; filename*=UTF-8''"+url.PathEscape(f.Item.Filename))
		w.Header().Set("X-Content-SHA256", f.Item.SHA256)
		w.Header().Set("X-Content-Version", f.Item.Version)
		w.Header().Set("X-Content-Kind", f.Item.Kind)
		w.WriteHeader(http.StatusOK)
		_, _ = io.Copy(w, f.File)
	}
}

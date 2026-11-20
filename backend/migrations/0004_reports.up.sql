-- 检测报告:一份报告可有多版本,投递记录按版本保存
CREATE TABLE IF NOT EXISTS reports (
  id              BIGSERIAL PRIMARY KEY,
  user_id         BIGINT NOT NULL REFERENCES users(id),
  title           TEXT   NOT NULL,
  current_version INT    NOT NULL DEFAULT 1,
  created_by      BIGINT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id, id DESC) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS report_versions (
  id           BIGSERIAL PRIMARY KEY,
  report_id    BIGINT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  version      INT    NOT NULL,
  filename     TEXT   NOT NULL,
  content_type TEXT   NOT NULL,
  size_bytes   BIGINT NOT NULL,
  sha256       TEXT   NOT NULL,
  storage_path TEXT   NOT NULL,
  uploaded_by  BIGINT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (report_id, version)
);

CREATE TABLE IF NOT EXISTS report_deliveries (
  report_id     BIGINT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  version       INT    NOT NULL,
  user_id       BIGINT NOT NULL,
  notified_at   TIMESTAMPTZ,
  downloaded_at TIMESTAMPTZ,
  read_at       TIMESTAMPTZ,
  PRIMARY KEY (report_id, version)
);
CREATE INDEX IF NOT EXISTS idx_deliveries_user ON report_deliveries(user_id, report_id);

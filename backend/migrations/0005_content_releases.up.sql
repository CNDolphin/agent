-- 在线更新:内容包/客户端程序包版本表
CREATE TABLE IF NOT EXISTS content_releases (
  id           BIGSERIAL PRIMARY KEY,
  kind         TEXT   NOT NULL,
  platform     TEXT   NOT NULL DEFAULT 'all',
  version      TEXT   NOT NULL,
  filename     TEXT   NOT NULL,
  content_type TEXT   NOT NULL DEFAULT 'application/zip',
  size_bytes   BIGINT NOT NULL,
  sha256       TEXT   NOT NULL,
  storage_path TEXT   NOT NULL,
  notes        TEXT   NOT NULL DEFAULT '',
  forced       BOOLEAN NOT NULL DEFAULT FALSE,
  status       TEXT   NOT NULL DEFAULT 'published',
  published_at TIMESTAMPTZ,
  created_by   BIGINT REFERENCES admin_users(id),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_content_kind_platform_version
  ON content_releases(kind, platform, version);
CREATE INDEX IF NOT EXISTS idx_content_kind_published
  ON content_releases(kind, published_at DESC);

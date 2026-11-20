-- 用户密码登录:为历史账号保留 NULL,首次注册或补设密码后写入 bcrypt 哈希。
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;

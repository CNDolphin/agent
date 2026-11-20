"""本地加密存储(sqlite3 + 字段级 Fernet 加密)。

表结构:
- `kv(key TEXT PRIMARY KEY, value BLOB)`             —— value 为密文
- `records(id INTEGER PRIMARY KEY, kind TEXT, created_at TEXT, payload BLOB)` —— payload 为密文

只有 `kind` 与 `created_at` 是明文,仅用于过滤;口令由用户设置,不上传。
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .crypto import Cipher, DecryptError

META_NAME = "meta.json"
DB_NAME = "mhagent.db"
VERIFIER_KEY = "__verifier__"
VERIFIER_TEXT = "mhagent-local-store-v1"
DIR_MODE = 0o700
FILE_MODE = 0o600


class StoreError(Exception):
    """本地库错误。"""


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_time(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


class LocalStore:
    """加密本地库。口令错误时打开会抛 `DecryptError` 且不修改原文件。"""

    def __init__(self, data_dir, passphrase: str):
        if not isinstance(passphrase, str) or not passphrase:
            raise ValueError("passphrase must be a non-empty string")
        self.data_dir = Path(data_dir).expanduser()
        self._passphrase = passphrase
        self._ensure_dir()
        salt = self._load_or_create_salt()
        self._salt = salt
        self.cipher = Cipher(passphrase, salt)
        self.db_path = self.data_dir / DB_NAME
        if self.db_path.exists():
            self._verify_passphrase()
        # 本地 API 的同步路由在线程池执行,连接需允许跨线程使用,并用锁串行化访问。
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        _chmod(self.db_path, FILE_MODE)
        self._init_schema()
        self._ensure_verifier()

    # ---- 目录与元数据 ----
    def _ensure_dir(self) -> None:
        if not self.data_dir.exists():
            self.data_dir.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
        _chmod(self.data_dir, DIR_MODE)

    def _load_or_create_salt(self) -> bytes:
        meta_path = self.data_dir / META_NAME
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                return bytes.fromhex(meta["salt"])
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                raise StoreError("meta.json 损坏") from exc
        salt = secrets.token_bytes(16)
        tmp = meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "salt": salt.hex()}, ensure_ascii=False), encoding="utf-8")
        _chmod(tmp, FILE_MODE)
        tmp.replace(meta_path)
        _chmod(meta_path, FILE_MODE)
        return salt

    def _verify_passphrase(self) -> None:
        """只读打开旧库校验口令,失败时不写入任何内容。"""
        try:
            uri = f"file:{self.db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
        except sqlite3.Error:
            return
        try:
            row = conn.execute("SELECT value FROM kv WHERE key = ?", (VERIFIER_KEY,)).fetchone()
        except sqlite3.Error:
            return
        finally:
            conn.close()
        if row is None:
            return
        try:
            text = self.cipher.decrypt_bytes(row[0]).decode("utf-8")
        except DecryptError as exc:
            raise DecryptError("本地库口令错误,数据未被修改") from exc
        try:
            stored = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DecryptError("本地库校验失败") from exc
        if stored != VERIFIER_TEXT:
            raise DecryptError("本地库校验失败")

    def _init_schema(self) -> None:
        self._conn.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value BLOB NOT NULL)")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS records ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "kind TEXT NOT NULL, "
            "created_at TEXT NOT NULL, "
            "payload BLOB NOT NULL)"
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_records_kind_time ON records(kind, created_at)")
        self._conn.commit()

    def _ensure_verifier(self) -> None:
        if self.kv_get(VERIFIER_KEY) is not None:
            return
        self._set_kv(VERIFIER_KEY, VERIFIER_TEXT)

    # ---- kv ----
    def _set_kv(self, key: str, value) -> None:
        blob = self.cipher.encrypt_text(json.dumps(value, ensure_ascii=False))
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, blob))
            self._conn.commit()

    def kv_set(self, key: str, value) -> None:
        if not key:
            raise ValueError("key must be non-empty")
        self._set_kv(key, value)

    def kv_get(self, key: str, default=None):
        with self._lock:
            row = self._conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(self.cipher.decrypt_text(row[0]))
        except DecryptError as exc:
            raise DecryptError(f"kv 解密失败: {key}") from exc

    def kv_delete(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM kv WHERE key = ?", (key,))
            self._conn.commit()

    def kv_keys(self) -> list[str]:
        with self._lock:
            return [row[0] for row in self._conn.execute("SELECT key FROM kv ORDER BY key")]

    # ---- records ----
    def add_record(self, kind: str, payload, created_at=None) -> int:
        if not isinstance(kind, str) or not kind:
            raise ValueError("kind must be a non-empty string")
        created = _iso(_parse_time(created_at) or datetime.now(timezone.utc))
        blob = self.cipher.encrypt_text(json.dumps(payload, ensure_ascii=False, default=str))
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO records (kind, created_at, payload) VALUES (?, ?, ?)",
                (kind, created, blob),
            )
            self._conn.commit()
        return int(cur.lastrowid)

    def list_records(self, kind=None, since=None, until=None) -> list[dict]:
        query = "SELECT id, kind, created_at, payload FROM records"
        params: list = []
        if kind is not None:
            query += " WHERE kind = ?"
            params.append(kind)
        query += " ORDER BY id"
        since_dt = _parse_time(since)
        until_dt = _parse_time(until)
        result = []
        with self._lock:
            rows = list(self._conn.execute(query, params))
        for row in rows:
            created = _parse_time(row[2])
            if since_dt is not None and created < since_dt:
                continue
            if until_dt is not None and created > until_dt:
                continue
            try:
                payload = json.loads(self.cipher.decrypt_text(row[3]))
            except DecryptError as exc:
                raise DecryptError(f"记录解密失败: id={row[0]}") from exc
            result.append({"id": row[0], "kind": row[1], "created_at": row[2], "payload": payload})
        return result

    def insert_encrypted_record(self, record_id: int, kind: str, created_at: str, payload) -> None:
        """导入时使用:保留原始 id。"""
        blob = self.cipher.encrypt_text(json.dumps(payload, ensure_ascii=False, default=str))
        with self._lock:
            self._conn.execute(
                "INSERT INTO records (id, kind, created_at, payload) VALUES (?, ?, ?, ?)",
                (int(record_id), kind, created_at, blob),
            )
            self._conn.commit()

    def record_exists(self, record_id: int) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM records WHERE id = ?", (int(record_id),)).fetchone()
        return row is not None

    def delete_record(self, record_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM records WHERE id = ?", (int(record_id),))
            self._conn.commit()

    def record_count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM records").fetchone()[0])

    def update_record(self, record_id: int, payload) -> None:
        """原地更新记录内容(仅 payload),用于会话元数据变更。"""
        blob = self.cipher.encrypt_text(json.dumps(payload, ensure_ascii=False, default=str))
        with self._lock:
            self._conn.execute("UPDATE records SET payload = ? WHERE id = ?", (blob, int(record_id)))
            self._conn.commit()

    def rekey(self, new_passphrase: str) -> None:
        """用新口令重加密全部数据;任一步失败则回滚,不改动原有内容。"""
        if not isinstance(new_passphrase, str) or not new_passphrase:
            raise ValueError("passphrase must be a non-empty string")
        with self._lock:
            old_cipher = self.cipher
            new_cipher = Cipher(new_passphrase, self._salt)
            kv_rows = list(self._conn.execute("SELECT key, value FROM kv"))
            record_rows = list(self._conn.execute("SELECT id, payload FROM records"))
            with self._conn:
                for key, blob in kv_rows:
                    plain = old_cipher.decrypt_bytes(blob)
                    self._conn.execute(
                        "UPDATE kv SET value = ? WHERE key = ?", (new_cipher.encrypt_bytes(plain), key)
                    )
                for record_id, blob in record_rows:
                    plain = old_cipher.decrypt_bytes(blob)
                    self._conn.execute(
                        "UPDATE records SET payload = ? WHERE id = ?", (new_cipher.encrypt_bytes(plain), record_id)
                    )
            self._passphrase = new_passphrase
            self.cipher = new_cipher

    # ---- 生命周期 ----
    @property
    def passphrase(self) -> str:
        """仅在内存中使用,用于导出时派生文件级密钥。"""
        return self._passphrase

    def close(self) -> None:
        try:
            with self._lock:
                self._conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

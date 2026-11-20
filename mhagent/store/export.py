"""加密导出/导入(单个文件)。

导出文件是一个 JSON 信封,其中的数据整体加密,并附带版本号与校验和:

```
{"version": 1, "exported_at": ..., "salt": "...", "checksum": "...", "ciphertext": "..."}
```

- 默认不覆盖已有文件,也不覆盖已有数据(冲突时需 `overwrite=True`);
- 口令错误或文件被篡改都会失败,不清空原库。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .crypto import Cipher, DecryptError, new_salt
from .db import LocalStore, VERIFIER_KEY

EXPORT_VERSION = 1
FILE_MODE = 0o600


class ExportError(Exception):
    """导出/导入错误。"""


class ImportConflict(ExportError):
    """目标库已有同 id 记录或同 key 的 kv。"""


def _checksum(ciphertext: bytes) -> str:
    return hashlib.sha256(ciphertext).hexdigest()


def _payload(store: LocalStore) -> dict:
    kv = {key: store.kv_get(key) for key in store.kv_keys() if key != VERIFIER_KEY}
    records = store.list_records()
    return {
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "kv": kv,
        "records": records,
    }


def export_store(store: LocalStore, path, *, overwrite: bool = False) -> Path:
    """把本地库导出为单个加密文件。"""
    target = Path(path).expanduser()
    if target.exists() and not overwrite:
        raise FileExistsError(str(target))
    salt = new_salt()
    cipher = Cipher(store.passphrase, salt)
    ciphertext = cipher.encrypt_bytes(
        json.dumps(_payload(store), ensure_ascii=False, default=str).encode("utf-8")
    )
    envelope = {
        "version": EXPORT_VERSION,
        "salt": salt.hex(),
        "checksum": _checksum(ciphertext),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }
    tmp = target.with_name(target.name + ".tmp")
    if target.parent.exists():
        tmp.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    else:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, FILE_MODE)
    except OSError:
        pass
    tmp.replace(target)
    return target


def _read_envelope(path) -> dict:
    source = Path(path).expanduser()
    if not source.exists():
        raise ExportError("导出文件不存在")
    try:
        envelope = json.loads(source.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ExportError("导出文件格式错误") from exc
    required = {"version", "salt", "checksum", "ciphertext"}
    if not required.issubset(envelope):
        raise ExportError("导出文件缺少字段")
    if int(envelope["version"]) != EXPORT_VERSION:
        raise ExportError(f"不支持的导出版本: {envelope['version']}")
    return envelope


def _decrypt_envelope(envelope: dict, passphrase: str) -> dict:
    try:
        ciphertext = base64.b64decode(envelope["ciphertext"])
    except (ValueError, TypeError) as exc:
        raise ExportError("导出文件密文损坏") from exc
    if _checksum(ciphertext) != envelope["checksum"]:
        raise ExportError("导出文件校验失败,可能被篡改")
    cipher = Cipher(passphrase, bytes.fromhex(envelope["salt"]))
    try:
        plaintext = cipher.decrypt_bytes(ciphertext)
    except DecryptError as exc:
        raise DecryptError("导出文件口令错误或已损坏") from exc
    return json.loads(plaintext.decode("utf-8"))


def import_store(store: LocalStore, path, *, overwrite: bool = False) -> dict:
    """把单文件备份导入本地库。默认遇到冲突即失败且不写入。"""
    payload = _decrypt_envelope(_read_envelope(path), store.passphrase)
    records = payload.get("records", [])
    kv = payload.get("kv", {})

    conflicting_records = [r for r in records if store.record_exists(int(r["id"]))]
    conflicting_keys = [k for k in kv if store.kv_get(k, None) is not None]
    if not overwrite and (conflicting_records or conflicting_keys):
        raise ImportConflict("目标库已有相同数据,如需覆盖请指定 overwrite=True")

    if overwrite:
        for record in conflicting_records:
            store.delete_record(int(record["id"]))
        for key in conflicting_keys:
            store.kv_delete(key)

    for key, value in kv.items():
        store.kv_set(key, value)
    for record in records:
        store.insert_encrypted_record(
            int(record["id"]),
            str(record["kind"]),
            str(record["created_at"]),
            record["payload"],
        )
    return {"records": len(records), "kv": len(kv)}

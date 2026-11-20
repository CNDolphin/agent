import hashlib
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mhagent.store.crypto import DecryptError
from mhagent.store.db import LocalStore

MARKER = "PRIVATE-MARKER-xyz"


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_plaintext_not_on_disk(tmp_path):
    store = LocalStore(tmp_path, "pw")
    store.add_record("journal", {"note": MARKER})
    store.kv_set("contact", {"value": MARKER})
    store.close()
    for path in tmp_path.iterdir():
        if path.is_file():
            assert MARKER.encode("utf-8") not in path.read_bytes(), path.name


def test_roundtrip(tmp_path):
    store = LocalStore(tmp_path, "pw")
    record_id = store.add_record("journal", {"event": "今天很累", "intensity": 7})
    store.kv_set("account", {"phone": "13800000000"})
    store.close()

    store = LocalStore(tmp_path, "pw")
    records = store.list_records("journal")
    assert records[0]["id"] == record_id
    assert records[0]["payload"]["event"] == "今天很累"
    assert store.kv_get("account") == {"phone": "13800000000"}
    assert store.kv_get("missing", "fallback") == "fallback"
    store.close()


def test_wrong_passphrase_does_not_modify(tmp_path):
    store = LocalStore(tmp_path, "pw")
    store.add_record("journal", {"note": "机密"})
    store.close()
    db_path = tmp_path / "mhagent.db"
    before = _hash_file(db_path)
    with pytest.raises(DecryptError):
        LocalStore(tmp_path, "wrong")
    assert _hash_file(db_path) == before
    # 正确口令仍然可用
    store = LocalStore(tmp_path, "pw")
    assert store.record_count() == 1
    store.close()


def test_time_filters(tmp_path):
    store = LocalStore(tmp_path, "pw")
    base = datetime(2026, 11, 1, tzinfo=timezone.utc)
    store.add_record("journal", {"i": 1}, created_at=base)
    store.add_record("journal", {"i": 2}, created_at=base + timedelta(days=2))
    store.add_record("assessment", {"i": 3}, created_at=base + timedelta(days=4))
    assert [r["payload"]["i"] for r in store.list_records("journal")] == [1, 2]
    assert [r["payload"]["i"] for r in store.list_records("journal", since=base + timedelta(days=1))] == [2]
    assert [r["payload"]["i"] for r in store.list_records(until=base + timedelta(days=1))] == [1]
    with pytest.raises(ValueError):
        store.add_record("", {})
    store.close()


def test_permissions(tmp_path):
    data_dir = tmp_path / "data"
    store = LocalStore(data_dir, "pw")
    store.add_record("journal", {"x": 1})
    assert oct(os.stat(data_dir).st_mode & 0o777) == oct(0o700)
    for name in ("mhagent.db", "meta.json"):
        assert oct(os.stat(data_dir / name).st_mode & 0o777) == oct(0o600)
    store.close()


def test_meta_salt_is_not_secret_but_kept(tmp_path):
    store = LocalStore(tmp_path, "pw")
    store.close()
    meta = (tmp_path / "meta.json").read_text(encoding="utf-8")
    assert "salt" in meta
    assert "pw" not in meta


def test_rekey_switches_passphrase(tmp_path):
    store = LocalStore(tmp_path, "old-pw")
    store.add_record("journal", {"note": "机密"})
    store.kv_set("account", {"phone": "13800000000"})
    store.rekey("new-pw")
    assert store.record_count() == 1
    assert store.kv_get("account") == {"phone": "13800000000"}
    store.close()

    with pytest.raises(DecryptError):
        LocalStore(tmp_path, "old-pw")
    store = LocalStore(tmp_path, "new-pw")
    assert store.list_records("journal")[0]["payload"]["note"] == "机密"
    store.close()


def test_rekey_allows_arbitrary_key(tmp_path):
    """迁移场景:新口令是设备随机密钥,可含非字母字符。"""
    store = LocalStore(tmp_path, "user-passphrase")
    store.add_record("journal", {"i": 1})
    key = "0" * 64
    store.rekey(key)
    store.close()
    store = LocalStore(tmp_path, key)
    assert store.record_count() == 1
    store.close()


def test_cross_thread_access(tmp_path):
    """本地 API 的同步路由在线程池执行,连接必须允许跨线程使用。"""
    store = LocalStore(tmp_path, "pw")
    errors: list[Exception] = []

    def worker(index: int) -> None:
        try:
            store.kv_set(f"k{index}", {"i": index})
            assert store.kv_get(f"k{index}") == {"i": index}
            store.add_record("journal", {"i": index})
            store.record_count()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors
    assert store.record_count() == 8
    store.close()

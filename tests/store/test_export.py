import json

import pytest

from mhagent.store.crypto import DecryptError
from mhagent.store.db import LocalStore
from mhagent.store.export import ExportError, ImportConflict, export_store, import_store

MARKER = "PRIVATE-MARKER-xyz"


def _seed(store):
    store.add_record("journal", {"note": MARKER}, created_at="2026-11-01T00:00:00+00:00")
    store.add_record("assessment", {"total": 9}, created_at="2026-11-02T00:00:00+00:00")
    store.kv_set("account", {"phone": MARKER})


def test_export_import_roundtrip(tmp_path):
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source = LocalStore(source_dir, "pw")
    _seed(source)
    backup = tmp_path / "backup.enc"
    export_store(source, backup)
    source.close()

    assert MARKER not in backup.read_text(encoding="utf-8")

    target = LocalStore(target_dir, "pw")
    counts = import_store(target, backup)
    assert counts == {"records": 2, "kv": 1}
    records = target.list_records()
    assert [r["payload"] for r in records] == [{"note": MARKER}, {"total": 9}]
    assert target.kv_get("account") == {"phone": MARKER}
    target.close()


def test_wrong_passphrase_fails(tmp_path):
    source = LocalStore(tmp_path / "s", "pw")
    _seed(source)
    backup = tmp_path / "b.enc"
    export_store(source, backup)
    source.close()
    target = LocalStore(tmp_path / "t", "other-pw")
    with pytest.raises(DecryptError):
        import_store(target, backup)
    assert target.record_count() == 0
    target.close()


def test_tampered_file_fails(tmp_path):
    source = LocalStore(tmp_path / "s", "pw")
    _seed(source)
    backup = tmp_path / "b.enc"
    export_store(source, backup)
    source.close()
    envelope = json.loads(backup.read_text(encoding="utf-8"))
    envelope["ciphertext"] = envelope["ciphertext"][:-4] + "AAAA"
    backup.write_text(json.dumps(envelope), encoding="utf-8")
    target = LocalStore(tmp_path / "t", "pw")
    with pytest.raises(ExportError):
        import_store(target, backup)
    target.close()


def test_no_overwrite_by_default(tmp_path):
    source = LocalStore(tmp_path / "s", "pw")
    _seed(source)
    backup = tmp_path / "b.enc"
    export_store(source, backup)
    with pytest.raises(FileExistsError):
        export_store(source, backup)
    export_store(source, backup, overwrite=True)
    source.close()

    target = LocalStore(tmp_path / "t", "pw")
    import_store(target, backup)
    with pytest.raises(ImportConflict):
        import_store(target, backup)
    counts = import_store(target, backup, overwrite=True)
    assert counts == {"records": 2, "kv": 1}
    assert target.record_count() == 2
    target.close()

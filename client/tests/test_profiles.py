"""档案注册表与多档案运行时管理测试。"""

from __future__ import annotations

import os

import pytest

from client.profiles import (
    DEVICE_KEY_NAME,
    MAIN_ID,
    DeviceAuthError,
    ProfileConflict,
    ProfileNotFound,
    ProfileStore,
    ProfileValidationError,
    RuntimeManager,
    device_key,
    hash_password,
    has_legacy_data,
    verify_password,
)
from client.tests.support import DEVICE_KEY, make_config
from mhagent.store.db import LocalStore


def test_device_key_is_created_once(tmp_path):
    first = device_key(tmp_path)
    second = device_key(tmp_path)
    assert first == second
    assert len(first) >= 32
    path = tmp_path / DEVICE_KEY_NAME
    assert oct(os.stat(path).st_mode & 0o777) == oct(0o600)


def test_has_legacy_data(tmp_path):
    assert has_legacy_data(tmp_path) is False
    LocalStore(tmp_path, "user-pw").close()
    assert has_legacy_data(tmp_path) is True
    device_key(tmp_path)
    assert has_legacy_data(tmp_path) is False


def test_password_hash_roundtrip():
    stored = hash_password("s3cret-pass")
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password(stored, "s3cret-pass") is True
    assert verify_password(stored, "wrong") is False
    assert verify_password("broken", "s3cret-pass") is False


def test_main_profile_is_created(tmp_path):
    store = ProfileStore(tmp_path)
    items = store.list()
    assert [item["id"] for item in items] == [MAIN_ID]
    assert items[0]["role"] == "main"
    assert "password_hash" not in items[0]


def test_create_and_authenticate_sub_profile(tmp_path):
    store = ProfileStore(tmp_path)
    profile = store.create("孩子", "kid_01", "password-1", note="备用", age_range="12-15")
    assert profile["role"] == "sub"
    assert "password_hash" not in profile
    assert (tmp_path / "profiles" / profile["id"]).is_dir()

    authed = store.authenticate("kid_01", "password-1")
    assert authed["id"] == profile["id"]

    with pytest.raises(DeviceAuthError):
        store.authenticate("kid_01", "wrong-pass")


def test_username_and_password_validation(tmp_path):
    store = ProfileStore(tmp_path)
    with pytest.raises(ProfileValidationError):
        store.create("孩子", "ab", "password-1")
    with pytest.raises(ProfileValidationError):
        store.create("孩子", "kid_02", "short")
    with pytest.raises(ProfileValidationError):
        store.create("  ", "kid_03", "password-1")


def test_duplicate_username_rejected(tmp_path):
    store = ProfileStore(tmp_path)
    store.create("孩子", "kid_01", "password-1")
    with pytest.raises(ProfileConflict):
        store.create("另一个", "kid_01", "password-2")


def test_update_profile_fields(tmp_path):
    store = ProfileStore(tmp_path)
    profile = store.create("孩子", "kid_01", "password-1")
    updated = store.update(
        profile["id"],
        nickname="小明",
        note="备注",
        age_range="6-9",
        username="kid_02",
        password="new-password",
    )
    assert updated["nickname"] == "小明"
    assert updated["username"] == "kid_02"
    assert store.authenticate("kid_02", "new-password") is not None
    with pytest.raises(DeviceAuthError):
        store.authenticate("kid_02", "password-1")
    with pytest.raises(DeviceAuthError):
        store.authenticate("kid_01", "password-1")

    store.update(profile["id"], status="disabled")
    with pytest.raises(DeviceAuthError):
        store.authenticate("kid_02", "new-password")


def test_main_profile_cannot_change_username_or_password(tmp_path):
    store = ProfileStore(tmp_path)
    with pytest.raises(ProfileConflict):
        store.update(MAIN_ID, username="other")
    with pytest.raises(ProfileConflict):
        store.update(MAIN_ID, password="password-1")
    assert store.update(MAIN_ID, nickname="我自己")["nickname"] == "我自己"


def test_delete_sub_profile_removes_directory(tmp_path):
    store = ProfileStore(tmp_path)
    profile = store.create("孩子", "kid_01", "password-1")
    directory = tmp_path / "profiles" / profile["id"]
    LocalStore(directory, DEVICE_KEY).close()
    store.delete(profile["id"])
    assert not directory.exists()
    with pytest.raises(ProfileNotFound):
        store.raw(profile["id"])
    with pytest.raises(ProfileConflict):
        store.delete(MAIN_ID)


def test_disabled_profile_cannot_login(tmp_path):
    store = ProfileStore(tmp_path)
    profile = store.create("孩子", "kid_01", "password-1")
    store.update(profile["id"], status="disabled")
    with pytest.raises(DeviceAuthError):
        store.authenticate("kid_01", "password-1")


def _manager(tmp_path, *, lan=False, data_dir=None):
    config = make_config(tmp_path / "data", lan=lan)
    return RuntimeManager(config, data_dir)


def test_manager_opens_main_runtime(tmp_path):
    manager = _manager(tmp_path)
    try:
        assert manager.status()["logged_in"] is False
        assert manager.runtime_for().profile_id == MAIN_ID
    finally:
        manager.close()


def test_manager_legacy_migration(tmp_path):
    data_dir = tmp_path / "data"
    store = LocalStore(data_dir, "old-pass")
    store.add_record("journal", {"note": "旧数据"})
    store.close()

    manager = _manager(tmp_path, data_dir=data_dir)
    assert manager.legacy_required is True
    manager.migrate_legacy("old-pass")
    assert manager.legacy_required is False
    assert (data_dir / DEVICE_KEY_NAME).exists()
    runtime = manager.runtime_for()
    assert runtime.store.list_records("journal")[0]["payload"]["note"] == "旧数据"
    manager.close()


def test_manager_rejects_wrong_legacy_passphrase(tmp_path):
    data_dir = tmp_path / "data"
    LocalStore(data_dir, "old-pass").close()
    manager = _manager(tmp_path, data_dir=data_dir)
    with pytest.raises(Exception):
        manager.migrate_legacy("wrong-pass")
    assert (data_dir / "meta.json").exists()
    assert manager.legacy_required is True
    manager.close()


def test_manager_create_activate_delete_profile(tmp_path):
    config = make_config(tmp_path / "data")
    manager = RuntimeManager(config)
    try:
        profile = manager.create_profile("孩子", "kid_01", "password-1")
        assert profile["role"] == "sub"

        state = manager.activate(profile["id"])
        assert state["active_profile"]["id"] == profile["id"]

        # 子档案共享主账号登录态,但各有自己的本地库
        sub = manager.runtime_for(profile["id"])
        assert sub.session is manager.main().session
        assert sub.store_dir != manager.main().store_dir

        manager.delete_profile(profile["id"])
        assert manager.status()["active_profile"]["id"] == MAIN_ID
        assert [item["id"] for item in manager.list_profiles()] == [MAIN_ID]
    finally:
        manager.close()


def test_manager_cannot_delete_main(tmp_path):
    manager = _manager(tmp_path)
    try:
        with pytest.raises(ProfileConflict):
            manager.delete_profile(MAIN_ID)
    finally:
        manager.close()


def test_manager_device_login_token(tmp_path):
    manager = _manager(tmp_path, lan=True)
    try:
        manager.create_profile("孩子", "kid_01", "password-1")
        result = manager.device_login("kid_01", "password-1")
        assert result["device_token"]
        profile_id = manager.profile_for_device_token(result["device_token"])
        assert manager.profiles.raw(profile_id)["username"] == "kid_01"

        with pytest.raises(DeviceAuthError):
            manager.profile_for_device_token("bad-token")
        with pytest.raises(DeviceAuthError):
            manager.device_login("kid_01", "wrong")
    finally:
        manager.close()


def test_device_token_expires(tmp_path):
    manager = _manager(tmp_path, lan=True)
    try:
        manager.create_profile("孩子", "kid_01", "password-1")
        result = manager.device_login("kid_01", "password-1")
        # 直接篡改过期时间,验证失效分支。
        manager._device_tokens[result["device_token"]]["expires_at"] = 0
        with pytest.raises(DeviceAuthError):
            manager.profile_for_device_token(result["device_token"])
    finally:
        manager.close()

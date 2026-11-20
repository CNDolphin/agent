"""本地档案(主账号/子账号)注册表与多档案运行时管理。

数据布局::

    data_dir/
      .device_key              # 设备密钥,0600,替代用户口令
      profiles.json            # 档案注册表,0600
      meta.json + mhagent.db   # 主档案(沿用根目录)
      profiles/<id>/           # 子档案,各自独立的加密库

子账号只存在于本机,不注册后端账号;登录态由主档案共享。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from client.runtime import Runtime

DEVICE_KEY_NAME = ".device_key"
PROFILES_NAME = "profiles.json"
PROFILES_DIR = "profiles"
META_NAME = "meta.json"
MAIN_ID = "main"
DIR_MODE = 0o700
FILE_MODE = 0o600
DEVICE_TOKEN_TTL_SECONDS = 24 * 3600
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 64
PBKDF2_ROUNDS = 100000


class ProfileError(Exception):
    """档案相关错误基类。"""


class ProfileValidationError(ProfileError):
    """字段校验失败。"""


class ProfileConflict(ProfileError):
    """用户名重复或不允许的操作。"""


class ProfileNotFound(ProfileError):
    """档案不存在。"""


class DeviceAuthError(ProfileError):
    """局域网设备登录失败或令牌失效。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def has_legacy_data(data_dir) -> bool:
    """旧版口令档案:根目录有 meta.json 且尚无设备密钥。"""
    root = Path(data_dir).expanduser()
    return (root / META_NAME).exists() and not (root / DEVICE_KEY_NAME).exists()


def _write_device_key(root: Path, value: str) -> None:
    root.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    path = root / DEVICE_KEY_NAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(value, encoding="utf-8")
    _chmod(tmp, FILE_MODE)
    tmp.replace(path)
    _chmod(path, FILE_MODE)


def device_key(data_dir) -> str:
    """读取或生成设备密钥,用作所有档案本地库的 passphrase。"""
    root = Path(data_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    _chmod(root, DIR_MODE)
    path = root / DEVICE_KEY_NAME
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if len(value) < 32:
            raise ProfileError("设备密钥损坏")
        return value
    value = secrets.token_hex(32)
    _write_device_key(root, value)
    return value


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(stored: str, password: str) -> bool:
    try:
        algorithm, rounds, salt_hex, digest_hex = str(stored).split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def validate_username(username: str) -> str:
    value = "" if username is None else str(username).strip()
    if not USERNAME_RE.match(value):
        raise ProfileValidationError("登录账号需为 3-32 位字母、数字或下划线")
    return value


def validate_password(password: str) -> str:
    value = "" if password is None else str(password)
    if len(value) < MIN_PASSWORD_LENGTH or len(value) > MAX_PASSWORD_LENGTH:
        raise ProfileValidationError(
            f"密码长度需为 {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} 位"
        )
    return value


def profile_view(profile: dict) -> dict:
    """对外展示:去掉密码哈希。"""
    return {k: v for k, v in profile.items() if k != "password_hash"}


class ProfileStore:
    """`profiles.json` 的读写,所有操作串行化。"""

    def __init__(self, data_dir):
        self.root = Path(data_dir).expanduser()
        self.root.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
        _chmod(self.root, DIR_MODE)
        self._lock = RLock()
        self._ensure_main()

    @property
    def registry_path(self) -> Path:
        return self.root / PROFILES_NAME

    def _load(self) -> dict:
        path = self.registry_path
        if not path.exists():
            return {"version": 1, "profiles": []}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise ProfileError("档案注册表损坏") from exc

    def _save(self, data: dict) -> None:
        path = self.registry_path
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        _chmod(tmp, FILE_MODE)
        tmp.replace(path)
        _chmod(path, FILE_MODE)

    def _ensure_main(self) -> None:
        with self._lock:
            data = self._load()
            if any(p.get("id") == MAIN_ID for p in data["profiles"]):
                return
            data["profiles"].insert(
                0,
                {
                    "id": MAIN_ID,
                    "role": "main",
                    "nickname": "我",
                    "username": "",
                    "note": "",
                    "age_range": "",
                    "phone_mask": "",
                    "status": "active",
                    "created_at": _now(),
                    "updated_at": _now(),
                },
            )
            self._save(data)

    def list(self) -> list[dict]:
        with self._lock:
            return [profile_view(p) for p in self._load()["profiles"]]

    def raw(self, profile_id: str) -> dict:
        with self._lock:
            for profile in self._load()["profiles"]:
                if profile.get("id") == profile_id:
                    return dict(profile)
        raise ProfileNotFound("档案不存在")

    def store_dir(self, profile_id: str) -> Path:
        if profile_id == MAIN_ID:
            return self.root
        self.raw(profile_id)
        return self.root / PROFILES_DIR / profile_id

    def set_phone_mask(self, phone_mask: str) -> None:
        with self._lock:
            data = self._load()
            for profile in data["profiles"]:
                if profile.get("id") == MAIN_ID:
                    profile["phone_mask"] = str(phone_mask or "")
                    profile["updated_at"] = _now()
                    break
            self._save(data)

    def create(
        self,
        nickname: str,
        username: str,
        password: str,
        *,
        note: str = "",
        age_range: str = "",
    ) -> dict:
        name = "" if nickname is None else str(nickname).strip()
        if not name:
            raise ProfileValidationError("昵称不能为空")
        account = validate_username(username)
        secret = validate_password(password)
        with self._lock:
            data = self._load()
            if any(p.get("username") == account for p in data["profiles"]):
                raise ProfileConflict("登录账号已存在")
            profile = {
                "id": f"p_{secrets.token_hex(4)}",
                "role": "sub",
                "nickname": name,
                "username": account,
                "password_hash": hash_password(secret),
                "note": str(note or ""),
                "age_range": str(age_range or ""),
                "phone_mask": "",
                "status": "active",
                "created_at": _now(),
                "updated_at": _now(),
            }
            directory = self.root / PROFILES_DIR / profile["id"]
            directory.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
            _chmod(directory, DIR_MODE)
            data["profiles"].append(profile)
            self._save(data)
            return profile_view(profile)

    def update(self, profile_id: str, **fields) -> dict:
        with self._lock:
            data = self._load()
            current = None
            for profile in data["profiles"]:
                if profile.get("id") == profile_id:
                    current = profile
                    break
            if current is None:
                raise ProfileNotFound("档案不存在")
            if fields.get("nickname") is not None:
                name = str(fields["nickname"]).strip()
                if not name:
                    raise ProfileValidationError("昵称不能为空")
                current["nickname"] = name
            if fields.get("note") is not None:
                current["note"] = str(fields["note"])
            if fields.get("age_range") is not None:
                current["age_range"] = str(fields["age_range"])
            if fields.get("username") is not None:
                if current["role"] == "main":
                    raise ProfileConflict("主账号不能修改登录账号")
                account = validate_username(fields["username"])
                if any(
                    p.get("username") == account and p.get("id") != profile_id
                    for p in data["profiles"]
                ):
                    raise ProfileConflict("登录账号已存在")
                current["username"] = account
            if fields.get("password") is not None:
                if current["role"] == "main":
                    raise ProfileConflict("主账号密码请通过手机验证码重置")
                current["password_hash"] = hash_password(validate_password(fields["password"]))
            if fields.get("status") is not None:
                status = str(fields["status"])
                if status not in ("active", "disabled"):
                    raise ProfileValidationError("状态只能是 active 或 disabled")
                current["status"] = status
            current["updated_at"] = _now()
            self._save(data)
            return profile_view(current)

    def delete(self, profile_id: str) -> None:
        if profile_id == MAIN_ID:
            raise ProfileConflict("主账号不能删除")
        with self._lock:
            data = self._load()
            target = next((p for p in data["profiles"] if p.get("id") == profile_id), None)
            if target is None:
                raise ProfileNotFound("档案不存在")
            data["profiles"] = [p for p in data["profiles"] if p.get("id") != profile_id]
            self._save(data)
            directory = self.root / PROFILES_DIR / profile_id
            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)

    def authenticate(self, username: str, password: str) -> dict:
        if username is None or password is None:
            raise DeviceAuthError("账号或密码错误")
        account = str(username).strip()
        secret = str(password)
        with self._lock:
            for profile in self._load()["profiles"]:
                if profile.get("role") != "sub" or profile.get("username") != account:
                    continue
                if profile.get("status") != "active":
                    raise DeviceAuthError("该账号已停用")
                if not verify_password(profile.get("password_hash", ""), secret):
                    raise DeviceAuthError("账号或密码错误")
                return profile_view(profile)
        raise DeviceAuthError("账号或密码错误")


class RuntimeManager:
    """多档案运行时:主账号认证、档案 CRUD、局域网设备令牌。"""

    def __init__(
        self,
        config: dict,
        data_dir=None,
        *,
        gateway_factory=None,
        notifier_factory=None,
        clock=None,
    ):
        self.config = config
        self.data_dir = Path(data_dir or config["storage"]["data_dir"]).expanduser()
        self._gateway_factory = gateway_factory
        self._notifier_factory = notifier_factory
        self._clock = clock
        self._lock = RLock()
        self._started_at = time.time()

        self._legacy = has_legacy_data(self.data_dir)
        self._device_key = None if self._legacy else device_key(self.data_dir)
        self.profiles: ProfileStore | None = None if self._legacy else ProfileStore(self.data_dir)
        self._active_id = MAIN_ID
        self._runtimes: dict[str, Runtime] = {}
        self._device_tokens: dict[str, dict] = {}
        if not self._legacy:
            self._open_runtime(MAIN_ID)

    # ---- 生命周期 ----
    @property
    def legacy_required(self) -> bool:
        return self._legacy

    @property
    def lan_enabled(self) -> bool:
        return bool(self.config.get("client", {}).get("lan", {}).get("enabled", False))

    def migrate_legacy(self, passphrase) -> dict:
        value = "" if passphrase is None else str(passphrase)
        if not value:
            raise ProfileValidationError("旧口令不能为空")
        with self._lock:
            if not self._legacy:
                return self.status()
            new_key = secrets.token_hex(32)
            from mhagent.store.db import LocalStore

            store = LocalStore(self.data_dir, value)
            try:
                store.rekey(new_key)
            finally:
                store.close()
            _write_device_key(self.data_dir, new_key)
            self._device_key = new_key
            self._legacy = False
            self.profiles = ProfileStore(self.data_dir)
            self._open_runtime(MAIN_ID)
            return self.status()

    def close(self) -> None:
        with self._lock:
            for runtime in self._runtimes.values():
                runtime.close()
            self._runtimes.clear()
            self._device_tokens.clear()

    # ---- 运行时 ----
    def _open_runtime(self, profile_id: str, *, shared_session=None) -> Runtime:
        cached = self._runtimes.get(profile_id)
        if cached is not None:
            return cached
        profile = self.profiles.raw(profile_id)
        archive = None
        if profile_id != MAIN_ID:
            # 子档案不单独归档,只读主档案里分配给自己的报告
            archive = self._open_runtime(MAIN_ID).reports
        runtime = Runtime(
            self.config,
            self.profiles.store_dir(profile_id),
            profile=profile,
            device_key=self._device_key,
            shared_session=shared_session,
            gateway_factory=self._gateway_factory,
            notifier_factory=self._notifier_factory,
            clock=self._clock,
            report_archive=archive,
            profiles_provider=self.profiles.list,
        )
        runtime.open()
        self._runtimes[profile_id] = runtime
        return runtime

    def main(self) -> Runtime:
        if self._legacy:
            raise ProfileError("请先升级旧版本地数据")
        with self._lock:
            return self._open_runtime(MAIN_ID)

    def runtime_for(self, profile_id: str | None = None) -> Runtime:
        if self._legacy:
            raise ProfileError("请先升级旧版本地数据")
        target = profile_id or self._active_id
        with self._lock:
            if target == MAIN_ID:
                return self._open_runtime(MAIN_ID)
            shared = self._open_runtime(MAIN_ID).session
            return self._open_runtime(target, shared_session=shared)

    def activate(self, profile_id: str) -> dict:
        with self._lock:
            profile = self.profiles.raw(profile_id)
            if profile.get("status") != "active":
                raise ProfileConflict("该档案已停用")
            self._active_id = profile_id
            return self.status()

    @property
    def active_profile(self) -> dict:
        return self.profiles.raw(self._active_id)

    # ---- 主账号认证 ----
    def status(self) -> dict:
        with self._lock:
            if self._legacy:
                return {
                    "legacy_required": True,
                    "logged_in": False,
                    "phone_mask": None,
                    "active_profile": None,
                    "profiles": [],
                    "consent_version": None,
                    "emergency_authorized": False,
                    "lan_enabled": self.lan_enabled,
                }
            main = self._open_runtime(MAIN_ID)
            active = self.runtime_for(self._active_id)
            state = active.status()
            return {
                "legacy_required": False,
                "logged_in": main.logged_in,
                "phone_mask": main.phone_mask,
                "active_profile": profile_view(self.active_profile),
                "profiles": self.profiles.list(),
                "consent_version": state["consent_version"],
                "emergency_authorized": state["emergency_authorized"],
                "lan_enabled": self.lan_enabled,
            }

    def send_code(self, phone) -> dict:
        return self.main().send_code(phone)

    def login_password(self, phone, password, *, force: bool = False) -> dict:
        with self._lock:
            result = self.main().login_password(phone, password, force=force)
            self.profiles.set_phone_mask(result["phone_mask"])
            return result

    def register(self, phone, code, password, *, force: bool = False) -> dict:
        with self._lock:
            result = self.main().register(phone, code, password, force=force)
            self.profiles.set_phone_mask(result["phone_mask"])
            return result

    def reset_password(self, phone, code, new_password) -> None:
        self.main().reset_password(phone, code, new_password)

    def logout(self) -> dict:
        return self.main().logout()

    def dev_sms_code(self, phone) -> str:
        return self.main().dev_sms_code(phone)

    # ---- 档案管理 ----
    def list_profiles(self) -> list[dict]:
        return self.profiles.list()

    def create_profile(self, nickname, username, password, *, note="", age_range="") -> dict:
        return self.profiles.create(nickname, username, password, note=note, age_range=age_range)

    def update_profile(self, profile_id: str, **fields) -> dict:
        return self.profiles.update(profile_id, **fields)

    def delete_profile(self, profile_id: str) -> None:
        if profile_id == MAIN_ID:
            raise ProfileConflict("主账号不能删除")
        with self._lock:
            if self._active_id == profile_id:
                self._active_id = MAIN_ID
            runtime = self._runtimes.pop(profile_id, None)
            if runtime is not None:
                runtime.close()
            self.profiles.delete(profile_id)

    # ---- 局域网设备令牌 ----
    def device_login(self, username, password) -> dict:
        if self._legacy:
            raise ProfileError("请先升级旧版本地数据")
        profile = self.profiles.authenticate(username, password)
        token = secrets.token_hex(32)
        with self._lock:
            self._device_tokens[token] = {
                "profile_id": profile["id"],
                "expires_at": time.time() + DEVICE_TOKEN_TTL_SECONDS,
            }
        return {"device_token": token, "profile": profile}

    def profile_for_device_token(self, token) -> str:
        with self._lock:
            entry = self._device_tokens.get(str(token or ""))
            if entry is None or entry["expires_at"] <= time.time():
                self._device_tokens.pop(str(token or ""), None)
                raise DeviceAuthError("设备登录已失效,请重新登录")
            profile = self.profiles.raw(entry["profile_id"])
            if profile.get("status") != "active":
                raise DeviceAuthError("该账号已停用")
            return profile["id"]

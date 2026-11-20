"""在线更新:检查版本、下载内容包、校验并应用到本地内容目录。

服务端只负责分发,客户端不会自动替换正在运行的代码:
- 内容包(skills/quiz/rules/scales)由用户确认后下载并落盘;
- 客户端程序包(app)只下载到 ``updates/app/<version>`` 并提示用户手动安装。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from mhagent import __version__, safety

from mhagent.content_paths import CONTENT_DIR_ENV

MAX_FILES = 500
MAX_TOTAL_BYTES = 100 * 1024 * 1024
AVAILABLE_KEY = "updates.available"

CONTENT_KINDS = ("skills", "quiz", "rules", "scales")


class UpdateError(RuntimeError):
    """更新检查或应用失败。"""


def _platform() -> str:
    if sys.platform == "darwin":
        return "macos"
    if os.name == "nt":
        return "windows"
    return "all"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class UpdateService:
    """单设备的内容更新服务,按档案串行调用。"""

    def __init__(self, gateway, store, data_dir: Path, *, lock=None, clock=None):
        self.gateway = gateway
        self.store = store
        self.data_dir = Path(data_dir).expanduser()
        self.root = self.data_dir / "content"
        self._lock = lock or threading.RLock()
        self._clock = clock or _now

    # ---- 查询 ----

    def status(self) -> dict:
        return {
            "app_version": __version__,
            "platform": _platform(),
            "applied": self._applied(),
            "available": self._available(),
        }

    def check(self) -> dict:
        with self._lock:
            items = self.gateway.latest_contents(_platform())
            applied = self._applied()
            available = [
                item for item in items
                if str(item.get("kind") or "") in CONTENT_KINDS + ("app",)
                and applied.get(str(item.get("kind"))) != str(item.get("version"))
            ]
            self.store.kv_set(AVAILABLE_KEY, available)
            return {
                "app_version": __version__,
                "platform": _platform(),
                "applied": applied,
                "available": available,
            }

    # ---- 更新 ----

    def download(self, release_id: int) -> dict:
        with self._lock:
            item = self._find(release_id)
            if item is None:
                self.check()
                item = self._find(release_id)
            if item is None:
                raise UpdateError("更新信息已失效,请重新检查更新")

            kind = str(item.get("kind") or "")
            version = str(item.get("version") or "")
            filename, content, digest, header_version = self.gateway.download_content(release_id)
            actual = hashlib.sha256(content).hexdigest()
            if digest and digest.lower() != actual:
                raise UpdateError("内容包校验失败(SHA256 不一致)")
            if header_version and version and header_version != version:
                raise UpdateError("内容包版本与列表不一致")

            if kind == "app":
                return self._save_app(content, filename, version)

            if kind not in CONTENT_KINDS:
                raise UpdateError("不支持的内容类型")

            dest = self.root / kind / version
            self._install(content, dest, kind, version)
            self._set_active(kind, version)
            if kind == "rules":
                safety.reload_rules()
            try:
                self.check()
            except Exception:  # noqa: BLE001 - 网络失败不影响已完成的更新
                pass
            return {
                "kind": kind,
                "version": version,
                "path": str(dest),
                "restart_required": kind != "skills",
                "manual": False,
            }

    # ---- 内部 ----

    def _available(self) -> list[dict]:
        raw = self.store.kv_get(AVAILABLE_KEY, [])
        return raw if isinstance(raw, list) else []

    def _find(self, release_id) -> dict | None:
        try:
            target = int(release_id)
        except (TypeError, ValueError):
            return None
        for item in self._available():
            if isinstance(item, dict) and int(item.get("id", 0)) == target:
                return item
        return None

    def _applied(self) -> dict:
        result: dict[str, str] = {}
        for kind in CONTENT_KINDS + ("app",):
            meta = self.root / kind / "active.json"
            if not meta.is_file():
                continue
            try:
                version = json.loads(meta.read_text(encoding="utf-8")).get("version")
            except (OSError, ValueError):
                continue
            if version:
                result[kind] = str(version)
        return result

    def _install(self, content: bytes, dest: Path, kind: str, version: str) -> None:
        tmp = dest.with_name(f".{dest.name}-{uuid.uuid4().hex[:8]}.tmp")
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        try:
            self._extract(content, tmp)
            self._verify_manifest(tmp, kind, version)
            if dest.exists():
                shutil.rmtree(dest)
            os.replace(tmp, dest)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

    def _extract(self, content: bytes, tmp: Path) -> None:
        try:
            archive = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile as exc:
            raise UpdateError("内容包不是合法的 zip 文件") from exc
        with archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            if len(infos) > MAX_FILES:
                raise UpdateError("内容包文件数超过限制")
            total = 0
            for info in infos:
                name = info.filename.replace("\\", "/")
                pure = PurePosixPath(name)
                if pure.is_absolute() or ".." in pure.parts:
                    raise UpdateError("内容包包含非法路径")
                total += info.file_size
                if total > MAX_TOTAL_BYTES:
                    raise UpdateError("内容包解压后过大")
                target = tmp / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    def _verify_manifest(self, tmp: Path, kind: str, version: str) -> None:
        manifest_path = tmp / "manifest.json"
        if not manifest_path.is_file():
            raise UpdateError("内容包缺少 manifest.json")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise UpdateError("manifest.json 不是合法 JSON") from exc
        if manifest.get("kind") != kind or manifest.get("version") != version:
            raise UpdateError("manifest 与更新版本不一致")
        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            raise UpdateError("manifest 未声明任何文件")
        for entry in files:
            if not isinstance(entry, dict):
                raise UpdateError("manifest 文件项非法")
            raw_path = str(entry.get("path") or "")
            pure = PurePosixPath(raw_path.replace("\\", "/"))
            if not raw_path or pure.is_absolute() or ".." in pure.parts:
                raise UpdateError("manifest 包含非法路径")
            file_path = tmp / raw_path
            if not file_path.is_file():
                raise UpdateError(f"manifest 声明的文件不存在: {raw_path}")
            digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
            if digest.lower() != str(entry.get("sha256") or "").lower():
                raise UpdateError(f"文件校验失败: {raw_path}")

    def _now_stamp(self) -> str:
        value = self._clock()
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    def _set_active(self, kind: str, version: str) -> None:
        base = self.root / kind
        base.mkdir(parents=True, exist_ok=True)
        tmp = base / f".active-{uuid.uuid4().hex[:8]}.json"
        tmp.write_text(
            json.dumps({"version": version, "applied_at": self._now_stamp()}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, base / "active.json")

    def _save_app(self, content: bytes, filename: str, version: str) -> dict:
        target_dir = self.data_dir / "updates" / "app" / version
        target_dir.mkdir(parents=True, exist_ok=True)
        name = Path(filename).name if filename else f"app-{version}.zip"
        path = target_dir / name
        path.write_bytes(content)
        base = self.root / "app"
        base.mkdir(parents=True, exist_ok=True)
        (base / "active.json").write_text(
            json.dumps({"version": version, "downloaded_at": self._now_stamp(), "path": str(path)},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        return {
            "kind": "app",
            "version": version,
            "path": str(path),
            "restart_required": False,
            "manual": True,
        }

    @staticmethod
    def set_content_root(data_dir: Path) -> None:
        """把内容目录指向主档案的 data_dir/content。"""
        os.environ[CONTENT_DIR_ENV] = str(Path(data_dir).expanduser() / "content")

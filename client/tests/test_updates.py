import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from client.updates import UpdateError, UpdateService
from mhagent import content_paths


class FakeStore:
    def __init__(self):
        self.data = {}

    def kv_get(self, key, default=None):
        return self.data.get(key, default)

    def kv_set(self, key, value):
        self.data[key] = value


def build_zip(kind, version, files: dict[str, bytes]) -> bytes:
    manifest = {"kind": kind, "version": version, "files": []}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            manifest["files"].append(
                {"path": name, "sha256": hashlib.sha256(data).hexdigest()}
            )
            zf.writestr(name, data)
        zf.writestr("manifest.json", json.dumps(manifest))
    return buf.getvalue()


class FakeGateway:
    def __init__(self, latest, packages):
        self.latest = latest
        self.packages = packages

    def latest_contents(self, platform):
        return self.latest

    def download_content(self, release_id):
        filename, content, version, digest = self.packages[int(release_id)]
        return filename, content, digest, version


def make_service(tmp_path, latest, packages):
    return UpdateService(
        FakeGateway(latest, packages),
        FakeStore(),
        tmp_path,
        clock=lambda: "2026-11-19T00:00:00Z",
    )


def test_check_filters_applied_versions(tmp_path, monkeypatch):
    monkeypatch.setenv(content_paths.CONTENT_DIR_ENV, str(tmp_path / "content"))
    active = tmp_path / "content" / "skills" / "active.json"
    active.parent.mkdir(parents=True)
    active.write_text(json.dumps({"version": "1.0.0"}), encoding="utf-8")

    latest = [
        {"id": 1, "kind": "skills", "version": "1.0.0"},
        {"id": 2, "kind": "quiz", "version": "2.0.0"},
        {"id": 3, "kind": "unknown", "version": "1.0.0"},
    ]
    service = make_service(tmp_path, latest, {})
    result = service.check()
    assert [item["id"] for item in result["available"]] == [2]
    assert result["applied"]["skills"] == "1.0.0"


def test_download_applies_skills_and_resolves(tmp_path, monkeypatch):
    monkeypatch.setenv(content_paths.CONTENT_DIR_ENV, str(tmp_path / "content"))
    content = build_zip(
        "skills", "1.0.1", {"skills/emotion/SKILL.md": b"# emotion\nv1.0.1"}
    )
    digest = hashlib.sha256(content).hexdigest()
    service = make_service(
        tmp_path,
        [{"id": 10, "kind": "skills", "version": "1.0.1"}],
        {10: ("skills-1.0.1.zip", content, "1.0.1", digest)},
    )
    service.check()
    result = service.download(10)

    assert result["restart_required"] is False
    target = tmp_path / "content" / "skills" / "1.0.1" / "skills" / "emotion" / "SKILL.md"
    assert target.is_file()
    assert target.read_text(encoding="utf-8").strip() == "# emotion\nv1.0.1"
    assert content_paths.skills_dir() == tmp_path / "content" / "skills" / "1.0.1" / "skills"
    assert service.status()["applied"]["skills"] == "1.0.1"


def test_download_rejects_bad_checksum(tmp_path, monkeypatch):
    monkeypatch.setenv(content_paths.CONTENT_DIR_ENV, str(tmp_path / "content"))
    content = build_zip("quiz", "1.0.0", {"mi_quiz.json": b"{}"})
    service = make_service(
        tmp_path,
        [{"id": 20, "kind": "quiz", "version": "1.0.0"}],
        {20: ("quiz.zip", content, "1.0.0", "0" * 64)},
    )
    service.check()
    with pytest.raises(UpdateError):
        service.download(20)
    assert not (tmp_path / "content" / "quiz" / "1.0.0").exists()


def test_download_rejects_zip_slip(tmp_path, monkeypatch):
    monkeypatch.setenv(content_paths.CONTENT_DIR_ENV, str(tmp_path / "content"))
    content = build_zip("rules", "1.0.0", {"../evil.json": b"{}"})
    digest = hashlib.sha256(content).hexdigest()
    service = make_service(
        tmp_path,
        [{"id": 30, "kind": "rules", "version": "1.0.0"}],
        {30: ("rules.zip", content, "1.0.0", digest)},
    )
    service.check()
    with pytest.raises(UpdateError):
        service.download(30)
    assert not (tmp_path / "content" / "rules" / "1.0.0").exists()


def test_app_package_only_saved(tmp_path, monkeypatch):
    monkeypatch.setenv(content_paths.CONTENT_DIR_ENV, str(tmp_path / "content"))
    content = build_zip("app", "0.2.0", {"app/main.py": b"print('hi')"})
    digest = hashlib.sha256(content).hexdigest()
    service = make_service(
        tmp_path,
        [{"id": 40, "kind": "app", "version": "0.2.0"}],
        {40: ("agent-0.2.0.zip", content, "0.2.0", digest)},
    )
    service.check()
    result = service.download(40)
    assert result["manual"] is True
    path = Path(result["path"])
    assert path.is_file()
    assert path.parent == tmp_path / "updates" / "app" / "0.2.0"
    assert service.status()["applied"]["app"] == "0.2.0"


def test_resolve_falls_back_without_content(tmp_path, monkeypatch):
    monkeypatch.delenv(content_paths.CONTENT_DIR_ENV, raising=False)
    default = tmp_path / "mi_quiz.json"
    default.write_text("{}", encoding="utf-8")
    assert content_paths.resolve("quiz", "mi_quiz.json", default) == default
    assert content_paths.active_dir("quiz") is None

from pathlib import Path

import pytest

from mhagent.skill_crypto import HEADER_SIZE, decrypt_file, encrypt_dir
from mhagent.skill_loader import list_skills, load_skill, route

SKILL_TEMPLATE = """---
name: {name}
description: {description}
triggers:
  - {trigger}
---

{body}
"""


def make_skills(root: Path) -> None:
    (root / "assessment").mkdir(parents=True)
    (root / "assessment" / "SKILL.md").write_text(
        SKILL_TEMPLATE.format(
            name="assessment",
            description="量表筛查",
            trigger="量表",
            body="筛查提示:结果仅供参考,不是诊断。",
        ),
        encoding="utf-8",
    )
    (root / "custom").mkdir(parents=True)
    (root / "custom" / "SKILL.md").write_text(
        SKILL_TEMPLATE.format(
            name="custom",
            description="自定义技能",
            trigger="暗号",
            body="这是自定义技能的正文内容。",
        ),
        encoding="utf-8",
    )
    (root / "custom" / "reference.md").write_text("参考附件内容 ABC123", encoding="utf-8")


def test_encrypt_decrypt_roundtrip(tmp_path):
    src = tmp_path / "skills"
    make_skills(src)
    out = tmp_path / "skills.enc"

    stats = encrypt_dir(src, out)
    assert stats["skills"] == ["assessment", "custom"]
    assert stats["files"] == 3

    original = {
        path.relative_to(src).as_posix(): path.read_bytes()
        for path in src.rglob("*")
        if path.is_file()
    }
    assert decrypt_file(out) == original


def test_ciphertext_does_not_leak_plaintext(tmp_path):
    src = tmp_path / "skills"
    make_skills(src)
    out = tmp_path / "skills.enc"
    encrypt_dir(src, out)

    blob = out.read_bytes()
    body = blob[HEADER_SIZE:]  # 头部是固定 magic,不含明文内容
    for marker in (b"SKILL", b"assessment", "筛查提示".encode("utf-8"), b"ABC123"):
        assert marker not in body


def test_tampered_bundle_rejected(tmp_path):
    src = tmp_path / "skills"
    make_skills(src)
    out = tmp_path / "skills.enc"
    encrypt_dir(src, out)

    blob = bytearray(out.read_bytes())
    blob[-1] ^= 0x01
    out.write_bytes(bytes(blob))

    with pytest.raises(ValueError, match="损坏"):
        decrypt_file(out)


def test_loader_reads_encrypted_source(tmp_path):
    src = tmp_path / "skills"
    make_skills(src)
    out = tmp_path / "skills.enc"
    encrypt_dir(src, out)

    metas = list_skills(out)
    assert [meta.name for meta in metas] == ["assessment", "custom"]
    assert load_skill("custom", out) == "这是自定义技能的正文内容。\n"
    assert route("说个暗号", out) == "custom"
    with pytest.raises(KeyError):
        load_skill("assessment", tmp_path / "missing.enc")


def test_loader_falls_back_to_empty_on_broken_bundle(tmp_path):
    broken = tmp_path / "broken.enc"
    broken.write_bytes(b"not-a-bundle")

    assert list_skills(broken) == []
    with pytest.raises(KeyError):
        load_skill("assessment", broken)


def test_empty_source_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(ValueError, match="SKILL.md"):
        encrypt_dir(empty, tmp_path / "skills.enc")

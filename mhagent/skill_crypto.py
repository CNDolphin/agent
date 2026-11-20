"""技能密文包:把整个 skills 目录加密为单文件。

格式(magic + 版本 + nonce + AES-256-GCM 密文),明文载荷是内存中的 ZIP,
条目为相对路径(如 ``assessment/SKILL.md``),便于将来加入二进制附件。

注意:内置密钥只是提高逆向门槛的混淆手段,不能替代服务端密钥托管。
"""

from __future__ import annotations

import functools
import hashlib
import io
import os
import zipfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"MHASKILL"
VERSION = 1
NONCE_SIZE = 12
HEADER_SIZE = len(MAGIC) + 1 + NONCE_SIZE

# 分段常量仅用于抬高直接读取密钥的门槛,不具备真正的保密性。
_SEED_PARTS = (
    "mhagent",
    "skill-bundle",
    "v1",
    "local-agent",
    "2026",
)
_SALT = bytes.fromhex("6d686167656e742d736b696c6c2d62756e646c652d7631")


def encrypted_path() -> Path:
    """返回默认密文包路径。"""
    return Path(__file__).resolve().parent / "data" / "skills.enc"


@functools.lru_cache(maxsize=1)
def _key() -> bytes:
    material = "|".join(_SEED_PARTS).encode("utf-8")
    return hashlib.scrypt(material, salt=_SALT, n=2**14, r=8, p=1, dklen=32)


def _pack(src_dir: Path) -> tuple[bytes, list[str]]:
    """把目录下所有文件打进内存 ZIP;返回 (zip 字节, 相对路径列表)。"""
    buffer = io.BytesIO()
    names: list[str] = []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(src_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(src_dir).as_posix()
            archive.write(path, relative)
            names.append(relative)
    return buffer.getvalue(), names


def _encrypt_bytes(payload: bytes) -> bytes:
    nonce = os.urandom(NONCE_SIZE)
    ciphertext = AESGCM(_key()).encrypt(nonce, payload, MAGIC)
    return MAGIC + bytes([VERSION]) + nonce + ciphertext


def encrypt_dir(src_dir, out_file) -> dict:
    """把 src_dir 下所有文件加密写入 out_file;返回统计信息。"""
    src = Path(src_dir)
    out = Path(out_file)
    if not src.is_dir():
        raise ValueError(f"技能目录不存在: {src}")
    if not any(src.glob("*/SKILL.md")):
        raise ValueError(f"技能目录为空或缺少 SKILL.md: {src}")

    payload, names = _pack(src)
    blob = _encrypt_bytes(payload)

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_bytes(blob)
    tmp.replace(out)

    skills = sorted({Path(name).parts[0] for name in names if len(Path(name).parts) > 1})
    return {"skills": skills, "files": len(names), "bytes": len(blob)}


def decrypt_file(path) -> dict[str, bytes]:
    """解密密文包,返回 {相对路径: 内容};格式错误或篡改时抛 ValueError。"""
    blob = Path(path).read_bytes()
    if len(blob) <= HEADER_SIZE or not blob.startswith(MAGIC):
        raise ValueError("技能包格式错误")
    version = blob[len(MAGIC)]
    if version != VERSION:
        raise ValueError(f"技能包版本不支持: {version}")
    nonce = blob[len(MAGIC) + 1 : HEADER_SIZE]
    try:
        payload = AESGCM(_key()).decrypt(nonce, blob[HEADER_SIZE:], MAGIC)
    except InvalidTag as exc:
        raise ValueError("技能包已损坏或密钥不匹配") from exc
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}

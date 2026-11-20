"""基于口令的本地加密工具。

口令通过 scrypt(n=2**15, r=8, p=1)派生 32 字节密钥,再交给 Fernet 做对称加密。
密文每次不同(Fernet 内部随机 IV),口令错误或密文被篡改都会抛 `DecryptError`。
"""

from __future__ import annotations

import base64
import hashlib
import secrets

from cryptography.fernet import Fernet, InvalidToken

SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
MAX_MEM = 64 * 1024 * 1024


class CryptoError(Exception):
    """加解密相关错误。"""


class DecryptError(CryptoError):
    """口令错误或密文损坏。"""


def derive_key(passphrase: str, salt: bytes, *, n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P) -> bytes:
    """由口令与 salt 派生 32 字节密钥。相同输入必定得到相同输出。"""
    if not isinstance(passphrase, str) or not passphrase:
        raise ValueError("passphrase must be a non-empty string")
    if not isinstance(salt, (bytes, bytearray)) or not salt:
        raise ValueError("salt must be non-empty bytes")
    return hashlib.scrypt(
        passphrase.encode("utf-8"),
        salt=bytes(salt),
        n=n,
        r=r,
        p=p,
        dklen=32,
        maxmem=MAX_MEM,
    )


def new_salt() -> bytes:
    return secrets.token_bytes(SALT_BYTES)


def _fernet(key: bytes) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(plaintext: str | bytes, passphrase: str, salt: bytes) -> bytes:
    """加密明文,返回 Fernet 密文(每次不同)。"""
    if isinstance(plaintext, str):
        data = plaintext.encode("utf-8")
    elif isinstance(plaintext, (bytes, bytearray)):
        data = bytes(plaintext)
    else:
        raise TypeError("plaintext must be str or bytes")
    return _fernet(derive_key(passphrase, salt)).encrypt(data)


def decrypt(token: bytes, passphrase: str, salt: bytes) -> bytes:
    """解密 Fernet 密文;口令错误或密文被篡改抛 `DecryptError`。"""
    try:
        return _fernet(derive_key(passphrase, salt)).decrypt(token)
    except (InvalidToken, TypeError, ValueError) as exc:
        raise DecryptError("wrong passphrase or corrupted ciphertext") from exc


class Cipher:
    """缓存派生密钥的加解密器,避免每次操作都跑一遍 scrypt。"""

    def __init__(self, passphrase: str, salt: bytes):
        if not isinstance(passphrase, str) or not passphrase:
            raise ValueError("passphrase must be a non-empty string")
        if not isinstance(salt, (bytes, bytearray)) or not salt:
            raise ValueError("salt must be non-empty bytes")
        self._fernet = _fernet(derive_key(passphrase, salt))

    def encrypt_bytes(self, data: bytes) -> bytes:
        return self._fernet.encrypt(data)

    def decrypt_bytes(self, token: bytes) -> bytes:
        try:
            return self._fernet.decrypt(token)
        except (InvalidToken, TypeError, ValueError) as exc:
            raise DecryptError("wrong passphrase or corrupted ciphertext") from exc

    def encrypt_text(self, text: str) -> bytes:
        return self.encrypt_bytes(text.encode("utf-8"))

    def decrypt_text(self, token: bytes) -> str:
        return self.decrypt_bytes(token).decode("utf-8")

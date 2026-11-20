import os
from pathlib import Path

import pytest

from mhagent.store.crypto import DecryptError, derive_key, encrypt, decrypt


def test_derive_key_deterministic():
    salt = b"0123456789abcdef"
    assert derive_key("pw", salt) == derive_key("pw", salt)
    assert len(derive_key("pw", salt)) == 32
    assert derive_key("pw", b"different-salt-") != derive_key("pw", salt)


def test_encrypt_roundtrip_and_random():
    salt = b"0123456789abcdef"
    token1 = encrypt("悄悄话", "pw", salt)
    token2 = encrypt("悄悄话", "pw", salt)
    assert token1 != token2
    assert decrypt(token1, "pw", salt) == "悄悄话".encode("utf-8")
    assert decrypt(token2, "pw", salt) == "悄悄话".encode("utf-8")
    assert encrypt(b"bytes", "pw", salt) != encrypt(b"bytes", "pw", salt)


def test_wrong_passphrase():
    salt = b"0123456789abcdef"
    token = encrypt("secret", "right", salt)
    with pytest.raises(DecryptError):
        decrypt(token, "wrong", salt)


def test_tampered_ciphertext():
    salt = b"0123456789abcdef"
    token = encrypt("secret", "pw", salt)
    tampered = token[:-1] + (b"A" if token[-1:] != b"A" else b"B")
    with pytest.raises(DecryptError):
        decrypt(tampered, "pw", salt)


def test_empty_passphrase():
    with pytest.raises(ValueError):
        derive_key("", b"0123456789abcdef")
    with pytest.raises(ValueError):
        encrypt("x", "", b"0123456789abcdef")
    with pytest.raises(ValueError):
        derive_key("pw", b"")

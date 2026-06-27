from __future__ import annotations

import pytest

from portal.vault.crypto import (
    InvalidKey,
    decrypt_master_key,
    decrypt_token,
    derive_wrap_key,
    encrypt_master_key,
    encrypt_token,
    generate_master_key,
    generate_recovery_code,
    generate_salt,
)

_KEK = bytes.fromhex("0" * 64)


def test_generate_master_key_32_bytes():
    k = generate_master_key()
    assert len(k) == 32 and k != generate_master_key()


def test_generate_salt_16_bytes():
    s = generate_salt()
    assert len(s) == 16 and s != generate_salt()


def test_generate_recovery_code_format():
    code = generate_recovery_code()
    parts = code.split("-")
    assert len(parts) == 6 and all(len(p) == 4 for p in parts)


def test_derive_wrap_key_deterministic():
    salt = generate_salt()
    assert derive_wrap_key("123456", salt, _KEK) == derive_wrap_key("123456", salt, _KEK)


def test_derive_wrap_key_pin_sensitive():
    salt = generate_salt()
    assert derive_wrap_key("123456", salt, _KEK) != derive_wrap_key("654321", salt, _KEK)


def test_derive_wrap_key_kek_sensitive():
    salt = generate_salt()
    kek2 = bytes(range(32))
    assert derive_wrap_key("123456", salt, _KEK) != derive_wrap_key("123456", salt, kek2)


def test_encrypt_decrypt_master_key_roundtrip():
    mk = generate_master_key()
    salt = generate_salt()
    wk = derive_wrap_key("123456", salt, _KEK)
    assert decrypt_master_key(encrypt_master_key(mk, wk), wk) == mk


def test_decrypt_master_key_wrong_key_raises():
    mk = generate_master_key()
    salt = generate_salt()
    wk = derive_wrap_key("123456", salt, _KEK)
    wrong = derive_wrap_key("000000", salt, _KEK)
    with pytest.raises(InvalidKey):
        decrypt_master_key(encrypt_master_key(mk, wk), wrong)


def test_encrypt_decrypt_token_roundtrip():
    mk = generate_master_key()
    assert decrypt_token(encrypt_token("hrpv_1_abc", mk), mk) == "hrpv_1_abc"

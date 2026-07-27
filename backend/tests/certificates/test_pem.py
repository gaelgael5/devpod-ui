"""Normalisation des PEM (clés/certs collés depuis Windows : CRLF, newline final).

`error in libcrypto` côté OpenSSH = PEM à fins de ligne CRLF ou sans newline
final. Les PEM importés (collés) doivent être normalisés avant stockage ET à la
matérialisation sur disque (répare aussi les entrées déjà stockées sales).
"""

from __future__ import annotations

from portal.certificates.pem import normalize_pem

_CLEAN = "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\nBBBB\n-----END OPENSSH PRIVATE KEY-----\n"


def test_crlf_converted_to_lf() -> None:
    dirty = _CLEAN.replace("\n", "\r\n")
    assert normalize_pem(dirty) == _CLEAN


def test_lone_cr_converted() -> None:
    dirty = _CLEAN.replace("\n", "\r")
    assert normalize_pem(dirty) == _CLEAN


def test_missing_trailing_newline_added() -> None:
    assert normalize_pem(_CLEAN.rstrip("\n")) == _CLEAN


def test_surrounding_whitespace_stripped() -> None:
    assert normalize_pem(f"  \n{_CLEAN}\n\n  ") == _CLEAN


def test_clean_input_is_idempotent() -> None:
    assert normalize_pem(_CLEAN) == _CLEAN


def test_empty_stays_empty() -> None:
    assert normalize_pem("") == ""
    assert normalize_pem("  \n ") == ""

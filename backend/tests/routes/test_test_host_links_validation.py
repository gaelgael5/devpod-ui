"""Validation des liens de serveur de test (clé + URL) — partie pure."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from portal.routes.test_vm import _LINK_KEY_RE, _validate_link_url


def test_key_accepts_readable_labels() -> None:
    for key in ("app", "Grafana", "front 3000", "api-v2", "doc.site", "n8n_ui"):
        assert _LINK_KEY_RE.fullmatch(key), key


def test_key_rejects_garbage() -> None:
    for key in ("", " lead", "a" * 51, "key\nx", "<script>", "a/b", "é&"):
        assert not _LINK_KEY_RE.fullmatch(key), repr(key)


def test_url_accepts_http_and_https() -> None:
    _validate_link_url("http://192.168.10.201:3000")
    _validate_link_url("https://grafana.dev.yoops.org/d/abc?from=now-1h")


def test_url_rejects_other_schemes_and_relative() -> None:
    for url in ("javascript:alert(1)", "ftp://x", "file:///etc/passwd", "/relative", "notaurl"):
        with pytest.raises(HTTPException):
            _validate_link_url(url)

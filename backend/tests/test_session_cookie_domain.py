# backend/tests/test_session_cookie_domain.py
"""Domaine du cookie de session : '.{base_domain}' pour le partager avec les
sous-domaines workspace (ws-xxx.{base_domain})."""
from __future__ import annotations

from portal.settings import session_cookie_domain


def test_returns_dotted_domain() -> None:
    assert session_cookie_domain("dev.yoops.org") == ".dev.yoops.org"


def test_empty_returns_none() -> None:
    assert session_cookie_domain("") is None
    assert session_cookie_domain("   ") is None


def test_strips_whitespace() -> None:
    assert session_cookie_domain("  dev.yoops.org ") == ".dev.yoops.org"

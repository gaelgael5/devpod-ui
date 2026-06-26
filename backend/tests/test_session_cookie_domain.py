# backend/tests/test_session_cookie_domain.py
"""Domaine du cookie de session.

cookie_domain explicite prime (cas où portail et workspaces ne partagent qu'un
ancêtre commun, ex. portail=dev.yoops.org, workspaces=ws-x.yoops.org → .yoops.org).
Sinon on retombe sur base_domain.
"""
from __future__ import annotations

from portal.settings import resolve_cookie_domain


def test_falls_back_to_base_domain() -> None:
    assert resolve_cookie_domain("", "dev.yoops.org") == ".dev.yoops.org"


def test_explicit_cookie_domain_wins() -> None:
    # Portail sur dev.yoops.org, workspaces sur ws-x.yoops.org → cookie sur .yoops.org.
    assert resolve_cookie_domain("yoops.org", "dev.yoops.org") == ".yoops.org"


def test_both_empty_returns_none() -> None:
    assert resolve_cookie_domain("", "") is None
    assert resolve_cookie_domain("   ", "  ") is None


def test_strips_whitespace() -> None:
    assert resolve_cookie_domain("  yoops.org ", "dev.yoops.org") == ".yoops.org"

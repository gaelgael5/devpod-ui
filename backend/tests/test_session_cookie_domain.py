# backend/tests/test_session_cookie_domain.py
"""Domaine du cookie de session.

cookie_domain explicite prime (cas où portail et workspaces ne partagent qu'un
ancêtre commun, ex. portail=dev.yoops.org, workspaces=ws-x.yoops.org → .yoops.org).
Sinon, si vs_proxy_domain est configuré, l'ancêtre DNS commun entre l'hôte du
portail (external_url) et vs_proxy_domain est dérivé automatiquement — sans quoi
le cookie host-only n'atteint jamais le proxy VS Code (redirection login
systématique depuis /vsproxy). En dernier recours : base_domain.
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


def test_derives_common_ancestor_from_vs_proxy_domain() -> None:
    # Portail dev.yoops.org + proxy VS Code vs-dev.yoops.org, ni cookie_domain ni
    # base_domain : le cookie doit couvrir les deux hôtes → .yoops.org.
    assert (
        resolve_cookie_domain(
            "",
            "",
            external_url="https://dev.yoops.org",
            vs_proxy_domain="vs-dev.yoops.org",
        )
        == ".yoops.org"
    )


def test_derivation_takes_precedence_over_base_domain() -> None:
    # base_domain=dev.yoops.org donnerait .dev.yoops.org, qui ne couvre pas
    # vs-dev.yoops.org (hôte frère, pas sous-domaine).
    assert (
        resolve_cookie_domain(
            "",
            "dev.yoops.org",
            external_url="https://dev.yoops.org",
            vs_proxy_domain="vs-dev.yoops.org",
        )
        == ".yoops.org"
    )


def test_explicit_cookie_domain_wins_over_derivation() -> None:
    assert (
        resolve_cookie_domain(
            "custom.example",
            "",
            external_url="https://dev.yoops.org",
            vs_proxy_domain="vs-dev.yoops.org",
        )
        == ".custom.example"
    )


def test_vs_proxy_subdomain_of_portal_host() -> None:
    assert (
        resolve_cookie_domain(
            "",
            "",
            external_url="https://dev.yoops.org",
            vs_proxy_domain="vs.dev.yoops.org",
        )
        == ".dev.yoops.org"
    )


def test_no_common_ancestor_falls_back_to_base_domain() -> None:
    assert (
        resolve_cookie_domain(
            "",
            "dev.yoops.org",
            external_url="https://dev.yoops.org",
            vs_proxy_domain="vs.example.com",
        )
        == ".dev.yoops.org"
    )


def test_single_label_common_suffix_rejected() -> None:
    # Un suffixe commun d'un seul label ("org") serait un cookie sur un TLD :
    # refusé par les navigateurs → pas de dérivation.
    assert (
        resolve_cookie_domain(
            "",
            "",
            external_url="https://portal.yoops.org",
            vs_proxy_domain="vs.other.org",
        )
        is None
    )


def test_no_external_url_no_derivation() -> None:
    assert (
        resolve_cookie_domain("", "", external_url="", vs_proxy_domain="vs-dev.yoops.org")
        is None
    )

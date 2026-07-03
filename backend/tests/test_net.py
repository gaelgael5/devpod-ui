from __future__ import annotations

import asyncio

import pytest

from portal.net import build_resolve_fqdn, is_ipv4, resolve_ipv4


def test_build_resolve_fqdn_with_domain() -> None:
    assert build_resolve_fqdn("portal", "home.lan") == "portal.home.lan"


def test_build_resolve_fqdn_without_domain() -> None:
    assert build_resolve_fqdn("portal", "") == "portal"


def test_build_resolve_fqdn_leaves_already_qualified_name_untouched() -> None:
    """Un nom contenant déjà un point (FQDN publique/privée) n'est pas suffixé."""
    assert build_resolve_fqdn("google.fr", "home.lan") == "google.fr"
    assert build_resolve_fqdn("portal.yoops.org", "home.lan") == "portal.yoops.org"


def test_is_ipv4_true_for_literal_ip() -> None:
    assert is_ipv4("192.168.10.50") is True


def test_is_ipv4_false_for_hostname() -> None:
    assert is_ipv4("portal.home.lan") is False


@pytest.mark.asyncio
async def test_resolve_ipv4_times_out_instead_of_hanging(monkeypatch) -> None:
    """Un resolver qui ne répond jamais doit lever plutôt que bloquer indéfiniment."""

    async def _never_resolves(*args: object, **kwargs: object) -> list[object]:
        await asyncio.sleep(10)
        return []

    loop = asyncio.get_event_loop()
    monkeypatch.setattr(loop, "getaddrinfo", _never_resolves)

    with pytest.raises(TimeoutError):
        await resolve_ipv4("unreachable.example", timeout=0.05)


@pytest.mark.asyncio
async def test_resolve_ipv4_timeout_is_an_oserror() -> None:
    """`TimeoutError` est une sous-classe d'`OSError` (contrat des appelants)."""
    assert issubclass(TimeoutError, OSError)

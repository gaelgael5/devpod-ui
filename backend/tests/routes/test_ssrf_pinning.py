"""Bug 022 — SSRF résiduelle par DNS rebinding (TOCTOU check → fetch).

L'ancien schéma « _check_ssrf(url) puis client.get(url) » re-résolvait le DNS
au moment du GET : un résolveur attaquant (TTL 0) pouvait renvoyer une IP
publique au check puis 169.254.169.254/127.0.0.1 au fetch. `pinned_get`
résout une fois, valide, et connecte httpx à l'IP validée (Host + SNI
d'origine) — la seconde résolution n'existe plus.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from portal.routes._ssrf import check_ssrf, pinned_get, resolve_pinned

_PUBLIC = ("1.2.3.4", 0)
_LOOPBACK = ("127.0.0.1", 0)
_METADATA = ("169.254.169.254", 0)


def _addrinfo(*sockaddrs: tuple[str, int]) -> list[tuple]:
    return [(2, 1, 6, "", sa) for sa in sockaddrs]


def test_resolve_pinned_returns_validated_ip() -> None:
    with patch("portal.routes._ssrf._socket.getaddrinfo", return_value=_addrinfo(_PUBLIC)):
        assert resolve_pinned("https://gallery.example.org/toc.txt") == "1.2.3.4"


def test_resolve_pinned_blocks_internal_addresses() -> None:
    for sockaddr in (_LOOPBACK, _METADATA):
        with patch(
            "portal.routes._ssrf._socket.getaddrinfo", return_value=_addrinfo(sockaddr)
        ):
            with pytest.raises(HTTPException) as exc_info:
                resolve_pinned("https://gallery.example.org/toc.txt")
            assert exc_info.value.status_code == 422
            assert "blocked internal address" in str(exc_info.value.detail)


def test_resolve_pinned_blocks_if_any_resolved_ip_is_internal() -> None:
    """Une seule adresse interne dans le lot suffit à rejeter l'URL."""
    with patch(
        "portal.routes._ssrf._socket.getaddrinfo",
        return_value=_addrinfo(_PUBLIC, _LOOPBACK),
    ), pytest.raises(HTTPException):
        resolve_pinned("https://gallery.example.org/toc.txt")


def test_resolve_pinned_rejects_bad_scheme_and_empty_host() -> None:
    with pytest.raises(HTTPException):
        resolve_pinned("ftp://example.org/x")
    with pytest.raises(HTTPException):
        resolve_pinned("https:///no-host")


def test_check_ssrf_same_contract() -> None:
    with (
        patch("portal.routes._ssrf._socket.getaddrinfo", return_value=_addrinfo(_LOOPBACK)),
        pytest.raises(HTTPException),
    ):
        check_ssrf("http://rebind.example.org/")


@pytest.mark.asyncio
async def test_pinned_get_connects_to_validated_ip_not_hostname() -> None:
    """Le GET part vers l'IP épinglée ; le hostname d'origine ne sert plus qu'au
    header Host et au SNI — une re-résolution DNS ne peut plus dévier le fetch."""
    client = AsyncMock()
    with patch("portal.routes._ssrf._socket.getaddrinfo", return_value=_addrinfo(_PUBLIC)):
        await pinned_get(client, "https://gallery.example.org/dir/toc.txt", timeout=5.0)

    client.get.assert_awaited_once()
    args, kwargs = client.get.await_args
    assert args[0] == "https://1.2.3.4/dir/toc.txt"
    assert kwargs["headers"]["Host"] == "gallery.example.org"
    assert kwargs["extensions"] == {"sni_hostname": "gallery.example.org"}
    assert kwargs["follow_redirects"] is False
    assert kwargs["timeout"] == 5.0


@pytest.mark.asyncio
async def test_pinned_get_preserves_explicit_port_and_plain_http() -> None:
    client = AsyncMock()
    with patch("portal.routes._ssrf._socket.getaddrinfo", return_value=_addrinfo(_PUBLIC)):
        await pinned_get(client, "http://gallery.example.org:8080/toc.txt")

    args, kwargs = client.get.await_args
    assert args[0] == "http://1.2.3.4:8080/toc.txt"
    assert kwargs["headers"]["Host"] == "gallery.example.org:8080"
    assert kwargs["extensions"] == {}  # pas de SNI en clair


@pytest.mark.asyncio
async def test_pinned_get_uses_preresolved_ip_without_new_lookup() -> None:
    """Avec pinned_ip fourni (résolu avant même de construire le client),
    aucune nouvelle résolution DNS n'a lieu."""
    client = AsyncMock()
    with patch("portal.routes._ssrf._socket.getaddrinfo") as mock_gai:
        await pinned_get(
            client, "https://gallery.example.org/x", pinned_ip="1.2.3.4"
        )
    mock_gai.assert_not_called()
    args, _kwargs = client.get.await_args
    assert args[0] == "https://1.2.3.4/x"


@pytest.mark.asyncio
async def test_pinned_get_blocks_before_any_network_call() -> None:
    client = AsyncMock()
    with (
        patch("portal.routes._ssrf._socket.getaddrinfo", return_value=_addrinfo(_METADATA)),
        pytest.raises(HTTPException),
    ):
        await pinned_get(client, "https://rebind.example.org/x")
    client.get.assert_not_awaited()

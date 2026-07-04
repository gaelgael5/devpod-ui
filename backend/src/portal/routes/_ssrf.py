"""Anti-SSRF partagé des routes qui fetchent des URLs configurées par un admin.

Deux niveaux de protection :

- ``check_ssrf(url)`` : validation seule (schéma http/https, hostname présent,
  aucune résolution vers une adresse interne). Suffisant quand on ne fait que
  PERSISTER l'URL.
- ``pinned_get(client, url)`` : GET anti-rebinding (bug 022). Un simple check
  préalable laisse une fenêtre TOCTOU — httpx re-résout le DNS au moment du
  GET, et un résolveur attaquant (TTL 0) peut renvoyer une IP publique au
  check puis 127.0.0.1/169.254.169.254 au fetch. Ici le nom est résolu UNE
  fois, l'IP validée, et la connexion se fait vers cette IP : le hostname
  d'origine passe en header Host et en SNI, la vérification du certificat TLS
  reste donc faite contre le nom (extension httpx ``sni_hostname``). Les
  redirections restent désactivées — une 30x re-déclencherait un lookup.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket as _socket
from urllib.parse import urlparse, urlunparse

import httpx
from fastapi import HTTPException


def resolve_pinned(url: str) -> str:
    """Valide l'URL et retourne l'IP (str) à laquelle se connecter.

    Lève HTTPException(422) si le schéma est invalide, le hostname absent ou
    irrésoluble, ou si l'une des adresses résolues est interne (loopback,
    lien-local, privée, multicast, réservée, non spécifiée).

    Bloquant (getaddrinfo) : appeler via ``asyncio.to_thread`` depuis un handler.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=422, detail=f"URL scheme must be http or https: {url!r}")
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host:
        raise HTTPException(status_code=422, detail="URL has no hostname")
    try:
        infos = _socket.getaddrinfo(host, None)
    except _socket.gaierror as exc:
        raise HTTPException(
            status_code=422, detail=f"Cannot resolve hostname '{host}': {exc}"
        ) from exc
    pinned: str | None = None
    for _fam, _type, _proto, _canon, sa in infos:
        try:
            ip = ipaddress.ip_address(sa[0])
        except ValueError:
            continue
        if (
            ip.is_loopback
            or ip.is_link_local
            or ip.is_private
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise HTTPException(
                status_code=422,
                detail=f"URL resolves to a blocked internal address: {ip}",
            )
        if pinned is None:
            pinned = str(ip)
    if pinned is None:
        raise HTTPException(
            status_code=422, detail=f"Cannot resolve hostname '{host}' to a usable address"
        )
    return pinned


def check_ssrf(url: str) -> None:
    """Validation seule (sans fetch) — même contrat d'erreurs que resolve_pinned."""
    resolve_pinned(url)


async def pinned_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout: float = 5.0,
    pinned_ip: str | None = None,
) -> httpx.Response:
    """GET épinglé sur l'IP validée (anti DNS rebinding, bug 022).

    ``pinned_ip`` permet de réutiliser une IP déjà résolue/validée par
    ``resolve_pinned`` (ex. validation avant même de construire le client) ;
    sinon la résolution+validation est faite ici.
    """
    if pinned_ip is None:
        pinned_ip = await asyncio.to_thread(resolve_pinned, url)
    parsed = urlparse(url)
    host = parsed.hostname or ""
    host_literal = f"[{host}]" if ":" in host else host
    ip_literal = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
    if parsed.port is None:
        host_header, netloc = host_literal, ip_literal
    else:
        host_header, netloc = f"{host_literal}:{parsed.port}", f"{ip_literal}:{parsed.port}"
    pinned_url = urlunparse(parsed._replace(netloc=netloc))
    extensions = {"sni_hostname": host} if parsed.scheme == "https" else {}
    return await client.get(
        pinned_url,
        headers={"Host": host_header},
        extensions=extensions,
        timeout=timeout,
        follow_redirects=False,
    )

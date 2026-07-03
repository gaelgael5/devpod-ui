"""Helpers réseau partagés : construction de FQDN et résolution DNS async.

Utilisés à la fois par la re-résolution d'IP DHCP des machines de test
(`routes/test_vm.py`) et par la construction des URLs de workspace en dev
(`exposure/`), où `server.workspace_host` peut être un hostname à re-résoudre.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket


def build_resolve_fqdn(name: str, local_domain: str) -> str:
    """FQDN à résoudre.

    `name` est un nom court (sans point, ex. "portal", "host-test-114-1") →
    `<name>.<local_domain>`. `name` contient déjà un point (FQDN publique ou
    privée déjà qualifiée, ex. "google.fr", "portal.yoops.org") → renvoyé tel
    quel, `local_domain` ne s'applique qu'aux noms courts à re-résoudre en DHCP.
    """
    domain = local_domain.strip().strip(".")
    if not domain or "." in name:
        return name
    return f"{name}.{domain}"


_RESOLVE_TIMEOUT = 5.0


async def resolve_ipv4(fqdn: str, timeout: float = _RESOLVE_TIMEOUT) -> str:
    """Première IPv4 résolue pour `fqdn` via le resolver du portail (async).

    Bornée par `timeout` (`TimeoutError`, sous-classe d'`OSError` — les appelants
    qui catchent déjà `OSError` n'ont rien à changer) : un resolver injoignable ou
    un domaine sans réponse ne doit jamais bloquer la requête HTTP jusqu'à ce
    qu'un proxy en amont (Cloudflare Tunnel, Caddy) la coupe lui-même et masque
    l'erreur réelle derrière un 502 générique.
    """
    loop = asyncio.get_event_loop()
    infos = await asyncio.wait_for(
        loop.getaddrinfo(fqdn, None, family=socket.AF_INET), timeout=timeout
    )
    if not infos:
        raise OSError(f"no address for {fqdn}")
    return str(infos[0][4][0])


def is_ipv4(value: str) -> bool:
    """True si `value` est une adresse IP littérale (pas un hostname à résoudre)."""
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False

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
    """FQDN à résoudre : `<name>.<local_domain>` (ou `<name>` si pas de domaine)."""
    domain = local_domain.strip().strip(".")
    return f"{name}.{domain}" if domain else name


async def resolve_ipv4(fqdn: str) -> str:
    """Première IPv4 résolue pour `fqdn` via le resolver du portail (async)."""
    loop = asyncio.get_event_loop()
    infos = await loop.getaddrinfo(fqdn, None, family=socket.AF_INET)
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

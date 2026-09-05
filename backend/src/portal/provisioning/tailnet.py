"""Adhésion au tailnet des machines provisionnées (ticket 7).

L'adresse d'une machine est son IP de tailnet : le portail fait du SSH
ordinaire sans savoir si la machine est sur pve2 ou en Suède, et la spec n'a
jamais à modéliser un VPC, un subnet ou un security group.

Décisions de conception (assumées ici, pas par commodité) :

- **Clé d'enrôlement à usage unique, pré-autorisée, à durée courte** — jamais
  une clé durable stockée dans une image. « Éphémère » qualifie la CLÉ, pas le
  nœud : un nœud Tailscale `ephemeral` disparaît après une absence prolongée,
  ce qu'on refuse pour un host de workspaces qui peut être éteint des jours.
  Le désenrôlement est donc EXPLICITE, à la destruction, via l'API.
- **Tags de nœud plutôt qu'ACL par machine** : les machines de workspace
  forment une classe, l'ACL décrit la relation entre classes — sinon elle
  grossit avec le parc.
- **Pas de repli silencieux** : tailnet demandé mais indisponible = échec net.
  Une adresse locale qui ne marchera pas depuis le cloud est pire qu'une
  erreur.

La garde anti-SSRF du portail (`routes/_ssrf.py`) bloque la plage CGNAT
100.64.0.0/10 pour les URL fournies par l'utilisateur — c'est voulu et ça ne
gêne pas ce chemin-ci : les adresses de machines sont déclarées par
l'administrateur ou rendues par un driver, jamais résolues via `resolve_pinned`.
"""

from __future__ import annotations

import ipaddress
from typing import Any

import httpx
import structlog

from .errors import DriverError

_log = structlog.get_logger(__name__)

_CGNAT = ipaddress.ip_network("100.64.0.0/10")
# Une clé sert UNE création de machine : une heure couvre le provisionnement le
# plus lent (cloud, quota, retries) sans laisser traîner un secret utilisable.
_KEY_EXPIRY_S = 3600


class TailnetIndisponible(DriverError):
    """Le tailnet est requis et ne répond pas : échec net, jamais de repli."""


class TailnetService:
    """Client de l'API Tailscale (`api.tailscale.com` ou compatible).

    `api_key` : clé d'API ou access-token OAuth (scope `auth_keys` + `devices`),
    résolue par l'appelant (Harpocrate) — jamais lue ici depuis un fichier.
    `tailnet` : nom du tailnet, `-` = celui de la clé.
    """

    def __init__(
        self,
        *,
        api_key: str,
        tag: str,
        tailnet: str = "-",
        api_base: str = "https://api.tailscale.com",
        timeout_s: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise TailnetIndisponible(
                "tailnet non configuré : aucune clé d'API — configurer le service "
                "ou provisionner sans adresse de tailnet"
            )
        if not tag.startswith("tag:"):
            raise ValueError(f"tag de nœud invalide (attendu 'tag:...') : {tag!r}")
        self._api_key = api_key
        self._tag = tag
        self._tailnet = tailnet
        self._api_base = api_base.rstrip("/")
        self._timeout_s = timeout_s
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._api_base,
            auth=(self._api_key, ""),
            timeout=self._timeout_s,
            transport=self._transport,
        )

    async def creer_cle_enrolement(self, *, hostname: str) -> str:
        """Clé à usage unique, pré-autorisée, taguée, expirant vite.

        La valeur rendue transite vers `configure-node.sh` par stdin/env — elle
        ne doit apparaître ni dans un log ni dans un argv, et ce module ne la
        journalise jamais.
        """
        payload = {
            "capabilities": {
                "devices": {
                    "create": {
                        "reusable": False,
                        "ephemeral": False,
                        "preauthorized": True,
                        "tags": [self._tag],
                    }
                }
            },
            "expirySeconds": _KEY_EXPIRY_S,
            "description": f"portal:{hostname}",
        }
        async with self._client() as client:
            try:
                resp = await client.post(f"/api/v2/tailnet/{self._tailnet}/keys", json=payload)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise TailnetIndisponible(
                    f"création de clé d'enrôlement impossible : {exc}"
                ) from exc
        key = str(resp.json().get("key") or "")
        if not key:
            raise TailnetIndisponible("l'API n'a pas rendu de clé d'enrôlement")
        _log.info("tailnet_cle_creee", hostname=hostname, tag=self._tag)
        return key

    async def ip_du_noeud(self, hostname: str) -> str | None:
        """Première adresse CGNAT du nœud dont le nom commence par `hostname`.

        Tailscale suffixe le nom de domaine du tailnet (`n1.tail1234.ts.net`) —
        on compare le premier label, en minuscules.
        """
        device = await self._trouver(hostname)
        if device is None:
            return None
        for addr in device.get("addresses") or []:
            try:
                ip = ipaddress.ip_address(str(addr))
            except ValueError:
                continue
            if isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT:
                return str(ip)
        return None

    async def desenroler(self, hostname: str) -> bool:
        """Retire le nœud du tailnet. `False` si aucun nœud ne porte ce nom —
        idempotent : détruire deux fois ne doit pas échouer la seconde."""
        device = await self._trouver(hostname)
        if device is None:
            _log.info("tailnet_desenrolement_noop", hostname=hostname)
            return False
        async with self._client() as client:
            try:
                resp = await client.delete(f"/api/v2/device/{device['id']}")
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise TailnetIndisponible(
                    f"désenrôlement de {hostname} impossible : {exc}"
                ) from exc
        _log.info("tailnet_desenrole", hostname=hostname, device_id=device["id"])
        return True

    async def _trouver(self, hostname: str) -> dict[str, Any] | None:
        cible = hostname.lower()
        async with self._client() as client:
            try:
                resp = await client.get(f"/api/v2/tailnet/{self._tailnet}/devices")
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise TailnetIndisponible(f"listing des nœuds impossible : {exc}") from exc
        for device in resp.json().get("devices") or []:
            name = str(device.get("name") or "")
            if name.split(".", 1)[0].lower() == cible:
                return dict(device)
        return None

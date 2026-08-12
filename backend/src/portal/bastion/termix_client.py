"""Client HTTP minimal de l'API Termix (provisioning bastion).

Appelle l'URL EXTERNE de Termix (ex. https://termix.yoops.org) avec l'apikey admin
(`Authorization: Bearer tmx_…`). Couvre le strict nécessaire au cycle de vie d'un
host bastion : credential (clé), host (référence credential), partage à un rôle,
et suppression. Chemins alignés sur le contrat OpenAPI
`ag-flow/ressources/contracts/termix/termix-hosts.openapi.json` (hosts sous
`/host/db/host`) ; les corps y sont volontairement permissifs, d'où le parsing
tolérant des réponses (champ `id`) via `_extract_id`.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

_log = structlog.get_logger(__name__)


def _extract_id(payload: Any) -> int | None:
    """Récupère un id numérique d'une réponse Termix (id|hostId|credentialId)."""
    if isinstance(payload, dict):
        for key in ("id", "hostId", "credentialId"):
            val = payload.get(key)
            if isinstance(val, int):
                return val
            if isinstance(val, str) and val.isdigit():
                return int(val)
    return None


class TermixClient:
    """Client Termix. À utiliser en `async with` (session httpx dédiée)."""

    def __init__(self, base_url: str, apikey: str, *, timeout: float = 15.0) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {apikey}"}
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> TermixClient:
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _req(
        self, method: str, path: str, *, allow_404: bool = False, **kw: Any
    ) -> httpx.Response:
        assert self._client is not None, "TermixClient hors contexte"
        resp = await self._client.request(
            method, f"{self._base}{path}", headers=self._headers, **kw
        )
        if resp.status_code == 404 and allow_404:
            return resp
        if resp.status_code >= 400:
            raise RuntimeError(f"Termix {method} {path} → {resp.status_code}: {resp.text[:300]}")
        return resp

    # ─── Rôles ──────────────────────────────────────────────────────────────
    async def find_role_id(self, name: str) -> int | None:
        resp = await self._req("GET", "/rbac/roles")
        data = resp.json()
        roles = data if isinstance(data, list) else data.get("roles", [])
        for r in roles:
            if isinstance(r, dict) and r.get("name") == name:
                rid = r.get("id")
                return int(rid) if isinstance(rid, (int, str)) and str(rid).isdigit() else None
        return None

    # ─── Credentials ────────────────────────────────────────────────────────
    async def create_credential(self, name: str, username: str, private_key: str) -> int | None:
        resp = await self._req(
            "POST",
            "/credentials",
            json={"name": name, "authType": "key", "username": username, "key": private_key},
        )
        return _extract_id(resp.json())

    async def delete_credential(self, credential_id: int) -> None:
        """Supprime un credential ; déjà absent (404) = succès (rejeu idempotent)."""
        await self._req("DELETE", f"/credentials/{credential_id}", allow_404=True)

    # ─── Hosts ──────────────────────────────────────────────────────────────
    async def create_host(
        self, name: str, ip: str, port: int, username: str, credential_id: int
    ) -> int | None:
        resp = await self._req(
            "POST",
            "/host/db/host",
            json={
                "name": name,
                "ip": ip,
                "port": port,
                "username": username,
                "authType": "key",
                "credentialId": credential_id,
            },
        )
        return _extract_id(resp.json())

    async def delete_host(self, host_id: int) -> None:
        """Supprime un host ; déjà absent (404) = succès (rejeu idempotent)."""
        await self._req("DELETE", f"/host/db/host/{host_id}", allow_404=True)

    async def list_host_ids(self) -> list[int] | None:
        """Ids des hosts existants (GET /host/db/host, opération `listHosts` du
        contrat). None si forme inattendue — l'appelant ne doit alors PAS
        conclure à la disparition d'un host."""
        try:
            resp = await self._req("GET", "/host/db/host")
            data = resp.json()
        except Exception:
            return None
        items: Any = data if isinstance(data, list) else None
        if items is None and isinstance(data, dict):
            items = data.get("hosts")
        if not isinstance(items, list):
            return None
        return [i for i in (_extract_id(it) for it in items) if i is not None]

    async def share_host_to_role(
        self, host_id: int, role_id: int, permission: str = "connect"
    ) -> None:
        await self._req(
            "POST",
            f"/rbac/host/{host_id}/share",
            json={"targets": [{"type": "role", "id": role_id}], "permissionLevel": permission},
        )

    # ─── Users (partage per-user, spec 18 T5) ────────────────────────────────
    async def find_user_id(self, username: str) -> str | None:
        """`userId` Termix du user dont `username == username` (= le `sub` OIDC).

        Réponse observée : `{"users":[{"userId":"<str>","username":"...", ...}]}`.
        `userId` est une **chaîne** (pas un int), d'où le type de retour. None si
        absent (compte pas encore créé côté Termix → l'appelant réessaie).
        """
        resp = await self._req("GET", "/users/list")
        data = resp.json()
        items = data if isinstance(data, list) else data.get("users", [])
        for u in items:
            if isinstance(u, dict) and u.get("username") == username:
                uid = u.get("userId") if u.get("userId") is not None else u.get("id")
                return str(uid) if uid is not None else None
        return None

    async def share_host_to_user(
        self, host_id: int, user_id: str, permission: str = "connect"
    ) -> None:
        await self._req(
            "POST",
            f"/rbac/host/{host_id}/share",
            json={"targets": [{"type": "user", "id": user_id}], "permissionLevel": permission},
        )

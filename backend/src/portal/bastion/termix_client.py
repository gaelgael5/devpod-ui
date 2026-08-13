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
        self,
        method: str,
        path: str,
        *,
        allow_404: bool = False,
        allow_409: bool = False,
        **kw: Any,
    ) -> httpx.Response:
        assert self._client is not None, "TermixClient hors contexte"
        resp = await self._client.request(
            method, f"{self._base}{path}", headers=self._headers, **kw
        )
        if resp.status_code == 404 and allow_404:
            return resp
        if resp.status_code == 409 and allow_409:
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

    async def list_credential_ids(self) -> list[int]:
        """Ids des credentials visibles (GET /credentials). Vide si forme inattendue."""
        try:
            resp = await self._req("GET", "/credentials")
            data = resp.json()
        except Exception:
            return []
        items: Any = data if isinstance(data, list) else None
        if items is None and isinstance(data, dict):
            items = data.get("credentials") or data.get("items")
        if not isinstance(items, list):
            return []
        return [i for i in (_extract_id(it) for it in items) if i is not None]

    # ─── Hosts ──────────────────────────────────────────────────────────────
    async def create_host(
        self,
        name: str,
        ip: str,
        port: int,
        username: str,
        credential_id: int,
        folder: str | None = None,
    ) -> int | None:
        """Crée un host. `folder` = dossier de regroupement Termix (barre latérale) ;
        None → hors dossier (le champ Termix accepte `folder || null`)."""
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
                "folder": folder,
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

    async def list_hosts(self) -> list[dict[str, Any]]:
        """Hosts existants avec leurs champs bruts (id, name, credentialId, …).

        `GET /host/db/host`. Retourne `[]` si erreur / forme inattendue. Sert au
        nettoyage par NOM (dé-provisioning d'un workspace : supprimer TOUS les
        hosts qui portent son `ws_id`, doublons compris)."""
        try:
            resp = await self._req("GET", "/host/db/host")
            data = resp.json()
        except Exception:
            return []
        items: Any = data if isinstance(data, list) else None
        if items is None and isinstance(data, dict):
            items = data.get("hosts")
        return [it for it in items if isinstance(it, dict)] if isinstance(items, list) else []

    async def share_host_to_role(
        self, host_id: int, role_id: int, permission: str = "connect"
    ) -> None:
        await self._req(
            "POST",
            f"/rbac/host/{host_id}/share",
            json={"targets": [{"type": "role", "id": role_id}], "permissionLevel": permission},
        )

    # ─── Users (partage per-user, spec 18 T5) ────────────────────────────────
    async def create_user(self, username: str, password: str) -> bool:
        """Crée un compte LOCAL Termix (`POST /users/admin-create`, `isOidc=false`).

        `username` = email de l'utilisateur (login Termix par email). Appelé à
        l'association user↔instance côté portail. 409 (existe déjà) toléré →
        idempotent. Retourne True si créé, False s'il existait déjà.
        """
        resp = await self._req(
            "POST",
            "/users/admin-create",
            json={"username": username, "password": password},
            allow_409=True,
        )
        return resp.status_code != 409

    async def create_apikey_for_user(
        self, user_id: str, name: str, expires_at: str | None = None
    ) -> tuple[str | None, str | None]:
        """Mint une apikey POUR un autre user (`POST /users/api-keys`, admin only).

        Permet de créer des objets « en tant que » l'user (host/credential possédés
        par lui, pas par l'admin). Retourne `(key_id, token)` ; `key_id` sert au
        nettoyage (`delete_apikey`). Réponse : `{apiKey:{...}, token:"tmx_..."}`.
        """
        body: dict[str, Any] = {"name": name, "userId": user_id}
        if expires_at:
            body["expiresAt"] = expires_at
        resp = await self._req("POST", "/users/api-keys", json=body)
        data = resp.json()
        meta = data.get("apiKey") if isinstance(data.get("apiKey"), dict) else {}
        # Champ d'id inconnu (corps non documenté) : on essaie les candidats usuels,
        # à défaut on cherche au niveau racine, et on loggue les clés vues pour
        # corriger le nettoyage sans re-minter à la main.
        key_id = None
        for src in (meta, data):
            for k in ("id", "keyId", "apiKeyId", "key_id", "api_key_id"):
                if isinstance(src, dict) and src.get(k) is not None:
                    key_id = src[k]
                    break
            if key_id is not None:
                break
        if key_id is None:
            _log.warning(
                "termix_apikey_id_unknown",
                apikey_fields=list(meta.keys()) if isinstance(meta, dict) else None,
                root_fields=list(data.keys()) if isinstance(data, dict) else None,
            )
        return (str(key_id) if key_id is not None else None, data.get("token"))

    async def delete_apikey(self, key_id: str) -> None:
        """Supprime une apikey (`DELETE /users/api-keys/{keyId}`) ; 404 toléré."""
        await self._req("DELETE", f"/users/api-keys/{key_id}", allow_404=True)

    async def list_apikeys(self) -> list[dict[str, Any]]:
        """Apikeys visibles (`GET /users/api-keys`, admin). Entrées brutes."""
        try:
            resp = await self._req("GET", "/users/api-keys")
            data = resp.json()
        except Exception:
            return []
        items: Any = data if isinstance(data, list) else None
        if items is None and isinstance(data, dict):
            items = data.get("apiKeys") or data.get("keys") or data.get("items")
        return [k for k in items if isinstance(k, dict)] if isinstance(items, list) else []

    async def delete_user_apikeys(self, user_id: str, username: str | None = None) -> int:
        """Supprime toutes les apikeys d'un user (match userId OU username). → nombre
        supprimé. Nécessaire avant delete-user (FK NOT NULL sur apikey.userId)."""
        n = 0
        for k in await self.list_apikeys():
            owner_id = k.get("userId") or k.get("user_id") or k.get("ownerId")
            owner_name = k.get("username") or k.get("user")
            if owner_id == user_id or (username is not None and owner_name == username):
                kid = k.get("id") or k.get("keyId") or k.get("apiKeyId") or k.get("key_id")
                if kid is not None:
                    await self.delete_apikey(str(kid))
                    n += 1
        return n

    async def delete_user(self, *, user_id: str | None = None, username: str | None = None) -> None:
        """Supprime un utilisateur (`DELETE /users/delete-user`), par `userId` OU
        `username` (l'API accepte les deux ; `username` sert aux comptes OIDC nommés
        par le claim `name`). Dé-association user↔instance (spec 18 T5) — l'user ne
        peut plus se connecter. 404 toléré (déjà supprimé)."""
        body: dict[str, str] = {}
        if user_id is not None:
            body["userId"] = user_id
        if username is not None:
            body["username"] = username
        await self._req("DELETE", "/users/delete-user", json=body, allow_404=True)

    async def find_user_id(self, username: str, *, oidc: bool | None = None) -> str | None:
        """`userId` Termix du user dont `username == username`.

        `oidc=True` : ne matche que les comptes OIDC (`is_oidc`) — pour partager au
        compte OIDC (username = `sub`) distinct du compte interne (username = email).
        Réponse : `{"users":[{"userId":"<str>","username":"...","is_oidc":bool}]}`.
        `userId` est une **chaîne**. None si absent.
        """
        resp = await self._req("GET", "/users/list")
        data = resp.json()
        items = data if isinstance(data, list) else data.get("users", [])
        for u in items:
            if not isinstance(u, dict) or u.get("username") != username:
                continue
            if oidc is not None and bool(u.get("is_oidc")) != oidc:
                continue
            uid = u.get("userId") if u.get("userId") is not None else u.get("id")
            return str(uid) if uid is not None else None
        # Diag (spec 18 T5) : ce que le portail voit réellement quand ça ne matche pas.
        _log.info(
            "termix_users_list_seen",
            searched=username,
            candidates=[u.get("username") for u in items if isinstance(u, dict)],
            raw_type=type(data).__name__,
        )
        return None

    async def find_user_ids(self, username: str) -> list[str]:
        """TOUS les `userId` portant ce username (compte interne + OIDC coexistent avec
        le même email). Sert au nettoyage COMPLET à la dé-association — supprimer les
        hosts sur chacun des comptes, pas seulement le premier trouvé."""
        resp = await self._req("GET", "/users/list")
        data = resp.json()
        items = data if isinstance(data, list) else data.get("users", [])
        out: list[str] = []
        for u in items:
            if not isinstance(u, dict) or u.get("username") != username:
                continue
            uid = u.get("userId") if u.get("userId") is not None else u.get("id")
            if uid is not None:
                out.append(str(uid))
        return out

    async def share_host_to_user(
        self, host_id: int, user_id: str, permission: str = "connect"
    ) -> None:
        await self._req(
            "POST",
            f"/rbac/host/{host_id}/share",
            json={"targets": [{"type": "user", "id": user_id}], "permissionLevel": permission},
        )

"""Inventaire Azure des ressources `managed-by=devflow` (ticket 11).

La vue « provider » du réconciliateur : ce qui existe VRAIMENT chez Azure,
indépendamment du portail et du state. Client credentials OAuth2 → ARM,
listing par tag — l'un des trois regards, jamais une source d'action.
"""

from __future__ import annotations

import httpx
import structlog

from .errors import DriverError

_log = structlog.get_logger(__name__)

_ARM = "https://management.azure.com"
_LOGIN = "https://login.microsoftonline.com"


class InventaireIndisponible(DriverError):
    """L'API provider ne répond pas : le réconciliateur doit le dire — une
    panne d'API ne rend pas le parc orphelin."""


class AzureInventaire:
    def __init__(
        self,
        *,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        subscription_id: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self._tenant = tenant_id
        self._client_id = client_id
        self._secret = client_secret
        self._subscription = subscription_id
        self._transport = transport
        self._timeout_s = timeout_s

    async def machines(self) -> set[str]:
        """Les identifiants de machine (tag `machine`) des ressources taguées
        `managed-by=devflow` de la souscription."""
        async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout_s) as client:
            try:
                token = await self._token(client)
                resp = await client.get(
                    f"{_ARM}/subscriptions/{self._subscription}/resources",
                    params={
                        "api-version": "2021-04-01",
                        "$filter": "tagName eq 'managed-by' and tagValue eq 'devflow'",
                        "$expand": "tags",
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise InventaireIndisponible(f"inventaire Azure impossible : {exc}") from exc
        machines = {
            str((res.get("tags") or {}).get("machine") or "")
            for res in resp.json().get("value") or []
        }
        machines.discard("")
        _log.info("azure_inventaire", machines=len(machines))
        return machines

    async def _token(self, client: httpx.AsyncClient) -> str:
        resp = await client.post(
            f"{_LOGIN}/{self._tenant}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._secret,
                "scope": f"{_ARM}/.default",
            },
        )
        resp.raise_for_status()
        return str(resp.json()["access_token"])

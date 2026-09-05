"""Client Listmonk : envoi transactionnel et gestion des templates.

Deux surfaces de l'API (schéma d'auth `Authorization: token api_user:token`,
le même que la route de test de connexion) :

- `POST /api/tx` — l'envoi : `subscriber_email` + `template_id` + `data`
  (rendu côté Listmonk avec `{{ .Tx.Data.* }}`) ;
- `GET/POST/PUT /api/templates` — la synchronisation des templates versionnés
  (`templates.py`), déclenchée par l'admin, jamais au démarrage.

La résolution nom → id est mise en cache par instance de client (une passe
d'envoi) : un template manquant est une erreur explicite qui dit quoi faire —
lancer la synchro — pas un 404 nu.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

_log = structlog.get_logger(__name__)

_TIMEOUT_S = 15.0


class ListmonkIndisponible(RuntimeError):
    """L'instance ne répond pas ou refuse : l'envoi se journalise en échec,
    il ne casse jamais la transition d'abonnement qui l'a déclenché."""


class TemplateAbsent(ListmonkIndisponible):
    """Le template n'existe pas côté Listmonk — lancer la synchro admin."""


class ListmonkTxClient:
    def __init__(
        self,
        *,
        url: str,
        credential: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = _TIMEOUT_S,
    ) -> None:
        self._url = url.rstrip("/")
        self._credential = credential
        self._transport = transport
        self._timeout_s = timeout_s
        self._ids: dict[str, int] | None = None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._url,
            headers={"Authorization": f"token {self._credential}"},
            timeout=self._timeout_s,
            transport=self._transport,
        )

    # ─── Envoi ───────────────────────────────────────────────────────────────

    async def envoyer(self, *, template: str, email: str, data: dict[str, Any]) -> None:
        """Un envoi transactionnel. Le payload ne porte jamais de secret —
        c'est le même dict qui est figé dans le journal d'envoi."""
        template_id = await self._resoudre(template)
        async with self._client() as client:
            try:
                resp = await client.post(
                    "/api/tx",
                    json={
                        "subscriber_email": email,
                        "template_id": template_id,
                        "data": data,
                        "content_type": "html",
                    },
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ListmonkIndisponible(
                    f"envoi refusé ({exc.response.status_code}) : {_motif(exc.response)}"
                ) from exc
            except httpx.HTTPError as exc:
                raise ListmonkIndisponible(f"instance injoignable : {exc}") from exc
        _log.info("email_tx_envoye", template=template)

    # ─── Templates ───────────────────────────────────────────────────────────

    async def synchroniser_template(self, *, nom: str, sujet: str, corps: str) -> str:
        """Crée ou met à jour un template tx. Rend `cree` ou `mis_a_jour`."""
        ids = await self._lister_templates(rafraichir=True)
        payload = {"name": nom, "type": "tx", "subject": sujet, "body": corps}
        async with self._client() as client:
            try:
                if nom in ids:
                    resp = await client.put(f"/api/templates/{ids[nom]}", json=payload)
                    action = "mis_a_jour"
                else:
                    resp = await client.post("/api/templates", json=payload)
                    action = "cree"
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ListmonkIndisponible(
                    f"synchro du template {nom!r} refusée "
                    f"({exc.response.status_code}) : {_motif(exc.response)}"
                ) from exc
            except httpx.HTTPError as exc:
                raise ListmonkIndisponible(f"instance injoignable : {exc}") from exc
        self._ids = None  # le cache d'ids est périmé
        return action

    async def _resoudre(self, nom: str) -> int:
        ids = await self._lister_templates()
        if nom not in ids:
            # Une seconde chance après rafraîchissement : le template a pu être
            # synchronisé depuis la construction du cache.
            ids = await self._lister_templates(rafraichir=True)
        if nom not in ids:
            raise TemplateAbsent(
                f"template {nom!r} absent de Listmonk — lancer la synchro "
                "(POST /admin/listmonk/sync-templates)"
            )
        return ids[nom]

    async def _lister_templates(self, rafraichir: bool = False) -> dict[str, int]:
        if self._ids is not None and not rafraichir:
            return self._ids
        async with self._client() as client:
            try:
                resp = await client.get("/api/templates")
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise ListmonkIndisponible(f"listing des templates impossible : {exc}") from exc
        data = resp.json().get("data") or []
        self._ids = {
            str(t.get("name")): int(t["id"])
            for t in data
            if isinstance(t, dict) and t.get("id") is not None
        }
        return self._ids


def _motif(resp: httpx.Response) -> str:
    try:
        corps = resp.json()
        if isinstance(corps, dict):
            return str(corps.get("message") or "")[:300]
    except ValueError:
        pass
    return resp.text[:300]

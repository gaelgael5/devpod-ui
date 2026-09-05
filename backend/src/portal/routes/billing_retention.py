"""L'API que les automates de rétention appellent : arrêter, détruire.

Couche 2 de la fiche « Arrêt, rétention et destruction d'un workspace non
payé » : le balayeur (couche 3) émet `subscription.retention_expired`, le
script d'automate (couche 1, workspace ressources) décide et appelle CETTE
route pour agir. Elle est donc accessible au jeton d'API du portail
(`PORTAL_TOKEN`), comme les scripts d'hyperviseur — et à un admin en session.

Ce que la route fait, et sa limite assumée : elle agit sur les **workspaces**
(conteneurs Docker) de l'utilisateur sur le host visé — arrêt via le lifecycle
existant, destruction avec `shelve` (le travail en attente est archivé sur le
remote git du workspace, c'est l'issue « archiver » de la fiche). La
destruction de la VM dédiée elle-même relève des actions d'hyperviseur, pas
d'ici : ce serait une seconde mécanique de destruction, hors du contrat.

L'appel est en LOT sur les workspaces trouvés : un échec sur l'un n'empêche pas
les autres, et chaque destruction laisse sa trace — journal structuré ET
événement `workspace.deleted` (journal d'events durable), c'est l'audit que la
fiche exige.
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin, require_admin_or_api_key
from ..billing.config import PolitiqueRetention
from ..config.store import load_global
from ..db.engine import get_conn
from ..db.global_config import save_global_db, set_cached_global
from ..db.user_config import user_exists_db
from ..db.workspace_status import list_by_login_db

router = APIRouter(tags=["billing-retention"])
log = structlog.get_logger(__name__)


# ─── Délais de rétention (onglet Rétention de la page Abonnements) ───────────


@router.get("/billing/retention/config")
async def lire_delais_retention(
    user: UserInfo = Depends(require_admin),
) -> PolitiqueRetention:
    return load_global().billing.retention


@router.put("/billing/retention/config")
async def ecrire_delais_retention(
    body: PolitiqueRetention,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> PolitiqueRetention:
    """Pose les deux délais. Le modèle borne déjà (≥ 1 jour) : un délai nul
    détruirait à la première passe du balayeur, sans fenêtre pour archiver."""
    cfg = load_global()
    cfg.billing = cfg.billing.model_copy(update={"retention": body})
    await save_global_db(cfg, conn)
    set_cached_global(cfg)
    log.info(
        "retention_delais_modifies",
        echec_paiement_jours=body.echec_paiement_jours,
        resiliation_jours=body.resiliation_jours,
        actor=user.login,
    )
    return body


class ActionRetention(BaseModel):
    """Le contrat décidé sur la fiche : action, type d'hébergement, user, host."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["arreter", "detruire"]
    type_hebergement: Literal["dedie", "mutualise"]
    user_id: str = Field(min_length=1, max_length=64)
    host_id: str = Field(min_length=1, max_length=128)


class ResultatWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ws_id: str
    statut: Literal["arrete", "detruit", "echec"]
    erreur: str = ""


class ReponseRetention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resultats: list[ResultatWorkspace]


def _service() -> Any:
    from .workspace_ops import _get_service

    return _get_service()


@router.post("/billing/retention/action")
async def executer_action_retention(
    body: ActionRetention,
    user: UserInfo = Depends(require_admin_or_api_key),
    conn: AsyncConnection = Depends(get_conn),
) -> ReponseRetention:
    if not await user_exists_db(body.user_id, conn):
        raise HTTPException(status_code=404, detail=f"Compte {body.user_id!r} introuvable")

    # Les workspaces du compte SUR CE HOST, et eux seuls : le host_id vient de
    # l'automate, le recouper avec le propriétaire interdit qu'un host_id erroné
    # touche les workspaces d'un autre locataire du même host.
    workspaces = [
        r for r in await list_by_login_db(body.user_id, conn) if r.get("host_name") == body.host_id
    ]
    log.info(
        "retention_action_recue",
        action=body.action,
        user_id=body.user_id,
        host_id=body.host_id,
        type_hebergement=body.type_hebergement,
        workspaces=len(workspaces),
        actor=user.login,
    )

    svc = _service()
    resultats: list[ResultatWorkspace] = []
    for ws in workspaces:
        ws_id = str(ws["ws_id"])
        try:
            if body.action == "arreter":
                await svc.stop(login=body.user_id, ws_id=ws_id)
                resultats.append(ResultatWorkspace(ws_id=ws_id, statut="arrete"))
            else:
                # `shelve=True` : le travail en attente part sur le remote git
                # du workspace AVANT la destruction — l'issue « archiver » de la
                # fiche, pas un dépôt de sauvegarde dédié.
                await svc.delete(login=body.user_id, ws_id=ws_id, shelve=True)
                resultats.append(ResultatWorkspace(ws_id=ws_id, statut="detruit"))
                # Trace d'audit de CHAQUE destruction (exigence de la fiche) —
                # en plus de l'événement workspace.deleted du lifecycle.
                log.info(
                    "retention_workspace_detruit",
                    ws_id=ws_id,
                    user_id=body.user_id,
                    host_id=body.host_id,
                    actor=user.login,
                )
        except Exception as exc:  # noqa: BLE001 — le lot continue, l'échec se voit
            log.error(
                "retention_action_echec",
                action=body.action,
                ws_id=ws_id,
                user_id=body.user_id,
                error=str(exc),
                exc_info=True,
            )
            resultats.append(ResultatWorkspace(ws_id=ws_id, statut="echec", erreur=str(exc)))
    return ReponseRetention(resultats=resultats)

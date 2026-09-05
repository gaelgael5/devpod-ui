"""L'adresse de facturation du compte, vue de son titulaire.

Deux règles au-dessus du CRUD :

- **jamais en clair dans un journal.** Une adresse n'est pas un secret au sens
  du résolveur : la redaction automatique ne la couvre pas. Les logs de ces
  routes ne portent donc QUE le login et le pays — et le modèle lui-même masque
  ses champs dans `repr()`.
- **modifier le profil ne réécrit aucune souscription passée.** L'adresse d'ici
  est la valeur courante ; celle d'un abonnement est figée à la souscription
  (`subscriptions.billing_address_enc`) et ne passe pas par ces routes.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..billing.adresse import AdresseFacturation
from ..db.billing_address import lire_adresse, poser_adresse
from ..db.engine import get_conn

router = APIRouter(tags=["billing-address"])
log = structlog.get_logger(__name__)


@router.get("/billing-address")
async def ma_adresse(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> AdresseFacturation | None:
    """L'adresse courante du compte, ou `null` s'il n'en a pas saisi."""
    return await lire_adresse(user.login, conn)


@router.put("/billing-address")
async def poser_ma_adresse(
    body: AdresseFacturation,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> AdresseFacturation:
    await poser_adresse(user.login, body, conn)
    # Le pays seul : c'est la seule composante qui pilote un comportement
    # (taxe, canal) — le reste de l'adresse n'a rien à faire dans un journal.
    log.info("billing_address_updated", login=user.login, country=body.country)
    return body

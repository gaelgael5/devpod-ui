"""La vue « parc » des hôtes Docker : filtres, tris et pagination serveur.

Route mince : toute la logique — inconnus en fin de tri, ordre stable, entrée
« Mutualisé » du filtre propriétaire — vit dans `db/host_parc.py`, testée
contre le vrai schéma.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..db.engine import get_conn
from ..db.host_parc import PageParc, TriParc, lister_parc

router = APIRouter(tags=["host-parc"])


@router.get("/hosts/parc")
async def parc(
    q: str = "",
    owner: str = "",
    tri: TriParc = "nom",
    descendant: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    hors_usages: str = "",
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> PageParc:
    """`owner` accepte un login ou la valeur spéciale `__mutualise__` (le pool).

    `hors_usages` : usages à exclure, séparés par des virgules — l'écran des
    hôtes de workspaces écarte tests/ressources/autres, qui ont leurs sections.
    """
    exclus = [u.strip() for u in hors_usages.split(",") if u.strip()]
    return await lister_parc(
        conn,
        q=q,
        owner=owner,
        tri=tri,
        descendant=descendant,
        page=page,
        page_size=page_size,
        hors_usages=exclus,
    )

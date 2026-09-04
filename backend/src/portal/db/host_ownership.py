"""Propriété d'une machine DÉDIÉE — et d'elle seule.

Une machine mutualisée n'a pas de propriétaire (migration 117) : aucune ligne
n'est jamais écrite ici pour une machine du pool. Le rattachement d'un
abonnement au pool vit dans `subscription_hosts`.
"""

from __future__ import annotations

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import host_ownership


async def poser_propriete(
    *,
    host_name: str,
    owner_login: str,
    offer_slug: str,
    offer_max_workspaces: int | None,
    conn: AsyncConnection,
) -> None:
    """Écrit la propriété d'une machine dédiée qui vient d'être montée.

    `offer_max_workspaces` est FIGÉ ici, au provisionnement : un changement de
    catalogue ne redimensionne pas rétroactivement une machine déjà livrée. La
    capacité physique, elle, n'est pas recopiée — elle vit sur `hosts`
    (migration 125).
    """
    await conn.execute(
        insert(host_ownership).values(
            host_name=host_name,
            owner_login=owner_login,
            hosting_type="dedie",
            offer_slug=offer_slug,
            offer_max_workspaces=offer_max_workspaces,
        )
    )

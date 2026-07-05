"""Persistance de la messagerie inter-agents (spec 34, table agent_messages).

Référence de workspace par ws_id texte ("{login}-{name}") : workspaces.id est
réattribué à chaque save de config, inutilisable en FK stable. owner_login scope
tout (v1 intra-utilisateur). Transitions autorisées : pending → delivered,
pending → cancelled ; un message délivré/annulé est immuable (gardé par le WHERE
status = 'pending' des UPDATE, contrôle du rowcount côté appelant).
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import agent_message as _t


def _row(row: Any) -> dict[str, Any]:
    d = dict(row)
    for k in ("created_at", "delivered_at", "cancelled_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d


async def create_message(
    conn: AsyncConnection,
    *,
    owner_login: str,
    from_ws_id: str,
    to_ws_id: str,
    subject: str,
    body: str,
    from_session: str | None = None,
    reply_to: str | None = None,
) -> str:
    """Crée un message en `pending`. Retourne son id (uuid4 texte)."""
    msg_id = str(uuid.uuid4())
    from .tables import agent_message

    await conn.execute(
        agent_message.insert().values(
            id=msg_id,
            owner_login=owner_login,
            from_ws_id=from_ws_id,
            to_ws_id=to_ws_id,
            subject=subject,
            body=body,
            from_session=from_session,
            reply_to=reply_to,
            status="pending",
        )
    )
    return msg_id


async def get_message(conn: AsyncConnection, msg_id: str) -> dict[str, Any] | None:
    row = (
        await conn.execute(select(_t).where(_t.c.id == msg_id))
    ).mappings().one_or_none()
    return _row(row) if row is not None else None


async def list_replies(conn: AsyncConnection, msg_id: str) -> list[dict[str, Any]]:
    """message_id + statut des réponses (reply_to = msg_id), plus anciennes d'abord."""
    rows = (
        await conn.execute(
            select(_t.c.id, _t.c.status, _t.c.created_at)
            .where(_t.c.reply_to == msg_id)
            .order_by(_t.c.created_at)
        )
    ).mappings().all()
    return [
        {
            "message_id": r["id"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


async def list_for_workspace(
    conn: AsyncConnection,
    *,
    owner_login: str,
    ws_id: str,
    direction: str = "received",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Messages d'un workspace pour l'API agent (MCP).

    - `received` : uniquement les `delivered` destinés à ws_id (un agent ne voit
      jamais les `pending` qui lui sont adressés — la file appartient à l'utilisateur).
    - `sent` : tous les envois de ws_id, quel que soit le statut.
    - `all` : les deux ci-dessus réunis.
    """
    recv = and_(
        _t.c.to_ws_id == ws_id, _t.c.owner_login == owner_login, _t.c.status == "delivered"
    )
    sent = and_(_t.c.from_ws_id == ws_id, _t.c.owner_login == owner_login)
    if direction == "sent":
        where = sent
    elif direction == "all":
        where = recv | sent
    else:
        where = recv
    rows = (
        await conn.execute(
            select(_t).where(where).order_by(desc(_t.c.created_at)).limit(limit)
        )
    ).mappings().all()
    return [_row(r) for r in rows]


async def list_pending(conn: AsyncConnection, owner_login: str) -> list[dict[str, Any]]:
    """File de délivrance : tous les `pending` de l'utilisateur, plus anciens d'abord."""
    rows = (
        await conn.execute(
            select(_t)
            .where(and_(_t.c.owner_login == owner_login, _t.c.status == "pending"))
            .order_by(_t.c.created_at)
        )
    ).mappings().all()
    return [_row(r) for r in rows]


async def count_pending_by_to_ws(
    conn: AsyncConnection, owner_login: str
) -> dict[str, int]:
    """Nombre de `pending` entrants par ws_id destinataire (badge UI)."""
    rows = (
        await conn.execute(
            select(_t.c.to_ws_id, func.count())
            .where(and_(_t.c.owner_login == owner_login, _t.c.status == "pending"))
            .group_by(_t.c.to_ws_id)
        )
    ).all()
    return {ws_id: int(n) for ws_id, n in rows}


async def mark_delivered(
    conn: AsyncConnection, msg_id: str, owner_login: str, session: str
) -> bool:
    """Passe pending → delivered si (et seulement si) encore pending (verrou optimiste).

    Retourne True si la transition a eu lieu. À appeler APRÈS l'injection réussie :
    l'ordre vérification → injection → transition garantit qu'un message delivered a
    réellement été injecté (spec 34 §5).
    """
    result = await conn.execute(
        update(_t)
        .where(
            and_(_t.c.id == msg_id, _t.c.owner_login == owner_login, _t.c.status == "pending")
        )
        .values(status="delivered", delivered_at=func.now(), delivered_to_session=session)
    )
    return (result.rowcount or 0) > 0


async def mark_cancelled(conn: AsyncConnection, msg_id: str, owner_login: str) -> bool:
    """Passe pending → cancelled si encore pending. Retourne True si transition."""
    result = await conn.execute(
        update(_t)
        .where(
            and_(_t.c.id == msg_id, _t.c.owner_login == owner_login, _t.c.status == "pending")
        )
        .values(status="cancelled", cancelled_at=func.now())
    )
    return (result.rowcount or 0) > 0

"""Endpoints REST de la messagerie inter-agents (spec 34).

La création passe exclusivement par MCP ; ici l'utilisateur pilote la file :
liste des `pending`, détail, délivrance vers une session, rejet. Scopé à
l'utilisateur courant (owner_login = user.login), v1 intra-utilisateur.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..db import agent_messages as amdb
from ..db.engine import get_conn
from ..mcp.devpod_tools import _session_get, _session_send
from ..mcp.devpod_tools.errors import DevpodToolError

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["agent-messages"])

_FRAMING = (
    "[Message inter-agent — de {from_ws} — id {mid}]\n"
    "Sujet : {subject}\n\n"
    "{body}\n\n"
    'Pour répondre, utiliser devpod__message_send avec reply_to="{mid}".\n'
    "La réponse sera transmise à l'émetteur après validation par l'utilisateur."
)


class DeliverBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: str


def _name_from_ws_id(ws_id: str, login: str) -> str:
    """Nom de workspace depuis ws_id ({login}-{name}) — login connu (scoping)."""
    return ws_id[len(login) + 1 :] if ws_id.startswith(f"{login}-") else ws_id


@router.get("/agent-messages")
async def list_agent_messages(
    status: str = Query("pending", pattern=r"^(pending)$"),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, object]]:
    """File de délivrance : messages `pending` de l'utilisateur, plus anciens d'abord."""
    rows = await amdb.list_pending(conn, user.login)
    return [
        {
            **m,
            "from_name": _name_from_ws_id(m["from_ws_id"], user.login),
            "to_name": _name_from_ws_id(m["to_ws_id"], user.login),
        }
        for m in rows
    ]


@router.get("/agent-messages/pending-counts")
async def pending_counts(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, int]:
    """Nombre de `pending` entrants par nom de workspace destinataire (badge UI)."""
    by_ws = await amdb.count_pending_by_to_ws(conn, user.login)
    return {_name_from_ws_id(ws_id, user.login): n for ws_id, n in by_ws.items()}


@router.get("/agent-messages/{msg_id}")
async def get_agent_message(
    msg_id: str,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    """Détail d'un message (corps complet, fil des réponses)."""
    msg = await amdb.get_message(conn, msg_id)
    if msg is None or msg["owner_login"] != user.login:
        raise HTTPException(status_code=404, detail="message introuvable")
    return {
        **msg,
        "from_name": _name_from_ws_id(msg["from_ws_id"], user.login),
        "to_name": _name_from_ws_id(msg["to_ws_id"], user.login),
        "replies": await amdb.list_replies(conn, msg_id),
    }


@router.post("/agent-messages/{msg_id}/deliver")
async def deliver_agent_message(
    msg_id: str,
    body: DeliverBody,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    """Transmet un message à une session du workspace destinataire (spec 34 §5).

    Ordre vérification → injection → transition : on ne marque `delivered`
    qu'après une injection réussie. On n'injecte jamais dans le stdin d'un agent
    en plein travail (`processing`). Aucune écriture DB n'est tenue pendant l'I/O
    de session (bug 026) : seul un SELECT précède l'injection.
    """
    # 1. Vérification (fail fast avant toute I/O) : encore pending et bien à nous.
    msg = await amdb.get_message(conn, msg_id)
    if msg is None or msg["owner_login"] != user.login:
        raise HTTPException(status_code=404, detail="message introuvable")
    if msg["status"] != "pending":
        raise HTTPException(status_code=409, detail="message déjà délivré ou annulé")

    to_name = _name_from_ws_id(msg["to_ws_id"], user.login)
    session = body.session

    # 2. Session cible : existante et non occupée. session_get/send n'utilisent
    #    pas `conn` (subprocess ws_exec) — pas de verrou DB tenu pendant l'I/O.
    try:
        info = await _session_get(conn, {"workspace": to_name, "session": session}, user.login)
    except DevpodToolError as exc:
        raise HTTPException(status_code=404, detail=f"session introuvable: {exc}") from exc
    if info.get("processing"):
        raise HTTPException(
            status_code=409,
            detail="Session occupée — réessayer quand l'agent aura rendu la main.",
        )

    # 3. Injection du message encadré.
    framing = _FRAMING.format(
        from_ws=msg["from_ws_id"], mid=msg_id, subject=msg["subject"], body=msg["body"]
    )
    try:
        await _session_send(
            conn,
            {"workspace": to_name, "session": session, "text": framing, "submit": True},
            user.login,
        )
    except DevpodToolError as exc:
        # Session morte entre-temps : le message reste pending, erreur remontée.
        raise HTTPException(
            status_code=409, detail=f"Injection échouée, message toujours en attente: {exc}"
        ) from exc

    # 4. Transition finale (verrou optimiste). rowcount 0 = course perdue :
    #    l'injection a eu lieu, doublon visible accepté (spec §5), pas de corruption.
    delivered = await amdb.mark_delivered(conn, msg_id, user.login, session)
    _log.info(
        "agent_message_delivered",
        msg_id=msg_id,
        to=msg["to_ws_id"],
        session=session,
        raced=not delivered,
    )
    return {"status": "delivered", "delivered_to_session": session}


@router.post("/agent-messages/{msg_id}/cancel")
async def cancel_agent_message(
    msg_id: str,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    """Rejette un message `pending` (→ cancelled)."""
    msg = await amdb.get_message(conn, msg_id)
    if msg is None or msg["owner_login"] != user.login:
        raise HTTPException(status_code=404, detail="message introuvable")
    if not await amdb.mark_cancelled(conn, msg_id, user.login):
        raise HTTPException(status_code=409, detail="message déjà délivré ou annulé")
    _log.info("agent_message_cancelled", msg_id=msg_id)
    return {"status": "cancelled"}

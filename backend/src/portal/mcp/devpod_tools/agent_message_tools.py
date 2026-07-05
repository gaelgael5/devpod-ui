"""MCP tools — messagerie inter-agents à délivrance pilotée (spec 34).

La couche MCP ne connaît que `owner_login` (pas de workspace émetteur ambiant) :
l'agent déclare donc explicitement `from_workspace` (le workspace dans lequel il
tourne). v1 intra-utilisateur : les deux workspaces appartiennent à owner_login.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from ...db import agent_messages as amdb
from ...db.user_config import load_user_db
from .errors import DevpodToolError

_WS_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")

_SEND_NOTE = (
    "La délivrance nécessite une action de l'utilisateur et n'est ni garantie ni "
    "immédiate. Poursuivez vos autres tâches."
)


async def _resolve_ws_id(conn: AsyncConnection, owner_login: str, name: str, field: str) -> str:
    """Valide `name` et vérifie qu'il désigne un workspace de owner_login → ws_id."""
    if not isinstance(name, str) or not _WS_NAME_RE.fullmatch(name):
        raise DevpodToolError(f"{field} invalide: {name!r}")
    cfg = await load_user_db(owner_login, conn)
    if not any(w.name == name for w in cfg.workspaces):
        raise DevpodToolError(f"workspace inconnu pour {field}: {name}")
    return f"{owner_login}-{name}"


async def _message_send(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    from_ws = str(args.get("from_workspace") or "")
    to_ws = str(args.get("to_workspace") or "")
    subject = str(args.get("subject") or "").strip()
    body = str(args.get("body") or "")
    reply_to = args.get("reply_to")
    from_session = args.get("from_session")

    from_ws_id = await _resolve_ws_id(conn, owner_login, from_ws, "from_workspace")
    to_ws_id = await _resolve_ws_id(conn, owner_login, to_ws, "to_workspace")
    if from_ws_id == to_ws_id:
        raise DevpodToolError("un agent ne peut pas s'envoyer un message à lui-même")
    if not subject or len(subject) > 200:
        raise DevpodToolError("subject requis, ≤ 200 caractères")
    if not body or len(body) > 20000:
        raise DevpodToolError("body requis, ≤ 20000 caractères")

    reply_to_id: str | None = None
    if reply_to is not None:
        parent = await amdb.get_message(conn, str(reply_to))
        # On ne répond qu'à un message qu'on a reçu : le workspace émetteur de la
        # réponse doit être le destinataire du message parent (spec 34 §3).
        if (
            parent is None
            or parent["owner_login"] != owner_login
            or parent["to_ws_id"] != from_ws_id
        ):
            raise DevpodToolError(
                "reply_to invalide : message inconnu ou non reçu par ce workspace"
            )
        reply_to_id = parent["id"]

    msg_id = await amdb.create_message(
        conn,
        owner_login=owner_login,
        from_ws_id=from_ws_id,
        to_ws_id=to_ws_id,
        subject=subject,
        body=body,
        from_session=str(from_session) if from_session else None,
        reply_to=reply_to_id,
    )
    return {"message_id": msg_id, "status": "pending", "note": _SEND_NOTE}


async def _message_status(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    msg_id = str(args.get("message_id") or "")
    if not msg_id:
        raise DevpodToolError("message_id requis")
    msg = await amdb.get_message(conn, msg_id)
    # Accessible uniquement à l'émetteur ou au destinataire (ici : même owner).
    if msg is None or msg["owner_login"] != owner_login:
        raise DevpodToolError("message introuvable")
    return {
        "message_id": msg["id"],
        "status": msg["status"],
        "from_workspace": msg["from_ws_id"],
        "to_workspace": msg["to_ws_id"],
        "created_at": msg["created_at"],
        "delivered_at": msg["delivered_at"],
        "delivered_to_session": msg["delivered_to_session"],
        "cancelled_at": msg["cancelled_at"],
        "replies": await amdb.list_replies(conn, msg_id),
    }


async def _message_list(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = str(args.get("workspace") or "")
    ws_id = await _resolve_ws_id(conn, owner_login, name, "workspace")
    direction = str(args.get("direction") or "received")
    if direction not in ("received", "sent", "all"):
        raise DevpodToolError("direction ∈ {received, sent, all}")
    raw_limit = args.get("limit") or 20
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise DevpodToolError(f"limit invalide: {raw_limit!r}") from exc
    if not (1 <= limit <= 100):
        raise DevpodToolError("limit doit être entre 1 et 100")
    msgs = await amdb.list_for_workspace(
        conn, owner_login=owner_login, ws_id=ws_id, direction=direction, limit=limit
    )
    return [
        {
            "message_id": m["id"],
            "status": m["status"],
            "from_workspace": m["from_ws_id"],
            "to_workspace": m["to_ws_id"],
            "subject": m["subject"],
            "body": m["body"],
            "reply_to": m["reply_to"],
            "created_at": m["created_at"],
            "delivered_at": m["delivered_at"],
        }
        for m in msgs
    ]


AGENT_MESSAGE_IMPLS: dict[str, Any] = {
    "message_send": _message_send,
    "message_status": _message_status,
    "message_list": _message_list,
}

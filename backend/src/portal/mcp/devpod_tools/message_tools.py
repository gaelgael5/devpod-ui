"""MCP tools — messages contextuels workspace."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from ...messages import db as mdb
from .errors import DevpodToolError

_MESSAGES_TOOL = "workspace_messages"


async def _workspace_messages(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    ws = str(args.get("workspace") or args.get("workspace_name") or "")
    if not ws:
        raise DevpodToolError("workspace est requis")
    raw_limit = args.get("limit") or 50
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise DevpodToolError(f"paramètre 'limit' invalide, entier attendu: {raw_limit!r}") from exc
    if not (1 <= limit <= 500):
        raise DevpodToolError("limit doit être entre 1 et 500")
    msgs = await mdb.list_messages(conn, owner_login, ws, limit=limit)
    return [
        {
            "id": m.id,
            "type": m.type,
            "message": m.message,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in msgs
    ]


MESSAGE_IMPLS: dict[str, Any] = {
    _MESSAGES_TOOL: _workspace_messages,
}

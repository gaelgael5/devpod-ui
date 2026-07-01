"""Accès DB pour jinja2_template et workspace_message."""
from __future__ import annotations

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db.tables import jinja2_template as _jt
from ..db.tables import workspace_message as _wm
from ..db.tables import workspaces as _ws
from .models import Jinja2Template, WorkspaceMessage

# ─── Jinja2 templates ─────────────────────────────────────────────────────────


async def get_template(conn: AsyncConnection, key: str, culture: str) -> str | None:
    """Retourne le body du template (key, culture), ou None si absent."""
    row = (
        await conn.execute(
            select(_jt.c.body).where((_jt.c.key == key) & (_jt.c.culture == culture))
        )
    ).scalar_one_or_none()
    return row


async def get_template_with_fallback(
    conn: AsyncConnection, key: str, culture: str, fallback: str = "en"
) -> str | None:
    """Résout (key, culture) avec fallback sur (key, fallback_culture)."""
    body = await get_template(conn, key, culture)
    if body is None and culture != fallback:
        body = await get_template(conn, key, fallback)
    return body


async def list_templates(conn: AsyncConnection) -> list[Jinja2Template]:
    rows = (
        await conn.execute(
            select(_jt).order_by(_jt.c.key, _jt.c.culture)
        )
    ).mappings().all()
    return [Jinja2Template(**dict(r)) for r in rows]


async def upsert_template(conn: AsyncConnection, tpl: Jinja2Template) -> None:
    stmt = (
        pg_insert(_jt)
        .values(key=tpl.key, culture=tpl.culture, body=tpl.body)
        .on_conflict_do_update(
            constraint="pk_jinja2_template",
            set_={"body": tpl.body, "updated_at": text("now()")},
        )
    )
    await conn.execute(stmt)


async def delete_template(conn: AsyncConnection, key: str, culture: str) -> None:
    await conn.execute(
        delete(_jt).where((_jt.c.key == key) & (_jt.c.culture == culture))
    )


# ─── Workspace messages ───────────────────────────────────────────────────────


async def create_message(
    conn: AsyncConnection,
    owner_login: str,
    workspace_name: str,
    msg_type: str,
    message: str,
) -> int:
    """Insère un message et retourne son id."""
    result = await conn.execute(
        pg_insert(_wm)
        .values(
            owner_login=owner_login,
            workspace_name=workspace_name,
            type=msg_type,
            message=message,
        )
        .returning(_wm.c.id)
    )
    return result.scalar_one()


async def get_message_by_id(
    conn: AsyncConnection, message_id: int
) -> WorkspaceMessage | None:
    row = (
        await conn.execute(select(_wm).where(_wm.c.id == message_id))
    ).mappings().first()
    return WorkspaceMessage(**dict(row)) if row else None


async def delete_message(conn: AsyncConnection, message_id: int) -> None:
    await conn.execute(delete(_wm).where(_wm.c.id == message_id))


async def list_messages(
    conn: AsyncConnection,
    owner_login: str,
    workspace_name: str,
    limit: int = 50,
) -> list[WorkspaceMessage]:
    rows = (
        await conn.execute(
            select(_wm)
            .where(
                (_wm.c.owner_login == owner_login)
                & (_wm.c.workspace_name == workspace_name)
            )
            .order_by(_wm.c.created_at.desc())
            .limit(limit)
        )
    ).mappings().all()
    return [WorkspaceMessage(**dict(r)) for r in rows]


async def purge_workspace_messages(
    conn: AsyncConnection, owner_login: str, workspace_name: str
) -> int:
    """Supprime tous les messages d'un workspace. Retourne le nombre supprimé."""
    result = await conn.execute(
        delete(_wm).where(
            (_wm.c.owner_login == owner_login)
            & (_wm.c.workspace_name == workspace_name)
        )
    )
    return result.rowcount


async def sweep_orphan_messages(conn: AsyncConnection) -> int:
    """Supprime les messages dont le workspace n'existe plus en DB.

    Retourne le nombre de messages supprimés.
    """
    ws_subq = (
        select(text("1"))
        .where(
            (_ws.c.login == _wm.c.owner_login)
            & (_ws.c.name == _wm.c.workspace_name)
        )
        .correlate(_wm)
        .exists()
    )
    result = await conn.execute(delete(_wm).where(~ws_subq))
    return result.rowcount

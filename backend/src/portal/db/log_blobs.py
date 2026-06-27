"""Persistance des logs de workspace par opération (option B — blob complet)."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import workspace_log_blobs


async def start_log_blob(
    ws_id: str,
    login: str,
    operation: str,
    conn: AsyncConnection,
) -> int:
    """Insère un log blob vide et retourne son id."""
    result = await conn.execute(
        insert(workspace_log_blobs)
        .values(ws_id=ws_id, login=login, operation=operation, content="")
        .returning(workspace_log_blobs.c.id)
    )
    return int(result.scalar_one())


async def finish_log_blob(
    blob_id: int,
    content: str,
    conn: AsyncConnection,
) -> None:
    """Met à jour le contenu et la date de fin d'un log blob existant."""
    await conn.execute(
        update(workspace_log_blobs)
        .where(workspace_log_blobs.c.id == blob_id)
        .values(content=content, finished_at=func.now())
    )


async def persist_log_blob_from_file(
    ws_id: str,
    login: str,
    operation: str,
    log_path: Path,
    conn: AsyncConnection,
) -> None:
    """Lit un fichier log et insère un blob complet (utilisé en post-run)."""
    import contextlib

    content = ""
    with contextlib.suppress(OSError):
        content = log_path.read_text(encoding="utf-8", errors="replace")
    await conn.execute(
        insert(workspace_log_blobs).values(
            ws_id=ws_id,
            login=login,
            operation=operation,
            content=content,
            finished_at=func.now(),
        )
    )


async def list_log_blobs(
    ws_id: str, conn: AsyncConnection
) -> list[dict[str, object]]:
    """Liste les blobs pour un ws_id, du plus récent au plus ancien."""
    rows = (
        await conn.execute(
            select(workspace_log_blobs)
            .where(workspace_log_blobs.c.ws_id == ws_id)
            .order_by(workspace_log_blobs.c.started_at.desc())
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def get_latest_log_blob(
    ws_id: str, operation: str, conn: AsyncConnection
) -> str | None:
    """Retourne le contenu du log le plus récent pour une opération donnée."""
    row = (
        await conn.execute(
            select(workspace_log_blobs.c.content)
            .where(
                (workspace_log_blobs.c.ws_id == ws_id)
                & (workspace_log_blobs.c.operation == operation)
            )
            .order_by(workspace_log_blobs.c.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row


async def delete_log_blobs(ws_id: str, conn: AsyncConnection) -> None:
    """Supprime tous les blobs pour un ws_id (lors de la suppression du workspace)."""
    await conn.execute(
        delete(workspace_log_blobs).where(workspace_log_blobs.c.ws_id == ws_id)
    )

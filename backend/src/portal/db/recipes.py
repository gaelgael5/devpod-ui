"""Persistance recipes (métadonnées uniquement — scripts restent sur filesystem)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from ..recipes.models import RecipeMeta
from .tables import recipes


def _login_key(login: str | None) -> str:
    return login or ""


def _row_to_meta(row: dict[str, Any]) -> RecipeMeta:
    return RecipeMeta.model_validate(
        {
            "id": row["id"],
            "key": row["key"],
            "type": row["type"],
            "version": row["version"],
            "description": row["description"],
            "options": row["options"] or {},
            "requires_secrets": row["requires_secrets"] or [],
            "installs_after": list(row["installs_after"] or []),
        }
    )


async def upsert_recipe_db(
    meta: RecipeMeta,
    scope: str,
    login: str | None,
    conn: AsyncConnection,
) -> None:
    lk = _login_key(login)
    existing = (
        await conn.execute(
            select(recipes.c.id).where(
                (recipes.c.id == meta.id)
                & (recipes.c.scope == scope)
                & (recipes.c.login_key == lk)
            )
        )
    ).scalar_one_or_none()

    vals: dict[str, Any] = {
        "id": meta.id,
        "login_key": lk,
        "scope": scope,
        "login": login,
        "key": meta.key,
        "type": meta.type,
        "version": meta.version,
        "description": meta.description,
        "options": {k: v.model_dump() for k, v in meta.options.items()},
        "requires_secrets": [s.model_dump() for s in meta.requires_secrets],
        "installs_after": list(meta.installs_after),
    }
    if existing is None:
        await conn.execute(insert(recipes).values(**vals))
    else:
        update_vals = {k: v for k, v in vals.items() if k not in ("id", "login_key", "scope")}
        update_vals["updated_at"] = func.now()
        await conn.execute(
            update(recipes)
            .where(
                (recipes.c.id == meta.id)
                & (recipes.c.scope == scope)
                & (recipes.c.login_key == lk)
            )
            .values(**update_vals)
        )


async def list_recipes_db(
    login: str,
    conn: AsyncConnection,
    scope_filter: str | None = None,
) -> list[tuple[str, RecipeMeta]]:
    """Retourne [(scope, RecipeMeta)] pour les recipes visibles par login."""
    cond = (recipes.c.scope == "shared") | (recipes.c.scope == "builtin")
    if login:
        cond = cond | ((recipes.c.scope == "user") & (recipes.c.login_key == login))

    q = select(recipes).where(cond)
    if scope_filter:
        q = q.where(recipes.c.scope == scope_filter)

    rows = (await conn.execute(q)).mappings().all()
    return [(r["scope"], _row_to_meta(dict(r))) for r in rows]


async def get_recipe_db(
    recipe_id: str, scope: str, login: str | None, conn: AsyncConnection
) -> RecipeMeta | None:
    lk = _login_key(login)
    row = (
        await conn.execute(
            select(recipes).where(
                (recipes.c.id == recipe_id)
                & (recipes.c.scope == scope)
                & (recipes.c.login_key == lk)
            )
        )
    ).mappings().one_or_none()
    return _row_to_meta(dict(row)) if row is not None else None


async def delete_recipe_db(
    recipe_id: str, scope: str, login: str | None, conn: AsyncConnection
) -> bool:
    lk = _login_key(login)
    result = await conn.execute(
        delete(recipes).where(
            (recipes.c.id == recipe_id)
            & (recipes.c.scope == scope)
            & (recipes.c.login_key == lk)
        )
    )
    return result.rowcount > 0


async def load_recipes_from_dir_to_db(
    directory: Path, scope: str, login: str | None, conn: AsyncConnection
) -> None:
    """Synchronise filesystem → DB pour un répertoire de recipes. Idempotent."""
    import yaml

    from ..recipes.models import RecipeMeta

    if not directory.exists():
        return
    for entry in sorted(directory.iterdir()):
        if not entry.is_dir():
            continue
        meta_file = entry / "recipe.meta.yaml"
        if not meta_file.exists():
            continue
        try:
            raw: object = yaml.safe_load(meta_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and "category" in raw and "type" not in raw:
                raw = dict(raw)
                raw["type"] = raw.pop("category")
            meta = RecipeMeta.model_validate(raw)
            await upsert_recipe_db(meta, scope, login, conn)
        except Exception as exc:
            import structlog as _sl
            _sl.get_logger(__name__).warning(
                "recipe_sync_skip", path=str(meta_file), error=str(exc)
            )


async def load_recipes_as_dict(
    login: str, conn: AsyncConnection, type_filter: str | None = None
) -> dict[str, RecipeMeta]:
    """Retourne un dict id→RecipeMeta pour toutes les recipes visibles par login."""
    entries = await list_recipes_db(login, conn)
    result: dict[str, RecipeMeta] = {}
    for _scope, meta in entries:
        if type_filter is None or meta.type == type_filter:
            result[meta.id] = meta
    return result

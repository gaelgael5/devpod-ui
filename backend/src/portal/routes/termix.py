"""Registre d'instances Termix — CRUD admin (spec 18 T2).

`GET/POST/PATCH/DELETE /admin/termix-instances`. Une instance = un serveur Termix
(URL + `apikey_secret` = slug d'un secret système portant l'apikey admin `tmx_`,
géré via l'écran secrets). `is_default` : au plus une (invariant DB). L'apikey
n'est jamais renvoyée par ces routes.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..db import termix_instance as ti
from ..db.engine import get_conn

router = APIRouter(tags=["termix-instances"])

_Admin = Annotated[UserInfo, Depends(require_admin)]
_Conn = Annotated[AsyncConnection, Depends(get_conn)]


def _validate_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="url doit être http(s)")
    return url


class InstanceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    url: str
    apikey_secret: str
    oidc_client_id: str = ""
    is_default: bool = False

    @field_validator("name", "apikey_secret")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("valeur requise")
        return v.strip()


class InstanceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    url: str | None = None
    apikey_secret: str | None = None
    oidc_client_id: str | None = None
    is_default: bool | None = None


@router.get("/termix-instances")
async def list_instances(_: _Admin, conn: _Conn) -> list[dict[str, Any]]:
    return await ti.list_all(conn)


@router.post("/termix-instances", status_code=201)
async def create_instance(body: InstanceCreate, _: _Admin, conn: _Conn) -> dict[str, Any]:
    if await ti.name_exists(conn, body.name):
        raise HTTPException(status_code=409, detail=f"nom déjà utilisé : {body.name!r}")
    return await ti.create(
        conn,
        name=body.name,
        url=_validate_url(body.url),
        apikey_secret=body.apikey_secret,
        oidc_client_id=body.oidc_client_id,
        is_default=body.is_default,
    )


@router.patch("/termix-instances/{instance_id}")
async def update_instance_route(
    instance_id: str, body: InstanceUpdate, _: _Admin, conn: _Conn
) -> dict[str, Any]:
    if await ti.get(conn, instance_id) is None:
        raise HTTPException(status_code=404, detail="instance introuvable")
    fields = body.model_dump(exclude_unset=True)
    if "name" in fields and fields["name"] is not None:
        name = str(fields["name"]).strip()
        if not name:
            raise HTTPException(status_code=422, detail="name vide")
        if await ti.name_exists(conn, name, exclude_id=instance_id):
            raise HTTPException(status_code=409, detail=f"nom déjà utilisé : {name!r}")
        fields["name"] = name
    if "url" in fields and fields["url"] is not None:
        fields["url"] = _validate_url(str(fields["url"]))
    updated = await ti.update_instance(conn, instance_id, **fields)
    assert updated is not None
    return updated


@router.delete("/termix-instances/{instance_id}", status_code=204)
async def delete_instance_route(instance_id: str, _: _Admin, conn: _Conn) -> None:
    if not await ti.delete_instance(conn, instance_id):
        raise HTTPException(status_code=404, detail="instance introuvable")

"""Templates de création de workspace — galerie admin, consommation utilisateur.

Cadrage validé le 05/09/2026 : les templates sont gérés par l'admin seulement ;
côté utilisateur l'UI est figée (nom + repo git, le preset fait le reste) et
l'API reste souple (surcharges explicites permises — même précédence que
l'outil MCP : explicite > template > défaut).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin, require_user
from ..config.models import WorkspaceTemplate
from ..db.engine import get_conn
from ..db.workspace_templates import (
    delete_template,
    get_template,
    list_templates,
    upsert_template,
)

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["workspace-templates"])


# ─── Côté utilisateur : la galerie publiée ────────────────────────────────────


@router.get("/workspace-templates")
async def galerie(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, object]]:
    """Les templates publiés — ce que le dialogue de création propose."""
    return [t.model_dump(mode="json") for t in await list_templates(conn, published_only=True)]


# ─── Côté admin : le CRUD de la galerie ──────────────────────────────────────


@router.get("/admin/workspace-templates")
async def lister_admin(
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, object]]:
    return [t.model_dump(mode="json") for t in await list_templates(conn)]


class _TemplateBody(BaseModel):
    """Corps d'upsert — le slug vient de l'URL, seule vérité d'identité."""

    model_config = ConfigDict(extra="forbid")

    label: str = ""
    description: str = ""
    published: bool = False
    spec: dict[str, object] = {}


@router.put("/admin/workspace-templates/{slug}")
async def enregistrer(
    slug: str,
    body: _TemplateBody,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    try:
        template = WorkspaceTemplate.model_validate({"slug": slug, **body.model_dump()})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await upsert_template(template, conn)
    _log.info(
        "workspace_template_saved",
        slug=slug,
        published=template.published,
        by=user.login,
    )
    return template.model_dump(mode="json")


@router.delete("/admin/workspace-templates/{slug}", status_code=204)
async def supprimer(
    slug: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if not await delete_template(slug, conn):
        raise HTTPException(status_code=404, detail=f"template {slug!r} introuvable")
    _log.info("workspace_template_deleted", slug=slug, by=user.login)


# ─── Création d'un workspace depuis un template ──────────────────────────────


class _FromTemplateBody(BaseModel):
    """Le contrat de l'UI figée : le template décide, l'utilisateur nomme."""

    model_config = ConfigDict(extra="forbid")

    template: str
    name: str
    source: str
    branch: str = ""
    host: str = ""
    git_credential: str = ""


@router.post("/me/workspaces/from-template", status_code=201)
async def creer_depuis_template(
    body: _FromTemplateBody,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    """Compose la spec depuis le template publié, puis suit EXACTEMENT le même
    chemin que la création classique (quota compris) — un chemin de création
    qui ne compte pas rendrait le quota contournable."""
    from ..devpod.ws_template import composer_spec
    from .me import enregistrer_workspace

    template = await get_template(body.template, conn)
    if template is None or not template.published:
        # Un brouillon est invisible : même réponse qu'un slug inconnu.
        raise HTTPException(status_code=404, detail=f"template {body.template!r} introuvable")
    surcharges: dict[str, object] = {}
    if body.branch:
        surcharges["branch"] = body.branch
    if body.host:
        surcharges["host"] = body.host
    if body.git_credential:
        surcharges["git_credential"] = body.git_credential
    try:
        spec = composer_spec(template, name=body.name, source=body.source, surcharges=surcharges)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    resultat = await enregistrer_workspace(spec, user, conn)
    _log.info(
        "workspace_added_from_template",
        login=user.login,
        name=body.name,
        template=body.template,
    )
    return resultat

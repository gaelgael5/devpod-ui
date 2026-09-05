# backend/tests/test_workspace_templates.py
"""Templates de création de workspace : merge (explicite > template > défaut),
galerie publiée seulement, chemin from-template qui passe par le même
enregistrement que la création classique, garde-fous MCP."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.auth.rbac import UserInfo, require_admin, require_user
from portal.config.models import (
    WorkspaceSpec,
    WorkspaceTemplate,
    WorkspaceTemplateSpec,
)
from portal.db.engine import get_conn
from portal.devpod.ws_template import composer_spec
from portal.mcp.devpod_tools import DevpodToolError, _workspace_create
from portal.routes import workspace_templates as routes

TEMPLATE = WorkspaceTemplate(
    slug="python-ia",
    label="Python + IA",
    published=True,
    spec=WorkspaceTemplateSpec(
        recipes=["python", "claude-code", "tmux"],
        agents=["claude"],
        memory_limit="8g",
        ssh_key=True,
        branch="main",
    ),
)


# ─── Le merge — la même précédence partout ───────────────────────────────────


def test_le_preset_s_applique_l_utilisateur_ne_donne_que_nom_et_repo() -> None:
    spec = composer_spec(TEMPLATE, name="mon-ws", source="https://git/x.git")
    assert isinstance(spec, WorkspaceSpec)
    assert spec.name == "mon-ws"
    assert spec.source == "https://git/x.git"
    assert spec.recipes == ["python", "claude-code", "tmux"]
    assert spec.agents == ["claude"]
    assert spec.memory_limit == "8g"
    assert spec.ssh_key is True
    assert spec.branch == "main"  # le défaut de branche vient du template


def test_l_explicite_prime_sur_le_template() -> None:
    spec = composer_spec(
        TEMPLATE,
        name="mon-ws",
        source="https://git/x.git",
        surcharges={"branch": "feat", "memory_limit": "4g", "recipes": ["python"]},
    )
    assert spec.branch == "feat"
    assert spec.memory_limit == "4g"
    assert spec.recipes == ["python"]
    assert spec.ssh_key is True  # non surchargé : le preset tient


def test_sans_branche_nulle_part_le_defaut_metier_est_dev() -> None:
    tpl = TEMPLATE.model_copy(update={"spec": WorkspaceTemplateSpec()})
    spec = composer_spec(tpl, name="ws", source="https://git/x.git")
    assert spec.branch == "dev"


def test_les_surcharges_hors_preset_passent_telles_quelles() -> None:
    spec = composer_spec(
        TEMPLATE,
        name="ws",
        source="https://git/x.git",
        surcharges={"host": "node-2", "git_credential": "gh"},
    )
    assert spec.host == "node-2"
    assert spec.git_credential == "gh"


# ─── Routes ───────────────────────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="root", roles=["admin"])
    app.dependency_overrides[require_user] = lambda: UserInfo(login="alice", roles=["dev"])
    app.dependency_overrides[get_conn] = lambda: None
    return TestClient(app)


async def test_la_galerie_ne_montre_que_le_publie(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    vus: dict[str, Any] = {}

    async def _list(conn: Any, *, published_only: bool = False) -> list[WorkspaceTemplate]:
        vus["published_only"] = published_only
        return [TEMPLATE]

    monkeypatch.setattr(routes, "list_templates", _list)
    resp = client.get("/workspace-templates")
    assert resp.status_code == 200
    assert vus["published_only"] is True
    assert resp.json()[0]["slug"] == "python-ia"


async def test_upsert_admin_refuse_un_slug_invalide(client: TestClient) -> None:
    resp = client.put("/admin/workspace-templates/Mauvais_Slug", json={})
    assert resp.status_code == 422


async def test_from_template_suit_le_chemin_d_enregistrement_commun(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _get(slug: str, conn: Any) -> WorkspaceTemplate | None:
        return TEMPLATE if slug == "python-ia" else None

    enregistres: list[WorkspaceSpec] = []

    async def _enregistrer(spec: WorkspaceSpec, user: Any, conn: Any) -> dict[str, Any]:
        enregistres.append(spec)
        return spec.model_dump(mode="json")

    monkeypatch.setattr(routes, "get_template", _get)
    monkeypatch.setattr("portal.routes.me.enregistrer_workspace", _enregistrer)

    resp = client.post(
        "/me/workspaces/from-template",
        json={"template": "python-ia", "name": "mon-ws", "source": "https://git/x.git"},
    )
    assert resp.status_code == 201, resp.text
    (spec,) = enregistres
    assert spec.recipes == ["python", "claude-code", "tmux"]
    assert spec.ssh_key is True
    assert spec.name == "mon-ws"


async def test_from_template_brouillon_invisible(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    brouillon = TEMPLATE.model_copy(update={"published": False})

    async def _get(slug: str, conn: Any) -> WorkspaceTemplate | None:
        return brouillon

    monkeypatch.setattr(routes, "get_template", _get)
    resp = client.post(
        "/me/workspaces/from-template",
        json={"template": "python-ia", "name": "ws", "source": "https://git/x.git"},
    )
    # Même réponse qu'un slug inconnu : un brouillon n'existe pas côté user.
    assert resp.status_code == 404


# ─── MCP : les garde-fous de l'argument template ─────────────────────────────


async def test_mcp_template_et_based_on_exclusifs() -> None:
    with pytest.raises(DevpodToolError) as exc:
        await _workspace_create(None, {"name": "ws", "template": "t", "based_on": "autre"}, "alice")
    assert "exclusifs" in str(exc.value)


async def test_mcp_template_introuvable_ou_brouillon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _get(slug: str, conn: Any) -> WorkspaceTemplate | None:
        return TEMPLATE.model_copy(update={"published": False})

    monkeypatch.setattr("portal.db.workspace_templates.get_template", _get)
    with pytest.raises(DevpodToolError) as exc:
        await _workspace_create(None, {"name": "ws", "template": "python-ia"}, "alice")
    assert "introuvable" in str(exc.value)


async def test_mcp_template_exige_le_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _get(slug: str, conn: Any) -> WorkspaceTemplate | None:
        return TEMPLATE

    monkeypatch.setattr("portal.db.workspace_templates.get_template", _get)
    with pytest.raises(DevpodToolError) as exc:
        await _workspace_create(None, {"name": "ws", "template": "python-ia"}, "alice")
    assert "repo" in str(exc.value)

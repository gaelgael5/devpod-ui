"""API d'application des recettes de host.

Le point sensible est l'exposition : cette API déclenche de l'exécution
privilégiée à distance. La recette est désignée par son identifiant de
catalogue — jamais par un chemin ni une commande transitant dans la requête.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.auth.rbac import UserInfo, require_admin
from portal.config.models import HostConfig
from portal.db.engine import get_conn
from portal.recipes.models import RecipeMeta
from portal.routes import host_recipes


def _host(usage: str = "tests") -> HostConfig:
    return HostConfig(name="test1", type="ssh", address="root@10.0.0.1", usage=usage)


def _recipes() -> dict[str, RecipeMeta]:
    return {
        "android-emulator": RecipeMeta.model_validate(
            {
                "id": "android-emulator",
                "version": "1.2.0",
                "scope": "host",
                "host_usages": ["tests"],
                "options": {"api": {"default": "35"}},
            }
        ),
        "prometheus": RecipeMeta.model_validate(
            {"id": "prometheus", "scope": "host", "host_usages": ["ressources"]}
        ),
        "python": RecipeMeta.model_validate({"id": "python"}),
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(host_recipes.router, prefix="/admin")
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="admin", roles=["admin"])
    # Aucun accès DB dans ces tests : le catalogue est injecté plus bas.
    app.dependency_overrides[get_conn] = lambda: None

    monkeypatch.setattr(
        host_recipes, "_load_host", lambda name: _host() if name == "test1" else None
    )

    async def _catalogue(login: str, conn: Any) -> dict[str, RecipeMeta]:
        return _recipes()

    monkeypatch.setattr(host_recipes, "_load_host_recipes", _catalogue)

    # Le contexte du workspace se lit en base : ici on n'en a pas, et une
    # machine sans workspace rattache est un cas normal (AC4 du ticket 29f3c418).
    async def _contexte(host_name: str, conn: Any) -> dict[str, str] | None:
        return None

    monkeypatch.setattr(host_recipes, "workspace_context_for_host", _contexte)
    return TestClient(app)


class TestCatalogue:
    def test_ne_propose_que_les_recettes_de_la_famille(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `prometheus` vise 'ressources', `python` est une recette de workspace :
        # ni l'une ni l'autre ne doit apparaître pour un serveur de test.
        monkeypatch.setattr(host_recipes, "_probe_state", _stub_state({}))

        res = client.get("/admin/hosts/test1/recipes")

        assert res.status_code == 200
        assert [r["id"] for r in res.json()["available"]] == ["android-emulator"]

    def test_remonte_ce_qui_est_deja_pose(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            host_recipes,
            "_probe_state",
            _stub_state({"android-emulator": {"version": "1.0.0", "applied_at": "2026-01-01"}}),
        )

        installed = client.get("/admin/hosts/test1/recipes").json()["installed"]

        assert installed["android-emulator"]["version"] == "1.0.0"

    def test_host_inconnu(self, client: TestClient) -> None:
        assert client.get("/admin/hosts/fantome/recipes").status_code == 404


class TestApplication:
    def test_lance_une_operation(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        # Une recette de 20 Go depasse tout timeout HTTP : la requete rend la
        # main sur un identifiant d'operation, jamais sur le resultat.
        monkeypatch.setattr(host_recipes, "_read_install_script", lambda _id, _login: "echo ok")
        monkeypatch.setattr(host_recipes, "_launch", _stub_launch("op-123"))

        res = client.post("/admin/hosts/test1/recipes/android-emulator")

        assert res.status_code == 202
        assert res.json()["operation_id"] == "op-123"

    def test_refuse_une_recette_hors_famille(self, client: TestClient) -> None:
        res = client.post("/admin/hosts/test1/recipes/prometheus")

        assert res.status_code == 422
        assert "famille" in res.json()["detail"]

    def test_refuse_une_recette_de_workspace(self, client: TestClient) -> None:
        # Le catalogue existant ne doit jamais devenir applicable sur une machine.
        res = client.post("/admin/hosts/test1/recipes/python")

        assert res.status_code == 422

    def test_recette_inconnue(self, client: TestClient) -> None:
        assert client.post("/admin/hosts/test1/recipes/fantome").status_code == 404

    def test_identifiant_invalide_rejete_avant_tout(self, client: TestClient) -> None:
        # Désignation par identifiant de catalogue : ni chemin, ni commande.
        res = client.post("/admin/hosts/test1/recipes/..%2F..%2Fetc%2Fpasswd")

        assert res.status_code in (404, 422)

    def test_script_absent(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(host_recipes, "_read_install_script", lambda _id, _login: None)

        res = client.post("/admin/hosts/test1/recipes/android-emulator")

        assert res.status_code == 422
        assert "install.sh" in res.json()["detail"]


def _stub_state(etat: dict[str, dict[str, str]]):
    async def _probe(host: HostConfig) -> dict[str, Any]:
        return etat

    return _probe


def _stub_launch(oid: str):
    async def _launch(**kwargs: Any) -> str:
        return oid

    return _launch


class TestParametres:
    def test_refuse_une_option_non_declaree_avant_de_lancer(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Une option invalide n'a pas a etre decouverte dans le journal d'une
        # operation lancee pour rien.
        lance = False

        async def _jamais(**kwargs: Any) -> str:
            nonlocal lance
            lance = True
            return "op"

        monkeypatch.setattr(host_recipes, "_launch", _jamais)
        monkeypatch.setattr(host_recipes, "_read_install_script", lambda _id, _login: "echo ok")

        res = client.post(
            "/admin/hosts/test1/recipes/android-emulator", json={"options": {"boom": "x"}}
        )

        assert res.status_code == 422
        assert lance is False

    def test_transmet_les_options_declarees(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(host_recipes, "_read_install_script", lambda _id, _login: "echo ok")
        monkeypatch.setattr(host_recipes, "_launch", _stub_launch("op-7"))

        res = client.post(
            "/admin/hosts/test1/recipes/android-emulator", json={"options": {"api": "34"}}
        )

        assert res.status_code == 202


class TestLectureDuScript:
    """`_read_install_script` s'exerce ici SANS mock : c'est le mock qui avait
    laisse passer un appel avec un login vide, ou `safe_user_path` leve — un 500
    la ou on attendait « recette introuvable »."""

    def test_login_valide_et_recette_absente_rend_none(self) -> None:
        # Le comportement attendu : None, jamais une exception.
        assert host_recipes._read_install_script("recette-qui-nexiste-pas", "admin") is None

    def test_login_vide_ferait_lever_la_garde(self) -> None:
        # Ce que faisait le code avant correction. On le documente pour que le
        # jour ou quelqu'un re-simplifie l'appel, le test le rattrape.
        with pytest.raises(ValueError, match="Invalid login"):
            host_recipes.locate_recipe_dir("", "android-emulator")


class TestContexteWorkspace:
    """Ticket 29f3c418 — le depot a builder appartient au WORKSPACE.

    La recette le DECLARE (`from: workspace.git_url`) ; le portail lui fournit
    la valeur. On capture le `work` remis a l'operation et on le joue : c'est le
    seul point ou le contexte se voit.
    """

    @staticmethod
    def _capture(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        capture: dict[str, Any] = {}

        async def _launch(**kwargs: Any) -> str:
            capture["work"] = kwargs["work"]
            return "op-ctx"

        async def _apply(meta: Any, **kwargs: Any) -> Any:
            capture["kwargs"] = kwargs

            class _R:
                changed = True
                version = "1.0.0"
                output = ""

            return _R()

        async def _emit(*args: Any, **kwargs: Any) -> None:
            return None

        monkeypatch.setattr(host_recipes, "_launch", _launch)
        monkeypatch.setattr(host_recipes, "apply_recipe_to_host", _apply)
        monkeypatch.setattr(host_recipes, "emit_event", _emit)
        monkeypatch.setattr(host_recipes, "_read_install_script", lambda _id, _login: "echo ok")
        return capture

    def test_transmet_le_contexte_du_workspace(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        contexte = {
            "workspace.id": "admin-termix-mobile",
            "workspace.git_url": "https://github.com/ag-flow/termix-mobile.git",
            "workspace.git_ref": "main",
        }

        async def _contexte(host_name: str, conn: Any) -> dict[str, str] | None:
            assert host_name == "test1"
            return contexte

        monkeypatch.setattr(host_recipes, "workspace_context_for_host", _contexte)
        capture = self._capture(monkeypatch)

        res = client.post("/admin/hosts/test1/recipes/android-emulator", json={"options": {}})
        assert res.status_code in (200, 202)

        asyncio.run(capture["work"]())
        assert capture["kwargs"]["context"] == contexte

    def test_machine_sans_workspace_ne_passe_aucun_contexte(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un host de workspaces ou un serveur de ressources n'a pas de depot a
        faire connaitre — ce n'est pas une erreur."""
        capture = self._capture(monkeypatch)

        res = client.post("/admin/hosts/test1/recipes/android-emulator", json={"options": {}})
        assert res.status_code in (200, 202)

        asyncio.run(capture["work"]())
        assert capture["kwargs"]["context"] is None

"""Les routes /me/* — profil, config, workspaces, git-credentials.

Réécrite sur le modèle des suites qui marchent (dette 99c91952) : APP MINIMALE
(le seul router `me`, pas `create_app()` et son lifespan), moteur global posé
par `db_engine_pool`, et `httpx.AsyncClient` sur ASGITransport — tout vit dans
LA MÊME boucle d'événements que les fixtures. C'est ce qui manquait à l'ancienne
suite : `create_app()` + `TestClient` multipliaient les boucles et le moteur
asyncpg fuyait de test en test.

`db_conn` (pool 1) est volontairement absent : ces routes ouvrent leurs propres
connexions via le moteur global — exactement le cas que `db_engine_pool` existe
pour couvrir.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from portal.auth.rbac import UserInfo, require_user
from portal.config.store import load_user
from portal.routes.me import router as me_router


@pytest.fixture
async def app_me(
    db_engine_pool, postgres_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> FastAPI:
    """App minimale + alice provisionnée (row users, dossiers, secret_ns)."""
    import portal.settings as mod

    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret-key-32chars-minimum!!")
    # provision_user ne fait l'upsert de la row users QUE si DATABASE_URL est
    # posé — le moteur global, lui, est déjà celui de db_engine_pool.
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    mod._settings = None

    from portal.auth.router import provision_user

    await provision_user(login="alice", sub="sub-alice", data_root=tmp_path)

    app = FastAPI()
    # SessionMiddleware : `_sid()` (reveal vault) et `require_user` lisent
    # request.session — sans lui, 500 au lieu du comportement réel.
    from starlette.middleware.sessions import SessionMiddleware

    app.add_middleware(SessionMiddleware, secret_key="test-secret-key-32chars-minimum!!")
    app.include_router(me_router, prefix="/me")
    yield app
    mod._settings = None


def _en_dev(app: FastAPI, role: str = "dev") -> FastAPI:
    app.dependency_overrides[require_user] = lambda: UserInfo(login="alice", roles=[role])
    return app


@pytest.fixture
async def client(app_me: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=_en_dev(app_me)), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture
async def client_admin(app_me: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=_en_dev(app_me, role="admin")), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture
def dev_mode(monkeypatch: pytest.MonkeyPatch):
    """DEV_MODE (vault désactivé) pour les routes qui touchent la table users."""
    import portal.settings as mod

    monkeypatch.setenv("DEV_MODE", "true")
    mod._settings = None
    yield
    mod._settings = None


# ─── /me ─────────────────────────────────────────────────────────────────────


async def test_get_me_returns_login_and_roles(client: AsyncClient) -> None:
    resp = await client.get("/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["login"] == "alice"
    assert data["roles"] == ["dev"]
    assert data["is_admin"] is False


async def test_get_me_admin_returns_admin_role(client_admin: AsyncClient) -> None:
    resp = await client_admin.get("/me")
    assert resp.status_code == 200
    assert "admin" in resp.json()["roles"]
    # is_admin est calculé côté serveur contre settings.oidc_admin_role.
    assert resp.json()["is_admin"] is True


async def test_get_me_config_returns_user_config(client: AsyncClient) -> None:
    resp = await client.get("/me/config")
    assert resp.status_code == 200
    assert "secret_ns" in resp.json()


async def test_put_me_config_updates_defaults(client: AsyncClient) -> None:
    payload = {"defaults": {"ide": "openvscode", "idle_timeout": "2h"}}
    resp = await client.put("/me/config", json=payload)
    assert resp.status_code == 200


async def test_put_me_config_rejects_unknown_field(client: AsyncClient) -> None:
    resp = await client.put("/me/config", json={"unknown_field": "value"})
    assert resp.status_code == 422


async def test_put_me_config_rejects_secret_ns_rewrite(client: AsyncClient, dev_mode) -> None:
    """Bug 008 : secret_ns est un champ valide de UserConfig — sans allowlist,
    pydantic le laisserait passer et un client pourrait réécrire son namespace
    de secrets. Doit être rejeté avant même de toucher load_user/save_user."""
    import uuid

    resp = await client.put("/me/config", json={"secret_ns": str(uuid.uuid4())})
    assert resp.status_code == 422
    assert "secret_ns" in resp.json()["detail"]


async def test_put_me_config_allows_culture_field(client: AsyncClient, dev_mode) -> None:
    resp = await client.put("/me/config", json={"culture": "en"})
    assert resp.status_code == 200
    assert resp.json()["culture"] == "en"


# ─── PATCH /me/profile (exigés par 67ecbae1) ─────────────────────────────────


async def test_patch_profile_updates_email(client: AsyncClient, dev_mode) -> None:
    resp = await client.patch("/me/profile", json={"email": "gaelgael5@gmail.com"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "gaelgael5@gmail.com"
    # Persisté : un GET ultérieur renvoie la même valeur.
    relu = await client.get("/me/profile")
    assert relu.json()["email"] == "gaelgael5@gmail.com"


async def test_patch_profile_rejects_invalid_email(client: AsyncClient, dev_mode) -> None:
    resp = await client.patch("/me/profile", json={"email": "pas-un-email"})
    assert resp.status_code == 422
    assert "email" in resp.json()["detail"]


async def test_patch_profile_updates_email_and_display_name(client: AsyncClient, dev_mode) -> None:
    resp = await client.patch("/me/profile", json={"email": "a@b.io", "display_name": "Gaël"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "a@b.io"
    assert body["display_name"] == "Gaël"


async def test_patch_profile_allows_clearing_email(client: AsyncClient, dev_mode) -> None:
    """Chaîne vide = efface l'email (pas de validation de format sur le vide)."""
    resp = await client.patch("/me/profile", json={"email": ""})
    assert resp.status_code == 200


async def test_patch_profile_rejects_login_field(client: AsyncClient, dev_mode) -> None:
    """Le login est immuable : extra='forbid' rejette toute tentative de le modifier."""
    resp = await client.patch("/me/profile", json={"login": "someone-else"})
    assert resp.status_code == 422


async def test_patch_profile_rejects_empty_patch(client: AsyncClient, dev_mode) -> None:
    resp = await client.patch("/me/profile", json={})
    assert resp.status_code == 422


# ─── /me/workspaces ──────────────────────────────────────────────────────────


async def test_get_me_workspaces_returns_empty_list(client: AsyncClient) -> None:
    resp = await client.get("/me/workspaces")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_post_me_workspace_adds_workspace(client: AsyncClient) -> None:
    ws = {"name": "myapp", "source": "git@github.com:user/repo.git"}
    resp = await client.post("/me/workspaces", json=ws)
    assert resp.status_code == 201
    resp2 = await client.get("/me/workspaces")
    assert any(w["name"] == "myapp" for w in resp2.json())


async def test_delete_me_workspace_removes_workspace(client: AsyncClient) -> None:
    ws = {"name": "todelete", "source": "git@github.com:user/repo.git"}
    await client.post("/me/workspaces", json=ws)
    resp = await client.delete("/me/workspaces/todelete")
    assert resp.status_code == 200
    resp2 = await client.get("/me/workspaces")
    assert not any(w["name"] == "todelete" for w in resp2.json())


async def test_patch_workspace_agents_updates_agents(client: AsyncClient) -> None:
    ws = {"name": "myapp", "source": "git@github.com:user/repo.git"}
    await client.post("/me/workspaces", json=ws)
    resp = await client.patch("/me/workspaces/myapp/agents", json={"agents": ["claude"]})
    assert resp.status_code == 200
    assert resp.json()["agents"] == ["claude"]
    resp2 = await client.get("/me/workspaces")
    stored = next(w for w in resp2.json() if w["name"] == "myapp")
    assert stored["agents"] == ["claude"]


async def test_patch_workspace_agents_preserves_other_fields(client: AsyncClient) -> None:
    ws = {"name": "myapp", "source": "git@github.com:user/repo.git", "branch": "main"}
    await client.post("/me/workspaces", json=ws)
    resp = await client.patch("/me/workspaces/myapp/agents", json={"agents": []})
    assert resp.status_code == 200
    assert resp.json()["source"] == "git@github.com:user/repo.git"
    assert resp.json()["branch"] == "main"


async def test_patch_workspace_agents_unknown_workspace_404(client: AsyncClient) -> None:
    resp = await client.patch("/me/workspaces/ghost/agents", json={"agents": ["claude"]})
    assert resp.status_code == 404


async def test_patch_workspace_agents_rejects_invalid_id(client: AsyncClient) -> None:
    ws = {"name": "myapp", "source": "git@github.com:user/repo.git"}
    await client.post("/me/workspaces", json=ws)
    resp = await client.patch("/me/workspaces/myapp/agents", json={"agents": ["Bad Id!"]})
    assert resp.status_code == 422


async def test_patch_workspace_agents_rejects_unknown_field(client: AsyncClient) -> None:
    ws = {"name": "myapp", "source": "git@github.com:user/repo.git"}
    await client.post("/me/workspaces", json=ws)
    resp = await client.patch(
        "/me/workspaces/myapp/agents", json={"agents": ["claude"], "host": "x"}
    )
    assert resp.status_code == 422


# ─── PATCH /me/workspaces/{name} — édition de la config d'un workspace ────────


async def test_patch_workspace_updates_config_and_flags_recreate(client: AsyncClient) -> None:
    """Ajouter une recette impose une recréation : c'est une feature devcontainer,
    elle n'existe nulle part tant que l'image n'est pas reconstruite."""
    ws = {"name": "myapp", "source": "git@github.com:user/repo.git", "recipes": ["python"]}
    await client.post("/me/workspaces", json=ws)
    resp = await client.patch("/me/workspaces/myapp", json={"recipes": ["python", "claude-code"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["requires_recreate"] == ["recipes"]
    assert body["added_recipes"] == ["claude-code"]
    assert body["spec"]["recipes"] == ["python", "claude-code"]


async def test_patch_workspace_persists_the_change(client: AsyncClient) -> None:
    ws = {"name": "myapp", "source": "git@github.com:user/repo.git"}
    await client.post("/me/workspaces", json=ws)
    await client.patch("/me/workspaces/myapp", json={"memory_limit": "2g"})
    stored = next(w for w in (await client.get("/me/workspaces")).json() if w["name"] == "myapp")
    assert stored["memory_limit"] == "2g"


async def test_patch_workspace_partial_never_erases_other_fields(client: AsyncClient) -> None:
    """Un PATCH partiel ne doit pas effacer le reste de la config — même piège que
    celui déjà corrigé sur POST /workspaces/{name}/up."""
    ws = {
        "name": "myapp",
        "source": "git@github.com:user/repo.git",
        "branch": "main",
        "recipes": ["python"],
        "agents": ["claude"],
    }
    await client.post("/me/workspaces", json=ws)
    resp = await client.patch("/me/workspaces/myapp", json={"branch": "feature/x"})
    spec = resp.json()["spec"]
    assert spec["branch"] == "feature/x"
    assert spec["source"] == "git@github.com:user/repo.git"
    assert spec["recipes"] == ["python"]
    assert spec["agents"] == ["claude"]


async def test_patch_workspace_restart_only_change_is_not_a_recreate(
    client: AsyncClient,
) -> None:
    ws = {"name": "myapp", "source": "git@github.com:user/repo.git", "branch": "main"}
    await client.post("/me/workspaces", json=ws)
    resp = await client.patch("/me/workspaces/myapp", json={"branch": "dev"})
    body = resp.json()
    assert body["requires_recreate"] == []
    assert body["requires_restart"] == ["branch"]


async def test_patch_workspace_noop_reports_no_impact(client: AsyncClient) -> None:
    ws = {"name": "myapp", "source": "git@github.com:user/repo.git", "recipes": ["python"]}
    await client.post("/me/workspaces", json=ws)
    resp = await client.patch("/me/workspaces/myapp", json={"recipes": ["python"]})
    body = resp.json()
    assert body["requires_recreate"] == []
    assert body["requires_restart"] == []
    assert body["added_recipes"] == []


async def test_patch_workspace_unknown_returns_404(client: AsyncClient) -> None:
    resp = await client.patch("/me/workspaces/ghost", json={"branch": "x"})
    assert resp.status_code == 404


async def test_patch_workspace_rejects_rename_and_unknown_fields(client: AsyncClient) -> None:
    """`name` est hors du modèle : renommer changerait le ws_id, donc l'identité
    du conteneur — ce n'est pas une édition de config."""
    ws = {"name": "myapp", "source": "git@github.com:user/repo.git"}
    await client.post("/me/workspaces", json=ws)
    assert (await client.patch("/me/workspaces/myapp", json={"name": "autre"})).status_code == 422
    assert (await client.patch("/me/workspaces/myapp", json={"nope": 1})).status_code == 422


async def test_patch_workspace_rejects_invalid_value(client: AsyncClient) -> None:
    ws = {"name": "myapp", "source": "git@github.com:user/repo.git"}
    await client.post("/me/workspaces", json=ws)
    resp = await client.patch("/me/workspaces/myapp", json={"memory_limit": "beaucoup"})
    assert resp.status_code == 422


# ─── /me/git-credentials — le contrat VAULT ──────────────────────────────────
# L'ancienne section testait un contrat DISPARU (token/clef privée inline,
# generate_key, endpoints public-key) : depuis la bascule vault, un credential
# RÉFÉRENCE un secret (`secret_slug`) ou un certificat (`cert_slug`) du
# gestionnaire — la valeur est révélée côté serveur, session déverrouillée.

_MASTER_KEY = b"0" * 32

_PEM = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "dGVzdC1rZXktZm9yLXRlc3Rpbmctb25seQ==\n"
    "-----END OPENSSH PRIVATE KEY-----"
)


@pytest.fixture
def vault_ouvert(monkeypatch: pytest.MonkeyPatch) -> bytes:
    """Session vault déverrouillée : les deux services (secrets, certificats)
    lisent la master key par `vault.session.get_master_key`."""
    from portal.vault import session as vault_session

    monkeypatch.setattr(vault_session, "get_master_key", lambda sid: _MASTER_KEY)
    return _MASTER_KEY


async def _seed_secret(slug: str = "gh-token", valeur: str = "ghp_old") -> None:
    from sqlalchemy import insert

    from portal.db.engine import _get_engine
    from portal.db.tables import harpo_secrets
    from portal.vault.crypto import encrypt_token

    async with _get_engine().begin() as conn:
        await conn.execute(
            insert(harpo_secrets).values(
                slug=slug,
                label=slug,
                description="",
                secret_type="CI_PASSWORD",
                secret_value_local=encrypt_token(valeur, _MASTER_KEY),
                secret_value_vault_ref=None,
                storage_type="local",
                vault_identifier="",
                owner_login="alice",
                is_public=False,
            )
        )


async def _seed_cert(slug: str = "gl-key") -> None:
    from sqlalchemy import insert

    from portal.db.engine import _get_engine
    from portal.db.tables import harpo_certificates
    from portal.vault.crypto import encrypt_token

    async with _get_engine().begin() as conn:
        await conn.execute(
            insert(harpo_certificates).values(
                slug=slug,
                label=slug,
                description="",
                cert_type="ssh-ed25519",
                public_key="ssh-ed25519 AAAA",
                private_key_local=encrypt_token(_PEM, _MASTER_KEY),
                private_key_vault_ref=None,
                storage_type="local",
                vault_identifier="",
                owner_login="alice",
                is_public=False,
            )
        )


async def _add_token_cred(client: AsyncClient, name: str = "gh") -> None:
    resp = await client.post(
        "/me/git-credentials",
        json={
            "name": name,
            "host": "github.com",
            "kind": "token",
            "username": "oauth2",
            "secret_slug": "gh-token",
        },
    )
    assert resp.status_code == 201, resp.text


async def test_create_token_cred_reveals_and_stores(client: AsyncClient, vault_ouvert) -> None:
    await _seed_secret()
    await _add_token_cred(client)

    cfg = await load_user("alice")
    assert cfg.git_credentials[0].token == "ghp_old"
    assert cfg.git_credentials[0].kind == "token"


async def test_get_git_credentials_includes_username(client: AsyncClient, vault_ouvert) -> None:
    await _seed_secret()
    await _add_token_cred(client)

    resp = await client.get("/me/git-credentials")

    assert resp.status_code == 200
    creds = resp.json()
    assert len(creds) == 1
    assert creds[0]["username"] == "oauth2"
    # La valeur du token n'est JAMAIS servie par le listing.
    assert "token" not in creds[0]


async def test_create_ssh_cred_writes_key_file(client: AsyncClient, vault_ouvert) -> None:
    await _seed_cert()

    resp = await client.post(
        "/me/git-credentials",
        json={"name": "gl-ssh", "host": "gitlab.com", "kind": "ssh", "cert_slug": "gl-key"},
    )

    assert resp.status_code == 201, resp.text
    cfg = await load_user("alice")
    cred = cfg.git_credentials[0]
    assert cred.kind == "ssh"
    assert cred.key_path != ""
    assert Path(cred.key_path).read_text().strip() == _PEM


async def test_vault_verrouille_rend_403(client: AsyncClient) -> None:
    """Sans session déverrouillée, on ne révèle RIEN — et on le dit."""
    resp = await client.post(
        "/me/git-credentials",
        json={"name": "gh", "host": "github.com", "kind": "token", "secret_slug": "gh-token"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "vault_locked"


async def test_secret_slug_inconnu_rend_404(client: AsyncClient, vault_ouvert) -> None:
    resp = await client.post(
        "/me/git-credentials",
        json={"name": "gh", "host": "github.com", "kind": "token", "secret_slug": "fantome"},
    )
    assert resp.status_code == 404


async def test_token_sans_secret_slug_rend_422(client: AsyncClient, vault_ouvert) -> None:
    resp = await client.post(
        "/me/git-credentials", json={"name": "gh", "host": "github.com", "kind": "token"}
    )
    assert resp.status_code == 422


async def test_duplicate_name_returns_409(client: AsyncClient, vault_ouvert) -> None:
    await _seed_secret()
    await _add_token_cred(client)

    resp = await client.post(
        "/me/git-credentials",
        json={"name": "gh", "host": "github.com", "kind": "token", "secret_slug": "gh-token"},
    )
    assert resp.status_code == 409


async def test_patch_git_credential_updates_host(client: AsyncClient, vault_ouvert) -> None:
    await _seed_secret()
    await _add_token_cred(client)

    resp = await client.patch("/me/git-credentials/gh", json={"host": "github.enterprise.com"})

    assert resp.status_code == 200
    assert resp.json()["host"] == "github.enterprise.com"
    creds = (await client.get("/me/git-credentials")).json()
    assert creds[0]["host"] == "github.enterprise.com"


async def test_patch_git_credential_token_to_ssh(client: AsyncClient, vault_ouvert) -> None:
    await _seed_secret()
    await _seed_cert()
    await _add_token_cred(client)

    resp = await client.patch("/me/git-credentials/gh", json={"kind": "ssh", "cert_slug": "gl-key"})

    assert resp.status_code == 200
    cfg = await load_user("alice")
    cred = cfg.git_credentials[0]
    assert cred.kind == "ssh"
    assert cred.token == ""
    assert cred.key_path != ""


async def test_patch_git_credential_ssh_to_token(client: AsyncClient, vault_ouvert) -> None:
    """Le passage en PAT efface la clef privée du disque : une clef orpheline
    qui traîne est une clef qu'on ne sait plus revoquer."""
    await _seed_secret()
    await _seed_cert()
    await client.post(
        "/me/git-credentials",
        json={"name": "gl-ssh", "host": "gitlab.com", "kind": "ssh", "cert_slug": "gl-key"},
    )
    key_path_avant = (await load_user("alice")).git_credentials[0].key_path

    resp = await client.patch(
        "/me/git-credentials/gl-ssh", json={"kind": "token", "secret_slug": "gh-token"}
    )

    assert resp.status_code == 200
    cred = (await load_user("alice")).git_credentials[0]
    assert cred.kind == "token"
    assert cred.token == "ghp_old"
    assert cred.key_path == ""
    assert not Path(key_path_avant).exists()


async def test_patch_git_credential_rename_cascades_workspaces(
    client: AsyncClient, vault_ouvert
) -> None:
    await _seed_secret()
    await _add_token_cred(client)
    await client.post(
        "/me/workspaces",
        json={
            "name": "myapp",
            "source": "github.com/org/repo",
            "git_credential": "gh",
            "extra_sources": [{"url": "github.com/org/lib", "git_credential": "gh"}],
        },
    )

    resp = await client.patch("/me/git-credentials/gh", json={"new_name": "github"})

    assert resp.status_code == 200
    assert resp.json()["name"] == "github"
    cfg = await load_user("alice")
    ws = cfg.workspaces[0]
    assert ws.git_credential == "github"
    assert ws.extra_sources[0].git_credential == "github"


async def test_patch_git_credential_ssh_rename_moves_key_file(
    client: AsyncClient, vault_ouvert
) -> None:
    await _seed_cert()
    await client.post(
        "/me/git-credentials",
        json={"name": "gl-ssh", "host": "gitlab.com", "kind": "ssh", "cert_slug": "gl-key"},
    )
    old_key_path = Path((await load_user("alice")).git_credentials[0].key_path)

    resp = await client.patch("/me/git-credentials/gl-ssh", json={"new_name": "gitlab-ssh"})

    assert resp.status_code == 200
    cred = (await load_user("alice")).git_credentials[0]
    assert cred.name == "gitlab-ssh"
    assert "gitlab-ssh" in cred.key_path
    assert Path(cred.key_path).exists()
    assert not old_key_path.exists()


async def test_patch_git_credential_duplicate_name_returns_409(
    client: AsyncClient, vault_ouvert
) -> None:
    await _seed_secret()
    await _add_token_cred(client, name="gh")
    await _add_token_cred(client, name="gh2")

    resp = await client.patch("/me/git-credentials/gh", json={"new_name": "gh2"})

    assert resp.status_code == 409


async def test_patch_git_credential_not_found_returns_404(client: AsyncClient) -> None:
    resp = await client.patch("/me/git-credentials/nope", json={"host": "example.com"})
    assert resp.status_code == 404


async def test_patch_git_credential_invalid_new_name_returns_422(
    client: AsyncClient, vault_ouvert
) -> None:
    await _seed_secret()
    await _add_token_cred(client)

    resp = await client.patch("/me/git-credentials/gh", json={"new_name": "a"})

    assert resp.status_code == 422


async def test_delete_git_credential_removes_it(client: AsyncClient, vault_ouvert) -> None:
    await _seed_secret()
    await _add_token_cred(client)

    resp = await client.delete("/me/git-credentials/gh")

    assert resp.status_code == 200
    assert (await client.get("/me/git-credentials")).json() == []


# ─── Auth ────────────────────────────────────────────────────────────────────


async def test_require_user_blocks_unauthenticated(app_me: FastAPI) -> None:
    """SANS override : la vraie dépendance `require_user` doit rendre 401 —
    l'app minimale suffit, la garde vit sur le router, pas dans create_app()."""
    async with AsyncClient(transport=ASGITransport(app=app_me), base_url="http://test") as c:
        resp = await c.get("/me/config")
    assert resp.status_code == 401


# ─── Bornage mémoire au plafond du nœud (fiche max_memory) ───────────────────


class TestBornageMemoire:
    """Le cœur de l'application du plafond `hosts.max_memory` à la création et à
    l'édition d'un workspace (fiche 1dae864d)."""

    def _doubler_hosts(self, monkeypatch, max_memory: str) -> None:
        from types import SimpleNamespace

        import portal.config.store as store

        host = SimpleNamespace(name="node-a", max_memory=max_memory)
        monkeypatch.setattr(store, "load_global", lambda: SimpleNamespace(hosts=[host]))

    def test_une_demande_au_dessus_du_plafond_est_refusee(self, monkeypatch) -> None:
        from fastapi import HTTPException

        from portal.routes.me import _borner_memoire

        self._doubler_hosts(monkeypatch, "4g")
        with pytest.raises(HTTPException) as exc:
            _borner_memoire("node-a", "8g")
        assert exc.value.status_code == 422
        assert "4g" in exc.value.detail

    def test_a_egalite_la_demande_passe(self, monkeypatch) -> None:
        from portal.routes.me import _borner_memoire

        self._doubler_hosts(monkeypatch, "4g")
        assert _borner_memoire("node-a", "4096m") == "4096m"

    def test_une_demande_vide_est_bornee_au_plafond(self, monkeypatch) -> None:
        from portal.routes.me import _borner_memoire

        self._doubler_hosts(monkeypatch, "4g")
        assert _borner_memoire("node-a", "") == "4g"

    def test_un_noeud_sans_plafond_ne_borne_rien(self, monkeypatch) -> None:
        from portal.routes.me import _borner_memoire

        self._doubler_hosts(monkeypatch, "")
        assert _borner_memoire("node-a", "32g") == "32g"
        assert _borner_memoire("node-a", "") == ""

    def test_un_host_inconnu_ne_borne_rien(self, monkeypatch) -> None:
        from portal.routes.me import _borner_memoire

        self._doubler_hosts(monkeypatch, "4g")
        assert _borner_memoire("autre-node", "32g") == "32g"

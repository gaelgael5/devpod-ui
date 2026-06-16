from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi.testclient import TestClient


def _provision_alice(tmp_path: Path) -> None:
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)

    async def _inner() -> None:
        from portal.auth.router import provision_user

        await provision_user(login="alice", sub="sub-alice", data_root=tmp_path)

    asyncio.run(_inner())


def _make_app(tmp_path: Path, role: str = "dev") -> TestClient:
    import portal.settings as mod

    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    mod._settings = None

    from portal.app import create_app
    from portal.auth.rbac import UserInfo, require_admin, require_user

    app = create_app()
    user = UserInfo(login="alice", roles=[role])
    app.dependency_overrides[require_user] = lambda: user
    if role == "admin":
        app.dependency_overrides[require_admin] = lambda: user
    return app


def test_get_me_returns_login_and_roles(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path, role="dev")
    with TestClient(app) as client:
        resp = client.get("/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["login"] == "alice"
    assert data["roles"] == ["dev"]


def test_get_me_admin_returns_admin_role(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path, role="admin")
    with TestClient(app) as client:
        resp = client.get("/me")
    assert resp.status_code == 200
    assert "admin" in resp.json()["roles"]


def test_get_me_config_returns_user_config(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/me/config")
    assert resp.status_code == 200
    assert "secret_ns" in resp.json()


def test_put_me_config_updates_defaults(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    payload = {"defaults": {"ide": "openvscode", "idle_timeout": "2h"}}
    with TestClient(app) as client:
        resp = client.put("/me/config", json=payload)
    assert resp.status_code == 200


def test_put_me_config_rejects_unknown_field(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.put("/me/config", json={"unknown_field": "value"})
    assert resp.status_code == 422


def test_get_me_workspaces_returns_empty_list(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/me/workspaces")
    assert resp.status_code == 200
    assert resp.json() == []


def test_post_me_workspace_adds_workspace(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    ws = {"name": "myapp", "source": "git@github.com:user/repo.git"}
    with TestClient(app) as client:
        resp = client.post("/me/workspaces", json=ws)
    assert resp.status_code == 201
    with TestClient(app) as client:
        resp2 = client.get("/me/workspaces")
    assert any(w["name"] == "myapp" for w in resp2.json())


def test_delete_me_workspace_removes_workspace(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    ws = {"name": "todelete", "source": "git@github.com:user/repo.git"}
    with TestClient(app) as client:
        client.post("/me/workspaces", json=ws)
        resp = client.delete("/me/workspaces/todelete")
    assert resp.status_code == 200
    with TestClient(app) as client:
        resp2 = client.get("/me/workspaces")
    assert not any(w["name"] == "todelete" for w in resp2.json())


def test_get_git_credentials_includes_username(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        client.post(
            "/me/git-credentials",
            json={
                "name": "gh",
                "host": "github.com",
                "kind": "token",
                "username": "oauth2",
                "token": "ghp_test123",
            },
        )
        resp = client.get("/me/git-credentials")
    assert resp.status_code == 200
    creds = resp.json()
    assert len(creds) == 1
    assert creds[0]["username"] == "oauth2"


# ── helpers ────────────────────────────────────────────────────────────────

_FAKE_SSH_KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "dGVzdC1rZXktZm9yLXRlc3Rpbmctb25seQ==\n"
    "-----END OPENSSH PRIVATE KEY-----"
)


def _add_token_cred(client: TestClient, name: str = "gh") -> None:
    client.post(
        "/me/git-credentials",
        json={
            "name": name,
            "host": "github.com",
            "kind": "token",
            "username": "oauth2",
            "token": "ghp_old",
        },
    )


def _add_ssh_cred(client: TestClient, name: str = "gl-ssh") -> None:
    client.post(
        "/me/git-credentials",
        json={
            "name": name,
            "host": "gitlab.com",
            "kind": "ssh",
            "private_key": _FAKE_SSH_KEY,
        },
    )


# ── PATCH tests ─────────────────────────────────────────────────────────────


def test_patch_git_credential_updates_host(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _add_token_cred(client)
        resp = client.patch("/me/git-credentials/gh", json={"host": "github.enterprise.com"})
    assert resp.status_code == 200
    assert resp.json()["host"] == "github.enterprise.com"
    with TestClient(app) as client:
        creds = client.get("/me/git-credentials").json()
    assert creds[0]["host"] == "github.enterprise.com"


def test_patch_git_credential_updates_token(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _add_token_cred(client)
        resp = client.patch("/me/git-credentials/gh", json={"token": "ghp_new"})
    assert resp.status_code == 200
    from portal.config.store import load_user

    cfg = load_user("alice")
    assert cfg.git_credentials[0].token == "ghp_new"


def test_patch_git_credential_unchanged_token_preserved(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _add_token_cred(client)
        resp = client.patch("/me/git-credentials/gh", json={"token": "__UNCHANGED__"})
    assert resp.status_code == 200
    from portal.config.store import load_user

    cfg = load_user("alice")
    assert cfg.git_credentials[0].token == "ghp_old"


def test_patch_git_credential_token_to_ssh(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _add_token_cred(client)
        resp = client.patch(
            "/me/git-credentials/gh",
            json={
                "kind": "ssh",
                "private_key": _FAKE_SSH_KEY,
            },
        )
    assert resp.status_code == 200
    from portal.config.store import load_user

    cfg = load_user("alice")
    cred = cfg.git_credentials[0]
    assert cred.kind == "ssh"
    assert cred.token == ""
    assert cred.key_path != ""


def test_patch_git_credential_ssh_to_token(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _add_ssh_cred(client)
        from portal.config.store import load_user as _lu

        key_path_before = _lu("alice").git_credentials[0].key_path
        resp = client.patch(
            "/me/git-credentials/gl-ssh",
            json={
                "kind": "token",
                "token": "glpat-new",
            },
        )
    assert resp.status_code == 200
    from portal.config.store import load_user

    cfg = load_user("alice")
    cred = cfg.git_credentials[0]
    assert cred.kind == "token"
    assert cred.token == "glpat-new"
    assert cred.key_path == ""
    assert not Path(key_path_before).exists()


def test_patch_git_credential_rename_cascades_workspaces(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _add_token_cred(client, name="gh")
        client.post(
            "/me/workspaces",
            json={
                "name": "myapp",
                "source": "github.com/org/repo",
                "git_credential": "gh",
                "extra_sources": [{"url": "github.com/org/lib", "git_credential": "gh"}],
            },
        )
        resp = client.patch("/me/git-credentials/gh", json={"new_name": "github"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "github"
    from portal.config.store import load_user

    cfg = load_user("alice")
    ws = cfg.workspaces[0]
    assert ws.git_credential == "github"
    assert ws.extra_sources[0].git_credential == "github"


def test_patch_git_credential_duplicate_name_returns_409(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _add_token_cred(client, name="gh")
        _add_token_cred(client, name="gh2")
        resp = client.patch("/me/git-credentials/gh", json={"new_name": "gh2"})
    assert resp.status_code == 409


def test_patch_git_credential_not_found_returns_404(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.patch("/me/git-credentials/nope", json={"host": "example.com"})
    assert resp.status_code == 404


def test_patch_git_credential_ssh_rename_moves_key_file(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _add_ssh_cred(client, name="gl-ssh")
        from portal.config.store import load_user as _lu

        old_key_path = Path(_lu("alice").git_credentials[0].key_path)
        resp = client.patch("/me/git-credentials/gl-ssh", json={"new_name": "gitlab-ssh"})
    assert resp.status_code == 200
    from portal.config.store import load_user

    cfg = load_user("alice")
    cred = cfg.git_credentials[0]
    assert cred.name == "gitlab-ssh"
    assert "gitlab-ssh" in cred.key_path
    assert Path(cred.key_path).exists()
    assert not old_key_path.exists()


def test_patch_git_credential_invalid_new_name_returns_422(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _add_token_cred(client)
        resp = client.patch("/me/git-credentials/gh", json={"new_name": "a"})
    assert resp.status_code == 422


# ── SSH key management tests ────────────────────────────────────────────────

def _real_ssh_pem() -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
    key = Ed25519PrivateKey.generate()
    return key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()).decode("utf-8")


def test_post_git_credential_generate_key_creates_credential(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/git-credentials",
            json={"name": "my-key", "host": "github.com", "kind": "ssh", "generate_key": True},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["kind"] == "ssh"
    assert "public_key" in data
    assert data["public_key"].startswith("ssh-ed25519 ")
    from portal.config.store import load_user
    cfg = load_user("alice")
    cred = next(c for c in cfg.git_credentials if c.name == "my-key")
    assert cred.key_path != ""
    from pathlib import Path as P
    priv = P(cred.key_path)
    assert priv.exists()
    assert (priv.parent / "id_ed25519.pub").exists()


def test_post_git_credential_generate_key_with_token_kind_returns_422(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/git-credentials",
            json={"name": "my-key", "host": "github.com", "kind": "token", "generate_key": True},
        )
    assert resp.status_code == 422


def test_post_git_credential_ssh_upload_derives_pub_for_valid_key(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    pem = _real_ssh_pem()
    with TestClient(app) as client:
        resp = client.post(
            "/me/git-credentials",
            json={"name": "gl-ssh", "host": "gitlab.com", "kind": "ssh", "private_key": pem},
        )
    assert resp.status_code == 201
    from portal.config.store import load_user
    from pathlib import Path as P
    cfg = load_user("alice")
    cred = next(c for c in cfg.git_credentials if c.name == "gl-ssh")
    assert (P(cred.key_path).parent / "id_ed25519.pub").exists()


def test_get_git_credential_public_key_on_generated(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        client.post(
            "/me/git-credentials",
            json={"name": "my-key", "host": "github.com", "kind": "ssh", "generate_key": True},
        )
        resp = client.get("/me/git-credentials/my-key/public-key")
    assert resp.status_code == 200
    assert resp.json()["public_key"].startswith("ssh-ed25519 ")


def test_get_git_credential_public_key_derives_on_the_fly(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    pem = _real_ssh_pem()
    with TestClient(app) as client:
        client.post(
            "/me/git-credentials",
            json={"name": "my-key", "host": "github.com", "kind": "ssh", "private_key": pem},
        )
        from portal.config.store import load_user as _lu
        from pathlib import Path as P
        cfg = _lu("alice")
        cred = next(c for c in cfg.git_credentials if c.name == "my-key")
        pub = P(cred.key_path).parent / "id_ed25519.pub"
        if pub.exists():
            pub.unlink()
        resp = client.get("/me/git-credentials/my-key/public-key")
    assert resp.status_code == 200
    assert resp.json()["public_key"].startswith("ssh-ed25519 ")


def test_get_git_credential_public_key_on_token_returns_404(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _add_token_cred(client, name="gh")
        resp = client.get("/me/git-credentials/gh/public-key")
    assert resp.status_code == 404


def test_get_git_credential_public_key_not_found_returns_404(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/me/git-credentials/nope/public-key")
    assert resp.status_code == 404


def test_patch_git_credential_updates_pub_on_new_key(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    pem = _real_ssh_pem()
    with TestClient(app) as client:
        client.post(
            "/me/git-credentials",
            json={"name": "my-key", "host": "github.com", "kind": "ssh", "generate_key": True},
        )
        resp = client.patch("/me/git-credentials/my-key", json={"private_key": pem})
    assert resp.status_code == 200
    from portal.config.store import load_user
    from pathlib import Path as P
    cfg = load_user("alice")
    cred = next(c for c in cfg.git_credentials if c.name == "my-key")
    assert (P(cred.key_path).parent / "id_ed25519.pub").exists()


def test_require_user_blocks_unauthenticated(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    import portal.settings as mod

    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["DEV_MODE"] = "true"
    mod._settings = None

    try:
        from portal.app import create_app

        app = create_app()  # no dependency_overrides
        with TestClient(app) as client:
            resp = client.get("/me/config")
        assert resp.status_code == 401
    finally:
        os.environ.pop("DEV_MODE", None)
        mod._settings = None

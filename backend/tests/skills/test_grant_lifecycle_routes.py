"""Routes de cycle de vie des grants (onglet Validations) — actions humaines.

DB mockée au niveau du module de routes (les primitives elles-mêmes sont
couvertes par tests/db/test_skills_registry.py) : on teste ici l'ownership,
les gardes d'états et la provenance serveur du hash approuvé.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

GRANT = {
    "id": 7,
    "user_subject": "sub-alice",
    "skill_id": "github/awesome-copilot/git-commit",
    "approved_hash": None,
    "statut": "pending",
}

_ENV_KEYS = ("PORTAL_DATA_ROOT", "SESSION_SECRET_KEY", "DEV_MODE")


@pytest.fixture(autouse=True)
def _restore_env():
    saved = {k: os.environ.get(k) for k in _ENV_KEYS}
    yield
    import portal.settings as mod

    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    mod._settings = None


def _client(tmp_path: Path, monkeypatch, grant, sub="sub-alice"):
    import portal.settings as mod

    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    os.environ["DEV_MODE"] = "true"
    mod._settings = None

    from fastapi.testclient import TestClient

    import portal.routes.skills as routes
    from portal.app import create_app
    from portal.auth.rbac import UserInfo, require_user
    from portal.db.engine import get_conn

    state = {"grant": dict(grant), "calls": []}

    async def fake_get_grant_by_id(grant_id, conn):
        return dict(state["grant"]) if grant_id == state["grant"]["id"] else None

    async def fake_approve(grant_id, approved_hash, conn):
        state["calls"].append(("approve", grant_id, approved_hash))
        state["grant"].update(statut="granted", approved_hash=approved_hash)
        return True

    async def fake_revoke(grant_id, conn):
        state["calls"].append(("revoke", grant_id))
        state["grant"]["statut"] = "revoked"
        return True

    async def fake_pause(grant_id, conn):
        state["calls"].append(("pause", grant_id))
        state["grant"]["statut"] = "paused"
        return True

    async def fake_resume(grant_id, conn):
        state["calls"].append(("resume", grant_id))
        state["grant"]["statut"] = "granted"
        return True

    class _FakeAdapter:
        async def skill_md(self, source, skill_id):
            state["calls"].append(("skill_md", source, skill_id))
            return {"content": "# skill", "hash": "sha256:current"}

    monkeypatch.setattr(routes, "get_grant_by_id", fake_get_grant_by_id)
    monkeypatch.setattr(routes, "approve_grant", fake_approve)
    monkeypatch.setattr(routes, "revoke_grant", fake_revoke)
    monkeypatch.setattr(routes, "pause_grant", fake_pause)
    monkeypatch.setattr(routes, "resume_grant", fake_resume)
    monkeypatch.setattr(routes, "get_skills_adapter", lambda: _FakeAdapter())

    app = create_app()
    app.dependency_overrides[require_user] = lambda: UserInfo(
        login="alice", roles=["dev"], sub=sub
    )

    async def _no_conn():
        yield None

    app.dependency_overrides[get_conn] = _no_conn
    return TestClient(app), state


def test_approve_uses_server_side_hash(tmp_path, monkeypatch):
    client, state = _client(tmp_path, monkeypatch, GRANT)
    with client:
        resp = client.post("/me/skills/grants/7/approve")
    assert resp.status_code == 200
    assert resp.json()["statut"] == "granted"
    assert ("approve", 7, "sha256:current") in state["calls"]
    # Le hash vient du SKILL.md canonique fetché côté serveur.
    assert ("skill_md", "github/awesome-copilot", "git-commit") in state["calls"]


def test_approve_rejects_non_pending(tmp_path, monkeypatch):
    client, state = _client(tmp_path, monkeypatch, {**GRANT, "statut": "granted"})
    with client:
        resp = client.post("/me/skills/grants/7/approve")
    assert resp.status_code == 409
    assert all(c[0] != "approve" for c in state["calls"])


def test_ownership_hides_others_grants(tmp_path, monkeypatch):
    """404 (pas 403) : ne pas révéler l'existence des grants d'autrui."""
    client, _ = _client(tmp_path, monkeypatch, GRANT, sub="sub-bob")
    with client:
        assert client.post("/me/skills/grants/7/approve").status_code == 404
        assert client.post("/me/skills/grants/7/revoke").status_code == 404
        assert client.get("/me/skills/grants/7/skillmd").status_code == 404


def test_revoke_any_state_but_not_twice(tmp_path, monkeypatch):
    client, state = _client(tmp_path, monkeypatch, {**GRANT, "statut": "granted"})
    with client:
        assert client.post("/me/skills/grants/7/revoke").status_code == 200
        assert client.post("/me/skills/grants/7/revoke").status_code == 409
    assert state["calls"].count(("revoke", 7)) == 1


def test_pause_requires_granted_and_resume_requires_paused(tmp_path, monkeypatch):
    client, state = _client(tmp_path, monkeypatch, {**GRANT, "statut": "granted"})
    with client:
        assert client.post("/me/skills/grants/7/resume").status_code == 409  # pas paused
        assert client.post("/me/skills/grants/7/pause").status_code == 200
        assert client.post("/me/skills/grants/7/pause").status_code == 409  # déjà paused
        assert client.post("/me/skills/grants/7/resume").status_code == 200


def test_skillmd_returns_current_and_approved_hash(tmp_path, monkeypatch):
    """L'écran de re-validation compare hash courant vs approved_hash conservé."""
    client, _ = _client(
        tmp_path, monkeypatch, {**GRANT, "approved_hash": "sha256:old"}
    )
    with client:
        resp = client.get("/me/skills/grants/7/skillmd")
    assert resp.status_code == 200
    body = resp.json()
    assert body["hash"] == "sha256:current"
    assert body["approved_hash"] == "sha256:old"
    assert body["content"] == "# skill"

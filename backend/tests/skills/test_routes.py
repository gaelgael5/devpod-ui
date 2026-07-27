"""Routes /me/skills — search/audit proxifiés + demande de grant (pending).

Les chemins sans DB (search/audit sans secret_slug, validation des DTO) sont
testés ici avec adaptateur mocké ; les chemins DB (grants) sont couverts par
tests/db/test_skills_registry.py et l'exécution complète sur test1.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from portal.routes.skills import GrantRequestBody

_ENV_KEYS = ("PORTAL_DATA_ROOT", "SESSION_SECRET_KEY", "DEV_MODE")


def _make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sub: str = "sub-alice"):
    import portal.settings as mod

    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    os.environ["DEV_MODE"] = "true"
    mod._settings = None

    from fastapi.testclient import TestClient

    from portal.app import create_app
    from portal.auth.rbac import UserInfo, require_user
    from portal.db.engine import get_conn

    app = create_app()
    app.dependency_overrides[require_user] = lambda: UserInfo(
        login="alice", roles=["dev"], sub=sub
    )

    async def _no_conn():  # les chemins testés ici n'utilisent pas la DB
        yield None

    app.dependency_overrides[get_conn] = _no_conn
    return TestClient(app)


class _FakeAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def search(self, query, search_type="fuzzy", api_key=None):
        self.calls.append(("search", query, search_type, api_key))
        return {"query": query, "searchType": search_type, "skills": []}

    async def audit(self, source, skill_ids, api_key=None):
        self.calls.append(("audit", source, tuple(skill_ids), api_key))
        return {sid: {"socket": {"risk": "safe"}} for sid in skill_ids}


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


def test_search_proxies_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeAdapter()
    import portal.routes.skills as mod

    monkeypatch.setattr(mod, "get_skills_adapter", lambda: fake)
    with _make_client(tmp_path, monkeypatch) as client:
        resp = client.get("/me/skills/search", params={"q": "git", "search_type": "semantic"})
    assert resp.status_code == 200
    assert resp.json()["searchType"] == "semantic"
    assert fake.calls == [("search", "git", "semantic", None)]


def test_search_rejects_bad_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with _make_client(tmp_path, monkeypatch) as client:
        resp = client.get("/me/skills/search", params={"q": "git", "search_type": "autre"})
    assert resp.status_code == 422


def test_audit_splits_skill_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeAdapter()
    import portal.routes.skills as mod

    monkeypatch.setattr(mod, "get_skills_adapter", lambda: fake)
    with _make_client(tmp_path, monkeypatch) as client:
        resp = client.get(
            "/me/skills/audit",
            params={"source": "github/awesome-copilot", "skills": "a, b ,c"},
        )
    assert resp.status_code == 200
    assert fake.calls == [("audit", "github/awesome-copilot", ("a", "b", "c"), None)]


def test_upstream_error_maps_to_502(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import portal.routes.skills as mod
    from portal.skills.adapter import SkillsShError

    class _Boom:
        async def search(self, *a, **k):
            raise SkillsShError("down", status=500)

    monkeypatch.setattr(mod, "get_skills_adapter", lambda: _Boom())
    with _make_client(tmp_path, monkeypatch) as client:
        resp = client.get("/me/skills/search", params={"q": "git"})
    assert resp.status_code == 502


def test_grants_require_subject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed : une session sans sub OIDC ne peut pas pétitionner."""
    with _make_client(tmp_path, monkeypatch, sub="") as client:
        resp = client.post("/me/skills/grants", json={"skill_id": "src/skill"})
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "skill_id",
    [
        "github/awesome-copilot/git-commit",  # forme réelle à 3 segments
        "src/skill",
    ],
)
def test_grant_body_accepts_valid_ids(skill_id: str) -> None:
    assert GrantRequestBody(skill_id=f" {skill_id} ").skill_id == skill_id


@pytest.mark.parametrize(
    "skill_id",
    ["", "sans-slash", "/absolu", "a//b", "a/b;drop", "x" * 301, "../traversal/x"],
)
def test_grant_body_rejects_invalid_ids(skill_id: str) -> None:
    with pytest.raises(ValidationError):
        GrantRequestBody(skill_id=skill_id)

"""Primitives MCP skills — pétitionne/restreint, n'accorde jamais.

Impls testées via leurs fonctions (conn mocké/monkeypatché) : les invariants
de sécurité (write-only pour approval, grant granted requis pour placement, pas
de resume, fail closed sans sub) et la parité registre↔impls.
"""
from __future__ import annotations

import pytest

import portal.mcp.devpod_tools.skills_tools as st
from portal.mcp.devpod_tools.errors import DevpodToolError


class FakeConn:
    """Sert users.sub via une seule requête scalaire (le _subject helper)."""

    def __init__(self, sub):
        self._sub = sub

    async def execute(self, _stmt):
        conn = self

        class _R:
            def scalar_one_or_none(self):
                return conn._sub

        return _R()


def test_registry_parity():
    from portal.mcp.devpod_tools import _IMPLS
    from portal.mcp.devpod_tools.registry import DEVPOD_PRIMITIVES

    for name in st.SKILLS_IMPLS:
        assert name in DEVPOD_PRIMITIVES, f"{name} manquant dans le registre"
        assert name in _IMPLS


def test_no_resume_or_approve_primitive():
    """Invariants d'asymétrie : aucun approve ni resume côté MCP."""
    from portal.mcp.devpod_tools.registry import DEVPOD_PRIMITIVES

    assert "skills_resume" not in DEVPOD_PRIMITIVES
    assert "skills_approve" not in DEVPOD_PRIMITIVES
    assert "skills_revoke" not in DEVPOD_PRIMITIVES


@pytest.mark.asyncio
async def test_search_proxies_adapter(monkeypatch):
    class _Ad:
        async def search(self, q, stype):
            return {"query": q, "searchType": stype, "skills": []}

    monkeypatch.setattr(st, "get_skills_adapter", lambda: _Ad())
    out = await st._skills_search(
        FakeConn("sub"), {"query": "git", "search_type": "semantic"}, "alice"
    )
    assert out["searchType"] == "semantic"


@pytest.mark.asyncio
async def test_request_approval_creates_pending(monkeypatch):
    seen = {}

    async def fake_create(subject, skill_id, conn):
        seen["subject"], seen["skill"] = subject, skill_id
        return {"id": 1, "statut": "pending"}, True

    monkeypatch.setattr(st, "create_or_get_grant", fake_create)
    out = await st._skills_request_approval(
        FakeConn("sub-alice"),
        {"skill_id": "github/x/y", "reason": "besoin"},
        "alice",
    )
    assert out["grant_statut"] == "pending"
    assert seen == {"subject": "sub-alice", "skill": "github/x/y"}


@pytest.mark.asyncio
async def test_no_sub_fails_closed(monkeypatch):
    """Compte non ancré OIDC (sub NULL) → refus, aucune écriture."""
    with pytest.raises(DevpodToolError):
        await st._skills_request_approval(FakeConn(None), {"skill_id": "a/b"}, "alice")


@pytest.mark.asyncio
async def test_place_requires_granted(monkeypatch):
    async def fake_get_grant(subject, skill_id, conn):
        return {"id": 1, "statut": "pending", "approved_hash": None}

    monkeypatch.setattr(st, "get_grant", fake_get_grant)
    with pytest.raises(DevpodToolError, match="validation humaine"):
        await st._skills_place(
            FakeConn("sub"), {"workspace": "doc", "skill_id": "a/b"}, "alice"
        )


@pytest.mark.asyncio
async def test_place_granted_calls_place_skill(monkeypatch):
    grant = {"id": 1, "statut": "granted", "approved_hash": "sha256:x"}
    called = {}

    async def fake_get_grant(subject, skill_id, conn):
        return grant

    async def fake_place(login, ws_id, g, conn):
        called["login"], called["ws_id"] = login, ws_id
        return {"statut": "verified"}

    monkeypatch.setattr(st, "get_grant", fake_get_grant)
    monkeypatch.setattr(st, "place_skill", fake_place)
    out = await st._skills_place(
        FakeConn("sub"), {"workspace": "doc", "skill_id": "a/b"}, "alice"
    )
    assert out["statut"] == "verified"
    assert called == {"login": "alice", "ws_id": "alice-doc"}


@pytest.mark.asyncio
async def test_pause_requires_granted(monkeypatch):
    async def fake_get_grant(subject, skill_id, conn):
        return {"id": 1, "statut": "paused"}

    monkeypatch.setattr(st, "get_grant", fake_get_grant)
    with pytest.raises(DevpodToolError):
        await st._skills_pause(FakeConn("sub"), {"skill_id": "a/b"}, "alice")


@pytest.mark.parametrize("bad", ["", "sans-slash", "../evil/x", "a/b;drop"])
@pytest.mark.asyncio
async def test_skill_id_validation(bad):
    with pytest.raises(DevpodToolError):
        await st._skills_pause(FakeConn("sub"), {"skill_id": bad}, "alice")

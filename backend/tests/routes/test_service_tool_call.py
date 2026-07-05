"""Bouton « Tester » de l'éditeur de règles : essai direct d'un outil MCP."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

import portal.routes.user_rules as rt

USER = type("U", (), {"login": "alice"})()
CONN = object()


def test_body_rejette_outil_vide() -> None:
    with pytest.raises(ValidationError):
        rt.ServiceCallBody(tool="  ")


@pytest.mark.asyncio
async def test_appel_rend_les_gabarits_et_retourne_le_resultat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str, dict[str, Any]]] = []

    async def fake_caller(owner: str, service_id: str, tool: str, args: dict[str, Any]) -> Any:
        calls.append((owner, service_id, tool, args))
        return {"exists": False}

    monkeypatch.setattr(rt, "call_service_primitive", fake_caller)
    body = rt.ServiceCallBody(
        tool="docflow__workspace_exists",
        args={"workspace_slug": "{workspace}"},
        workspace="mon-projet",
    )
    out = await rt.test_service_call_route("svc-1", body, user=USER, conn=CONN)
    assert out == {
        "ok": True,
        "args": {"workspace_slug": "mon-projet"},
        "result": {"exists": False},
    }
    assert calls == [
        ("alice", "svc-1", "docflow__workspace_exists", {"workspace_slug": "mon-projet"})
    ]


@pytest.mark.asyncio
async def test_workspace_absent_donne_chaine_vide(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []

    async def fake_caller(owner: str, service_id: str, tool: str, args: dict[str, Any]) -> Any:
        seen.append(args)
        return []

    monkeypatch.setattr(rt, "call_service_primitive", fake_caller)
    body = rt.ServiceCallBody(tool="t", args={"slug": "{workspace}"})
    out = await rt.test_service_call_route("svc-1", body, user=USER, conn=CONN)
    assert out["ok"] is True
    assert seen == [{"slug": ""}]


@pytest.mark.asyncio
async def test_erreur_retournee_en_clair(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_caller(owner: str, service_id: str, tool: str, args: dict[str, Any]) -> Any:
        raise rt.AutomationError("outil 'x' non autorisé par le profil")

    monkeypatch.setattr(rt, "call_service_primitive", fake_caller)
    out = await rt.test_service_call_route(
        "svc-1", rt.ServiceCallBody(tool="x"), user=USER, conn=CONN
    )
    assert out["ok"] is False
    assert "non autorisé" in out["error"]

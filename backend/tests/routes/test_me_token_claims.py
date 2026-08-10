"""Endpoint GET /me/token-claims : renvoie les claims de session, jamais le jeton brut."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from portal.auth.rbac import UserInfo, require_user
from portal.routes.me import router as me_router


def _client(session: dict) -> TestClient:
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(me_router, prefix="/me")
    app.dependency_overrides[require_user] = lambda: UserInfo(login="gael", roles=["dev"])

    @app.get("/_seed")
    def _seed(request: Request) -> dict[str, str]:  # pragma: no cover - utilitaire test
        request.session.update(session)
        return {"ok": "1"}

    c = TestClient(app)
    c.get("/_seed")  # pose le cookie de session
    return c


def test_returns_curated_claims() -> None:
    claims = {"sub": "abc-123", "email": "u@x.org", "preferred_username": "gael"}
    resp = _client({"token_claims": claims, "user": {"sub": "abc-123"}}).get("/me/token-claims")
    assert resp.status_code == 200
    assert resp.json() == {"claims": claims}


def test_sub_guaranteed_from_session_user_if_claims_absent() -> None:
    # Session antérieure à la feature : pas de token_claims, mais user.sub présent.
    resp = _client({"user": {"sub": "anchor-sub"}}).get("/me/token-claims")
    assert resp.status_code == 200
    assert resp.json() == {"claims": {"sub": "anchor-sub"}}


def test_empty_when_nothing() -> None:
    resp = _client({}).get("/me/token-claims")
    assert resp.status_code == 200
    assert resp.json() == {"claims": {}}

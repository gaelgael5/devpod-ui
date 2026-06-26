"""Endpoints OAuth de l'Authorization Server (découverte, DCR, token)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncConnection

from ..config.store import load_global
from ..db.engine import get_conn
from ..oauth import service

router = APIRouter(tags=["oauth"])


def _issuer() -> str:
    return load_global().server.external_url.rstrip("/")


@router.get("/.well-known/oauth-protected-resource")
async def protected_resource() -> dict[str, Any]:
    base = _issuer()
    return {"resource": f"{base}/mcp", "authorization_servers": [base]}


@router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata() -> dict[str, Any]:
    base = _issuer()
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }


@router.post("/oauth/register", status_code=201)
async def register(body: dict[str, Any], conn: AsyncConnection = Depends(get_conn)) -> Any:
    """Enregistrement dynamique (RFC 7591) — client public PKCE."""
    try:
        return await service.register_client(
            conn,
            redirect_uris=list(body.get("redirect_uris") or []),
            client_name=str(body.get("client_name", "")),
            metadata=body,
        )
    except service.OAuthError as exc:
        return JSONResponse(
            {"error": exc.error, "error_description": exc.description}, status_code=400
        )


def _req(form: Any, key: str) -> str:
    val = form.get(key)
    if val is None:
        raise KeyError(key)
    return str(val)


@router.post("/oauth/token")
async def token(request: Request, conn: AsyncConnection = Depends(get_conn)) -> Any:
    """Token endpoint (RFC 6749) — form-encoded ; authorization_code ou refresh_token."""
    form = await request.form()
    grant_type = form.get("grant_type")
    try:
        if grant_type == "authorization_code":
            return await service.exchange_code(
                conn,
                code=_req(form, "code"),
                client_id=_req(form, "client_id"),
                redirect_uri=_req(form, "redirect_uri"),
                code_verifier=_req(form, "code_verifier"),
            )
        if grant_type == "refresh_token":
            return await service.refresh(
                conn,
                refresh_token=_req(form, "refresh_token"),
                client_id=_req(form, "client_id"),
            )
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
    except service.OAuthError as exc:
        return JSONResponse(
            {"error": exc.error, "error_description": exc.description}, status_code=400
        )
    except KeyError as exc:
        return JSONResponse(
            {"error": "invalid_request", "error_description": f"missing {exc}"}, status_code=400
        )

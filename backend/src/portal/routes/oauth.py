"""Endpoints OAuth de l'Authorization Server (découverte, DCR, token)."""
from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import get_current_user
from ..config.store import load_global
from ..db import oauth as oauth_db
from ..db.engine import get_conn
from ..oauth import service

router = APIRouter(tags=["oauth"])
log = structlog.get_logger(__name__)


def _issuer() -> str:
    return load_global().server.external_url.rstrip("/")


@router.api_route(
    "/mcp", methods=["GET", "POST", "DELETE", "OPTIONS"], include_in_schema=False
)
async def mcp_trailing_slash(request: Request) -> RedirectResponse:
    """Le transport MCP est monté sur /mcp/ ; on redirige /mcp (sans slash, 307 pour
    préserver la méthode/body) pour les clients qui n'ajoutent pas le slash."""
    q = request.url.query
    return RedirectResponse("/mcp/" + (f"?{q}" if q else ""), status_code=307)


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
    # Diagnostic OAuth : noms de champs uniquement (jamais code/verifier/secret).
    log.info(
        "oauth_token_request",
        grant_type=grant_type,
        field_keys=sorted(form.keys()),
        content_type=request.headers.get("content-type"),
        has_auth_header="authorization" in {k.lower() for k in request.headers},
    )
    try:
        if grant_type == "authorization_code":
            res = await service.exchange_code(
                conn,
                code=_req(form, "code"),
                client_id=_req(form, "client_id"),
                redirect_uri=_req(form, "redirect_uri"),
                code_verifier=_req(form, "code_verifier"),
            )
            log.info("oauth_token_issued", grant_type=grant_type)
            return res
        if grant_type == "refresh_token":
            res = await service.refresh(
                conn,
                refresh_token=_req(form, "refresh_token"),
                client_id=_req(form, "client_id"),
            )
            log.info("oauth_token_issued", grant_type=grant_type)
            return res
        log.warning("oauth_token_unsupported_grant", grant_type=grant_type)
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
    except service.OAuthError as exc:
        log.warning("oauth_token_error", error=exc.error, description=exc.description)
        return JSONResponse(
            {"error": exc.error, "error_description": exc.description}, status_code=400
        )
    except KeyError as exc:
        log.warning("oauth_token_missing_param", missing=str(exc))
        return JSONResponse(
            {"error": "invalid_request", "error_description": f"missing {exc}"}, status_code=400
        )
    except Exception:  # noqa: BLE001 — pas de 500 muet : on logge le traceback complet.
        log.exception("oauth_token_unexpected_error", grant_type=grant_type)
        return JSONResponse({"error": "server_error"}, status_code=500)


async def _validate_client(conn: AsyncConnection, client_id: str, redirect_uri: str) -> None:
    client = await oauth_db.get_client(conn, client_id)
    if client is None:
        raise service.OAuthError("invalid_request", "client inconnu")
    if redirect_uri not in (client.get("redirect_uris") or []):
        raise service.OAuthError("invalid_request", "redirect_uri non enregistré")
    # Défense en profondeur : re-rejette un schéma dangereux même si déjà stocké.
    service.ensure_valid_redirect_uri(redirect_uri)


@router.get("/oauth/authorize")
async def authorize(
    request: Request,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    response_type: str = "code",
    code_challenge_method: str = "S256",
    state: str = "",
    scope: str = "",
    conn: AsyncConnection = Depends(get_conn),
) -> Any:
    if response_type != "code" or code_challenge_method != "S256" or not code_challenge:
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    try:
        await _validate_client(conn, client_id, redirect_uri)
    except service.OAuthError as exc:
        return JSONResponse(
            {"error": exc.error, "error_description": exc.description}, status_code=400
        )
    base = _issuer()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "state": state,
        "scope": scope,
    }
    if get_current_user(request) is None:
        nxt = "/oauth/authorize?" + urlencode(
            {**params, "response_type": "code", "code_challenge_method": "S256"}
        )
        return RedirectResponse(f"{base}/auth/login?next={quote(nxt, safe='')}", status_code=302)
    return RedirectResponse(f"{base}/oauth/consent?" + urlencode(params), status_code=302)


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str
    redirect_uri: str
    code_challenge: str
    state: str = ""
    scope: str = ""
    approve: bool
    grants: list[dict[str, Any]] = []
    profile_id: str | None = None


@router.post("/oauth/authorize/decision")
async def decision(
    body: DecisionBody, request: Request, conn: AsyncConnection = Depends(get_conn)
) -> Any:
    user = get_current_user(request)
    if user is None:
        return JSONResponse({"error": "login_required"}, status_code=401)
    try:
        await _validate_client(conn, body.client_id, body.redirect_uri)
    except service.OAuthError as exc:
        return JSONResponse(
            {"error": exc.error, "error_description": exc.description}, status_code=400
        )
    sep = "&" if "?" in body.redirect_uri else "?"
    if not body.approve:
        q = urlencode({"error": "access_denied", "state": body.state})
        return {"redirect": f"{body.redirect_uri}{sep}{q}"}
    code = await service.make_authcode(
        conn,
        client_id=body.client_id,
        owner_login=user.login,
        redirect_uri=body.redirect_uri,
        code_challenge=body.code_challenge,
        scope=body.scope,
        grants=body.grants,
        profile_id=body.profile_id,
    )
    q = urlencode({"code": code, "state": body.state})
    return {"redirect": f"{body.redirect_uri}{sep}{q}"}

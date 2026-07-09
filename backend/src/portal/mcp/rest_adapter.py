"""Adaptateur REST→MCP : expose une API REST externe comme backend MCP.

Un backend de transport `rest` porte, par outil, un mapping déclaratif
(`RestToolSpec`) d'un appel d'outil MCP vers une requête HTTP. Le secret de la
clé backend peut être injecté dans le corps, la query ou un header (certaines
API — ex. rag — attendent leur `api_key` dans le corps JSON, pas en Bearer).

Contrat sécurité : le secret n'est manipulé qu'ici, au point d'appel httpx, et
n'est jamais loggé. Toute sortie renvoyée à l'appelant (y compris les réponses
d'erreur, qui peuvent ré-échoyer le corps envoyé) est expurgée du secret.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import quote

import httpx
import structlog
from mcp import types
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db.mcp_catalog import get_primitive_definition
from .connections import BackendUnavailable

_log = structlog.get_logger(__name__)

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


class RestToolSpec(BaseModel):
    """Mapping déclaratif d'un outil MCP vers une requête HTTP REST.

    Les noms d'arguments MCP servent tels quels de noms de champs REST
    (`body_args`/`query_args`/`path_args` listent les arguments à placer dans
    le corps, la query, ou substitués dans `{name}` du chemin).
    """

    model_config = ConfigDict(extra="forbid")

    method: HttpMethod = "POST"
    path: str = ""
    path_args: list[str] = Field(default_factory=list)
    body_args: list[str] = Field(default_factory=list)
    query_args: list[str] = Field(default_factory=list)
    secret_field: str | None = None
    secret_in: Literal["body", "query", "header"] = "body"
    result_path: str | None = None


@dataclass(frozen=True)
class RestCall:
    """Requête HTTP résolue, prête à être exécutée (secret déjà injecté)."""

    method: str
    url: str
    params: dict[str, Any] = field(default_factory=dict)
    json_body: dict[str, Any] | None = None
    headers: dict[str, str] = field(default_factory=dict)


def _render_path(path: str, arguments: dict[str, Any], path_args: list[str]) -> str:
    rendered = path
    for name in path_args:
        if name in arguments:
            rendered = rendered.replace("{" + name + "}", quote(str(arguments[name]), safe=""))
    return rendered


def _join_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    return base if not path else f"{base}/{path.lstrip('/')}"


def build_call(
    base_url: str,
    spec: RestToolSpec,
    arguments: dict[str, Any],
    *,
    secret: str | None,
) -> RestCall:
    """Construit la requête HTTP à partir du mapping et des arguments (pur)."""
    url = _join_url(base_url, _render_path(spec.path, arguments, spec.path_args))
    params = {name: arguments[name] for name in spec.query_args if name in arguments}
    body = {name: arguments[name] for name in spec.body_args if name in arguments}
    json_body: dict[str, Any] | None = body if (body or spec.secret_in == "body") else None
    headers: dict[str, str] = {}

    if secret and spec.secret_field:
        if spec.secret_in == "query":
            params[spec.secret_field] = secret
        elif spec.secret_in == "header":
            headers[spec.secret_field] = secret
        else:
            json_body = json_body if json_body is not None else {}
            json_body[spec.secret_field] = secret

    return RestCall(
        method=spec.method, url=url, params=params, json_body=json_body, headers=headers
    )


def _dig(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _redact(text: str, secret: str | None) -> str:
    return text.replace(secret, "***") if secret else text


def translate_response(
    spec: RestToolSpec,
    status_code: int,
    text: str,
    json_obj: Any,
    *,
    secret: str | None,
) -> types.CallToolResult:
    """Traduit une réponse HTTP en CallToolResult, secret expurgé de la sortie."""
    if json_obj is not None:
        extracted = _dig(json_obj, spec.result_path) if spec.result_path else json_obj
        out = json.dumps(extracted, ensure_ascii=False, indent=2)
    else:
        out = text
    out = _redact(out, secret)
    is_error = status_code >= 400
    return types.CallToolResult(
        isError=is_error, content=[types.TextContent(type="text", text=out)]
    )


async def execute_rest_tool(
    base_url: str,
    spec: RestToolSpec,
    arguments: dict[str, Any],
    *,
    secret: str | None,
    client: httpx.AsyncClient,
) -> types.CallToolResult:
    """Exécute l'appel REST et retourne un CallToolResult.

    Une erreur de transport (connexion/timeout) devient BackendUnavailable, comme
    pour les transports MCP HTTP — le dispatch la mappe en McpError uniforme.
    """
    call = build_call(base_url, spec, arguments, secret=secret)
    try:
        resp = await client.request(
            call.method,
            call.url,
            params=call.params,
            json=call.json_body,
            headers=call.headers,
        )
    except httpx.HTTPError as exc:
        _log.warning(
            "rest_backend_unavailable",
            url=call.url,
            method=call.method,
            exc_type=type(exc).__name__,  # message volontairement absent (peut porter des données)
        )
        raise BackendUnavailable(f"rest backend injoignable ({type(exc).__name__})") from exc

    try:
        json_obj: Any = resp.json()
        text = ""
    except ValueError:
        json_obj, text = None, resp.text
    return translate_response(spec, resp.status_code, text, json_obj, secret=secret)


def _load_spec(definition: dict[str, Any] | None) -> RestToolSpec:
    if not definition or "rest" not in definition:
        raise BackendUnavailable("outil rest sans mapping REST dans le catalogue")
    try:
        return RestToolSpec.model_validate(definition["rest"])
    except ValidationError as exc:
        raise BackendUnavailable(f"mapping REST invalide: {exc.error_count()} erreur(s)") from exc


async def dispatch_rest_tool(
    conn: AsyncConnection,
    *,
    backend_id: str,
    original_name: str,
    base_url: str,
    arguments: dict[str, Any],
    secret: str | None,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 30.0,
) -> types.CallToolResult:
    """Charge le mapping REST du catalogue et exécute l'appel (dispatch transport `rest`).

    Un mapping absent ou invalide rend l'outil inutilisable → BackendUnavailable
    (mappé en McpError uniforme par le dispatch, comme un backend injoignable).
    """
    spec = _load_spec(await get_primitive_definition(conn, backend_id, "tool", original_name))
    if client is not None:
        return await execute_rest_tool(base_url, spec, arguments, secret=secret, client=client)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as owned:
        return await execute_rest_tool(base_url, spec, arguments, secret=secret, client=owned)


async def probe_rest_health(
    base_url: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 10.0,
) -> bool:
    """Santé d'un backend `rest` = joignabilité HTTP de l'URL de base.

    Toute réponse HTTP (même 4xx) prouve la joignabilité → up. Une erreur de
    transport (connexion refusée, timeout) → down. On ne récupère PAS de
    catalogue MCP : celui d'un backend REST est déclaré par l'admin, pas découvert.
    """
    try:
        if client is not None:
            await client.get(base_url)
        else:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as owned:
                await owned.get(base_url)
        return True
    except httpx.HTTPError:
        return False

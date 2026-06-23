from __future__ import annotations

from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import McpError

from portal.db.engine import _get_engine
from portal.mcp.handlers import (
    _UNAUTHORIZED,
    build_prompt_descriptors,
    build_tool_descriptors,
    execute_prompt_get,
    execute_tool_call,
    extract_bearer,
    resolve_tenant,
)


def build_server() -> tuple[Server, StreamableHTTPSessionManager]:
    """Construit le serveur MCP frontal bas-niveau + son gestionnaire de sessions.

    Note : l'authentification est vérifiée ici, à la frontière des primitives
    (list_tools / call_tool), et non à l'étape initialize — c'est intentionnel :
    initialize ne transporte pas encore les en-têtes de la requête cliente.
    """
    server: Server = Server("workspace-portal-mcp")

    @server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def _list_tools() -> list[types.Tool]:
        req = server.request_context.request
        token = extract_bearer(req.headers if req is not None else {})
        # Lecture seule — pas de commit nécessaire.
        async with _get_engine().connect() as conn:
            tenant = await resolve_tenant(conn, token)
            if tenant is None:
                raise McpError(_UNAUTHORIZED)
            return await build_tool_descriptors(
                conn, apikey_id=str(tenant["id"]), owner_login=str(tenant["owner_login"])
            )

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> types.CallToolResult:
        req = server.request_context.request
        token = extract_bearer(req.headers if req is not None else {})
        # connect() + commit() explicite : la ligne d'audit est persistée même
        # quand execute_tool_call lève McpError (denied / error / timeout).
        # begin() rollbackerait sur exception, effaçant la trace — c'est le bug corrigé ici.
        async with _get_engine().connect() as conn:
            tenant = await resolve_tenant(conn, token)
            if tenant is None:
                # Pas d'audit écrit avant ce point — rollback implicite est sans effet.
                raise McpError(_UNAUTHORIZED)
            try:
                result = await execute_tool_call(
                    conn, apikey_id=str(tenant["id"]),
                    owner_login=str(tenant["owner_login"]),
                    name=name, arguments=arguments or {},
                )
            except McpError:
                await conn.commit()  # persiste la ligne d'audit écrite avant le raise
                raise
            await conn.commit()
            return result

    @server.list_prompts()  # type: ignore[no-untyped-call,untyped-decorator]
    async def _list_prompts() -> list[types.Prompt]:
        req = server.request_context.request
        token = extract_bearer(req.headers if req is not None else {})
        async with _get_engine().connect() as conn:
            tenant = await resolve_tenant(conn, token)
            if tenant is None:
                raise McpError(_UNAUTHORIZED)
            return await build_prompt_descriptors(
                conn, apikey_id=str(tenant["id"]), owner_login=str(tenant["owner_login"])
            )

    @server.get_prompt()  # type: ignore[no-untyped-call,untyped-decorator]
    async def _get_prompt(
        name: str, arguments: dict[str, str] | None
    ) -> types.GetPromptResult:
        req = server.request_context.request
        token = extract_bearer(req.headers if req is not None else {})
        async with _get_engine().connect() as conn:
            tenant = await resolve_tenant(conn, token)
            if tenant is None:
                raise McpError(_UNAUTHORIZED)
            try:
                result = await execute_prompt_get(
                    conn, apikey_id=str(tenant["id"]),
                    owner_login=str(tenant["owner_login"]),
                    name=name, arguments=arguments,
                )
            except McpError:
                await conn.commit()
                raise
            await conn.commit()
            return result

    manager = StreamableHTTPSessionManager(app=server, stateless=False)
    return server, manager

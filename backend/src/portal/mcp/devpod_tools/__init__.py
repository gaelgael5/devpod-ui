"""Backend MCP interne `devpod` : dispatch + implémentations des primitives.

Façade I-1 : les impls appellent les services internes du portail (`DevPodService`,
`ws_exec`), jamais SSH/tmux en direct. Routé depuis `handlers.execute_tool_call`
quand `target.transport == "internal"`.
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
from collections.abc import Awaitable, Callable
from typing import Any

from mcp import types
from mcp.shared.exceptions import McpError
from mcp.types import METHOD_NOT_FOUND, ErrorData
from sqlalchemy.ext.asyncio import AsyncConnection

from ...db.user_config import load_user_db
from ...devpod.exec import ws_exec
from .errors import DevpodToolError
from .paths import safe_workspace_path

_WS_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")
_DEFAULT_IGNORE = [".git", ".venv", "node_modules", "__pycache__"]

__all__ = ["DevpodToolError", "execute_internal_tool"]


def get_service() -> Any:
    """Singleton DevPodService (lazy import : évite le cycle mcp ↔ routes)."""
    from ...routes.workspace_ops import _get_service

    return _get_service()


def _require_ws(args: dict[str, Any]) -> str:
    name = args.get("workspace")
    if not isinstance(name, str) or not _WS_NAME_RE.fullmatch(name):
        raise DevpodToolError(f"nom de workspace invalide: {name!r}")
    return name


def _require_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str):
        raise DevpodToolError(f"paramètre requis manquant: {key}")
    return value


def _ok(payload: Any) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(payload))])


def _err(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        isError=True, content=[types.TextContent(type="text", text=message)]
    )


def _ws_summary(spec: Any, ws_id: str, status: str) -> dict[str, Any]:
    return {
        "id": ws_id,
        "name": spec.name,
        "repo": spec.source,
        "status": status,
        "node": spec.host or None,
        "recipe": spec.recipes,
        "tags": [],  # WorkspaceSpec n'a pas de tags en v1 (backlog).
    }


async def _workspace_list(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    cfg = await load_user_db(owner_login, conn)
    statuses = {
        s["ws_id"]: s.get("status", "unknown")
        for s in await get_service().list_workspaces(owner_login)
    }
    flt = args.get("status", "all")
    rows = []
    for spec in cfg.workspaces:
        ws_id = f"{owner_login}-{spec.name}"
        status = statuses.get(ws_id, "unknown")
        if flt != "all" and status != flt:
            continue
        rows.append(_ws_summary(spec, ws_id, status))
    return rows


async def _workspace_status(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    ws_id = f"{owner_login}-{name}"
    st = await get_service().status(owner_login, ws_id)
    status = st.get("status", "unknown")
    return {
        "workspace": name,
        "health": status,
        "container_up": status == "running",
        "agent_up": None,  # sondé via session_* (lot 5) ; non résolu ici.
    }


def _build_tree(lines: list[str]) -> dict[str, Any]:
    """Construit une arborescence imbriquée depuis la sortie `find -printf '%y\\t%p\\n'`."""
    root: dict[str, Any] = {"name": ".", "type": "dir", "children": []}
    for raw in lines:
        line = raw.rstrip("\n")
        if "\t" not in line:
            continue
        typ, path = line.split("\t", 1)
        if path in (".", "./", ""):
            continue
        rel = path[2:] if path.startswith("./") else path
        parts = [seg for seg in rel.split("/") if seg]
        cur = root
        for i, part in enumerate(parts):
            is_leaf = i == len(parts) - 1
            children = cur.setdefault("children", [])
            node = next((c for c in children if c["name"] == part), None)
            if node is None:
                node_type = ("dir" if typ == "d" else "file") if is_leaf else "dir"
                node = {"name": part, "type": node_type}
                if node_type == "dir":
                    node["children"] = []
                children.append(node)
            cur = node
    return root


async def _workspace_read_file(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    name = _require_ws(args)
    rel = _require_str(args, "path")
    p = safe_workspace_path(name, rel)
    rc, out = await ws_exec(owner_login, f"{owner_login}-{name}", f"cat {shlex.quote(p)}")
    if rc != 0:
        raise DevpodToolError(f"lecture impossible: {out}")
    data = out.encode()
    return {
        "path": rel,
        "content": out,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


async def _workspace_tree(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    p = safe_workspace_path(name, str(args.get("path", ".")))
    depth = int(args.get("depth", 2))
    ignore = args.get("ignore", _DEFAULT_IGNORE)
    prune = ""
    if ignore:
        ign = " -o ".join(f"-name {shlex.quote(str(i))}" for i in ignore)
        prune = f"\\( {ign} \\) -prune -o"
    cmd = f"cd {shlex.quote(p)} && find . -maxdepth {depth} {prune} -printf '%y\\t%p\\n'"
    rc, out = await ws_exec(owner_login, f"{owner_login}-{name}", cmd)
    if rc != 0:
        raise DevpodToolError(f"arborescence indisponible: {out}")
    return _build_tree(out.splitlines())


_IMPLS: dict[str, Callable[[AsyncConnection, dict[str, Any], str], Awaitable[Any]]] = {
    "workspace_list": _workspace_list,
    "workspace_status": _workspace_status,
    "workspace_tree": _workspace_tree,
    "workspace_read_file": _workspace_read_file,
}


async def execute_internal_tool(
    conn: AsyncConnection, name: str, arguments: dict[str, Any], *, owner_login: str
) -> types.CallToolResult:
    """Dispatch d'une primitive devpod. Erreur métier → isError ; tool inconnu → McpError."""
    impl = _IMPLS.get(name)
    if impl is None:
        raise McpError(ErrorData(code=METHOD_NOT_FOUND, message="unknown devpod tool"))
    try:
        payload = await impl(conn, arguments, owner_login)
    except DevpodToolError as exc:
        return _err(exc.message)
    return _ok(payload)

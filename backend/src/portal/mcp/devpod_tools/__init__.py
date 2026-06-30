"""Backend MCP interne `devpod` : dispatch + implémentations des primitives.

Façade I-1 : les impls appellent les services internes du portail (`DevPodService`,
`ws_exec`), jamais SSH/tmux en direct. Routé depuis `handlers.execute_tool_call`
quand `target.transport == "internal"`.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import posixpath
import re
import shlex
import time
from collections.abc import Awaitable, Callable
from typing import Any

from mcp import types
from mcp.shared.exceptions import McpError
from mcp.types import METHOD_NOT_FOUND, ErrorData
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ...config.store import _data_root, load_global, load_user, save_user
from ...db.user_config import load_user_db
from ...devpod.exec import TMUX_SOCK_DETECT, tmux, ws_exec
from . import operations
from .compose_tools import COMPOSE_IMPLS
from .errors import DevpodToolError
from .message_tools import MESSAGE_IMPLS
from .paths import safe_workspace_path

# Préfixe socket réutilisable pour les commandes tmux multi-étapes (session_open).
_TMUX_SOCK = '${TMUX_SOCK:+-S "$TMUX_SOCK"}'

_WS_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")
_SECRET_REF_RE = re.compile(r"^\$\{(vault|env)://.+\}$")
_ENV_TARGET_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
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
    container_up = status == "running"

    agent_up: bool | None = None
    if container_up:
        rc, _ = await ws_exec(owner_login, ws_id, "true", timeout=5.0)
        agent_up = rc == 0

    return {
        "workspace": name,
        "health": status,
        "container_up": container_up,
        "agent_up": agent_up,
    }


async def _workspace_logs(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    source = str(args.get("source", "container"))
    lines = int(args.get("lines", 200))
    if source == "agent":
        cap = await _session_capture(conn, {"workspace": name, "lines": lines}, owner_login)
        return {"source": "agent", "output": cap["output"]}
    # setup / container : journal de provisioning du portail (flux unique en v1).
    ws_id = f"{owner_login}-{name}"
    logs_root = _data_root() / "logs"
    log_file = logs_root / owner_login / f"{ws_id}.log"
    if not log_file.is_relative_to(logs_root) or not log_file.exists():
        return {"source": source, "output": ""}
    text = await asyncio.to_thread(log_file.read_text, encoding="utf-8", errors="replace")
    tail = "\n".join(text.splitlines()[-lines:])
    return {"source": source, "output": tail}


def _to_int_or_none(token: str) -> int | None:
    token = token.strip()
    return int(token) if token.isdigit() else None


async def _workspace_resources(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    name = _require_ws(args)
    ws_id = f"{owner_login}-{name}"
    root = f"/workspaces/{name}"
    cg = "/sys/fs/cgroup"
    # CPU reads anchored to emit exactly one line (missing file → empty line)
    cpu_read = (
        f"{{ cat {cg}/cpu.stat 2>/dev/null | "
        f"awk '/usage_usec/{{print $2}}'; }} | head -1 | grep . || echo ''; "
    )
    cmd = (
        cpu_read +
        "sleep 0.1; " +
        cpu_read +
        f"cat {cg}/memory.current 2>/dev/null || echo ''; " +
        f"cat {cg}/memory.max 2>/dev/null || echo ''; " +
        f"df -B1 --output=used,size {shlex.quote(root)} 2>/dev/null | tail -1"
    )
    rc, out = await ws_exec(owner_login, ws_id, cmd, timeout=10.0)
    if rc != 0:
        raise DevpodToolError(f"ressources indisponibles: {out}")
    lines = out.splitlines()
    u1 = _to_int_or_none(lines[0]) if len(lines) > 0 else None
    u2 = _to_int_or_none(lines[1]) if len(lines) > 1 else None
    cpu_pct = round((u2 - u1) / 100_000 * 100, 1) if u1 is not None and u2 is not None else None
    mem_used = _to_int_or_none(lines[2]) if len(lines) > 2 else None
    mem_limit = _to_int_or_none(lines[3]) if len(lines) > 3 else None  # "max" -> None
    disk_used = disk_limit = None
    if len(lines) > 4:
        parts = lines[4].split()
        if len(parts) == 2:
            disk_used, disk_limit = _to_int_or_none(parts[0]), _to_int_or_none(parts[1])
    return {
        "cpu_pct": cpu_pct,
        "mem_used": mem_used,
        "mem_limit": mem_limit,
        "disk_used": disk_used,
        "disk_limit": disk_limit,
    }


def _parse_git_porcelain(out: str) -> dict[str, Any]:
    branch = ""
    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []
    for line in out.splitlines():
        if line.startswith("## "):
            branch = line[3:].split("...", 1)[0].strip()
            continue
        if len(line) < 3:
            continue
        x, y, path = line[0], line[1], line[3:]
        if line.startswith("??"):
            untracked.append(path)
            continue
        if x != " ":
            staged.append(path)
        if y != " ":
            unstaged.append(path)
    return {"branch": branch, "staged": staged, "unstaged": unstaged, "untracked": untracked}


async def _workspace_git_status(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    name = _require_ws(args)
    ws_id = f"{owner_login}-{name}"
    root = f"/workspaces/{name}"
    cmd = f"cd {shlex.quote(root)} && git status --porcelain=v1 -b"
    rc, out = await ws_exec(owner_login, ws_id, cmd)
    if rc != 0:
        raise DevpodToolError(f"git status impossible: {out}")
    result = _parse_git_porcelain(out)
    if args.get("with_diff", False):
        diff_cmd = f"cd {shlex.quote(root)} && git diff"
        rc2, diff = await ws_exec(owner_login, ws_id, diff_cmd)
        if rc2 != 0:
            raise DevpodToolError(f"git diff impossible: {diff}")
        result["diff"] = diff
    return result


async def _workspace_git_commit(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    name = _require_ws(args)
    message = _require_str(args, "message")
    ws_id = f"{owner_login}-{name}"
    root = f"/workspaces/{name}"

    cmd = f"cd {shlex.quote(root)} && git rev-parse --abbrev-ref HEAD"
    rc, branch = await ws_exec(owner_login, ws_id, cmd)
    branch = branch.strip()
    if rc != 0:
        raise DevpodToolError(f"branche introuvable: {branch}")
    if branch != "dev":
        raise DevpodToolError(f"commit refusé : branche '{branch}' ≠ 'dev'")

    files = args.get("files")
    if isinstance(files, list) and files:
        add = "git add " + " ".join(shlex.quote(str(f)) for f in files)
    else:
        add = "git add -A"
    rc, out = await ws_exec(
        owner_login, ws_id,
        f"cd {shlex.quote(root)} && {add} && git commit -m {shlex.quote(message)}",
    )
    if rc != 0:
        raise DevpodToolError(f"commit échoué: {out}")

    rc, sha = await ws_exec(
        owner_login, ws_id, f"cd {shlex.quote(root)} && git rev-parse HEAD"
    )
    if rc != 0:
        raise DevpodToolError(f"rev-parse HEAD échoué: {sha}")
    sha = sha.strip()

    pushed = False
    if bool(args.get("push", False)):
        cmd = f"cd {shlex.quote(root)} && git push origin dev"
        rc, out = await ws_exec(owner_login, ws_id, cmd)
        if rc != 0:
            raise DevpodToolError(f"push échoué: {out}")
        pushed = True
    return {"commit_sha": sha, "branch": branch, "pushed": pushed}


async def _workspace_get(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    cfg = await load_user_db(owner_login, conn)
    spec = next((s for s in cfg.workspaces if s.name == name), None)
    if spec is None:
        raise DevpodToolError(f"workspace inconnu: {name}")
    ws_id = f"{owner_login}-{name}"
    st = await get_service().status(owner_login, ws_id)
    sessions = await _session_list(conn, {"workspace": name}, owner_login)
    raw_dt = st.get("created_at") or st.get("updated_at")
    return {
        "id": ws_id,
        "name": spec.name,
        "repo": spec.source,
        "branch": spec.branch or None,
        "status": st.get("status", "unknown"),
        "node": spec.host or None,
        "recipe": spec.recipes,
        "tags": [],
        "devcontainer_ref": spec.devcontainer_path or spec.template or None,
        "sessions": sessions,
        "created_at": raw_dt.isoformat() if hasattr(raw_dt, "isoformat") else raw_dt,
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


async def _workspace_secrets_list(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    name = _require_ws(args)
    cfg = await load_user_db(owner_login, conn)
    spec = next((s for s in cfg.workspaces if s.name == name), None)
    if spec is None:
        raise DevpodToolError(f"workspace inconnu: {name}")
    refs = [
        {"target": key, "reference": val}
        for key, val in (spec.env or {}).items()
        if isinstance(val, str) and _SECRET_REF_RE.fullmatch(val)
    ]
    return {"references": refs}


async def _workspace_secrets_bind(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    name = _require_ws(args)
    reference = _require_str(args, "reference")
    target = _require_str(args, "target")
    if not _SECRET_REF_RE.fullmatch(reference):
        raise DevpodToolError("reference invalide : attendu '${vault://...}' ou '${env://...}'")
    if not _ENV_TARGET_RE.fullmatch(target):
        raise DevpodToolError(f"cible env invalide: {target!r}")
    cfg = await load_user(owner_login)
    spec = next((s for s in cfg.workspaces if s.name == name), None)
    if spec is None:
        raise DevpodToolError(f"workspace inconnu: {name}")
    updated = spec.model_copy(update={"env": {**(spec.env or {}), target: reference}})
    cfg.workspaces = [updated if s.name == name else s for s in cfg.workspaces]
    await save_user(owner_login, cfg)
    return {"target": target, "bound": True}


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


async def _workspace_mkdir(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    rel = _require_str(args, "path")
    p = safe_workspace_path(name, rel)
    rc, out = await ws_exec(owner_login, f"{owner_login}-{name}", f"mkdir -p {shlex.quote(p)}")
    if rc != 0:
        raise DevpodToolError(out)
    return {"path": rel}


async def _workspace_write_file(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    name = _require_ws(args)
    rel = _require_str(args, "path")
    p = safe_workspace_path(name, rel)
    content = _require_str(args, "content")
    create = bool(args.get("create_dirs", True))
    b64 = base64.b64encode(content.encode()).decode()
    parent = posixpath.dirname(p)
    mk = f"mkdir -p {shlex.quote(parent)} && " if create else ""
    # Écriture atomique (I-6) : tempfile dans le répertoire cible + rename.
    cmd = (
        f"{mk}tmp=$(mktemp {shlex.quote(parent)}/.tmp.XXXXXX) && "
        f'printf %s {shlex.quote(b64)} | base64 -d > "$tmp" && mv -f "$tmp" {shlex.quote(p)}'
    )
    rc, out = await ws_exec(owner_login, f"{owner_login}-{name}", cmd)
    if rc != 0:
        raise DevpodToolError(out)
    data = content.encode()
    return {"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


async def _workspace_exec(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    command = _require_str(args, "command")
    timeout = int(args.get("timeout_s", 60))
    cwd_arg = args.get("cwd")
    cwd = safe_workspace_path(name, str(cwd_arg)) if cwd_arg else f"/workspaces/{name}"
    full = f"cd {shlex.quote(cwd)} && {command}"
    rc, out = await ws_exec(owner_login, f"{owner_login}-{name}", full, timeout=float(timeout))
    # Commande one-shot : le code retour fait partie du résultat (pas une erreur métier).
    # ws_exec fusionne stdout+stderr → stderr vide en v1 (séparation = backlog §7).
    return {"stdout": out, "stderr": "", "exit_code": rc}


async def _workspace_stop(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)

    async def work() -> Any:
        await get_service().stop(owner_login, f"{owner_login}-{name}")
        return {"workspace": name, "status": "stopped"}

    return {"operation_id": operations.launch_operation("workspace_stop", name, owner_login, work)}


async def _start_existing(login: str, name: str, conn: AsyncConnection) -> str:
    """Indirection testable vers le redémarrage (lazy import : cycle mcp ↔ routes)."""
    from ...routes.workspace_ops import start_existing_workspace

    return await start_existing_workspace(login, name, conn)


async def _workspace_reconnect(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    name = _require_ws(args)

    async def work() -> Any:
        from ...db.engine import _get_engine

        async with _get_engine().begin() as bg_conn:
            await _start_existing(owner_login, name, bg_conn)
        return {"workspace": name, "status": "provisioning"}

    op = operations.launch_operation("workspace_reconnect", name, owner_login, work)
    return {"operation_id": op}


async def _workspace_restart(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)

    async def work() -> Any:
        from ...db.engine import _get_engine

        await get_service().stop(owner_login, f"{owner_login}-{name}")
        async with _get_engine().begin() as bg_conn:
            await _start_existing(owner_login, name, bg_conn)
        return {"workspace": name, "status": "provisioning"}

    oid = operations.launch_operation("workspace_restart", name, owner_login, work)
    return {"operation_id": oid}


def _session_id(workspace: str, session: str) -> str:
    return f"{workspace}:{session}"


async def _session_open(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    sess = str(args.get("name", "main"))
    command = _require_str(args, "command")
    cwd = safe_workspace_path(name, str(args["cwd"])) if args.get("cwd") else f"/workspaces/{name}"
    inner = f"cd {shlex.quote(cwd)} && {command}"
    # Idempotent (I-3) : on ne relance l'agent que si la session n'existe pas déjà.
    cmd = (
        f"{TMUX_SOCK_DETECT}; "
        f"tmux {_TMUX_SOCK} has-session -t {shlex.quote(sess)} 2>/dev/null || "
        f"tmux {_TMUX_SOCK} new-session -d -s {shlex.quote(sess)} {shlex.quote(inner)}"
    )
    rc, out = await ws_exec(owner_login, f"{owner_login}-{name}", cmd)
    if rc != 0:
        raise DevpodToolError(out)
    return {
        "session_id": _session_id(name, sess),
        "workspace": name,
        "name": sess,
        "command": command,
    }


async def _session_send(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    sess = str(args.get("session", "main"))
    text = _require_str(args, "text")
    submit = bool(args.get("submit", True))
    # _origin / _depth (I-7) présents au schéma mais non câblés en v1 : ignorés ici.
    keys = shlex.quote(text) + (" Enter" if submit else "")
    rc, out = await ws_exec(
        owner_login, f"{owner_login}-{name}", tmux(f"send-keys -t {shlex.quote(sess)} {keys}")
    )
    if rc != 0:
        raise DevpodToolError(out)
    return {"sent": True}


async def _session_interrupt(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    sess = str(args.get("session", "main"))
    rc, out = await ws_exec(
        owner_login, f"{owner_login}-{name}", tmux(f"send-keys -t {shlex.quote(sess)} C-c")
    )
    if rc != 0:
        raise DevpodToolError(out)
    return {"interrupted": True}


async def _session_close(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    sess = _require_str(args, "session")
    rc, out = await ws_exec(
        owner_login, f"{owner_login}-{name}", tmux(f"kill-session -t {shlex.quote(sess)}")
    )
    if rc != 0:
        raise DevpodToolError(out)
    return {"closed": True}


async def _session_capture(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    sess = str(args.get("session", "main"))
    lines = int(args.get("lines", 200))
    # -e conserve les codes ANSI : buffer brut tel que l'œil le verrait (I-2/I-4).
    rc, out = await ws_exec(
        owner_login,
        f"{owner_login}-{name}",
        tmux(f"capture-pane -p -e -t {shlex.quote(sess)} -S -{lines}"),
    )
    if rc != 0:
        raise DevpodToolError(out)
    return {"output": out}


async def _session_list(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    fmt = "'#{session_name}|#{pane_current_command}'"
    rc, out = await ws_exec(
        owner_login, f"{owner_login}-{name}", tmux(f"list-sessions -F {fmt} 2>/dev/null || true")
    )
    sessions = []
    for line in out.splitlines():
        if "|" not in line:
            continue
        sname, _, cmd = line.partition("|")
        sessions.append(
            {"session_id": _session_id(name, sname), "name": sname, "command": cmd, "alive": True}
        )
    return sessions


async def _session_get(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    sess = str(args.get("session", "main"))
    fmt = "'#{session_name}|#{pane_id}|#{pane_current_command}|#{session_created}'"
    rc, out = await ws_exec(
        owner_login,
        f"{owner_login}-{name}",
        tmux(f"display-message -p -t {shlex.quote(sess)} {fmt} 2>/dev/null || true"),
    )
    line = out.strip()
    if not line or "|" not in line:
        raise DevpodToolError("session introuvable")
    parts = line.split("|")
    created = parts[3] if len(parts) > 3 else "0"
    uptime = max(0, int(time.time()) - int(created)) if created.isdigit() else 0
    return {
        "session_id": _session_id(name, parts[0]),
        "name": parts[0],
        "command": parts[2] if len(parts) > 2 else "",
        "alive": True,
        "pane_id": parts[1] if len(parts) > 1 else "",
        "uptime_s": uptime,
    }


class _ReloadResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str
    reconnected: bool
    reason: str | None = None


async def _portal_reload(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    ws_id = f"{owner_login}-{name}"

    try:
        st = await get_service().status(owner_login, ws_id)
        status = st.get("status", "unknown")
    except Exception:
        return _ReloadResult(
            workspace=name, reconnected=False, reason="node_unreachable"
        ).model_dump()

    if status != "running":
        return _ReloadResult(
            workspace=name, reconnected=False, reason="container_down"
        ).model_dump()

    get_service().reconnect(owner_login, ws_id)
    return _ReloadResult(workspace=name, reconnected=True).model_dump()


async def _node_list(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    cfg = load_global()
    rows = []
    for h in cfg.hosts:
        if getattr(h, "usage", "workspaces") != "workspaces":
            continue
        rows.append({
            "node_id": h.name,
            "name": h.name,
            "host": h.address or h.docker_host or None,
            "status": "configured",
            "capacity": None,
        })
    return rows


async def _operations_get(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    oid = _require_str(args, "operation_id")
    op = operations.get_operation(oid)
    if op is None or op.get("owner_login") != owner_login:
        raise DevpodToolError(f"opération inconnue: {oid}")
    return {k: op[k] for k in (
        "operation_id", "kind", "workspace", "state", "progress", "result", "error",
    )}


async def _operations_list(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    ws = args.get("workspace")
    rows = operations.list_operations(owner_login, workspace=ws if isinstance(ws, str) else None)
    return [
        {k: op[k] for k in ("operation_id", "kind", "workspace", "state", "progress")}
        for op in rows
    ]


async def _workspace_create(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    """Crée un workspace de façon asynchrone. Retourne un operation_id (spec 25 §B)."""
    name = str(args.get("name", ""))
    if not _WS_NAME_RE.fullmatch(name):
        raise DevpodToolError(f"nom de workspace invalide: {name!r}")
    repo = _require_str(args, "repo")
    branch = str(args.get("branch", "dev"))
    recipe = args.get("recipe")
    node = str(args.get("node", ""))
    recipes = [str(recipe)] if isinstance(recipe, str) and recipe else []

    async def work() -> Any:
        from ...db.engine import _get_engine
        from ...devpod.provision import ProvisionParams, provision_workspace

        async with _get_engine().begin() as bg_conn:
            ws_id = await provision_workspace(
                owner_login,
                ProvisionParams(
                    name=name, source=repo, branch=branch, host=node, recipes=recipes
                ),
                bg_conn,
            )
        return {"workspace": name, "ws_id": ws_id, "status": "provisioning"}

    oid = operations.launch_operation("workspace_create", name, owner_login, work)
    return {"operation_id": oid}


async def _workspace_delete(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    """Supprime un workspace de façon asynchrone. Retourne un operation_id (spec 25 §B)."""
    name = _require_ws(args)
    if args.get("confirm") is not True:
        raise DevpodToolError("suppression refusée : confirm doit valoir true")

    async def work() -> Any:
        result = await get_service().delete(owner_login, f"{owner_login}-{name}", shelve=True)
        return {"workspace": name, "deleted": True, **result}

    oid = operations.launch_operation("workspace_delete", name, owner_login, work)
    return {"operation_id": oid}


async def _recreate_workspace(
    owner_login: str, name: str, mutate: Callable[[Any], Any]
) -> str:
    """Recrée un workspace après mutation de son spec (save -> delete shelve=False -> re-provision).

    Retourne le nouveau ws_id.
    """
    from ...db.engine import _get_engine
    from ...devpod.provision import ProvisionParams, provision_workspace

    cfg = await load_user(owner_login)
    spec = next((s for s in cfg.workspaces if s.name == name), None)
    if spec is None:
        raise DevpodToolError(f"workspace inconnu: {name}")
    spec_updated = mutate(spec)
    cfg.workspaces = [spec_updated if s.name == name else s for s in cfg.workspaces]
    await save_user(owner_login, cfg)
    await get_service().delete(owner_login, f"{owner_login}-{name}", shelve=False)
    async with _get_engine().begin() as bg_conn:
        return await provision_workspace(
            owner_login,
            ProvisionParams(
                name=name, source=spec_updated.source, branch=spec_updated.branch,
                git_credential=spec_updated.git_credential, host=spec_updated.host,
                recipes=spec_updated.recipes, extra_sources=spec_updated.extra_sources,
                profile=spec_updated.profile, recipe_volumes=spec_updated.recipe_volumes,
                generate_ssh_key=spec_updated.ssh_key,
            ),
            bg_conn,
        )


async def _workspace_apply_recipe(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    """Applique/met à jour une recette sur un workspace existant de façon asynchrone."""
    name = _require_ws(args)
    recipe = _require_str(args, "recipe")

    async def work() -> Any:
        recipes_holder: dict[str, Any] = {}

        def mutate(spec: Any) -> Any:
            recipes = list(dict.fromkeys([*spec.recipes, recipe]))
            recipes_holder["recipes"] = recipes
            return spec.model_copy(update={"recipes": recipes})

        ws_id = await _recreate_workspace(owner_login, name, mutate)
        return {
            "workspace": name,
            "ws_id": ws_id,
            "recipes": recipes_holder["recipes"],
            "status": "provisioning",
        }

    oid = operations.launch_operation("workspace_apply_recipe", name, owner_login, work)
    return {"operation_id": oid}


async def _workspace_profile_set(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    """Applique un profil VS Code au workspace existant de façon asynchrone (recréation)."""
    name = _require_ws(args)
    profile_slug = _require_str(args, "profile")

    async def work() -> Any:
        from ...config.models import ProfileRef

        def mutate(spec: Any) -> Any:
            return spec.model_copy(update={"profile": ProfileRef(scope="user", slug=profile_slug)})

        ws_id = await _recreate_workspace(owner_login, name, mutate)
        return {
            "workspace": name,
            "ws_id": ws_id,
            "profile": profile_slug,
            "status": "provisioning",
        }

    oid = operations.launch_operation("workspace_profile_set", name, owner_login, work)
    return {"operation_id": oid}


_IMPLS: dict[str, Callable[[AsyncConnection, dict[str, Any], str], Awaitable[Any]]] = {
    "workspace_list": _workspace_list,
    "workspace_status": _workspace_status,
    "workspace_logs": _workspace_logs,
    "workspace_resources": _workspace_resources,
    "workspace_git_status": _workspace_git_status,
    "workspace_git_commit": _workspace_git_commit,
    "workspace_get": _workspace_get,
    "workspace_tree": _workspace_tree,
    "workspace_read_file": _workspace_read_file,
    "workspace_secrets_list": _workspace_secrets_list,
    "workspace_secrets_bind": _workspace_secrets_bind,
    "workspace_mkdir": _workspace_mkdir,
    "workspace_write_file": _workspace_write_file,
    "workspace_exec": _workspace_exec,
    "workspace_reconnect": _workspace_reconnect,
    "workspace_stop": _workspace_stop,
    "workspace_restart": _workspace_restart,
    "session_open": _session_open,
    "session_send": _session_send,
    "session_interrupt": _session_interrupt,
    "session_close": _session_close,
    "session_capture": _session_capture,
    "session_list": _session_list,
    "session_get": _session_get,
    "node_list": _node_list,
    "operations_get": _operations_get,
    "operations_list": _operations_list,
    "portal_reload": _portal_reload,
    "workspace_create": _workspace_create,
    "workspace_delete": _workspace_delete,
    "workspace_apply_recipe": _workspace_apply_recipe,
    "workspace_profile_set": _workspace_profile_set,
    **COMPOSE_IMPLS,
    **MESSAGE_IMPLS,
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

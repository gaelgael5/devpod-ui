from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..auth.rbac import UserInfo, require_admin
from ..config.models import _PROXMOX_NAME_RE, ProxmoxNode
from ..config.store import load_global, save_global

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["admin"])

_MAX_KEY_BYTES = 16 * 1024  # 16 Ko — largement suffisant pour une clé SSH


# ─── Helpers filesystem ───────────────────────────────────────────────────────

def _data_root() -> Path:
    return Path(os.environ.get("PORTAL_DATA_ROOT", "/data"))


def _key_dir() -> Path:
    p = _data_root() / "ssh_keys" / "proxmox"
    p.mkdir(parents=True, exist_ok=True)
    p.chmod(0o700)  # répertoire owner-only, indépendamment du umask
    return p


def _write_key_atomic(key_path: Path, key_bytes: bytes) -> None:
    """Écrit la clé SSH de façon atomique avec permissions 0o600."""
    tmp = key_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)  # nettoie un éventuel résidu
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key_bytes)
        tmp.rename(key_path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _validate_key_bytes(key_bytes: bytes) -> None:
    if len(key_bytes) > _MAX_KEY_BYTES:
        raise HTTPException(status_code=413, detail="SSH key file too large (max 16 KB)")
    if not key_bytes.startswith(b"-----BEGIN"):
        raise HTTPException(status_code=422, detail="SSH key must be a PEM-encoded private key")


# ─── Helpers SSH ──────────────────────────────────────────────────────────────

def _ssh_opts(node: ProxmoxNode) -> list[str]:
    return [
        "-i", node.ssh_key_path,
        "-p", str(node.ssh_port),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=15",
        "-o", "ServerAliveInterval=10",
    ]


async def _ssh_run(node: ProxmoxNode, command: str, timeout: float = 30.0) -> str:
    """Exécute une commande SSH et retourne stdout (stderr ignoré)."""
    proc = await asyncio.create_subprocess_exec(
        "ssh", *_ssh_opts(node), f"{node.ssh_user}@{node.address}",
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return stdout.decode("utf-8", errors="replace")


async def _ssh_stream(node: ProxmoxNode, commands: list[str]):
    """Exécute des commandes shell sur le nœud SSH et streame stdout+stderr."""
    script = "set -euo pipefail\n" + "\n".join(commands) + "\n"
    proc = await asyncio.create_subprocess_exec(
        "ssh", *_ssh_opts(node), f"{node.ssh_user}@{node.address}",
        "bash -s",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write(script.encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()

    while True:
        chunk = await proc.stdout.read(4096)
        if not chunk:
            break
        yield chunk

    await proc.wait()
    if proc.returncode != 0:
        yield f"\n[ERROR] Script terminé avec le code {proc.returncode}\n".encode()


def _substitute(template: str, args: dict[str, str]) -> str:
    for k, v in args.items():
        template = template.replace(f"{{{k}}}", v)
    return template


# ─── CRUD nœuds Proxmox ───────────────────────────────────────────────────────

@router.get("/proxmox")
async def list_proxmox_nodes(
    user: UserInfo = Depends(require_admin),
) -> list[dict[str, object]]:
    cfg = load_global()
    return [n.model_dump(mode="json") for n in cfg.proxmox_nodes]


@router.post("/proxmox", status_code=201)
async def add_proxmox_node(
    name: str = Form(...),
    address: str = Form(...),
    ssh_user: str = Form("root"),
    ssh_port: int = Form(22),
    pve_node: str = Form("pve"),
    script_url: str = Form(""),
    ssh_key: UploadFile = File(...),
    user: UserInfo = Depends(require_admin),
) -> dict[str, object]:
    if not _PROXMOX_NAME_RE.fullmatch(name):
        raise HTTPException(
            status_code=422,
            detail=f"name {name!r} must match ^[a-z0-9]([a-z0-9-]{{0,38}}[a-z0-9])?$",
        )

    cfg = load_global()
    if any(n.name == name for n in cfg.proxmox_nodes):
        raise HTTPException(status_code=409, detail=f"Proxmox node {name!r} already exists")

    key_bytes = await ssh_key.read(_MAX_KEY_BYTES + 1)
    _validate_key_bytes(key_bytes)

    key_path = _key_dir() / name
    _write_key_atomic(key_path, key_bytes)

    node = ProxmoxNode(
        name=name,
        address=address,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        ssh_key_path=str(key_path),
        pve_node=pve_node,
        script_url=script_url,
    )
    cfg.proxmox_nodes.append(node)
    save_global(cfg)
    _log.info("proxmox_node_added", name=name, address=address, by=user.login)
    return node.model_dump(mode="json")


@router.put("/proxmox/{name}", status_code=200)
async def update_proxmox_node(
    name: str,
    address: str = Form(...),
    ssh_user: str = Form("root"),
    ssh_port: int = Form(22),
    pve_node: str = Form("pve"),
    script_url: str = Form(""),
    ssh_key: Optional[UploadFile] = File(default=None),
    user: UserInfo = Depends(require_admin),
) -> dict[str, object]:
    cfg = load_global()
    node = next((n for n in cfg.proxmox_nodes if n.name == name), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Proxmox node {name!r} not found")

    key_path = node.ssh_key_path  # conserve la clé existante par défaut

    if ssh_key is not None:
        key_bytes = await ssh_key.read(_MAX_KEY_BYTES + 1)
        if key_bytes:  # vide = pas de remplacement
            _validate_key_bytes(key_bytes)
            _write_key_atomic(Path(key_path), key_bytes)

    updated = ProxmoxNode(
        name=name,
        address=address,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        ssh_key_path=key_path,
        pve_node=pve_node,
        script_url=script_url,
    )
    cfg.proxmox_nodes = [updated if n.name == name else n for n in cfg.proxmox_nodes]
    save_global(cfg)
    _log.info("proxmox_node_updated", name=name, address=address, by=user.login)
    return updated.model_dump(mode="json")


@router.delete("/proxmox/{name}", status_code=204)
async def delete_proxmox_node(
    name: str,
    user: UserInfo = Depends(require_admin),
) -> None:
    cfg = load_global()
    node = next((n for n in cfg.proxmox_nodes if n.name == name), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Proxmox node {name!r} not found")
    cfg.proxmox_nodes = [n for n in cfg.proxmox_nodes if n.name != name]
    save_global(cfg)
    Path(node.ssh_key_path).unlink(missing_ok=True)
    _log.info("proxmox_node_deleted", name=name, by=user.login)


# ─── Exécution de script via SSH ──────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    args: dict[str, str]


async def _fetch_spec(node: ProxmoxNode) -> dict[str, object]:
    if not node.script_url:
        raise HTTPException(status_code=404, detail=f"Node {node.name!r} has no script_url configured")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(node.script_url, timeout=15.0, follow_redirects=True)
            resp.raise_for_status()
            return dict(resp.json())
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Failed to fetch script spec: {exc}") from exc


@router.get("/proxmox/{name}/script")
async def get_node_script(
    name: str,
    user: UserInfo = Depends(require_admin),
) -> dict[str, object]:
    """Retourne la spec JSON du script, avec les options dynamiques (option_script) résolues via SSH."""
    cfg = load_global()
    node = next((n for n in cfg.proxmox_nodes if n.name == name), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Proxmox node {name!r} not found")

    spec = await _fetch_spec(node)

    for arg in spec.get("args", []):  # type: ignore[union-attr]
        option_script = arg.get("option_script") if isinstance(arg, dict) else None
        if not option_script:
            continue
        try:
            output = await _ssh_run(node, option_script)
            dynamic = [
                {"value": v.strip(), "label": v.strip()}
                for v in output.strip().splitlines()
                if v.strip()
            ]
            existing = arg.get("options", []) or []
            arg["options"] = existing + dynamic
        except Exception as exc:
            _log.warning("option_script_failed", node=name, arg=arg.get("arg"), error=str(exc))

    return spec


@router.post("/proxmox/{name}/execute")
async def execute_node_script(
    name: str,
    body: ExecuteRequest,
    user: UserInfo = Depends(require_admin),
) -> StreamingResponse:
    """Exécute les commandes du script sur le nœud Proxmox via SSH et streame la sortie."""
    cfg = load_global()
    node = next((n for n in cfg.proxmox_nodes if n.name == name), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Proxmox node {name!r} not found")

    spec = await _fetch_spec(node)
    commands_raw: list[str] = spec.get("commands", [])  # type: ignore[assignment]
    commands = [_substitute(cmd, body.args) for cmd in commands_raw]

    _log.info("proxmox_script_execute", node=name, by=user.login, commands=len(commands))
    return StreamingResponse(
        _ssh_stream(node, commands),
        media_type="text/plain; charset=utf-8",
    )

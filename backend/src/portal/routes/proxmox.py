from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import AsyncIterator, Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..auth.rbac import UserInfo, require_admin
from ..config.models import _PROXMOX_NAME_RE, ProxmoxNode
from ..config.store import load_global, save_global
from ..settings import get_settings

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


def _normalize_key(key_bytes: bytes) -> bytes:
    """Normalise les fins de ligne CRLF → LF et assure une newline finale."""
    text = key_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if not text.endswith(b"\n"):
        text += b"\n"
    return text


def _write_key_atomic(key_path: Path, key_bytes: bytes) -> None:
    """Écrit la clé SSH de façon atomique avec permissions 0o600."""
    key_bytes = _normalize_key(key_bytes)
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
        "-o", "ServerAliveCountMax=30",  # 30 × 10 s = 5 min sans réponse avant déconnexion
        "-o", "TCPKeepAlive=yes",
    ]


async def _ssh_run(node: ProxmoxNode, command: str, timeout: float = 30.0) -> str:
    """Exécute une commande SSH et retourne stdout ; lève RuntimeError si le code de retour est non-zéro."""
    proc = await asyncio.create_subprocess_exec(
        "ssh", *_ssh_opts(node), f"{node.ssh_user}@{node.address}",
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    if proc.returncode != 0:
        msg = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"SSH exited {proc.returncode}: {msg or '(no stderr)'}")
    return stdout.decode("utf-8", errors="replace")


async def _ssh_run_nocheck(node: ProxmoxNode, command: str, timeout: float = 30.0) -> int:
    """Exécute une commande SSH et retourne le code de retour sans lever d'exception."""
    proc = await asyncio.create_subprocess_exec(
        "ssh", *_ssh_opts(node), f"{node.ssh_user}@{node.address}",
        command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return -1
    return proc.returncode or 0


def _flatten_args(args: list[object]) -> list[dict[str, object]]:
    """Aplatit les args en incluant les args imbriqués dans les groupes 'sub'."""
    result: list[dict[str, object]] = []
    for a in args:
        if not isinstance(a, dict):
            continue
        if a.get("type") == "sub":
            result.extend(_flatten_args(a.get("args", [])))  # type: ignore[arg-type]
        else:
            result.append(a)
    return result


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

    try:
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            yield chunk
    except BaseException:
        # GeneratorExit (client déconnecté) ou autre exception : tuer le subprocess
        if proc.returncode is None:
            proc.kill()
        raise
    finally:
        # Toujours reaper le subprocess pour éviter les zombies
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            if proc.returncode is None:
                proc.kill()

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
    password: str = Form(""),
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
        password=password,
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
    password: str = Form(""),
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
        password=password if password else node.password,  # vide = conserver l'existant
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


# ─── Test de connexion SSH ────────────────────────────────────────────────────

@router.post("/proxmox/test-connection")
async def test_proxmox_connection(
    address: str = Form(...),
    ssh_user: str = Form("root"),
    ssh_port: int = Form(22),
    ssh_key: UploadFile = File(...),
    user: UserInfo = Depends(require_admin),
) -> dict[str, object]:
    """Teste une connexion SSH à partir de paramètres fournis directement (clé non encore sauvegardée)."""
    key_bytes = await ssh_key.read(_MAX_KEY_BYTES + 1)
    _validate_key_bytes(key_bytes)
    key_bytes = _normalize_key(key_bytes)
    fd, tmp_path = tempfile.mkstemp(suffix=".key")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(key_bytes)
        os.chmod(tmp_path, 0o600)
        node = ProxmoxNode(
            name="test", address=address,
            ssh_user=ssh_user, ssh_port=ssh_port, ssh_key_path=tmp_path,
        )
        out = await _ssh_run(node, "echo OK", timeout=15.0)
        if out.strip() == "OK":
            return {"ok": True, "error": None}
        return {"ok": False, "error": f"Unexpected output: {out.strip()!r}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.get("/proxmox/{name}/ping")
async def ping_proxmox_node(
    name: str,
    user: UserInfo = Depends(require_admin),
) -> dict[str, object]:
    """Teste la connexion SSH d'un nœud enregistré en utilisant ses paramètres stockés."""
    cfg = load_global()
    node = next((n for n in cfg.proxmox_nodes if n.name == name), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Proxmox node {name!r} not found")
    try:
        out = await _ssh_run(node, "echo OK", timeout=15.0)
        if out.strip() == "OK":
            return {"ok": True, "error": None}
        return {"ok": False, "error": f"Unexpected output: {out.strip()!r}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


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

    for arg in _flatten_args(spec.get("args", [])):  # type: ignore[arg-type]
        option_script = arg.get("option_script")
        if not option_script:
            continue
        try:
            output = await _ssh_run(node, option_script)
            dynamic: list[dict[str, str]] = []
            for v in output.strip().splitlines():
                v = v.strip()
                if not v:
                    continue
                if "|" in v:
                    val, _, lbl = v.partition("|")
                    dynamic.append({"value": val.strip(), "label": lbl.strip()})
                else:
                    dynamic.append({"value": v, "label": v})
            existing = arg.get("options", []) or []
            arg["options"] = existing + dynamic
        except Exception as exc:
            err = str(exc)
            _log.warning("option_script_failed", node=name, arg=arg.get("arg"), error=err)
            arg["_option_script_error"] = err

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

    # Injecter les coordonnées du portail — toujours en dernier pour ne pas être
    # écrasées par des valeurs soumises par l'utilisateur (qui ne voit pas ces champs).
    settings = get_settings()
    body.args["PORTAL_URL"] = cfg.server.external_url
    body.args["PORTAL_TOKEN"] = settings.portal_api_key
    body.args["PORTAL_PVE_NODE"] = node.name

    commands = [_substitute(cmd, body.args) for cmd in commands_raw]

    # Version affichée : token remplacé par *** pour ne jamais apparaître dans le stream
    redacted_args = {**body.args, "PORTAL_TOKEN": "***"}
    display_commands = [_substitute(cmd, redacted_args) for cmd in commands_raw]

    _log.info("proxmox_script_execute", node=name, by=user.login, commands=len(commands))

    async def _stream() -> AsyncIterator[bytes]:
        lines = "\n".join(f"    {cmd}" for cmd in display_commands)
        header = f"==> Commandes exécutées :\n{lines}\n\n"
        yield header.encode("utf-8")
        async for chunk in _ssh_stream(node, commands):
            yield chunk

    return StreamingResponse(_stream(), media_type="text/plain; charset=utf-8")


class ValidateArgRequest(BaseModel):
    arg: str
    args: dict[str, str]


@router.post("/proxmox/{name}/validate-arg")
async def validate_arg(
    name: str,
    body: ValidateArgRequest,
    user: UserInfo = Depends(require_admin),
) -> dict[str, object]:
    """Exécute le test_script d'un argument et retourne valid + message."""
    cfg = load_global()
    node = next((n for n in cfg.proxmox_nodes if n.name == name), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Proxmox node {name!r} not found")

    spec = await _fetch_spec(node)
    flat = _flatten_args(spec.get("args", []))  # type: ignore[arg-type]
    arg_spec = next((a for a in flat if a.get("arg") == body.arg), None)
    if arg_spec is None:
        raise HTTPException(status_code=404, detail=f"Arg {body.arg!r} not found in spec")

    test_script = arg_spec.get("test_script")
    if not isinstance(test_script, dict):
        return {"valid": True, "message": None}

    if_cmd = _substitute(str(test_script.get("if", "")), body.args).strip()
    if not if_cmd:
        return {"valid": True, "message": None}

    code = await _ssh_run_nocheck(node, if_cmd)
    if code == 0:
        return {"valid": True, "message": test_script.get("then") or None}
    return {"valid": False, "message": test_script.get("else") or None}

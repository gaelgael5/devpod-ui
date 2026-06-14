from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..auth.rbac import UserInfo, require_admin
from ..config.models import _PROXMOX_NAME_RE, GlobalConfig, Hypervisor, HypervisorType
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
    p.chmod(0o700)
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
    tmp.unlink(missing_ok=True)
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

def _ssh_opts(node: Hypervisor) -> list[str]:
    return [
        "-i", node.ssh_key_path,
        "-p", str(node.ssh_port),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=15",
        "-o", "ServerAliveInterval=10",
        "-o", "ServerAliveCountMax=30",
        "-o", "TCPKeepAlive=yes",
    ]


async def _ssh_run(node: Hypervisor, command: str, timeout: float = 30.0) -> str:
    """Exécute une commande SSH et retourne stdout.

    Lève RuntimeError si le code de retour est non-zéro.
    """
    proc = await asyncio.create_subprocess_exec(
        "ssh", *_ssh_opts(node), f"{node.ssh_user}@{node.address}",
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        raise
    if proc.returncode != 0:
        msg = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"SSH exited {proc.returncode}: {msg or '(no stderr)'}")
    return stdout.decode("utf-8", errors="replace")


async def _ssh_run_nocheck(node: Hypervisor, command: str, timeout: float = 30.0) -> int:
    """Exécute une commande SSH et retourne le code de retour sans lever d'exception."""
    proc = await asyncio.create_subprocess_exec(
        "ssh", *_ssh_opts(node), f"{node.ssh_user}@{node.address}",
        command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
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
            sub_args = a["args"] if isinstance(a.get("args"), list) else []
            result.extend(_flatten_args(sub_args))
        else:
            result.append(a)
    return result


async def _ssh_stream(node: Hypervisor, commands: list[str]) -> AsyncIterator[bytes]:
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
        if proc.returncode is None:
            proc.kill()
        raise
    finally:
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except TimeoutError:
            if proc.returncode is None:
                proc.kill()

    if proc.returncode != 0:
        yield f"\n[ERROR] Script terminé avec le code {proc.returncode}\n".encode()


def _substitute(template: str, args: dict[str, str]) -> str:
    for k, v in args.items():
        template = template.replace(f"{{{k}}}", v)
    return template


# ─── CRUD types d'hyperviseurs ────────────────────────────────────────────────

class HypervisorTypeRequest(BaseModel):
    name: str
    add_script: str = ""
    destroy_script: str = ""


@router.get("/hypervisor-types")
async def list_hypervisor_types(
    user: UserInfo = Depends(require_admin),
) -> list[dict[str, object]]:
    cfg = load_global()
    return [t.model_dump(mode="json") for t in cfg.hypervisor_types]


@router.post("/hypervisor-types", status_code=201)
async def add_hypervisor_type(
    body: HypervisorTypeRequest,
    user: UserInfo = Depends(require_admin),
) -> dict[str, object]:
    if not _PROXMOX_NAME_RE.fullmatch(body.name):
        raise HTTPException(
            status_code=422,
            detail=f"name {body.name!r} must match ^[a-z0-9]([a-z0-9-]{{0,38}}[a-z0-9])?$",
        )
    cfg = load_global()
    if any(t.name == body.name for t in cfg.hypervisor_types):
        raise HTTPException(status_code=409, detail=f"Hypervisor type {body.name!r} already exists")
    ht = HypervisorType(
        name=body.name, add_script=body.add_script, destroy_script=body.destroy_script,
    )
    cfg.hypervisor_types.append(ht)
    save_global(cfg)
    _log.info("hypervisor_type_added", name=body.name, by=user.login)
    return ht.model_dump(mode="json")


@router.put("/hypervisor-types/{name}", status_code=200)
async def update_hypervisor_type(
    name: str,
    body: HypervisorTypeRequest,
    user: UserInfo = Depends(require_admin),
) -> dict[str, object]:
    cfg = load_global()
    ht = next((t for t in cfg.hypervisor_types if t.name == name), None)
    if ht is None:
        raise HTTPException(status_code=404, detail=f"Hypervisor type {name!r} not found")
    updated = HypervisorType(
        name=name, add_script=body.add_script, destroy_script=body.destroy_script,
    )
    cfg.hypervisor_types = [updated if t.name == name else t for t in cfg.hypervisor_types]
    save_global(cfg)
    _log.info("hypervisor_type_updated", name=name, by=user.login)
    return updated.model_dump(mode="json")


@router.delete("/hypervisor-types/{name}", status_code=204)
async def delete_hypervisor_type(
    name: str,
    user: UserInfo = Depends(require_admin),
) -> None:
    cfg = load_global()
    if not any(t.name == name for t in cfg.hypervisor_types):
        raise HTTPException(status_code=404, detail=f"Hypervisor type {name!r} not found")
    cfg.hypervisor_types = [t for t in cfg.hypervisor_types if t.name != name]
    save_global(cfg)
    _log.info("hypervisor_type_deleted", name=name, by=user.login)


# ─── CRUD hyperviseurs ────────────────────────────────────────────────────────

@router.get("/hypervisors")
async def list_hypervisors(
    user: UserInfo = Depends(require_admin),
) -> list[dict[str, object]]:
    cfg = load_global()
    return [n.model_dump(mode="json") for n in cfg.hypervisors]


@router.post("/hypervisors", status_code=201)
async def add_hypervisor(
    name: str = Form(...),
    address: str = Form(...),
    ssh_user: str = Form("root"),
    ssh_port: int = Form(22),
    pve_node: str = Form("pve"),
    hypervisor_type: str = Form(""),
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
    if any(n.name == name for n in cfg.hypervisors):
        raise HTTPException(status_code=409, detail=f"Hypervisor {name!r} already exists")

    key_bytes = await ssh_key.read(_MAX_KEY_BYTES + 1)
    _validate_key_bytes(key_bytes)

    key_path = _key_dir() / name
    _write_key_atomic(key_path, key_bytes)

    node = Hypervisor(
        name=name,
        address=address,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        ssh_key_path=str(key_path),
        pve_node=pve_node,
        hypervisor_type=hypervisor_type,
        password=password,
    )
    cfg.hypervisors.append(node)
    save_global(cfg)
    _log.info("hypervisor_added", name=name, address=address, by=user.login)
    return node.model_dump(mode="json")


@router.put("/hypervisors/{name}", status_code=200)
async def update_hypervisor(
    name: str,
    address: str = Form(...),
    ssh_user: str = Form("root"),
    ssh_port: int = Form(22),
    pve_node: str = Form("pve"),
    hypervisor_type: str = Form(""),
    password: str = Form(""),
    ssh_key: UploadFile | None = File(default=None),
    user: UserInfo = Depends(require_admin),
) -> dict[str, object]:
    cfg = load_global()
    node = next((n for n in cfg.hypervisors if n.name == name), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Hypervisor {name!r} not found")

    key_path = node.ssh_key_path

    if ssh_key is not None:
        key_bytes = await ssh_key.read(_MAX_KEY_BYTES + 1)
        if key_bytes:
            _validate_key_bytes(key_bytes)
            _write_key_atomic(Path(key_path), key_bytes)

    updated = Hypervisor(
        name=name,
        address=address,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        ssh_key_path=key_path,
        pve_node=pve_node,
        hypervisor_type=hypervisor_type,
        password=password if password else node.password,
    )
    cfg.hypervisors = [updated if n.name == name else n for n in cfg.hypervisors]
    save_global(cfg)
    _log.info("hypervisor_updated", name=name, address=address, by=user.login)
    return updated.model_dump(mode="json")


@router.delete("/hypervisors/{name}", status_code=204)
async def delete_hypervisor(
    name: str,
    user: UserInfo = Depends(require_admin),
) -> None:
    cfg = load_global()
    node = next((n for n in cfg.hypervisors if n.name == name), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Hypervisor {name!r} not found")
    cfg.hypervisors = [n for n in cfg.hypervisors if n.name != name]
    save_global(cfg)
    Path(node.ssh_key_path).unlink(missing_ok=True)
    _log.info("hypervisor_deleted", name=name, by=user.login)


# ─── Test de connexion SSH ────────────────────────────────────────────────────

@router.post("/hypervisors/test-connection")
async def test_hypervisor_connection(
    address: str = Form(...),
    ssh_user: str = Form("root"),
    ssh_port: int = Form(22),
    ssh_key: UploadFile = File(...),
    user: UserInfo = Depends(require_admin),
) -> dict[str, object]:
    """Teste une connexion SSH à partir de paramètres directs (clé non encore sauvegardée)."""
    key_bytes = await ssh_key.read(_MAX_KEY_BYTES + 1)
    _validate_key_bytes(key_bytes)
    key_bytes = _normalize_key(key_bytes)
    fd, tmp_path = tempfile.mkstemp(suffix=".key")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(key_bytes)
        os.chmod(tmp_path, 0o600)
        node = Hypervisor(
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


@router.get("/hypervisors/{name}/ping")
async def ping_hypervisor(
    name: str,
    user: UserInfo = Depends(require_admin),
) -> dict[str, object]:
    """Teste la connexion SSH d'un hyperviseur enregistré en utilisant ses paramètres stockés."""
    cfg = load_global()
    node = next((n for n in cfg.hypervisors if n.name == name), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Hypervisor {name!r} not found")
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


async def _fetch_spec(node: Hypervisor, cfg: GlobalConfig) -> dict[str, object]:
    if not node.hypervisor_type:
        raise HTTPException(
            status_code=404,
            detail=f"Hypervisor {node.name!r} has no type configured",
        )
    hyp_type = next((t for t in cfg.hypervisor_types if t.name == node.hypervisor_type), None)
    if hyp_type is None:
        raise HTTPException(
            status_code=404,
            detail=f"Hypervisor type {node.hypervisor_type!r} not found",
        )
    if not hyp_type.add_script:
        raise HTTPException(
            status_code=404,
            detail=f"Hypervisor type {node.hypervisor_type!r} has no add_script configured",
        )
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(hyp_type.add_script, timeout=15.0, follow_redirects=True)
            resp.raise_for_status()
            return dict(resp.json())
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502, detail=f"Failed to fetch script spec: {exc}",
            ) from exc


@router.get("/hypervisors/{name}/script")
async def get_hypervisor_script(
    name: str,
    user: UserInfo = Depends(require_admin),
) -> dict[str, object]:
    """Retourne la spec JSON du script, avec les options dynamiques résolues via SSH."""
    cfg = load_global()
    node = next((n for n in cfg.hypervisors if n.name == name), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Hypervisor {name!r} not found")

    spec = await _fetch_spec(node, cfg)

    for arg in _flatten_args(spec.get("args", [])):  # type: ignore[arg-type]
        option_script = arg.get("option_script")
        if not option_script:
            continue
        try:
            output = await _ssh_run(node, str(option_script))
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
            raw_opts = arg.get("options") or []
            existing: list[dict[str, str]] = raw_opts if isinstance(raw_opts, list) else []
            arg["options"] = existing + dynamic
        except Exception as exc:
            err = str(exc)
            _log.warning("option_script_failed", node=name, arg=arg.get("arg"), error=err)
            arg["_option_script_error"] = err

    return spec


@router.post("/hypervisors/{name}/execute")
async def execute_hypervisor_script(
    name: str,
    body: ExecuteRequest,
    user: UserInfo = Depends(require_admin),
) -> StreamingResponse:
    """Exécute les commandes du script sur l'hyperviseur via SSH et streame la sortie."""
    cfg = load_global()
    node = next((n for n in cfg.hypervisors if n.name == name), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Hypervisor {name!r} not found")

    spec = await _fetch_spec(node, cfg)
    commands_raw: list[str] = spec.get("commands", [])  # type: ignore[assignment]

    settings = get_settings()
    body.args["PORTAL_URL"] = cfg.server.external_url
    body.args["PORTAL_TOKEN"] = settings.portal_api_key
    body.args["PORTAL_PVE_NODE"] = node.name

    commands = [_substitute(cmd, body.args) for cmd in commands_raw]

    redacted_args = {**body.args, "PORTAL_TOKEN": "***"}
    display_commands = [_substitute(cmd, redacted_args) for cmd in commands_raw]

    _log.info("hypervisor_script_execute", node=name, by=user.login, commands=len(commands))

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


@router.post("/hypervisors/{name}/validate-arg")
async def validate_hypervisor_arg(
    name: str,
    body: ValidateArgRequest,
    user: UserInfo = Depends(require_admin),
) -> dict[str, object]:
    """Exécute le test_script d'un argument et retourne valid + message."""
    cfg = load_global()
    node = next((n for n in cfg.hypervisors if n.name == name), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Hypervisor {name!r} not found")

    spec = await _fetch_spec(node, cfg)
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

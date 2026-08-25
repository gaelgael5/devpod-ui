from __future__ import annotations

import asyncio
import os
import re
import shlex
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..auth.rbac import UserInfo, require_admin
from ..config.models import _PROXMOX_NAME_RE, GlobalConfig, HostConfig, Hypervisor, HypervisorType
from ..config.store import load_global, save_global
from ..settings import get_settings
from ._ssrf import pinned_get, resolve_pinned

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
        "-i",
        node.ssh_key_path,
        "-p",
        str(node.ssh_port),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "ServerAliveInterval=10",
        "-o",
        "ServerAliveCountMax=30",
        "-o",
        "TCPKeepAlive=yes",
    ]


async def _ssh_run(node: Hypervisor, command: str, timeout: float = 30.0) -> str:
    """Exécute une commande SSH et retourne stdout.

    Lève RuntimeError si le code de retour est non-zéro.
    """
    proc = await asyncio.create_subprocess_exec(
        "ssh",
        *_ssh_opts(node),
        f"{node.ssh_user}@{node.address}",
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
        "ssh",
        *_ssh_opts(node),
        f"{node.ssh_user}@{node.address}",
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


def find_identifier_arg(spec: dict[str, object]) -> str | None:
    """Nom de l'arg marqué ``identifier: true`` dans la spec (ou None).

    L'arg identifiant (ex. le vmid) est unique par machine : non pré-remplissable,
    à saisir/générer à chaque création. Un seul arg par spec porte ce flag ;
    les groupes ``sub`` sont parcourus via ``_flatten_args``.
    """
    raw_args = spec.get("args", [])
    args = raw_args if isinstance(raw_args, list) else []
    for arg in _flatten_args(args):
        if arg.get("identifier") is True:
            name = arg.get("arg")
            if isinstance(name, str):
                return name
    return None


def spec_arg_defaults(spec: dict[str, object]) -> dict[str, str]:
    """Valeurs `default` déclarées dans la spec (args + groupes `sub`), en str.

    Sert de base aux args de création : un arg déclaré avec un `default` s'applique
    même si les `test_host_params` stockés — saisis AVANT l'ajout de cet arg à la
    spec — ne le portent pas. Sans ça, un nouvel arg (ex. SWAP_PERCENT) partait en
    placeholder littéral au script. L'arg identifiant est exclu (jamais de défaut).
    """
    raw_args = spec.get("args", [])
    args = raw_args if isinstance(raw_args, list) else []
    out: dict[str, str] = {}
    for arg in _flatten_args(args):
        if arg.get("identifier") is True or "default" not in arg:
            continue
        name = arg.get("arg")
        if isinstance(name, str):
            out[name] = str(arg["default"])
    return out


async def _ssh_stream(node: Hypervisor, commands: list[str]) -> AsyncIterator[bytes]:
    """Exécute des commandes shell sur le nœud SSH et streame stdout+stderr."""
    script = "set -euo pipefail\n" + "\n".join(commands) + "\n"
    proc = await asyncio.create_subprocess_exec(
        "ssh",
        *_ssh_opts(node),
        f"{node.ssh_user}@{node.address}",
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
        # Le flux part au navigateur ; on trace AUSSI côté serveur pour que l'échec
        # d'un script d'hyperviseur soit diagnosticable a posteriori (Loki).
        _log.warning("ssh_stream_nonzero_exit", node=node.name, returncode=proc.returncode)
        yield f"\n[ERROR] Script terminé avec le code {proc.returncode}\n".encode()


_SUBST_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _substitute(template: str, args: dict[str, str]) -> str:
    """Remplace les placeholders {KEY} par shlex.quote(value), en une seule passe.

    re.sub scanne le template original une seule fois : le texte produit par une
    substitution n'est jamais réexaminé pour un futur remplacement — contrairement
    à un enchaînement de str.replace, où la valeur d'un arg contenant littéralement
    "{PORTAL_TOKEN}" se ferait re-substituer par le vrai token à l'itération
    suivante (bug 024, exfiltration). shlex.quote protège aussi l'injection shell
    dans les commandes exécutées via `bash -s`.
    """

    def _repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in args:
            return m.group(0)
        return shlex.quote(args[key])

    return _SUBST_PLACEHOLDER_RE.sub(_repl, template)


def missing_placeholders(templates: list[str], args: dict[str, str]) -> set[str]:
    """Placeholders `{KEY}` référencés dans les templates mais absents des args.

    Permet d'échouer TÔT et clairement quand la config d'un type d'hyperviseur ne
    fournit pas un paramètre attendu par le script (sinon `{KEY}` part littéral au
    script, qui le rejette avec un message cryptique — cf. SWAP_PERCENT).
    """
    referenced = {m.group(1) for t in templates for m in _SUBST_PLACEHOLDER_RE.finditer(t)}
    return referenced - set(args)


async def _run_destroy_script(cfg: GlobalConfig, host_cfg: HostConfig) -> None:
    """Exécute le destroy_script de l'hyperviseur pour la VM associée au host.

    Sans effet si proxmox_node/vmid manquants ou si destroy_script non configuré.
    Les erreurs sont loguées sans lever d'exception — la suppression du host continue.
    """
    if not host_cfg.proxmox_node or not host_cfg.vmid:
        return

    node = next((n for n in cfg.hypervisors if n.name == host_cfg.proxmox_node), None)
    if node is None:
        _log.warning(
            "host_destroy_hypervisor_not_found",
            host=host_cfg.name,
            proxmox_node=host_cfg.proxmox_node,
        )
        return

    if not node.hypervisor_type:
        return

    hyp_type = next((t for t in cfg.hypervisor_types if t.name == node.hypervisor_type), None)
    if hyp_type is None or not hyp_type.destroy_script:
        return

    try:
        pinned_ip = await asyncio.to_thread(resolve_pinned, hyp_type.destroy_script)
    except HTTPException as exc:
        _log.error("host_destroy_script_fetch_failed", host=host_cfg.name, error=str(exc.detail))
        return

    async with httpx.AsyncClient() as client:
        try:
            # Connexion épinglée sur l'IP validée (anti-rebinding, bug 022)
            resp = await pinned_get(
                client, hyp_type.destroy_script, timeout=15.0, pinned_ip=pinned_ip
            )
            resp.raise_for_status()
            spec = dict(resp.json())
        except httpx.HTTPError as exc:
            _log.error("host_destroy_script_fetch_failed", host=host_cfg.name, error=str(exc))
            return

    from ..settings import get_settings

    settings = get_settings()
    commands_raw: list[str] = list(spec.get("commands", []))
    args = {
        "VMID": host_cfg.vmid,
        "PORTAL_URL": cfg.server.external_url,
        "PORTAL_TOKEN": settings.portal_api_key,
        "PORTAL_PVE_NODE": node.name,
    }
    commands = [_substitute(cmd, args) for cmd in commands_raw]

    _log.info("host_destroy_script_starting", host=host_cfg.name, vmid=host_cfg.vmid)
    chunks: list[bytes] = []
    async for chunk in _ssh_stream(node, commands):
        chunks.append(chunk)
    output = b"".join(chunks).decode("utf-8", errors="replace")
    _log.info(
        "host_destroy_script_done",
        host=host_cfg.name,
        vmid=host_cfg.vmid,
        output=output[:500],
    )


# ─── CRUD types d'hyperviseurs ────────────────────────────────────────────────


class HypervisorTypeRequest(BaseModel):
    label: str = ""
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
        label=body.label,
        name=body.name,
        add_script=body.add_script,
        destroy_script=body.destroy_script,
    )
    cfg.hypervisor_types.append(ht)
    await save_global(cfg)
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
        label=body.label,
        name=name,
        add_script=body.add_script,
        destroy_script=body.destroy_script,
        test_host_params=ht.test_host_params,  # préservé (réglé via /test-params)
    )
    cfg.hypervisor_types = [updated if t.name == name else t for t in cfg.hypervisor_types]
    await save_global(cfg)
    _log.info("hypervisor_type_updated", name=name, by=user.login)
    return updated.model_dump(mode="json")


@router.get("/hypervisor-types/{name}/script")
async def get_hypervisor_type_script(
    name: str,
    user: UserInfo = Depends(require_admin),
) -> dict[str, object]:
    """Spec JSON d'un type, options dynamiques résolues sur les machines du type.

    Un `option_script` décrit les valeurs disponibles *sur l'hyperviseur* (les
    templates Proxmox clonables, par exemple) : sans l'exécuter, la liste se
    réduit au seul `auto` déclaré en dur dans la spec. On l'exécute donc sur
    toutes les machines qui portent ce type ; sans machine enregistrée, la spec
    part telle quelle.
    """
    cfg = load_global()
    ht = next((t for t in cfg.hypervisor_types if t.name == name), None)
    if ht is None:
        raise HTTPException(status_code=404, detail=f"Hypervisor type {name!r} not found")
    spec = await _fetch_spec_for_type(ht)
    await resolve_option_scripts(spec, [n for n in cfg.hypervisors if n.hypervisor_type == name])
    return spec


class TestHostParamsRequest(BaseModel):
    params: dict[str, str]


@router.put("/hypervisor-types/{name}/test-params", status_code=200)
async def set_test_host_params(
    name: str,
    body: TestHostParamsRequest,
    user: UserInfo = Depends(require_admin),
) -> dict[str, object]:
    """Enregistre les valeurs par défaut du host de test pour ce type.

    L'arg identifiant (vmid) n'est jamais pré-rempli ; le front l'exclut déjà de la
    saisie.
    """
    cfg = load_global()
    ht = next((t for t in cfg.hypervisor_types if t.name == name), None)
    if ht is None:
        raise HTTPException(status_code=404, detail=f"Hypervisor type {name!r} not found")
    updated = HypervisorType(
        label=ht.label,
        name=ht.name,
        add_script=ht.add_script,
        destroy_script=ht.destroy_script,
        test_host_params=body.params,
    )
    cfg.hypervisor_types = [updated if t.name == name else t for t in cfg.hypervisor_types]
    await save_global(cfg)
    _log.info("test_host_params_saved", type=name, by=user.login, keys=sorted(body.params))
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
    await save_global(cfg)
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
    )
    cfg.hypervisors.append(node)
    await save_global(cfg)
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
    )
    cfg.hypervisors = [updated if n.name == name else n for n in cfg.hypervisors]
    await save_global(cfg)
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
    await save_global(cfg)
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
            name="test",
            address=address,
            ssh_user=ssh_user,
            ssh_port=ssh_port,
            ssh_key_path=tmp_path,
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


async def _fetch_spec_for_type(hyp_type: HypervisorType) -> dict[str, object]:
    """Télécharge la spec JSON d'un type d'hyperviseur (sans résolution SSH)."""
    if not hyp_type.add_script:
        raise HTTPException(
            status_code=404,
            detail=f"Hypervisor type {hyp_type.name!r} has no add_script configured",
        )
    pinned_ip = await asyncio.to_thread(resolve_pinned, hyp_type.add_script)
    async with httpx.AsyncClient() as client:
        try:
            # Connexion épinglée sur l'IP validée (anti-rebinding, bug 022)
            resp = await pinned_get(client, hyp_type.add_script, timeout=15.0, pinned_ip=pinned_ip)
            resp.raise_for_status()
            return dict(resp.json())
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch script spec: {exc}",
            ) from exc


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
    return await _fetch_spec_for_type(hyp_type)


def parse_option_lines(output: str) -> list[dict[str, str]]:
    """Sortie d'un `option_script` → options. Une ligne `valeur|libellé`, ou la
    valeur seule quand elle fait aussi office de libellé."""
    options: list[dict[str, str]] = []
    for ligne in output.strip().splitlines():
        ligne = ligne.strip()
        if not ligne:
            continue
        if "|" in ligne:
            val, _, lbl = ligne.partition("|")
            options.append({"value": val.strip(), "label": lbl.strip()})
        else:
            options.append({"value": ligne, "label": ligne})
    return options


async def resolve_option_scripts(
    spec: dict[str, object],
    nodes: list[Hypervisor],
) -> None:
    """Résout les `option_script` de la spec **en place**, sur les machines données.

    Plusieurs machines d'un même type peuvent proposer des valeurs différentes
    (des templates Proxmox, par exemple) : on interroge chacune et on fusionne,
    en dédupliquant sur la valeur — deux nœuds d'un même cluster voient le même
    `/etc/pve` et renverraient deux fois la même liste.

    Une machine injoignable ne fait pas échouer la spec : les autres répondent.
    L'erreur n'est remontée à l'UI que si AUCUNE valeur n'a pu être obtenue,
    sinon un nœud éteint masquerait une liste par ailleurs correcte.
    """
    for arg in _flatten_args(spec.get("args", [])):  # type: ignore[arg-type]
        option_script = arg.get("option_script")
        if not option_script:
            continue
        dynamic: list[dict[str, str]] = []
        vues: set[str] = set()
        erreurs: list[str] = []
        for node in nodes:
            try:
                output = await _ssh_run(node, str(option_script))
            except Exception as exc:
                erreurs.append(f"{node.name}: {exc}")
                _log.warning(
                    "option_script_failed", node=node.name, arg=arg.get("arg"), error=str(exc)
                )
                continue
            for option in parse_option_lines(output):
                if option["value"] in vues:
                    continue
                vues.add(option["value"])
                dynamic.append(option)
        raw_opts = arg.get("options") or []
        existing: list[dict[str, str]] = raw_opts if isinstance(raw_opts, list) else []
        arg["options"] = existing + dynamic
        if erreurs and not dynamic:
            arg["_option_script_error"] = "; ".join(erreurs)


async def resolve_node_script(node: Hypervisor, cfg: GlobalConfig) -> dict[str, object]:
    """Spec du node avec les options dynamiques (`option_script`) résolues via SSH."""
    spec = await _fetch_spec(node, cfg)
    await resolve_option_scripts(spec, [node])
    return spec


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
    return await resolve_node_script(node, cfg)


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


class DestroyRequest(BaseModel):
    vmid: str


@router.post("/hypervisors/{name}/execute-destroy")
async def execute_hypervisor_destroy_script(
    name: str,
    body: DestroyRequest,
    user: UserInfo = Depends(require_admin),
) -> StreamingResponse:
    """Exécute le destroy_script de l'hyperviseur pour supprimer la VM identifiée par vmid."""
    cfg = load_global()
    node = next((n for n in cfg.hypervisors if n.name == name), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Hypervisor {name!r} not found")
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
    if not hyp_type.destroy_script:
        raise HTTPException(
            status_code=404,
            detail=f"Hypervisor type {node.hypervisor_type!r} has no destroy_script configured",
        )

    pinned_ip = await asyncio.to_thread(resolve_pinned, hyp_type.destroy_script)
    async with httpx.AsyncClient() as client:
        try:
            # Connexion épinglée sur l'IP validée (anti-rebinding, bug 022)
            resp = await pinned_get(
                client, hyp_type.destroy_script, timeout=15.0, pinned_ip=pinned_ip
            )
            resp.raise_for_status()
            spec = dict(resp.json())
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch destroy script spec: {exc}",
            ) from exc

    commands_raw: list[str] = list(spec.get("commands", []))
    settings = get_settings()
    args = {
        "VMID": body.vmid,
        "PORTAL_URL": cfg.server.external_url,
        "PORTAL_TOKEN": settings.portal_api_key,
        "PORTAL_PVE_NODE": node.name,
    }
    commands = [_substitute(cmd, args) for cmd in commands_raw]
    redacted_args = {**args, "PORTAL_TOKEN": "***"}
    display_commands = [_substitute(cmd, redacted_args) for cmd in commands_raw]

    _log.info("hypervisor_destroy_script_execute", node=name, vmid=body.vmid, by=user.login)

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

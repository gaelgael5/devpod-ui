from __future__ import annotations

import asyncio
import base64
import ipaddress
import os
import socket as _socket
import tempfile
from urllib.parse import urlparse

import structlog
from fastapi import HTTPException

from ..config.store import load_user

_log = structlog.get_logger(__name__)


def _check_git_ssrf(url: str) -> None:
    """Rejette les URLs git pointant vers un réseau interne (protection SSRF)."""
    if url.startswith("git@"):
        host = url[4:].split(":")[0].split("/")[0].rstrip(".").lower()
    else:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https", "ssh"):
            raise HTTPException(
                status_code=422, detail=f"Schéma git non supporté : {parsed.scheme!r}"
            )
        host = (parsed.hostname or "").rstrip(".").lower()
    if not host:
        raise HTTPException(status_code=422, detail="URL sans hostname")
    try:
        infos = _socket.getaddrinfo(host, None)
    except _socket.gaierror as exc:
        raise HTTPException(
            status_code=422, detail=f"Hostname introuvable : '{host}'"
        ) from exc
    for _fam, _type, _proto, _canon, sa in infos:
        try:
            ip = ipaddress.ip_address(sa[0])
        except ValueError:
            continue
        if (
            ip.is_loopback
            or ip.is_link_local
            or ip.is_private
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise HTTPException(
                status_code=422,
                detail=f"URL résolue vers une adresse interne bloquée : {ip}",
            )


async def run_git_ls_remote(
    url: str,
    credential_name: str,
    login: str,
) -> tuple[int, bytes, bytes]:
    """Exécute ``git ls-remote --symref --heads`` sur l'URL donnée.

    Normalise l'URL, vérifie SSRF, injecte les credentials de l'utilisateur.
    Retourne ``(returncode, stdout, stderr)``.
    Lève ``HTTPException`` sur SSRF, hostname invalide, timeout ou erreur subprocess.
    """
    git_url = url.strip()
    if not git_url:
        raise HTTPException(status_code=422, detail="url is required")
    if not git_url.startswith(("http://", "https://", "git@", "ssh://")):
        git_url = f"https://{git_url}"

    _check_git_ssrf(git_url)

    # `git -c` est portable depuis git 1.7. On désactive le credential store
    # système pour éviter qu'il injecte un credential qui entrerait en conflit
    # avec celui qu'on fournit via include.path.
    git_cmd: list[str] = [
        "git",
        "-c", "http.followRedirects=false",
        "-c", "credential.helper=",
    ]
    env: dict[str, str] = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"}
    tmp_config: str | None = None

    if credential_name:
        cfg = load_user(login)
        cred = next((c for c in cfg.git_credentials if c.name == credential_name), None)
        if cred:
            if cred.kind == "ssh" and cred.key_path:
                env["GIT_SSH_COMMAND"] = (
                    f"ssh -i {cred.key_path}"
                    " -o StrictHostKeyChecking=no -o BatchMode=yes"
                )
            elif cred.kind == "token" and cred.token:
                username = cred.username or "oauth2"
                b64 = base64.b64encode(f"{username}:{cred.token}".encode()).decode()
                # Le token ne transite PAS via argv (visible dans /proc/PID/cmdline).
                # On l'écrit dans un fichier temporaire 0o600 inclus via include.path.
                fd, tmp_config = tempfile.mkstemp(suffix=".gitconfig")
                try:
                    with os.fdopen(fd, "w") as fh:
                        fh.write(f"[http]\n\textraHeader = Authorization: Basic {b64}\n")
                    os.chmod(tmp_config, 0o600)
                except Exception:
                    os.unlink(tmp_config)
                    tmp_config = None
                    raise
                git_cmd.extend(["-c", f"include.path={tmp_config}"])

    git_cmd.extend(["ls-remote", "--symref", "--heads", git_url])

    try:
        proc = await asyncio.create_subprocess_exec(
            *git_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="git ls-remote timed out") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        if tmp_config:
            try:
                os.unlink(tmp_config)
            except OSError:
                pass

    return proc.returncode if proc.returncode is not None else -1, stdout, stderr

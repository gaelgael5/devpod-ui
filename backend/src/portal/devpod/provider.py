from __future__ import annotations

import asyncio

import structlog

_log = structlog.get_logger(__name__)

_PROVIDER_FOR_HOST: dict[str, str] = {
    "docker-tls": "docker",
    "ssh": "ssh",
}


async def ensure_provider(
    login: str,
    host_type: str,
    env: dict[str, str],
    devpod_bin: list[str] | None = None,
) -> None:
    """
    S'assure que le provider requis existe dans ce DEVPOD_HOME.
    Idempotent : ne refait rien si le provider est déjà présent.

    Note : devpod provider list (v0.6.15) ne supporte pas --output json.
    On parse la sortie texte tabulaire.
    """
    provider_name = _PROVIDER_FOR_HOST.get(host_type, "docker")
    cmd = devpod_bin if devpod_bin is not None else ["devpod"]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        "provider",
        "list",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode(errors="replace")

    # Vérifier si le provider apparaît dans la sortie tabulaire
    if provider_name in output:
        _log.debug("provider_already_present", login=login, provider=provider_name)
        return

    _log.info("provider_add", login=login, provider=provider_name)
    add_proc = await asyncio.create_subprocess_exec(
        *cmd,
        "provider",
        "add",
        provider_name,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await add_proc.wait()
    if add_proc.returncode != 0:
        _log.warning(
            "provider_add_failed",
            login=login,
            provider=provider_name,
            returncode=add_proc.returncode,
        )

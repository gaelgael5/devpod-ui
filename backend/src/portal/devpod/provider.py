from __future__ import annotations

import asyncio

import structlog

_log = structlog.get_logger(__name__)

_PROVIDER_FOR_HOST: dict[str, str] = {
    "docker-tls": "docker",
    "ssh": "ssh",
}


class ProviderError(RuntimeError):
    """Échec lors de l'initialisation du provider devpod."""


def _parse_providers(output: str) -> set[str]:
    """Parse la sortie tabulaire de `devpod provider list` et retourne les noms exacts."""
    providers: set[str] = set()
    for line in output.splitlines():
        stripped = line.strip()
        # Ignorer les lignes vides, l'en-tête (contient "NAME"), les séparateurs
        if not stripped or "NAME" in stripped or stripped.startswith("-"):
            continue
        if "|" not in stripped:
            continue
        parts = stripped.split("|")
        name = parts[0].strip()
        if name:
            providers.add(name)
    return providers


async def ensure_provider(
    login: str,
    host_type: str,
    env: dict[str, str],
    devpod_bin: list[str] | None = None,
) -> None:
    """
    S'assure que le provider requis existe dans ce DEVPOD_HOME.
    Idempotent : ne refait rien si le provider est déjà présent.
    Lève ProviderError si l'ajout échoue.
    Lève ValueError si host_type est inconnu.

    Note : devpod provider list (v0.6.15) ne supporte pas --output json.
    On parse la sortie tabulaire ligne par ligne, colonne NAME exacte.
    """
    if host_type not in _PROVIDER_FOR_HOST:
        raise ValueError(
            f"Unknown host_type: {host_type!r}. Expected one of {list(_PROVIDER_FOR_HOST)}"
        )
    provider_name = _PROVIDER_FOR_HOST[host_type]
    cmd = devpod_bin if devpod_bin is not None else ["devpod"]

    # Lister les providers existants
    list_proc = await asyncio.create_subprocess_exec(
        *cmd,
        "provider",
        "list",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr_bytes = await list_proc.communicate()
    output = stdout.decode(errors="replace")

    if list_proc.returncode != 0:
        _log.warning(
            "provider_list_failed",
            login=login,
            returncode=list_proc.returncode,
            stderr=stderr_bytes.decode(errors="replace"),
        )

    existing = _parse_providers(output)
    if provider_name in existing:
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
    _, add_stderr = await add_proc.communicate()
    if add_proc.returncode != 0:
        err = add_stderr.decode(errors="replace").strip()
        raise ProviderError(
            f"devpod provider add {provider_name!r} failed (exit {add_proc.returncode}): {err}"
        )
    _log.info("provider_added", login=login, provider=provider_name)

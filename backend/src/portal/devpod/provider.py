from __future__ import annotations

import asyncio
import re

import structlog

_log = structlog.get_logger(__name__)

_SAFE_RE = re.compile(r"[^a-z0-9-]")


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


def _ssh_provider_name(host_name: str) -> str:
    """Construit le nom de provider DevPod pour un host SSH donné."""
    safe = _SAFE_RE.sub("-", host_name.lower()).strip("-") or "default"
    return f"ssh-{safe}"


async def ensure_provider(
    login: str,
    host_type: str,
    env: dict[str, str],
    host_name: str = "",
    ssh_host: str = "",
    ssh_user: str = "root",
    devpod_bin: list[str] | None = None,
) -> str:
    """
    S'assure que le provider requis existe dans ce DEVPOD_HOME.
    Idempotent : ne refait rien si le provider est déjà présent.
    Lève ProviderError si l'ajout échoue.
    Lève ValueError si host_type est inconnu.

    Pour SSH : crée un provider nommé "ssh-<host_name>" avec l'option HOST=user@ip,
    ce qui permet d'avoir plusieurs hosts SSH distincts par user.

    Retourne le nom du provider à passer à --provider dans devpod up.

    Note : devpod provider list (v0.6.15) ne supporte pas --output json.
    On parse la sortie tabulaire ligne par ligne, colonne NAME exacte.
    """
    if host_type not in ("docker-tls", "ssh"):
        raise ValueError(
            f"Unknown host_type: {host_type!r}. Expected one of ['docker-tls', 'ssh']"
        )

    provider_name = "docker" if host_type == "docker-tls" else _ssh_provider_name(host_name)
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
        return provider_name

    _log.info("provider_add", login=login, provider=provider_name)

    if host_type == "docker-tls":
        add_args = [*cmd, "provider", "add", "docker"]
    else:
        if not ssh_host:
            raise ProviderError(
                f"ssh_host requis pour ajouter le provider SSH {provider_name!r}"
            )
        # --name crée une instance nommée du provider SSH (un par host).
        # USER n'est pas un flag valide du provider SSH DevPod — l'utilisateur
        # doit être inclus dans HOST au format user@hostname.
        host_value = f"{ssh_user}@{ssh_host}" if ssh_user else ssh_host
        add_args = [
            *cmd, "provider", "add", "ssh",
            "--name", provider_name,
            "--option", f"HOST={host_value}",
        ]

    add_proc = await asyncio.create_subprocess_exec(
        *add_args,
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
    return provider_name

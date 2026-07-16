"""Bundle mTLS par host docker-tls, matérialisé depuis le gestionnaire de certificats.

Un host docker-tls peut référencer un cert du gestionnaire (`docker_cert_slug`).
Le résolveur d'env devpod n'a ni session ni master key : le bundle est donc
matérialisé à l'ASSOCIATION (session admin disponible) sous
`/data/certs/hosts/<name>/{ca.pem,cert.pem,key.pem}` — même posture sur disque
que le répertoire partagé `client_cert_path`, mais isolé par host.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import tempfile
from pathlib import Path

import anyio
import structlog

from ..config.store import _data_root

_log = structlog.get_logger(__name__)

# Nom de host : même famille que les slugs (pas de dot → aucun segment ".." possible).
_HOST_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$")

_BUNDLE_FILES = ("ca.pem", "cert.pem", "key.pem")


def host_bundle_dir(host_name: str) -> Path:
    """Répertoire du bundle mTLS d'un host — nom validé strictement (jamais de concat brute)."""
    if not _HOST_NAME_RE.fullmatch(host_name):
        raise ValueError(f"Invalid host name: {host_name!r}")
    return _data_root() / "certs" / "hosts" / host_name


def bundle_exists(host_name: str) -> bool:
    """True si les trois fichiers du bundle sont présents."""
    bundle = host_bundle_dir(host_name)
    return all((bundle / name).is_file() for name in _BUNDLE_FILES)


def _write_bundle_sync(bundle: Path, contents: dict[str, str]) -> None:
    bundle.mkdir(parents=True, exist_ok=True)
    os.chmod(bundle, 0o700)
    for name, content in contents.items():
        # Écriture atomique : tempfile dans le même dossier + os.replace.
        fd, tmp_path = tempfile.mkstemp(dir=bundle, prefix=f".{name}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, bundle / name)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise


async def materialize_host_bundle(
    host_name: str, *, ca_pem: str, cert_pem: str, key_pem: str
) -> Path:
    """Écrit (ou remplace) le bundle mTLS du host. Dossier 700, fichiers 600."""
    bundle = host_bundle_dir(host_name)
    contents = {"ca.pem": ca_pem, "cert.pem": cert_pem, "key.pem": key_pem}
    await anyio.to_thread.run_sync(lambda: _write_bundle_sync(bundle, contents))
    _log.info("docker_bundle_materialized", host=host_name, path=str(bundle))
    return bundle


def _remove_bundle_sync(bundle: Path) -> bool:
    if not bundle.exists():
        return False
    shutil.rmtree(bundle)
    return True


async def remove_host_bundle(host_name: str) -> None:
    """Supprime le bundle du host. Idempotent (absent = no-op)."""
    bundle = host_bundle_dir(host_name)
    removed = await anyio.to_thread.run_sync(lambda: _remove_bundle_sync(bundle))
    if removed:
        _log.info("docker_bundle_removed", host=host_name, path=str(bundle))

"""Enregistrement des drivers embarqués.

Appelé au démarrage du portail (lifespan) ; les tests l'appellent directement.
Les drivers tiers restent possibles via `register_driver` avec un
`ExecutableDriver` pointant sur leur exécutable.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from .driver import register_driver
from .existing import ExistingMachineDriver

_log = structlog.get_logger(__name__)

# Dans l'image, les modules sont copiés en /app/tofu-modules ; en dev, ils
# vivent dans deploy/tofu-modules à la racine du dépôt.
_MODULES_CANDIDATS = (
    Path("/app/tofu-modules"),
    Path(__file__).parents[4] / "deploy" / "tofu-modules",
)


def _modules_dir(configure: str) -> Path | None:
    if configure:
        chemin = Path(configure)
        return chemin if chemin.is_dir() else None
    for candidat in _MODULES_CANDIDATS:
        if candidat.is_dir():
            return candidat
    return None


def _conn_str_depuis(database_url: str) -> str:
    """`postgresql+asyncpg://…` (SQLAlchemy) → libpq, dialecte de tofu."""
    return (
        database_url.replace("postgresql+asyncpg://", "postgres://")
        + ("&" if "?" in database_url else "?")
        + "sslmode=disable"
    )


def register_builtin_drivers() -> None:
    register_driver("existing", ExistingMachineDriver())

    from ..settings import get_settings

    settings = get_settings()
    if not (
        settings.tofu_state_passphrase
        and settings.proxmox_ve_endpoint
        and settings.proxmox_ve_api_token
    ):
        # Chemin script inchangé ; le driver IaC est un opt-in de configuration.
        _log.info("provisioning_driver_proxmox_non_configure")
        return
    modules = _modules_dir(settings.tofu_modules_dir)
    if modules is None or not (modules / "proxmox-vm").is_dir():
        _log.warning("provisioning_modules_introuvables", configure=settings.tofu_modules_dir)
        return

    from .proxmox import ProxmoxTofuDriver

    register_driver(
        "proxmox",
        ProxmoxTofuDriver(
            module_dir=modules / "proxmox-vm",
            pg_conn_str=settings.tofu_pg_conn_str or _conn_str_depuis(settings.database_url),
            state_passphrase=settings.tofu_state_passphrase,
            endpoint=settings.proxmox_ve_endpoint,
            api_token=settings.proxmox_ve_api_token,
            tofu_binary=settings.tofu_binary,
            provider_mirror=(
                Path(settings.tofu_provider_mirror) if settings.tofu_provider_mirror else None
            ),
        ),
    )
    _log.info("provisioning_driver_proxmox_enregistre", modules=str(modules))

"""Cycle de vie du sshd bastion : démarré/arrêté À CHAUD depuis la config DB.

Plus d'`.env` ni d'entrypoint : l'app démarre le sshd au boot si `GlobalConfig.bastion.
enabled`, et le PUT admin le (re)démarre/arrête quand on toggle. Idempotent, best-effort.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import structlog

from ..config.store import _data_root

_log = structlog.get_logger(__name__)

_SSHD = "/usr/sbin/sshd"
_CONFIG = "/etc/ssh/bastion_sshd_config"

_proc: subprocess.Popen[bytes] | None = None


def _bastion_dir() -> Path:
    return _data_root() / "bastion"


def setup_dir() -> None:
    """Prépare /data/bastion : dossier 700, authorized_keys 600, host key persistée."""
    d = _bastion_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    ak = d / "authorized_keys"
    if not ak.exists():
        ak.touch()
    os.chmod(ak, 0o600)
    host_key = d / "ssh_host_ed25519_key"
    if not host_key.exists():
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-f", str(host_key), "-N", "", "-q"], check=True
        )


def is_running() -> bool:
    return _proc is not None and _proc.poll() is None


def start() -> None:
    global _proc
    if is_running():
        return
    if not os.path.exists(_SSHD):
        _log.warning("bastion_sshd_absent")  # image sans openssh-server
        return
    setup_dir()
    os.makedirs("/run/sshd", exist_ok=True)  # privilege separation dir du sshd
    # -D foreground (process supervisé, terminable) ; -e logs vers stderr → Loki.
    _proc = subprocess.Popen([_SSHD, "-D", "-e", "-f", _CONFIG])
    _log.info("bastion_sshd_started", pid=_proc.pid)


def stop() -> None:
    global _proc
    if _proc is not None and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except Exception:
            _proc.kill()
        _log.info("bastion_sshd_stopped")
    _proc = None


def apply(enabled: bool) -> None:
    """Aligne l'état du sshd sur la config (toggle à chaud). Best-effort."""
    try:
        if enabled:
            start()
        else:
            stop()
    except Exception:
        _log.warning("bastion_sshd_apply_failed", exc_info=True)

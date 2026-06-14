from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from .config.store import safe_user_path


def ensure_workspace_ssh_key(login: str, workspace_name: str) -> str:
    """Génère la paire Ed25519 pour un workspace si absente. Retourne la clé publique."""
    key_dir = safe_user_path(login, "keys", "workspaces", workspace_name)
    pub_path = key_dir / "id_ed25519.pub"
    priv_path = key_dir / "id_ed25519"

    if pub_path.exists():
        return pub_path.read_text(encoding="utf-8").strip()

    key_dir.mkdir(parents=True, exist_ok=True)

    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
    public_bytes = private_key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)
    public_str = public_bytes.decode("ascii") + f" devpod:{login}/{workspace_name}"

    _atomic_write(priv_path, private_pem, mode=0o600)
    _atomic_write(pub_path, public_str.encode("ascii"), mode=0o644)

    return public_str


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        with contextlib.suppress(OSError):
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise

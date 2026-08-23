"""Gestion atomique du `authorized_keys` du bastion (une ligne par workspace).

Chaque ligne force la commande de relais et interdit tout forwarding/shell :
`command="…/ws-bastion <login> <ws_id>",<restrictions> <pubkey>`. Le couple
(login, ws_id) est **strictement validé** (regex) avant d'entrer dans la commande —
il finit dans un argv exécuté par le sshd, la moindre injection serait critique.
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from pathlib import Path

import structlog

from ..config.store import _data_root

_log = structlog.get_logger(__name__)

# Chemin du wrapper de relais installé dans l'image portail (cf. deploy/Dockerfile).
WRAPPER = "/usr/local/bin/ws-bastion"

# Durcissement : ni forwarding, ni rc utilisateur (on garde le pty : terminal interactif).
_RESTRICTIONS = "no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-user-rc"

# login / ws_id : minuscules, chiffres, tirets — jamais rien d'autre (anti-injection
# dans la commande forcée). ws_id = `{login}-{nom}`.
_LOGIN_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_WS_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")

_lock = asyncio.Lock()


def _akeys_path() -> Path:
    return _data_root() / "bastion" / "authorized_keys"


def _validate(login: str, ws_id: str) -> None:
    if not _LOGIN_RE.fullmatch(login):
        raise ValueError(f"login invalide : {login!r}")
    if not _WS_ID_RE.fullmatch(ws_id):
        raise ValueError(f"ws_id invalide : {ws_id!r}")


def _line_for(login: str, ws_id: str, pubkey: str) -> str:
    key = pubkey.strip()
    if "\n" in key or not key.startswith("ssh-"):
        raise ValueError("clé publique invalide")
    return f'command="{WRAPPER} {login} {ws_id}",{_RESTRICTIONS} {key}'


def _marker(login: str, ws_id: str) -> str:
    """Sous-chaîne identifiant la ligne d'un workspace (pour set/remove idempotents)."""
    return f'command="{WRAPPER} {login} {ws_id}"'


def _write_atomic(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    content = ("\n".join(lines) + "\n") if lines else ""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent))
    try:
        os.write(fd, content.encode())
        os.close(fd)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [ln for ln in path.read_text().splitlines() if ln.strip()]


async def set_entry(login: str, ws_id: str, pubkey: str) -> None:
    """Pose (ou remplace) la ligne autorisant `pubkey` à relayer vers `ws_id`."""
    _validate(login, ws_id)
    line = _line_for(login, ws_id, pubkey)
    marker = _marker(login, ws_id)
    async with _lock:
        path = _akeys_path()
        lines = [ln for ln in _read_lines(path) if marker not in ln]
        lines.append(line)
        _write_atomic(path, lines)
    _log.info("bastion_authorized_key_set", login=login, ws_id=ws_id)


async def remove_entry(login: str, ws_id: str) -> bool:
    """Retire la ligne d'un workspace. True si une ligne a été retirée."""
    _validate(login, ws_id)
    marker = _marker(login, ws_id)
    async with _lock:
        path = _akeys_path()
        before = _read_lines(path)
        after = [ln for ln in before if marker not in ln]
        if len(after) == len(before):
            return False
        _write_atomic(path, after)
    _log.info("bastion_authorized_key_removed", login=login, ws_id=ws_id)
    return True

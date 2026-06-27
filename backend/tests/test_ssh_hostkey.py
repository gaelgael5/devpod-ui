# backend/tests/test_ssh_hostkey.py
"""Détection d'un changement de clé d'hôte SSH (nœud recréé)."""
from __future__ import annotations

from portal.devpod.ssh_exec import host_key_changed


def test_detects_changed_host_key() -> None:
    stderr = (
        b"@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@\n"
        b"@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @\n"
        b"Host key for 192.168.10.161 has changed and you have requested strict checking.\n"
        b"Host key verification failed.\n"
    )
    assert host_key_changed(stderr) is True


def test_unknown_host_is_not_changed() -> None:
    # Hôte jamais vu (à accepter via accept-new) ≠ clé changée → pas de purge.
    stderr = (
        b"No ED25519 host key is known for 192.168.10.200 and you have requested "
        b"strict checking.\nHost key verification failed.\n"
    )
    assert host_key_changed(stderr) is False


def test_success_is_not_changed() -> None:
    assert host_key_changed(b"") is False

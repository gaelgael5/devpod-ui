# backend/tests/test_vm_init.py
from __future__ import annotations

from portal.devpod.vm_init import build_vm_root_inject_script, generate_root_password


def test_generate_root_password_is_safe() -> None:
    p = generate_root_password()
    assert len(p) >= 8
    assert all(c.isalnum() or c in "-_" for c in p)
    # deux appels diffèrent
    assert generate_root_password() != generate_root_password()


def test_inject_script_has_key_and_password() -> None:
    s = build_vm_root_inject_script(
        "ssh-ed25519 AAAAkey container", "Secr3t_pw", "debian@192.168.1.50"
    )
    assert "/root/.ssh/authorized_keys" in s
    assert "chpasswd" in s
    assert "ssh-ed25519 AAAAkey container" in s
    assert "debian@192.168.1.50" in s
    assert "root:Secr3t_pw" in s
    assert "sudo" in s


def test_inject_script_quotes_dangerous_password() -> None:
    # Un mot de passe avec des métacaractères shell doit être quoté (pas d'injection).
    s = build_vm_root_inject_script("pk", "a;rm -rf /", "u@h")
    # La séquence dangereuse n'apparaît jamais hors d'une portion quotée :
    # shlex.quote enveloppe 'root:a;rm -rf /' d'apostrophes.
    assert "'root:a;rm -rf /'" in s

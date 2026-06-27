# backend/tests/test_vm_init.py
from __future__ import annotations

from portal.devpod.vm_init import (
    build_container_ssh_config_cmd,
    build_container_ssh_config_remove_cmd,
    build_vm_root_inject_script,
    generate_root_password,
)


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


def test_container_ssh_config_cmd_builds_block() -> None:
    cmd = build_container_ssh_config_cmd("test1", "192.168.10.160")
    # Le bloc utilise l'alias comme Host, avec l'IP, root et la clé du container.
    assert "Host test1" in cmd
    assert "HostName 192.168.10.160" in cmd
    assert "User root" in cmd
    assert "IdentityFile ~/.ssh/id_ed25519" in cmd
    # VM de test éphémère (recréée) → pas de pinning de clé d'hôte dans le container.
    assert "StrictHostKeyChecking no" in cmd
    assert "UserKnownHostsFile /dev/null" in cmd
    # Délimité par des marqueurs propres à l'alias (pour le remplacement idempotent).
    assert "# >>> portal test-vm test1 >>>" in cmd
    assert "# <<< portal test-vm test1 <<<" in cmd
    # Cible le fichier de config SSH et fixe des perms sûres.
    assert "~/.ssh/config" in cmd
    assert "chmod 600" in cmd


def test_container_ssh_config_cmd_is_idempotent() -> None:
    # Un sed de suppression du bloc précédent précède l'ajout → ré-exécution = remplacement.
    cmd = build_container_ssh_config_cmd("test1", "10.0.0.5")
    assert "sed -i" in cmd
    # La suppression vise la plage entre les deux marqueurs de cet alias.
    assert "/^# >>> portal test-vm test1 >>>$/" in cmd
    assert "/^# <<< portal test-vm test1 <<<$/d" in cmd


def test_container_ssh_config_cmd_quotes_values() -> None:
    # Une IP forgée avec des métacaractères shell ne doit pas s'échapper de son quoting.
    cmd = build_container_ssh_config_cmd("test1", "1.2.3.4; rm -rf /")
    # Le bloc complet (donc l'IP) est confiné dans un unique quoting passé à printf :
    # shlex.quote enveloppe d'apostrophes, le `;` y est inerte.
    assert "printf '%s' '# >>> portal test-vm test1 >>>" in cmd
    assert "1.2.3.4; rm -rf /" in cmd  # présent, mais à l'intérieur du quoting


def test_container_ssh_config_remove_cmd_targets_block() -> None:
    cmd = build_container_ssh_config_remove_cmd("test2")
    # Un sed -i retire la plage entre les marqueurs de cet alias.
    assert "sed -i" in cmd
    assert "/^# >>> portal test-vm test2 >>>$/" in cmd
    assert "/^# <<< portal test-vm test2 <<<$/d" in cmd
    assert "~/.ssh/config" in cmd


def test_container_ssh_config_remove_cmd_noop_if_absent() -> None:
    # Ne doit pas échouer si le fichier n'existe pas (test d'existence avant sed).
    cmd = build_container_ssh_config_remove_cmd("test3")
    assert "[ -f ~/.ssh/config ]" in cmd

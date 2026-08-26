"""Descripteurs des actions de redimensionnement d'une VM (memoire / disque).

Ce sont les fichiers REELLEMENT livres que le portail telecharge : on les valide
avec son propre parseur, pas avec une copie de test. Une erreur ici ne se voit
qu'a l'execution, sur un host Proxmox, plusieurs minutes plus tard.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from portal.routes.proxmox import _flatten_args, _substitute, missing_placeholders

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

_ACTIONS = {
    "proxmox-vm-memory-add.json": ("proxmox-vm-memory.sh", "--delta +1024"),
    "proxmox-vm-memory-sub.json": ("proxmox-vm-memory.sh", "--delta -1024"),
    "proxmox-vm-disk-add.json": ("proxmox-vm-disk.sh", "--delta +10G"),
}


def _spec(nom: str) -> dict[str, Any]:
    spec = json.loads((_SCRIPTS / nom).read_text(encoding="utf-8"))
    assert isinstance(spec, dict)
    return spec


@pytest.mark.parametrize("nom", sorted(_ACTIONS))
def test_le_descripteur_n_expose_que_le_vmid(nom: str) -> None:
    """Le delta est fige par l'action — c'est ce qui la distingue de la
    suivante. Seule la VM cible se choisit."""
    args = _flatten_args(_spec(nom)["args"])

    assert [a["arg"] for a in args] == ["VMID"]
    assert args[0]["type"] == "select"
    assert args[0]["required"] is True


@pytest.mark.parametrize("nom", sorted(_ACTIONS))
def test_le_vmid_se_resout_sur_l_hyperviseur(nom: str) -> None:
    """Sans `option_script`, la liste des VM serait vide et l'action
    inutilisable."""
    args = _flatten_args(_spec(nom)["args"])

    assert args[0].get("option_script")
    assert args[0]["options"] == []  # remplies par le portail a la lecture


@pytest.mark.parametrize("nom", sorted(_ACTIONS))
def test_aucun_placeholder_ne_reste_a_resoudre(nom: str) -> None:
    """Un placeholder non fourni part LITTERAL au shell : `--delta {DELTA}`
    serait rejete par le script apres coup."""
    assert missing_placeholders(_spec(nom)["commands"], {"VMID": "105"}) == set()


@pytest.mark.parametrize(("nom", "attendu"), sorted(_ACTIONS.items()))
def test_la_commande_porte_le_bon_delta(nom: str, attendu: tuple[str, str]) -> None:
    script, delta = attendu
    ligne = _substitute(_spec(nom)["commands"][-1], {"VMID": "105"})

    assert ligne.startswith(f"/tmp/{script} 105 ")
    assert delta in ligne


@pytest.mark.parametrize("nom", sorted(_ACTIONS))
def test_le_script_telecharge_est_celui_qui_est_execute(nom: str) -> None:
    """Un `curl` vers un fichier et un appel a un autre est une erreur muette :
    la commande echoue avec « No such file »."""
    commands = _spec(nom)["commands"]
    script = _ACTIONS[nom][0]

    assert commands[0].startswith(f"curl -fsSL -o /tmp/{script} https://")
    assert script in commands[1]
    assert commands[2].startswith(f"/tmp/{script} ")


@pytest.mark.parametrize("nom", sorted(_ACTIONS))
def test_le_script_reference_existe_dans_le_depot(nom: str) -> None:
    assert (_SCRIPTS / _ACTIONS[nom][0]).is_file()


@pytest.mark.parametrize("script", sorted({v[0] for v in _ACTIONS.values()}))
def test_le_script_est_syntaxiquement_valide(script: str) -> None:
    """`bash -n` : une coquille dans un script telecharge ne se verrait qu'a
    l'execution, sur l'hyperviseur."""
    rc = subprocess.run(  # noqa: S603 — chemin construit depuis une liste fermee
        ["bash", "-n", str(_SCRIPTS / script)],
        capture_output=True,
        check=False,
    )
    assert rc.returncode == 0, rc.stderr.decode()


def test_la_reduction_de_disque_est_refusee_et_expliquee() -> None:
    """Proxmox : « Shrinking disk size is not supported ». Aucune action de
    reduction n'est livree, et le script refuse un delta negatif au lieu de
    laisser `qm` echouer avec un message obscur."""
    assert not list(_SCRIPTS.glob("proxmox-vm-disk-sub.json"))

    source = (_SCRIPTS / "proxmox-vm-disk.sh").read_text(encoding="utf-8")
    assert "Shrinking disk size is not supported" in source

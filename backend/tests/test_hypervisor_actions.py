"""Actions supplementaires d'un type d'hyperviseur.

Creer et detruire sont deux actions parmi d'autres. Les suivantes se declarent
plutot que se codent : un label, un slug, l'URL d'un descripteur JSON du meme
format que le script de creation.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from portal.config.models import HypervisorAction, HypervisorType, qualify_action_slug
from portal.routes.proxmox import _actions_qualifiees


def test_type_sans_action_par_defaut() -> None:
    assert HypervisorType(name="proxmox").actions == []


def test_action_refuse_un_slug_invalide() -> None:
    """Le slug sert d'identifiant : majuscules, espaces et accents sont exclus."""
    with pytest.raises(ValidationError):
        HypervisorAction(label="Reboot", slug="Reboot VM")


def test_qualification_prefixe_par_le_type() -> None:
    assert qualify_action_slug("proxmox", "reboot") == "proxmox-reboot"


def test_qualification_idempotente() -> None:
    """Re-enregistrer un type ne doit pas produire `proxmox-proxmox-reboot`."""
    assert qualify_action_slug("proxmox", "proxmox-reboot") == "proxmox-reboot"


def test_actions_qualifiees_prefixe_toute_la_liste() -> None:
    actions = [
        HypervisorAction(label="Reboot", slug="reboot", script="https://x/reboot.json"),
        HypervisorAction(label="Snapshot", slug="snapshot"),
    ]

    sorties = _actions_qualifiees("proxmox", actions)

    assert [a.slug for a in sorties] == ["proxmox-reboot", "proxmox-snapshot"]
    # Le reste de l'action passe intact.
    assert sorties[0].script == "https://x/reboot.json"


def test_actions_qualifiees_refuse_les_doublons() -> None:
    """Deux entrees du meme slug seraient indiscernables dans la liste."""
    actions = [
        HypervisorAction(label="Reboot", slug="reboot"),
        HypervisorAction(label="Redemarrer", slug="proxmox-reboot"),
    ]

    with pytest.raises(HTTPException) as exc:
        _actions_qualifiees("proxmox", actions)
    assert exc.value.status_code == 422
    assert "proxmox-reboot" in str(exc.value.detail)


def test_actions_qualifiees_liste_vide() -> None:
    assert _actions_qualifiees("proxmox", []) == []


def test_deux_types_peuvent_porter_la_meme_action() -> None:
    """C'est tout l'interet du prefixe : un « reboot » par type, sans collision."""
    a = _actions_qualifiees("proxmox", [HypervisorAction(label="R", slug="reboot")])
    b = _actions_qualifiees("libvirt", [HypervisorAction(label="R", slug="reboot")])

    assert a[0].slug != b[0].slug

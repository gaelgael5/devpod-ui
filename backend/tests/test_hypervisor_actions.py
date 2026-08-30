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


# ─── Cible de l'action (hyperviseur vs machine) ───────────────────────────────


def test_action_sans_cible_vaut_machine() -> None:
    """Defaut retro-compatible : les actions deja declarees visent toutes des VM.

    Un defaut `hyperviseur` reclasserait a tort tout l'existant — memoire et
    disque s'appliquent a une machine, pas a l'hyperviseur qui l'heberge.
    """
    assert HypervisorAction(label="Increase memory", slug="mem-1g").cible == "machine"


def test_action_refuse_une_cible_inconnue() -> None:
    with pytest.raises(ValidationError):
        HypervisorAction(label="Reboot", slug="reboot", cible="cluster")


def test_type_historique_deserialise_ses_actions_en_machine() -> None:
    """Relecture d'un type enregistre avant l'introduction du champ."""
    ht = HypervisorType.model_validate(
        {
            "name": "proxmox4vm",
            "actions": [
                {"label": "Increase memory +1G", "slug": "proxmox4vm-increase-memory-1g"},
                {"label": "Increase disk 10G", "slug": "proxmox4vm-increase-disk-10g"},
            ],
        }
    )

    assert [a.cible for a in ht.actions] == ["machine", "machine"]


def test_qualification_preserve_la_cible() -> None:
    """`_actions_qualifiees` ne recopie que le slug : le reste doit passer intact."""
    actions = [HypervisorAction(label="Inventaire", slug="inv", cible="hyperviseur")]

    assert _actions_qualifiees("proxmox", actions)[0].cible == "hyperviseur"


def test_unicite_des_slugs_sur_les_deux_cibles() -> None:
    """Une seule liste, donc une seule regle : un slug ne peut pas exister deux
    fois, meme avec des cibles differentes — l'execution le retrouve par son
    slug, elle ne saurait pas laquelle choisir."""
    actions = [
        HypervisorAction(label="Reboot hote", slug="reboot", cible="hyperviseur"),
        HypervisorAction(label="Reboot VM", slug="reboot", cible="machine"),
    ]

    with pytest.raises(HTTPException) as exc:
        _actions_qualifiees("proxmox", actions)
    assert exc.value.status_code == 422

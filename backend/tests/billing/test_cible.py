"""Sur quel gabarit une souscription fait naître sa machine.

L'offre liste des profils de host par priorité ; il faut en tirer une cible
exécutable. La chaîne a trois maillons, et chacun peut manquer :

    profil de host → profil de machine → type d'hyperviseur → hyperviseur

Ces tests fixent ce qui se passe quand un maillon casse. Le risque n'est pas
théorique : un maillon manquant qu'on traiterait comme « rien à faire »
laisserait un client payer sans jamais recevoir d'accès, et sans que rien ne le
signale.
"""

from __future__ import annotations

from portal.billing.cible import Catalogue, resoudre_cible

HOTES = {
    "host-standard": "pve-4g",
    "host-gros": "pve-16g",
}
MACHINES = {
    "pve-4g": "proxmox4vm",
    "pve-16g": "proxmox4vm",
}
HYPERVISEURS = [("pve-a", "proxmox4vm", "pve"), ("pve-b", "proxmox4vm", "pve2")]


def _catalogue(**surcharges: object) -> Catalogue:
    base: dict[str, object] = {
        "machine_par_profil_host": dict(HOTES),
        "type_par_profil_machine": dict(MACHINES),
        "hyperviseurs": list(HYPERVISEURS),
    }
    base.update(surcharges)
    return Catalogue.model_validate(base)


# ─── Le chemin nominal ───────────────────────────────────────────────────────


def test_la_cible_suit_la_chaine_complete() -> None:
    cible = resoudre_cible(["host-standard"], _catalogue())

    assert cible is not None
    assert cible.host_profile == "host-standard"
    assert cible.machine_profile == "pve-4g"
    assert cible.hypervisor == "pve-a"
    assert cible.noeud == "pve"


def test_l_hyperviseur_le_moins_charge_est_retenu() -> None:
    """L'arbitrage entre hyperviseurs d'un même type : le moins de machines à
    workspaces en fonctionnement. Décision de l'architecte, 31/08/2026."""
    cible = resoudre_cible(
        ["host-gros"],
        _catalogue(charge_par_hyperviseur={"pve-a": 3, "pve-b": 1}),
    )

    assert cible is not None
    assert cible.hypervisor == "pve-b"
    assert cible.noeud == "pve2"


def test_a_charge_egale_le_nom_departage() -> None:
    """Un tri instable rendrait deux résolutions successives divergentes sans
    raison — le rejeu d'un webhook est la norme, pas l'exception."""
    cible = resoudre_cible(
        ["host-gros"],
        _catalogue(
            hyperviseurs=[("zeta", "proxmox4vm", "pve"), ("alpha", "proxmox4vm", "pve2")],
            charge_par_hyperviseur={"zeta": 2, "alpha": 2},
        ),
    )

    assert cible is not None
    assert cible.hypervisor == "alpha"


def test_une_charge_inconnue_vaut_zero() -> None:
    """Un hyperviseur qui n'a encore rien monté n'apparaît pas dans la charge :
    l'absence se lit « rien ne tourne », pas « inéligible »."""
    cible = resoudre_cible(
        ["host-gros"],
        _catalogue(charge_par_hyperviseur={"pve-a": 5}),
    )

    assert cible is not None
    assert cible.hypervisor == "pve-b"


def test_l_ordre_de_l_offre_est_l_ordre_d_essai() -> None:
    """La priorité saisie par l'administrateur décide, pas l'ordre du
    catalogue."""
    cible = resoudre_cible(["host-gros", "host-standard"], _catalogue())

    assert cible is not None
    assert cible.host_profile == "host-gros"


# ─── Repli : un profil qui ne se résout pas cède la place au suivant ──────────


def test_un_profil_de_host_inconnu_laisse_la_place_au_suivant() -> None:
    """C'est tout l'intérêt d'une LISTE priorisée : le second sert quand le
    premier ne peut pas être honoré."""
    cible = resoudre_cible(["fantome", "host-standard"], _catalogue())

    assert cible is not None
    assert cible.host_profile == "host-standard"


def test_un_profil_de_machine_disparu_laisse_la_place_au_suivant() -> None:
    catalogue = _catalogue(type_par_profil_machine={"pve-16g": "proxmox4vm"})

    cible = resoudre_cible(["host-standard", "host-gros"], catalogue)

    assert cible is not None
    assert cible.host_profile == "host-gros"


def test_un_type_sans_aucun_hyperviseur_laisse_la_place_au_suivant() -> None:
    catalogue = _catalogue(
        type_par_profil_machine={"pve-4g": "vmware", "pve-16g": "proxmox4vm"},
    )

    cible = resoudre_cible(["host-standard", "host-gros"], catalogue)

    assert cible is not None
    assert cible.host_profile == "host-gros"


# ─── Rien ne se résout : il faut le dire, pas le taire ────────────────────────


def test_une_offre_sans_aucun_profil_ne_donne_pas_de_cible() -> None:
    assert resoudre_cible([], _catalogue()) is None


def test_aucun_profil_resoluble_ne_donne_pas_de_cible() -> None:
    """Le `None` remonte à l'appelant, qui doit en faire un échec traçable —
    surtout pas un « rien à faire »."""
    assert resoudre_cible(["fantome", "revenant"], _catalogue()) is None


def test_un_hyperviseur_sans_type_declare_n_est_jamais_retenu() -> None:
    """`hypervisor_type` vaut `""` par défaut sur un hyperviseur enrôlé avant
    les types. Le faire correspondre à un profil serait un coup de chance."""
    catalogue = _catalogue(hyperviseurs=[("vieux", "", "pve")])

    assert resoudre_cible(["host-standard"], catalogue) is None


# ─── Plus aucun nœud interdit en dur ─────────────────────────────────────────


def test_un_hyperviseur_declare_sur_n_importe_quel_noeud_est_eligible() -> None:
    """`NOEUDS_EXCLUS` a disparu : le catalogue est la seule source de vérité.

    La garantie que pve2 (RTX 4090, réservée à l'inférence LLM) ne reçoit
    aucune VM d'abonné repose désormais UNIQUEMENT sur le fait de ne pas y
    déclarer d'hyperviseur — ce n'est plus le code qui la tient."""
    catalogue = _catalogue(hyperviseurs=[("gpu", "proxmox4vm", "pve2")])

    cible = resoudre_cible(["host-standard"], catalogue)

    assert cible is not None
    assert cible.noeud == "pve2"

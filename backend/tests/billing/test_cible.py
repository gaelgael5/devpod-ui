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


def test_le_premier_hyperviseur_du_type_est_retenu() -> None:
    """Premier lot : aucun arbitrage entre hyperviseurs de même type. On prend
    le premier déclaré — un tirage instable rendrait le rejeu d'un événement,
    qui est la norme avec des webhooks, non idempotent."""
    cible = resoudre_cible(["host-gros"], _catalogue())

    assert cible is not None
    assert cible.hypervisor == "pve-a"


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


# ─── Nœuds interdits aux abonnés ─────────────────────────────────────────────


def test_un_noeud_exclu_n_est_jamais_retenu() -> None:
    """pve2 porte la RTX 4090, réservée à l'inférence LLM : aucune VM d'abonné
    n'y naît. La règle survit au passage du nœud figé à la chaîne de profils —
    elle change seulement de forme, de cible imposée à exclusion."""
    catalogue = _catalogue(hyperviseurs=[("gpu", "proxmox4vm", "pve2")])

    assert resoudre_cible(["host-standard"], catalogue, frozenset({"pve2"})) is None


def test_l_exclusion_laisse_la_place_a_l_hyperviseur_suivant() -> None:
    """Exclure n'est pas renoncer : c'est le suivant du type qui sert."""
    catalogue = _catalogue(
        hyperviseurs=[("gpu", "proxmox4vm", "pve2"), ("pve-b", "proxmox4vm", "pve")],
    )

    cible = resoudre_cible(["host-standard"], catalogue, frozenset({"pve2"}))

    assert cible is not None
    assert cible.hypervisor == "pve-b"

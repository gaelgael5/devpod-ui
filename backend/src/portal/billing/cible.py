"""Sur quel gabarit une souscription fait naître sa machine.

`provisioning` sait dire QUOI faire — ouvrir une VM dédiée, ouvrir un host
mutualisé — mais pas AVEC QUOI. Ce module répond, en suivant la chaîne que
l'administrateur a construite maillon par maillon :

    profil de host → profil de machine → type d'hyperviseur → hyperviseur

Chaque maillon a son propriétaire : l'offre choisit des profils de host et les
CLASSE, le profil de host porte le profil de machine, le profil de machine porte
le type, et le type désigne les hyperviseurs capables de l'exécuter.

Deux partis pris :

1. **L'ordre de l'offre est l'ordre d'essai.** La priorité saisie par
   l'administrateur décide ; le premier profil qui se résout entièrement gagne.
   Un profil dont un maillon manque cède la place au suivant : c'est tout
   l'intérêt d'une liste priorisée plutôt que d'un choix unique.
2. **Entre hyperviseurs d'un même type, le moins chargé est retenu** — le moins
   de machines à workspaces en fonctionnement, le nom départageant les égalités
   (un tri instable rendrait deux résolutions successives divergentes sans
   raison). Le choix dépend donc de l'instant : l'idempotence d'un rejeu ne
   repose plus sur le déterminisme du choix mais UNIQUEMENT sur le garde-fou
   « cet abonnement a déjà sa machine » (`deja_provisionne` + registre).

Ce module ne lit ni la base ni la configuration : il reçoit un `Catalogue` déjà
constitué et rend un verdict. Les règles se testent donc sans base et sans
Proxmox, comme celles de `provisioning` et `ownership`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Catalogue(BaseModel):
    """Ce qu'il faut savoir pour résoudre une cible, à plat.

    Trois dictionnaires plutôt que les modèles complets : la résolution n'a
    besoin que des arêtes du graphe, et les recevoir à plat rend visible ce dont
    elle dépend vraiment — donc ce qu'un appelant doit charger.
    """

    model_config = ConfigDict(extra="forbid")

    #: slug de profil de host → slug de profil de machine
    machine_par_profil_host: dict[str, str] = Field(default_factory=dict)
    #: slug de profil de machine → nom de type d'hyperviseur
    type_par_profil_machine: dict[str, str] = Field(default_factory=dict)
    #: hyperviseurs déclarés : (nom, type, nœud).
    hyperviseurs: list[tuple[str, str, str]] = Field(default_factory=list)
    #: Machines à workspaces EN FONCTIONNEMENT, par nom d'hyperviseur — la
    #: métrique de l'arbitrage. L'appelant la constitue (et la groupe par
    #: machine physique quand deux entrées visent le même fer) ; absent = rien
    #: ne tourne, pas « inéligible ».
    charge_par_hyperviseur: dict[str, int] = Field(default_factory=dict)


class Cible(BaseModel):
    """Le gabarit retenu, de bout en bout.

    Les quatre maillons sont conservés, pas seulement le dernier : le jour où
    l'on se demande pourquoi telle machine a été montée ainsi, la réponse doit
    se lire dans la trace du provisioning, pas se reconstituer.
    """

    model_config = ConfigDict(extra="forbid")

    host_profile: str
    machine_profile: str
    hypervisor: str
    #: Nœud de l'hyperviseur retenu — ce que le script de création vise.
    noeud: str


def _hyperviseur_le_moins_charge(
    type_hyperviseur: str, catalogue: Catalogue
) -> tuple[str, str] | None:
    """`(nom, nœud)` de l'hyperviseur du type le moins chargé, ou None.

    Un type vide n'est jamais servi : `Hypervisor.hypervisor_type` vaut `""` par
    défaut sur une machine enrôlée avant les types, et la faire correspondre à
    un profil serait un coup de chance, pas une décision.

    Plus aucun nœud interdit en dur : la garantie que pve2 (RTX 4090, réservée
    à l'inférence LLM) ne reçoit aucune VM d'abonné repose désormais UNIQUEMENT
    sur le fait de ne pas y déclarer d'hyperviseur — le catalogue est la seule
    source de vérité, une exclusion codée la doublerait pour finir par la
    contredire.
    """
    if not type_hyperviseur:
        return None
    candidats = [
        (nom, noeud)
        for nom, type_declare, noeud in catalogue.hyperviseurs
        if type_declare and type_declare == type_hyperviseur
    ]
    if not candidats:
        return None
    return min(
        candidats,
        key=lambda c: (catalogue.charge_par_hyperviseur.get(c[0], 0), c[0]),
    )


def resoudre_cible(
    profils_host: list[str],
    catalogue: Catalogue,
) -> Cible | None:
    """Premier profil de l'offre dont la chaîne se résout entièrement.

    `None` quand aucun ne se résout — y compris quand l'offre n'en liste aucun.
    L'appelant doit en faire un échec TRAÇABLE : traiter ce cas comme « rien à
    faire » laisserait un client payer sans jamais recevoir d'accès, et sans que
    rien ne le signale. C'est précisément l'écart que `provisioning_runs` existe
    pour rendre visible.
    """
    for profil_host in profils_host:
        profil_machine = catalogue.machine_par_profil_host.get(profil_host)
        if profil_machine is None:
            continue
        type_hyperviseur = catalogue.type_par_profil_machine.get(profil_machine)
        if type_hyperviseur is None:
            continue
        hyperviseur = _hyperviseur_le_moins_charge(type_hyperviseur, catalogue)
        if hyperviseur is None:
            continue
        nom, noeud = hyperviseur
        return Cible(
            host_profile=profil_host,
            machine_profile=profil_machine,
            hypervisor=nom,
            noeud=noeud,
        )
    return None

"""Constitution du catalogue que la résolution de cible consomme.

`billing.cible` ne lit ni la base ni la configuration : il reçoit les arêtes du
graphe déjà à plat. Ce module va les chercher, et c'est tout ce qu'il fait.

Les trois maillons ne vivent pas au même endroit, et c'est voulu :

- les **profils de host** et les **profils de machine** sont en base — ils se
  créent et se modifient depuis l'administration ;
- les **hyperviseurs** vivent dans la configuration globale, comme les hosts :
  ce sont des machines physiques enrôlées, pas des objets de catalogue.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from ..billing.cible import Catalogue
from ..config.models import Hypervisor
from ..config.store import load_global
from .host_profiles import list_host_profiles
from .machine_profiles import list_profiles
from .tables import host_health, hosts


async def charger_catalogue(conn: AsyncConnection) -> Catalogue:
    """Les arêtes du graphe, dans l'état où elles sont maintenant.

    Rechargé à chaque provisioning plutôt que mis en cache : un profil ajouté
    ou un hyperviseur enrôlé doit servir à la souscription suivante, pas au
    prochain redémarrage du portail.
    """
    profils_host = await list_host_profiles(conn)
    profils_machine = await list_profiles(conn)
    cfg = load_global()
    return Catalogue(
        machine_par_profil_host={p.slug: p.machine_profile for p in profils_host},
        type_par_profil_machine={p.slug: p.hypervisor_type for p in profils_machine},
        hyperviseurs=[(h.name, h.hypervisor_type, h.pve_node) for h in cfg.hypervisors],
        charge_par_hyperviseur=await _charge_par_hyperviseur(cfg.hypervisors, conn),
    )


async def _charge_par_hyperviseur(
    hyperviseurs: list[Hypervisor], conn: AsyncConnection
) -> dict[str, int]:
    """Machines à workspaces en fonctionnement, par nom d'hyperviseur.

    Le rattachement machine → hyperviseur passe par `hosts.hypervisor` — la
    provenance posée à la création — et JAMAIS par un rapprochement de noms de
    nœuds (`proxmox_node`), ambigu dès que deux entrées partagent un nœud.
    Une machine sans provenance ne compte pour personne : un lien deviné serait
    pire qu'un lien absent.

    « En fonctionnement » = non prouvée injoignable. Une machine JAMAIS SONDÉE
    compte donc comme en marche : la traiter comme absente enverrait toute la
    charge vers l'hyperviseur dont les machines viennent de naître — celles
    qu'aucune sonde n'a encore vues.

    Ce qui sature est la MACHINE PHYSIQUE, pas l'entrée déclarée : deux entrées
    visant le même fer (même adresse, même nœud — une bascule d'accès SSH, par
    exemple) partagent leur charge. Sans ce regroupement, l'une paraîtrait
    pleine et l'autre vide, et tout partirait… sur le même fer.
    """
    stmt = (
        select(hosts.c.hypervisor, func.count())
        .select_from(hosts.outerjoin(host_health, host_health.c.name == hosts.c.name))
        .where(
            hosts.c.usage == "workspaces",
            hosts.c.hypervisor != "",
            host_health.c.reachable.isnot(False),
        )
        .group_by(hosts.c.hypervisor)
    )
    par_entree = {nom: int(n) for nom, n in (await conn.execute(stmt)).all()}

    fer_de = {h.name: (h.address, h.pve_node) for h in hyperviseurs}
    charge_par_fer: dict[tuple[str, str], int] = {}
    for nom, n in par_entree.items():
        fer = fer_de.get(nom)
        if fer is None:
            # Provenance vers un hyperviseur disparu : la machine existe mais
            # ne pèse sur aucune entrée déclarée.
            continue
        charge_par_fer[fer] = charge_par_fer.get(fer, 0) + n
    return {nom: charge_par_fer.get(fer, 0) for nom, fer in fer_de.items()}

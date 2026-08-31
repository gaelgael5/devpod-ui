"""Constitution du catalogue que la résolution de cible consomme.

`billing.cible` ne lit ni la base ni la configuration : il reçoit les arêtes du
graphe déjà à plat. Ce module va les chercher, et c'est tout ce qu'il fait.

Les trois maillons ne vivent pas au même endroit, et c'est voulu :

- les **profils de host** et les **profils de machine** sont en base — ils se
  créent et se modifient depuis l'administration ;
- les **hyperviseurs** vivent dans la configuration globale, comme les hosts :
  ce sont des machines physiques enrôlées, pas des objets de catalogue.

L'ordre de déclaration des hyperviseurs est conservé tel quel : c'est lui qui
porte la règle « le premier du type gagne ». Un tri appliqué ici la casserait
sans que rien ne le signale.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncConnection

from ..billing.cible import Catalogue
from ..config.store import load_global
from .host_profiles import list_host_profiles
from .machine_profiles import list_profiles


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
    )

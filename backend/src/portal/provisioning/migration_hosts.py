"""Migration des hosts existants vers provider/provider_ref (tickets 4 et 9).

Étape 1 de la procédure du cadrage — purement additive et déterministe :

- une machine avec `vmid` a été montée par le chemin Proxmox →
  `provider="proxmox"`, `provider_ref={"vmid", "node"}` ;
- une machine sans `vmid` a été enrôlée à la main → `provider="existing"`,
  `provider_ref={}` — **explicitement** existing, pas un état ambigu.

Un lien faux est pire qu'un lien absent : rien n'est deviné (le vmid vient de
la colonne, le nœud de `proxmox_node`, tel quel même vide). Les colonnes
historiques restent en place jusqu'à l'étape 3 de la procédure.

Idempotent : un host déjà migré (provider non vide) n'est jamais retouché —
notamment pas ceux créés directement par un driver.
"""

from __future__ import annotations

import structlog

from ..config.models import GlobalConfig

_log = structlog.get_logger(__name__)


def migrer_hosts_vers_provider_ref(cfg: GlobalConfig) -> int:
    """Complète en place les hosts sans provenance. Rend le nombre modifié."""
    migres = 0
    for host in cfg.hosts:
        if host.provider:
            continue
        if host.vmid:
            host.provider = "proxmox"
            host.provider_ref = {"vmid": host.vmid, "node": host.proxmox_node}
        else:
            host.provider = "existing"
            host.provider_ref = {}
        migres += 1
    if migres:
        _log.info("hosts_migres_provider_ref", count=migres)
    return migres

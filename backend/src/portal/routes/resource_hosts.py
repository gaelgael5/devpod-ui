"""Hosts de ressource exposés à l'utilisateur — `/me/resource-hosts`.

Un host `usage="ressources"` (spec 33) est un nœud partagé permanent, sans
propriétaire, destiné à héberger des services. En v1, tout host de ressource
enrôlé est déployable par n'importe quel utilisateur authentifié (pas de RBAC
fin) : cette route en fournit la liste au portail, en n'exposant que des champs
sûrs — jamais les slugs de secrets ni la configuration mTLS.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..auth.rbac import UserInfo, require_user
from ..config.store import load_global

me_router = APIRouter(tags=["resource-hosts"])


@me_router.get("/resource-hosts")
async def list_resource_hosts_route(
    user: UserInfo = Depends(require_user),
) -> list[dict[str, Any]]:
    """Hosts de ressource ouverts au déploiement (v1 : tous)."""
    cfg = load_global()
    return [
        {"name": h.name, "address": h.address, "type": h.type}
        for h in cfg.hosts
        if h.usage == "ressources"
    ]

"""Génération de docker-compose.override.yml pour un déploiement portal.

L'override ajoute uniquement les labels de traçabilité sur tous les services ;
il ne touche pas aux ports (la réécriture est faite en amont dans port_aliases).
"""
from __future__ import annotations

from typing import Any

import yaml

LABEL_PREFIX = "io.yoops.portal"


def _service_names(compose_content: str) -> list[str]:
    try:
        parsed = yaml.safe_load(compose_content)
        services = (parsed or {}).get("services") or {}
        if isinstance(services, dict):
            return list(services.keys())
    except Exception:
        pass
    return []


def build_override(
    compose_content: str,
    *,
    deployment_id: str,
    template_id: str,
    owner_login: str,
) -> str:
    """Retourne le contenu YAML du docker-compose.override.yml."""
    labels: dict[str, Any] = {
        f"{LABEL_PREFIX}.deployment_id": deployment_id,
        f"{LABEL_PREFIX}.template_id": template_id,
        f"{LABEL_PREFIX}.owner": owner_login,
    }
    services: dict[str, Any] = {
        name: {"labels": labels} for name in _service_names(compose_content)
    }
    if not services:
        return ""
    return yaml.dump(
        {"services": services},
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )

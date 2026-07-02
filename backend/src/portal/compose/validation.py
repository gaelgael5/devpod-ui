"""Validation et lint des templates compose (spec 26 §5/§7)."""

from __future__ import annotations

import re
from typing import Any

import yaml

from .models import ComposeParam, TemplateSource
from .port_aliases import is_alias_entry

# Bind-mounts système autorisés (lecture seule) pour les templates builtin ou
# importés (source réseau explicitement configurée puis validée par un admin —
# même niveau de confiance que l'import de recettes, qui exécute déjà des
# install.sh arbitraires). Jamais pour les templates "user" (créés/édités par
# un utilisateur quelconque via l'API/MCP).
_SYSTEM_BIND_ALLOWED_SOURCES: frozenset[TemplateSource] = frozenset({"builtin", "imported"})
_BUILTIN_ALLOWED_BINDS: frozenset[str] = frozenset(
    {
        "/var/run/docker.sock",
        "/var/log",
        "/run/log/journal",
        "/etc/machine-id",
    }
)

# Formes compose : ${VAR}, ${VAR:-def}, ${VAR-def}, ${VAR:?msg}, ${VAR?msg}, ${VAR:+alt}
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?[-+?][^}]*)?\}")

# Variables de contexte injectées par le portail à chaque déploiement
# (compose/service.py _log_context_vars) : toujours considérées déclarées.
PORTAL_INJECTED_VARS: frozenset[str] = frozenset({"LOKI_URL", "HOSTNAME", "MODULE", "ROLE"})


class TemplateValidationError(Exception):
    """Erreur dure de validation d'un template (FR)."""


def referenced_vars(compose_content: str) -> set[str]:
    return set(_VAR_RE.findall(compose_content))


def _port_mappings(parsed: dict[str, Any]) -> list[Any]:
    """Retourne les entrées brutes de la liste 'ports' de chaque service (str, int ou dict)."""
    out: list[Any] = []
    services = (parsed or {}).get("services") or {}
    if not isinstance(services, dict):
        return out
    for svc in services.values():
        if not isinstance(svc, dict):
            continue
        ports = svc.get("ports") or []
        if isinstance(ports, list):
            out.extend(ports)
    return out


def _absolute_bind_mounts(svc: dict[str, Any]) -> list[str]:
    """Retourne les chemins de bind-mount absolus (interdits)."""
    bad: list[str] = []
    for vol in svc.get("volumes") or []:
        if isinstance(vol, str):
            src = vol.split(":")[0]
            if src.startswith("/"):
                bad.append(src)
        elif isinstance(vol, dict) and vol.get("type") == "bind":
            src = str(vol.get("source", ""))
            if src.startswith("/"):
                bad.append(src)
    return bad


def _is_hardcoded_host_port(entry: Any) -> bool:
    """True si l'entrée port publie un port hôte littéral (non via ${VAR}).

    Formes supportées :
      - str "HOST:CONTAINER"         → 2 parties, hôte = première
      - str "IP:HOST:CONTAINER"      → 3 parties, hôte = deuxième
      - dict {published: N, ...}     → hôte = published (int ou str de chiffres)
    Les entrées sans port hôte (entier seul, str "80") ne déclenchent pas l'erreur.
    """
    if isinstance(entry, dict):
        published = entry.get("published")
        if published is None:
            return False
        if isinstance(published, int):
            return True
        # Chaîne : digit-only → codé en dur ; "${VAR}" → variable
        return str(published).isdigit()
    if isinstance(entry, int):
        # port conteneur seul (ex. `- 8080`) → aucun port hôte publié
        return False
    s = str(entry)
    parts = s.split(":")
    if len(parts) == 2:
        # "HOST:CONTAINER"
        return parts[0].isdigit()
    if len(parts) == 3:
        # "IP:HOST:CONTAINER"
        return parts[1].isdigit()
    return False


def validate_template(
    compose_content: str,
    parameters: list[ComposeParam],
    source: TemplateSource = "user",
) -> list[str]:
    try:
        parsed = yaml.safe_load(compose_content)
    except yaml.YAMLError as exc:
        raise TemplateValidationError(f"YAML compose non parsable: {exc}") from exc
    if not isinstance(parsed, dict) or "services" not in parsed:
        raise TemplateValidationError("compose invalide: clé 'services' absente")

    declared = {p.key for p in parameters}
    used = referenced_vars(compose_content)
    missing = used - declared - PORTAL_INJECTED_VARS
    if missing:
        raise TemplateValidationError(
            f"variables référencées non déclarées en paramètres: {sorted(missing)}"
        )

    for entry in _port_mappings(parsed):
        # Le format alias>min:container est valide : il sera résolu à l'heure du déploiement.
        if is_alias_entry(entry):
            continue
        if _is_hardcoded_host_port(entry):
            raise TemplateValidationError(
                f"port hôte codé en dur ({entry!r}) : "
                f"utilisez le format alias>min_port:container_port (ex: web>3000:3000)"
            )

    # Lint : bind-mounts absolus interdits (isolation workspace-to-workspace).
    # Exception : templates builtin/imported autorisés sur la whitelist système
    # (lecture seule) — jamais les templates "user".
    services = parsed.get("services") or {}
    for svc_name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        for bad_path in _absolute_bind_mounts(svc):
            if source in _SYSTEM_BIND_ALLOWED_SOURCES and bad_path in _BUILTIN_ALLOWED_BINDS:
                continue
            raise TemplateValidationError(
                f"service {svc_name!r}: bind-mount absolu interdit ({bad_path!r}) ; "
                f"utilisez un chemin relatif (ex: ./data:/app/data) ou un volume nommé"
            )

    # Warnings (non bloquants) : images non épinglées → déploiements non reproductibles.
    warnings: list[str] = []
    for svc_name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        image = svc.get("image")
        if not isinstance(image, str) or not image or "${" in image:
            continue
        # Le tag est dans le dernier segment (après le dernier '/'), pour ne pas
        # confondre le port d'un registre (registry:5000/img) avec un tag.
        ref = image.rsplit("/", 1)[-1]
        if ":" not in ref:
            warnings.append(
                f"service {svc_name!r}: image {image!r} sans tag (latest implicite) — "
                "épinglez une version"
            )
        elif ref.endswith(":latest"):
            warnings.append(
                f"service {svc_name!r}: image {image!r} utilise le tag latest — "
                "épinglez une version"
            )

    return warnings

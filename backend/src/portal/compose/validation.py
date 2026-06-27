"""Validation et lint des templates compose (spec 26 §5/§7)."""
from __future__ import annotations

import re
from typing import Any

import yaml

from .models import ComposeParam

_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-[^}]*)?\}")


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


def validate_template(compose_content: str, parameters: list[ComposeParam]) -> list[str]:
    try:
        parsed = yaml.safe_load(compose_content)
    except yaml.YAMLError as exc:
        raise TemplateValidationError(f"YAML compose non parsable: {exc}") from exc
    if not isinstance(parsed, dict) or "services" not in parsed:
        raise TemplateValidationError("compose invalide: clé 'services' absente")

    declared = {p.key for p in parameters}
    used = referenced_vars(compose_content)
    missing = used - declared
    if missing:
        raise TemplateValidationError(
            f"variables référencées non déclarées en paramètres: {sorted(missing)}"
        )

    for entry in _port_mappings(parsed):
        if _is_hardcoded_host_port(entry):
            raise TemplateValidationError(
                f"port hôte codé en dur ({entry!r}) : "
                f"exposez-le via un paramètre type=port (${{VAR}})"
            )

    warnings: list[str] = []
    for line in compose_content.splitlines():
        has_latest = re.search(r"image:\s*\S+:latest(\s|$)", line)
        has_no_tag = re.search(r"image:\s*[^:\s]+\s*$", line)
        if has_latest or has_no_tag:
            warnings.append(
                f"image non épinglée ('latest' ou sans tag): {line.strip()}"
            )
    return warnings

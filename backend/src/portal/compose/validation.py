"""Validation et lint des templates compose (spec 26 §5/§7)."""
from __future__ import annotations

import re
from typing import Any

import yaml

from .models import ComposeParam

_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-[^}]*)?\}")
# Mapping de ports avec un littéral numérique en partie hôte (port hôte codé en dur).
_HARDCODED_PORT_RE = re.compile(r"^\s*\"?(\d{1,5}):")


class TemplateValidationError(Exception):
    """Erreur dure de validation d'un template (FR)."""


def referenced_vars(compose_content: str) -> set[str]:
    return set(_VAR_RE.findall(compose_content))


def _port_mappings(parsed: dict[str, Any]) -> list[str]:
    out: list[str] = []
    services = (parsed or {}).get("services") or {}
    if not isinstance(services, dict):
        return out
    for svc in services.values():
        if not isinstance(svc, dict):
            continue
        ports = svc.get("ports") or []
        if isinstance(ports, list):
            out.extend(str(p) for p in ports)
    return out


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

    for mapping in _port_mappings(parsed):
        if _HARDCODED_PORT_RE.match(mapping):
            raise TemplateValidationError(
                f"port hôte codé en dur ({mapping!r}) : "
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

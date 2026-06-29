"""Parse et réécriture du format de port alias dans les templates compose.

Syntaxe : alias>min_host_port:container_port
Exemple : "chromium>3000:3000"
  → alias        = "chromium"
  → min_host_port = 3000 (premier port disponible ≥ 3000)
  → container_port = 3000

À l'heure du déploiement, le moteur alloue un port libre ≥ min_host_port
et réécrit les entrées dans le contenu YAML envoyé au nœud.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import yaml

_ALIAS_RE = re.compile(r"^([a-z][a-z0-9-]*)>(\d{1,5}):(\d{1,5})$")


@dataclass(frozen=True)
class PortAlias:
    alias: str
    min_host_port: int
    container_port: int

    @property
    def env_var(self) -> str:
        return f"PORT_{self.alias.upper().replace('-', '_')}"


def is_alias_entry(entry: Any) -> bool:
    """True si l'entrée de port est au format alias>N:M."""
    if not isinstance(entry, str):
        return False
    return bool(_ALIAS_RE.fullmatch(entry.strip()))


def _collect_port_entries(parsed: dict[str, Any]) -> list[str]:
    entries: list[str] = []
    for svc in ((parsed.get("services") or {}).values()):
        if not isinstance(svc, dict):
            continue
        for p in svc.get("ports") or []:
            if isinstance(p, str):
                entries.append(p.strip())
    return entries


def parse_port_aliases(compose_content: str) -> list[PortAlias]:
    """Retourne les PortAlias uniques trouvés dans le YAML du template."""
    try:
        parsed = yaml.safe_load(compose_content)
    except Exception:
        return []

    aliases: list[PortAlias] = []
    seen: set[str] = set()
    for entry in _collect_port_entries(parsed or {}):
        m = _ALIAS_RE.fullmatch(entry)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            aliases.append(
                PortAlias(
                    alias=m.group(1),
                    min_host_port=int(m.group(2)),
                    container_port=int(m.group(3)),
                )
            )
    return aliases


def rewrite_compose_ports(compose_content: str, port_map: dict[str, int]) -> str:
    """Remplace chaque entrée alias>min:container par host_port:container dans le YAML brut.

    On opère sur le texte brut (regex) pour préserver le style YAML original.
    """
    result = compose_content
    for alias, host_port in port_map.items():
        result = re.sub(
            rf"{re.escape(alias)}>(\d{{1,5}}):(\d{{1,5}})",
            lambda m, p=host_port: f"{p}:{m.group(2)}",
            result,
        )
    return result

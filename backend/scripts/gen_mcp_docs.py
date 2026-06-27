"""Génère docs/mcp/devpod-tools.md depuis le registre DEVPOD_PRIMITIVES (spec 24 §6).

Source de vérité unique : le registre implémenté → la doc ne peut pas diverger du contrat.
Lancer après toute évolution des primitives : `uv run python scripts/gen_mcp_docs.py`.
"""
from __future__ import annotations

import json
from pathlib import Path

from portal.mcp.devpod_tools.registry import DEVPOD_PRIMITIVES

_HEADER = (
    "# Passerelle MCP — outils `devpod`\n\n"
    "> Généré depuis `portal.mcp.devpod_tools.registry` — **ne pas éditer à la main**.\n"
    "> Contrat des primitives de pilotage des workspaces (spec 24). Régénérer via\n"
    "> `uv run python scripts/gen_mcp_docs.py`.\n"
)


def render() -> str:
    parts = [_HEADER]
    for name, defn in DEVPOD_PRIMITIVES.items():
        schema = json.dumps(defn["inputSchema"], indent=2, ensure_ascii=False)
        parts.append(
            f"## `devpod__{name}`\n\n"
            f"- **Scope** : `{defn['scope']}`\n"
            f"- **Description** : {defn['description']}\n"
            f"- **Schéma d'entrée** :\n\n"
            f"```json\n{schema}\n```\n"
        )
    return "\n".join(parts)


def main() -> None:
    out = Path(__file__).resolve().parents[2] / "docs" / "mcp" / "devpod-tools.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(), encoding="utf-8")
    print(f"écrit {out} ({len(DEVPOD_PRIMITIVES)} primitives)")


if __name__ == "__main__":
    main()

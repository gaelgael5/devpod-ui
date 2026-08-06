"""Spec 35 — type d'agent GitHub Copilot CLI (~/.copilot/mcp-config.json).

Format vérifié contre la doc GitHub (2026-08-06) : Copilot CLI stocke ses serveurs
MCP dans un fichier DÉDIÉ ~/.copilot/mcp-config.json (override COPILOT_HOME). Une
entrée `mcpServers.<id>` d'un serveur distant porte `type: "http"` (transport
Streamable HTTP), `url`, `headers.Authorization` et un filtre `tools`. Fichier
dédié au MCP comme .cursor/mcp.json — pas de risque d'écraser des réglages Copilot
(mode `replace` sûr).

Le binaire Copilot CLI (@github/copilot) est installé séparément par la recette
`copilot-cli` (repo ag-flow/ressources) ; ce seed ne fait que câbler le MCP de la
gateway du portail quand l'utilisateur sélectionne l'agent à la création.

Skills : ce seed ne couvre que le MCP (un agent_type = un fichier de config).
Copilot CLI n'a PAS de fichier de config de skills — il auto-scanne .claude/skills
(entre autres : .github/skills, .agents/skills, ~/.copilot/skills), soit exactement
là où le portail dépose déjà les SKILL.md via skills/placement.py. Les skills
validées sont donc lues nativement par Copilot, sans template ni changement.

Revision ID: 083
Revises: 082
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "083"
down_revision: str | None = "082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COPILOT_TEMPLATE = """\
{
  "mcpServers": {
{%- for s in servers %}
    {{ s.name | tojson }}: {
      "type": "http",
      "url": {{ s.url | tojson }},
      "headers": {"Authorization": {{ ("Bearer " ~ s.token) | tojson }}},
      "tools": ["*"]
    }{{ "," if not loop.last }}
{%- endfor %}
  }
}
"""

_COPILOT_AGENT_TYPE = {
    "id": "copilot",
    "label": "GitHub Copilot CLI",
    "filename": "mcp-config.json",
    "template": _COPILOT_TEMPLATE,
    "target_path": "{{ home }}/.copilot/mcp-config.json",
}


def upgrade() -> None:
    agent_type = sa.table(
        "agent_type",
        sa.column("id", sa.Text),
        sa.column("label", sa.Text),
        sa.column("filename", sa.Text),
        sa.column("template", sa.Text),
        sa.column("target_path", sa.Text),
    )
    op.bulk_insert(agent_type, [_COPILOT_AGENT_TYPE])


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM agent_type WHERE id = 'copilot'"))

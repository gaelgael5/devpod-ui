"""Spec 35 — type d'agent Kimi Code CLI (~/.kimi-code/mcp.json).

Format vérifié contre la doc Moonshot (2026-08-07) : Kimi Code CLI auto-lit ses
serveurs MCP dans ~/.kimi-code/mcp.json (ou le projet .kimi-code/mcp.json). Une
entrée `mcpServers.<id>` d'un serveur distant HTTP porte `url` + `headers`
(pas de champ `transport` : `url` sans `transport` = HTTP). Fichier dédié au MCP
(à côté de config.toml/tui.toml) → mode `replace` sûr.

Le binaire (@moonshot-ai/kimi-code, commande `kimi`) est installé séparément par
la recette `kimi-code` (repo ag-flow/ressources) ; ce seed ne fait que câbler le
MCP de la gateway quand l'utilisateur sélectionne l'agent à la création.

Convention : id court d'agent_type `kimi` ≠ id de recette `kimi-code` (comme
claude/claude-code, copilot/copilot-cli).

Revision ID: 085
Revises: 084
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "085"
down_revision: str | None = "084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KIMI_TEMPLATE = """\
{
  "mcpServers": {
{%- for s in servers %}
    {{ s.name | tojson }}: {
      "url": {{ s.url | tojson }},
      "headers": {"Authorization": {{ ("Bearer " ~ s.token) | tojson }}}
    }{{ "," if not loop.last }}
{%- endfor %}
  }
}
"""

_KIMI_AGENT_TYPE = {
    "id": "kimi",
    "label": "Kimi Code CLI",
    "filename": "mcp.json",
    "template": _KIMI_TEMPLATE,
    "target_path": "{{ home }}/.kimi-code/mcp.json",
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
    op.bulk_insert(agent_type, [_KIMI_AGENT_TYPE])


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM agent_type WHERE id = 'kimi'"))

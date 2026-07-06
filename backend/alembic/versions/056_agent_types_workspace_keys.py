"""Spec 35 — accès MCP direct des agents workspace.

- mcp_profile.exposed_in_workspaces : profil injecté dans les fichiers MCP des
  workspaces de son owner (défaut false).
- agent_type : types d'agents déclaratifs (template Jinja + filename + target_path),
  seed 'claude' (Claude Code, .mcp.json à la racine du projet).
- mcp_apikey.workspace_ref : clefs générées par workspace (ws_id texte
  "{login}-{name}", convention spec 34 — pas de FK dure) + index partiel.

Revision ID: 056
Revises: 055
Create Date: 2026-07-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "056"
down_revision: str | None = "055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Template seed pour Claude Code : une entrée mcpServers par profil exposé.
_CLAUDE_TEMPLATE = """\
{
  "mcpServers": {
{%- for s in servers %}
    {{ s.name | tojson }}: {
      "type": "http",
      "url": {{ s.url | tojson }},
      "headers": {"Authorization": {{ ("Bearer " ~ s.token) | tojson }}}
    }{{ "," if not loop.last }}
{%- endfor %}
  }
}
"""


def upgrade() -> None:
    op.add_column(
        "mcp_profile",
        sa.Column("exposed_in_workspaces", sa.Boolean(), nullable=False, server_default="false"),
    )

    op.add_column("mcp_apikey", sa.Column("workspace_ref", sa.Text(), nullable=True))
    op.create_index(
        "idx_mcp_apikey_workspace_ref",
        "mcp_apikey",
        ["workspace_ref"],
        postgresql_where=sa.text("workspace_ref IS NOT NULL"),
    )

    table = op.create_table(
        "agent_type",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("target_path", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.bulk_insert(
        table,
        [
            {
                "id": "claude",
                "label": "Claude Code",
                "filename": ".mcp.json",
                "template": _CLAUDE_TEMPLATE,
                "target_path": "{{ project_root }}/.mcp.json",
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("agent_type")
    op.drop_index("idx_mcp_apikey_workspace_ref", table_name="mcp_apikey")
    op.drop_column("mcp_apikey", "workspace_ref")
    op.drop_column("mcp_profile", "exposed_in_workspaces")

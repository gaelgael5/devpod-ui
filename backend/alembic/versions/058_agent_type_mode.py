"""Spec 35 (addendum merge) — colonne `mode` sur agent_type.

Distingue deux stratégies de matérialisation de la config MCP dans le workspace :

- `replace` (défaut, comportement historique) : le fichier cible est **dédié**
  au MCP (`.mcp.json`, `.cursor/mcp.json`, Cline, Devin) ; il est monté en
  lecture seule et lié par symlink. Le portail possède tout le fichier.
- `merge` : le fichier cible est **partagé** avec d'autres réglages du client
  (Codex `config.toml`, Gemini `settings.json`). Le portail ne possède que sa
  section serveurs et doit fusionner le connecteur dans le fichier existant sans
  écraser les réglages utilisateur.

Codex et Gemini passent en `merge` mais sont **désactivés** par cette migration :
le mécanisme de merge n'existe pas encore, les laisser mappables écraserait la
config des workspaces. Ils seront réactivés à la fin du chantier merge.

Revision ID: 058
Revises: 057
Create Date: 2026-07-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "058"
down_revision: str | None = "057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Clients à fichier de config partagé → merge + désactivés jusqu'à livraison.
_MERGE_CLIENTS = ["codex", "gemini"]


def upgrade() -> None:
    op.add_column(
        "agent_type",
        sa.Column("mode", sa.Text(), nullable=False, server_default="replace"),
    )
    op.execute(
        sa.text(
            "UPDATE agent_type SET mode = 'merge', enabled = false WHERE id = ANY(:ids)"
        ).bindparams(sa.bindparam("ids", value=_MERGE_CLIENTS, type_=sa.ARRAY(sa.Text())))
    )


def downgrade() -> None:
    # Restaure l'état 057 : clients merge réactivés, colonne supprimée.
    op.execute(
        sa.text("UPDATE agent_type SET enabled = true WHERE id = ANY(:ids)").bindparams(
            sa.bindparam("ids", value=_MERGE_CLIENTS, type_=sa.ARRAY(sa.Text()))
        )
    )
    op.drop_column("agent_type", "mode")

"""Sources de découverte MCP (serveurs qui exposent un catalogue de services).

Une source = une instance mcp-manager (ex. mcp.yoops.org) qu'on interroge pour
rechercher des services MCP puis les ajouter comme serveurs. On stocke l'URL de
base et une **référence** (slug) vers un secret utilisateur de type
`MCP_DISCOVERY` — jamais la valeur de la clé.

Revision ID: 063
Revises: 062
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "063"
down_revision: str | None = "062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_discovery_source",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "login",
            sa.Text(),
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("secret_slug", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("login", "slug", name="uq_mcp_discovery_source_login_slug"),
    )


def downgrade() -> None:
    op.drop_table("mcp_discovery_source")

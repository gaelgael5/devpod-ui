"""user_services : registre de services (nom, URL, profil MCP d'accès).

Hub « Services & Security » — adresses de services externes utiles au travail
de l'utilisateur. mcp_profile_id nullable + ON DELETE SET NULL : la suppression
du profil ne fait jamais disparaître le service enregistré, seulement son
association (l'UI signale « aucun profil »).

Revision ID: 050
Revises: 049
Create Date: 2026-07-05
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "050"
down_revision: str | None = "049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_services",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "owner_login",
            sa.Text(),
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "mcp_profile_id",
            sa.Text(),
            sa.ForeignKey("mcp_profile.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("user_services")

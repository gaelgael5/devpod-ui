"""mcp_workspace_profile : surcharge persistante du profil MCP d'un workspace.

Le profil « exposé par défaut » alimente un workspace tant que l'utilisateur ne
choisit rien ; dès qu'il fixe un profil sur la ligne (écran Client API Keys), le
choix est mémorisé ici et **survit à la rotation des clefs** — la rotation
consulte cette table en priorité sur les profils exposés.

FK profil CASCADE : profil supprimé → la surcharge disparaît → le workspace
re-suit le défaut. ws_id = convention "{login}-{name}" (pas de FK dure).

Revision ID: 082
Revises: 081
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "082"
down_revision: str | None = "081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_workspace_profile",
        sa.Column("ws_id", sa.Text(), primary_key=True),
        sa.Column(
            "owner_login",
            sa.Text(),
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profile_id",
            sa.Text(),
            sa.ForeignKey("mcp_profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("mcp_workspace_profile")

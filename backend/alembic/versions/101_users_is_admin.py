"""Rôle admin persisté : colonne `users.is_admin`.

Le rôle admin vient des claims OIDC (Keycloak) et n'était donc pas connu côté
serveur hors requête. Pour pousser des connexions Termix aux admins (hosts d'infra,
serveurs de ressources) au fil des changements, on persiste `is_admin` à chaque
login OIDC (d'après `settings.oidc_admin_role`). Défaut false.

Revision ID: 101
Revises: 100
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "101"
down_revision: str | None = "100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")

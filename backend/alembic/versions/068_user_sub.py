"""user_sub : ancre l'identité sur le sujet OIDC (users.sub, nullable unique).

Revision ID: 068
Revises: 067
Create Date: 2026-07-14
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "068"
down_revision: str | None = "067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable : les comptes existants n'ont pas de sub — backfillé au 1er login
    # OIDC. UNIQUE via index (plusieurs NULL autorisés sous contrainte unique
    # Postgres → aucun conflit sur les lignes non encore ancrées).
    op.add_column("users", sa.Column("sub", sa.Text(), nullable=True))
    op.create_index("uq_users_sub", "users", ["sub"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_users_sub", table_name="users")
    op.drop_column("users", "sub")

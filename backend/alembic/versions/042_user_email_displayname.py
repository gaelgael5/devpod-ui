"""user_email_displayname : ajoute email et display_name sur la table users.

Revision ID: 042
Revises: 041
Create Date: 2026-07-01
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "042"
down_revision: str | None = "041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.Text(), nullable=False, server_default=""))
    op.add_column(
        "users", sa.Column("display_name", sa.Text(), nullable=False, server_default="")
    )


def downgrade() -> None:
    op.drop_column("users", "display_name")
    op.drop_column("users", "email")

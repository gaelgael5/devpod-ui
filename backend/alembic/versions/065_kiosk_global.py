"""kiosk_applications : le kiosque devient global, géré par l'admin.

Remplace user_applications (kiosque par utilisateur, 064) par une table globale
sans scope login : une seule liste de boutons, visible par tous, gérée par un
admin. Les lignes existantes sont reprises (première occurrence par nom).

Revision ID: 065
Revises: 064
Create Date: 2026-07-13
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "065"
down_revision: str | None = "064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kiosk_applications",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("icon", sa.Text(), nullable=False, server_default=""),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
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
    )
    # Reprise des liens déjà créés (064) : première occurrence par nom, l'ordre
    # position/id d'origine est conservé.
    op.execute(
        """
        INSERT INTO kiosk_applications (name, url, icon, position, created_at, updated_at)
        SELECT DISTINCT ON (name) name, url, icon, position, created_at, updated_at
        FROM user_applications
        ORDER BY name, id
        """
    )
    op.drop_table("user_applications")


def downgrade() -> None:
    op.create_table(
        "user_applications",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "login",
            sa.Text(),
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("icon", sa.Text(), nullable=False, server_default=""),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
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
        sa.UniqueConstraint("login", "name", name="uq_user_applications_login_name"),
    )
    # Perte assumée au downgrade : le scope par login n'existe plus.
    op.drop_table("kiosk_applications")

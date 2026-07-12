"""Table générique de préférences utilisateur (clé fonctionnelle + valeur typée).

Stocke des réglages d'UI par utilisateur sans multiplier les colonnes sur
`users` : une ligne = (login, pref_key) → une valeur, rangée dans la colonne
typée correspondante (`value_int` / `value_text` / `value_bool`). `value_type`
lève toute ambiguïté de lecture (ex. int 0 vs bool false vs absent). Premier
consommateur : l'état replié/déplié des groupes de workspaces.

Revision ID: 062
Revises: 061
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "062"
down_revision: str | None = "061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "login",
            sa.Text(),
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pref_key", sa.Text(), nullable=False),
        sa.Column("value_type", sa.Text(), nullable=False),
        sa.Column("value_int", sa.Integer(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_bool", sa.Boolean(), nullable=True),
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
        sa.CheckConstraint(
            "value_type IN ('int', 'string', 'bool')",
            name="ck_user_preferences_value_type",
        ),
        sa.UniqueConstraint("login", "pref_key", name="uq_user_preferences_login_key"),
    )


def downgrade() -> None:
    op.drop_table("user_preferences")

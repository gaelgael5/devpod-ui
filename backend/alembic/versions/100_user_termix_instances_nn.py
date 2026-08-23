"""Rattachement user→instances Termix : N-N ≤3 (spec 18 T4b).

Supersède la colonne unique `users.termix_instance_id` (migration 099) : l'admin
peut associer jusqu'à 3 instances Termix à un user (fallback + migration), et le
provisioning fan-out réplique ses hosts sur chacune. Backfill : la colonne unique
existante devient une ligne de la table N-N, puis la colonne est supprimée.

Revision ID: 100
Revises: 099
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "100"
down_revision: str | None = "099"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_termix_instance",
        sa.Column(
            "login", sa.Text(), sa.ForeignKey("users.login", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "instance_id",
            sa.Text(),
            sa.ForeignKey("termix_instance.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    # Backfill : reporter l'assignation unique (099) dans la N-N.
    op.execute(
        """
        INSERT INTO user_termix_instance (login, instance_id)
        SELECT login, termix_instance_id FROM users
        WHERE termix_instance_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    op.drop_constraint("fk_users_termix_instance", "users", type_="foreignkey")
    op.drop_column("users", "termix_instance_id")


def downgrade() -> None:
    op.add_column("users", sa.Column("termix_instance_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_users_termix_instance",
        "users",
        "termix_instance",
        ["termix_instance_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        """
        UPDATE users u SET termix_instance_id = (
            SELECT instance_id FROM user_termix_instance x
            WHERE x.login = u.login ORDER BY x.created_at LIMIT 1
        )
        """
    )
    op.drop_table("user_termix_instance")

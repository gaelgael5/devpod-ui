"""Rattachement user→instance Termix : colonne `users.termix_instance_id` (spec 18 T4).

NULL = héritage de l'instance `is_default`. FK SET NULL : supprimer une instance
retombe les users rattachés sur le défaut. Assignée par l'admin via la page
Utilisateurs. Résolution : explicite si posée, sinon `is_default` (option A).

Revision ID: 099
Revises: 098
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "099"
down_revision: str | None = "098"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("termix_instance_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_users_termix_instance",
        "users",
        "termix_instance",
        ["termix_instance_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_termix_instance", "users", type_="foreignkey")
    op.drop_column("users", "termix_instance_id")

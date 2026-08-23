"""Registre d'instances Termix : table `termix_instance` (spec 18 T2).

Une instance = un serveur Termix (URL + apikey admin en secret système), avec un
`client_id` OIDC Keycloak de référence et un flag `is_default` (au plus une à
True, invariant tenu par la couche applicative). Un user est ensuite rattaché à
une instance (T4).

Revision ID: 097
Revises: 096
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "097"
down_revision: str | None = "096"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "termix_instance",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("apikey_secret", sa.Text(), nullable=False),
        sa.Column("oidc_client_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("termix_instance")

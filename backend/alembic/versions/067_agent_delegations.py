"""agent_delegations : délégation agent↔humain (acteur on-behalf-of).

Revision ID: 067
Revises: 066
Create Date: 2026-07-14
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "067"
down_revision: str | None = "066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_delegations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("principal_subject", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False, server_default="skills"),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Une seule délégation ACTIVE par (agent, scope) ; les révoquées restent
    # en base pour l'audit — d'où l'index unique PARTIEL.
    op.create_index(
        "uq_agent_delegations_active",
        "agent_delegations",
        ["agent_id", "scope"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_delegations_active", table_name="agent_delegations")
    op.drop_table("agent_delegations")

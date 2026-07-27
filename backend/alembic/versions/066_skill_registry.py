"""skill_registry : grants (autorisation per-user) + placements (installation
per-workspace) pour l'intégration skills.sh — deux lifecycles liés par FK.

Revision ID: 066
Revises: 065
Create Date: 2026-07-14
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "066"
down_revision: str | None = "065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skill_grants",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("user_subject", sa.Text(), nullable=False),
        sa.Column("skill_id", sa.Text(), nullable=False),
        sa.Column("approved_hash", sa.Text(), nullable=True),
        sa.Column("statut", sa.Text(), nullable=False, server_default="pending"),
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
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "statut IN ('requested', 'pending', 'granted', 'paused', 'revoked')",
            name="ck_skill_grants_statut",
        ),
        sa.UniqueConstraint(
            "user_subject", "skill_id", name="uq_skill_grants_subject_skill"
        ),
    )
    op.create_table(
        "skill_placements",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "grant_id",
            sa.BigInteger(),
            sa.ForeignKey("skill_grants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("installed_hash", sa.Text(), nullable=True),
        sa.Column("statut", sa.Text(), nullable=False, server_default="requested"),
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
            "statut IN ('requested', 'placed', 'verified', 'unverified')",
            name="ck_skill_placements_statut",
        ),
        sa.UniqueConstraint(
            "grant_id", "workspace_id", name="uq_skill_placements_grant_ws"
        ),
    )
    # Requête de routage : placements d'un workspace (JOIN grants).
    op.create_index(
        "ix_skill_placements_workspace", "skill_placements", ["workspace_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_skill_placements_workspace", table_name="skill_placements")
    op.drop_table("skill_placements")
    op.drop_table("skill_grants")

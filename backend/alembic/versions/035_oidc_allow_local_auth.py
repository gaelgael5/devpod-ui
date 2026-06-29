"""oidc_allow_local_auth: toggle break-glass local login depuis l'UI admin

Revision ID: 035
Revises: 034
Create Date: 2026-06-28
"""
from alembic import op
import sqlalchemy as sa

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "global_config",
        sa.Column(
            "oidc_allow_local_auth",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )


def downgrade() -> None:
    op.drop_column("global_config", "oidc_allow_local_auth")

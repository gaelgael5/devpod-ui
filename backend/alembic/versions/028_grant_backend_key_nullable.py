"""mcp_apikey_grant.backend_key_id nullable (grant vers un backend public sans clé).

La 018 déclarait déjà nullable=True dans le modèle, mais d'anciennes bases ont été
créées avec la contrainte NOT NULL. On l'aligne explicitement : un grant vers un
backend public (sans clé d'authentification) doit pouvoir avoir backend_key_id NULL.

Revision ID: 028
Revises: 027
Create Date: 2026-06-26
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "028"
down_revision: str | None = "027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "mcp_apikey_grant", "backend_key_id", existing_type=sa.Text(), nullable=True
    )


def downgrade() -> None:
    op.alter_column(
        "mcp_apikey_grant", "backend_key_id", existing_type=sa.Text(), nullable=False
    )

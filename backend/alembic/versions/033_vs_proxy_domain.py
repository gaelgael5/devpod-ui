"""Ajout de vs_proxy_domain à global_config.

Sous-domaine fixe pour le proxy VS Code (ex. vs-dev.yoops.org) : quand renseigné,
le portail utilise ce domaine au lieu de sous-domaines per-workspace.
Caddy résout l'upstream dynamiquement via l'en-tête X-Workspace-Upstream retourné
par /auth/caddy/verify-workspace.

Revision ID: 033
Revises: 032
Create Date: 2026-06-28
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "033"
down_revision: str | None = "032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "global_config",
        sa.Column("vs_proxy_domain", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("global_config", "vs_proxy_domain")

"""Ajout de la config logs (Loki/Grafana) à global_config.

Le champ GlobalConfig.logs (LogsConfig) n'avait aucune colonne : PUT /admin/config
acceptait et retournait la valeur sans jamais la persister — perdue au premier
redémarrage du portail. Corrige la lacune, symétrique à cookie_domain (034).

Revision ID: 043
Revises: 042
Create Date: 2026-07-02
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "043"
down_revision: str | None = "042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "global_config",
        sa.Column("logs_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "global_config",
        sa.Column("logs_loki_push_url", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "global_config",
        sa.Column("logs_loki_query_url", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "global_config",
        sa.Column("logs_grafana_url", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "global_config",
        sa.Column("logs_module", sa.Text(), nullable=False, server_default="devpod"),
    )
    op.add_column(
        "global_config",
        sa.Column("logs_push_token", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("global_config", "logs_push_token")
    op.drop_column("global_config", "logs_module")
    op.drop_column("global_config", "logs_grafana_url")
    op.drop_column("global_config", "logs_loki_query_url")
    op.drop_column("global_config", "logs_loki_push_url")
    op.drop_column("global_config", "logs_enabled")

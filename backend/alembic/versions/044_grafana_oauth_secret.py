"""Ajout de la config OAuth Keycloak de Grafana à global_config.

Login SSO de Grafana lui-même (client Keycloak, ID par défaut "agflow-grafana")
— distinct de logs_push_token qui authentifie les collecteurs Alloy vers Loki.
Auth/token/userinfo URL dérivées de oidc_issuer côté application, pas stockées.

Revision ID: 044
Revises: 043
Create Date: 2026-07-02
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "044"
down_revision: str | None = "043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "global_config",
        sa.Column(
            "logs_grafana_oauth_client_id",
            sa.Text(),
            nullable=False,
            server_default="agflow-grafana",
        ),
    )
    op.add_column(
        "global_config",
        sa.Column(
            "logs_grafana_oauth_client_secret", sa.Text(), nullable=False, server_default=""
        ),
    )


def downgrade() -> None:
    op.drop_column("global_config", "logs_grafana_oauth_client_secret")
    op.drop_column("global_config", "logs_grafana_oauth_client_id")

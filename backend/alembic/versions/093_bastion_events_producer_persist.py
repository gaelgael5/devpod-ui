"""Persistance des sections `bastion` et `events_producer` de la GlobalConfig.

Les deux sections étaient éditables via l'IHM admin (PUT /admin/bastion-config,
PUT /admin/events-producer) mais jamais sérialisées par `_cfg_to_scalars` ni
reconstruites par `_build_global_config` : elles ne vivaient que dans le cache
RAM et retombaient aux défauts à chaque redémarrage du portail (sshd bastion non
redémarré, provisioning Termix silencieusement inactif, relais d'events coupé).

Ajoute les colonnes `bastion_*` et `events_*` à `global_config`, défauts alignés
sur les modèles pydantic (BastionConfig / EventsProducerConfig).

Revision ID: 093
Revises: 092
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "093"
down_revision: str | None = "092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS: list[sa.Column] = [
    sa.Column("events_enabled", sa.Boolean(), nullable=False, server_default="false"),
    sa.Column("events_workflow_base_url", sa.Text(), nullable=False, server_default=""),
    sa.Column("events_source_id", sa.Text(), nullable=False, server_default=""),
    sa.Column(
        "events_secret_slug", sa.Text(), nullable=False, server_default="workflow_events_hmac"
    ),
    sa.Column("events_source_uri", sa.Text(), nullable=False, server_default="urn:yoops:devpod"),
    sa.Column("events_types", sa.ARRAY(sa.Text()), nullable=False, server_default="{}"),
    sa.Column("bastion_enabled", sa.Boolean(), nullable=False, server_default="false"),
    sa.Column("bastion_api_url", sa.Text(), nullable=False, server_default=""),
    sa.Column("bastion_host", sa.Text(), nullable=False, server_default=""),
    sa.Column("bastion_port", sa.Integer(), nullable=False, server_default="2222"),
    sa.Column("bastion_role", sa.Text(), nullable=False, server_default=""),
    sa.Column("bastion_apikey_secret", sa.Text(), nullable=False, server_default="termix-apikey"),
]


def upgrade() -> None:
    for col in _COLUMNS:
        op.add_column("global_config", col)


def downgrade() -> None:
    for col in reversed(_COLUMNS):
        op.drop_column("global_config", col.name)

"""compose_deployment : uid UUID PK + contrainte (id, node_id) unique par nœud

Revision ID: 038
Revises: 037
Create Date: 2026-06-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Ajouter la colonne uid (nullable temporairement pour remplir les lignes existantes)
    op.add_column("compose_deployment", sa.Column("uid", sa.Text(), nullable=True))

    # 2. Remplir les lignes existantes avec un UUID généré par PostgreSQL
    op.execute(
        "UPDATE compose_deployment SET uid = gen_random_uuid()::text WHERE uid IS NULL"
    )

    # 3. Passer uid en NOT NULL
    op.alter_column("compose_deployment", "uid", nullable=False)

    # 4. Supprimer l'ancienne contrainte de PK sur id
    op.drop_constraint("compose_deployment_pkey", "compose_deployment", type_="primary")

    # 5. Créer la nouvelle PK sur uid
    op.create_primary_key("compose_deployment_pkey", "compose_deployment", ["uid"])

    # 6. Ajouter la contrainte d'unicité (id, node_id) — unicité par nœud
    op.create_unique_constraint(
        "uq_compose_deployment_name_node",
        "compose_deployment",
        ["id", "node_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_compose_deployment_name_node", "compose_deployment", type_="unique")
    op.drop_constraint("compose_deployment_pkey", "compose_deployment", type_="primary")
    op.create_primary_key("compose_deployment_pkey", "compose_deployment", ["id"])
    op.drop_column("compose_deployment", "uid")

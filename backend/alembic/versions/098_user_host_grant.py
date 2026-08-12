"""Portée user→host SSH : table N-N `user_host_grant` (spec 18 T3).

Décide quels users ont accès à quel host Termix (= un workspace SSH publié,
`ws_id`). Backfill « tout-accordé » : chaque host publié existant (workspace_status
avec un `ssh_port`) est accordé à tous les users connus — on part d'un partage
ouvert, l'admin restreint ensuite via la page Utilisateurs (T4). Le provisioning
(T5) consulte cette table pour partager le host aux seuls users accordés.

Revision ID: 098
Revises: 097
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "098"
down_revision: str | None = "097"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_host_grant",
        sa.Column(
            "login",
            sa.Text(),
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "ws_id",
            sa.Text(),
            sa.ForeignKey("workspace_status.ws_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    # Backfill tout-accordé : produit croisé (users) × (hosts SSH publiés).
    op.execute(
        """
        INSERT INTO user_host_grant (login, ws_id)
        SELECT u.login, s.ws_id
        FROM users u
        CROSS JOIN workspace_status s
        WHERE s.ssh_port IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("user_host_grant")

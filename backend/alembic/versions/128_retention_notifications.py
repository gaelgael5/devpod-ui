"""Trace des expirations de retention notifiees.

Le scheduler de retention repere les abonnements en `echec_paiement` ou
`resilie` dont le delai est ecoule, et emet `subscription.retention_expired`
vers les automates. Cette table est ce qui garantit qu'il l'emet UNE fois par
episode : c'est la fiche « Arret, retention et destruction d'un workspace non
paye » qui l'exige — un scheduler qui se declenche deux fois sur le meme
episode, et l'on detruit deux fois, ou l'on detruit ce qu'un paiement venait de
rattraper.

L'episode est identifie par `(subscription_id, state, state_changed_at)` : un
abonnement qui retombe en echec de paiement APRES s'etre retabli est un nouvel
episode — son `state_changed_at` a change — et merite sa propre notification.

C'est aussi la trace d'audit : QUAND on a signale l'expiration, pour quel etat,
arme a quel instant.

Revision ID: 128
Revises: 127
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "128"
down_revision: str | None = "127"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "retention_notifications",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "subscription_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("state_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "emitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "subscription_id",
            "state",
            "state_changed_at",
            name="uq_retention_notification_episode",
        ),
        sa.CheckConstraint(
            "state IN ('echec_paiement','resilie')",
            name="ck_retention_notification_state",
        ),
    )


def downgrade() -> None:
    op.drop_table("retention_notifications")

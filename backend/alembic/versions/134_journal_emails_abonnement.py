"""Journal des emails du cycle d'abonnement (fiche 6fdfdaab).

Idempotence par épisode — `(subscription_id, kind, dedup_key)` tranche à
l'écriture, comme provisioning_runs — et preuve : le payload est figé dans la
ligne, dates limites comprises, pour pouvoir prouver ce qui a été annoncé même
si la politique de rétention change ensuite.

Revision ID: 134
Revises: 133
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "134"
down_revision: str | Sequence[str] | None = "133"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "emails_envoyes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "subscription_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # 5 kinds du cycle + 'avertissement_destruction' (balayeur).
        sa.Column("kind", sa.Text(), nullable=False),
        # provider_event_id du webhook, ou cle d'episode du balayeur.
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.Column("destinataire", sa.Text(), nullable=False),
        sa.Column("culture", sa.Text(), nullable=False, server_default="fr"),
        sa.Column("template", sa.Text(), nullable=False),
        # Payload FIGE — jamais un secret : c'est une trace d'ecran.
        sa.Column("data", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("statut", sa.Text(), nullable=False, server_default="reserve"),
        sa.Column("erreur", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "statut IN ('reserve','envoye','echec')", name="ck_email_envoye_statut"
        ),
        sa.UniqueConstraint(
            "subscription_id", "kind", "dedup_key", name="uq_email_envoye_episode"
        ),
    )
    op.create_index(
        "ix_emails_envoyes_echec",
        "emails_envoyes",
        ["statut"],
        postgresql_where=sa.text("statut = 'echec'"),
    )


def downgrade() -> None:
    op.drop_index("ix_emails_envoyes_echec", table_name="emails_envoyes")
    op.drop_table("emails_envoyes")

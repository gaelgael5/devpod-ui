"""Trace des provisionings : ce qui a ete decide, et ce qui en est advenu.

Un abonnement peut etre paye sans que l'acces existe : la creation de VM echoue,
le pool est injoignable, le script rend une erreur. Sans trace, cet ecart est
INVISIBLE — le client paie, personne ne le sait, et on le decouvre par une
reclamation.

Cette table est le registre de ces tentatives. Elle porte le verdict du decideur
(`billing.provisioning`) et son issue, pour que l'echec soit une ligne qu'on
peut lister, pas une ligne de journal qui defile.

`uq_provisioning_run_event` porte l'idempotence : un webhook rejoue — c'est la
norme, pas l'exception — ne cree pas une seconde tentative.

Revision ID: 113
Revises: 112
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "113"
down_revision: str | Sequence[str] | None = "112"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provisioning_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "subscription_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Identifiant de l'evenement declencheur cote provider. Vide pour un
        # declenchement manuel depuis l'administration.
        sa.Column("provider_event_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "owner_login",
            sa.Text(),
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("offer_slug", sa.Text(), nullable=False),
        # Verdict du decideur, recopie tel quel : on doit pouvoir relire ce qui
        # a ete decide meme si la regle a change depuis.
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("host_name", sa.Text(), nullable=True),
        sa.Column("motif", sa.Text(), nullable=False, server_default=""),
        sa.Column("state", sa.Text(), nullable=False, server_default="decide"),
        # Message d'erreur du dernier echec. Jamais un secret : c'est une trace
        # destinee a un ecran d'administration.
        sa.Column("erreur", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "action IN ('rien','assigner_host','creer_host_mutualise','creer_vm_dediee')",
            name="ck_provisioning_action",
        ),
        sa.CheckConstraint(
            "state IN ('decide','en_cours','fait','echec')",
            name="ck_provisioning_state",
        ),
        sa.UniqueConstraint(
            "subscription_id", "provider_event_id", name="uq_provisioning_run_event"
        ),
    )
    # Les echecs se listent : c'est le seul index dont l'ecran d'exploitation a
    # besoin, et il reste petit.
    op.create_index(
        "ix_provisioning_runs_echec",
        "provisioning_runs",
        ["state"],
        postgresql_where=sa.text("state = 'echec'"),
    )


def downgrade() -> None:
    if "provisioning_runs" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("provisioning_runs")

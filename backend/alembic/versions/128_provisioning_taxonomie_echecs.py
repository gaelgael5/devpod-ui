"""Taxonomie des échecs de provisionnement (ticket 6 de l'épic hyperviseur).

La distinction qui compte n'est pas succès/échec, c'est ce qu'il reste
derrière : `echec_avant_creation` se rejoue sans risque, `echec_apres_creation`
porte un `provider_ref` (machine créée, configuration incomplète — reprendre ou
détruire), `indetermine` exige une décision humaine (timeout en plein apply :
rejouer automatiquement, c'est facturer deux VM).

`echec` reste accepté : c'est la valeur des lignes antérieures à cette
migration (issue inconnue faute de taxonomie à l'époque) — le nouveau code ne
l'écrit plus.

`provider` + `provider_ref` : ce que le driver a laissé derrière lui, posé dès
que la machine existe. `provider_ref` est opaque (contrat du ticket 4).

Revision ID: 128
Revises: 127
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "128"
down_revision: str | Sequence[str] | None = "127"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ETATS = (
    "'decide','en_cours','fait','echec',"
    "'echec_avant_creation','echec_apres_creation','indetermine'"
)


def upgrade() -> None:
    op.drop_constraint("ck_provisioning_state", "provisioning_runs", type_="check")
    op.create_check_constraint(
        "ck_provisioning_state", "provisioning_runs", f"state IN ({_ETATS})"
    )
    op.add_column(
        "provisioning_runs",
        sa.Column("provider", sa.Text(), nullable=False, server_default=""),
    )
    # Le noeud vise par le verdict (cible.noeud) : sans lui, un rejeu ne peut
    # pas reproduire la decision a l'identique.
    op.add_column(
        "provisioning_runs",
        sa.Column("noeud", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "provisioning_runs",
        sa.Column("provider_ref", sa.dialects.postgresql.JSONB(), nullable=True),
    )
    # L'index partiel des échecs couvre toute la taxonomie, sinon l'écran
    # d'exploitation ne voit plus les nouveaux états.
    op.drop_index("ix_provisioning_runs_echec", table_name="provisioning_runs")
    op.create_index(
        "ix_provisioning_runs_echec",
        "provisioning_runs",
        ["state"],
        postgresql_where=sa.text(
            "state IN ('echec','echec_avant_creation','echec_apres_creation','indetermine')"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_provisioning_runs_echec", table_name="provisioning_runs")
    op.create_index(
        "ix_provisioning_runs_echec",
        "provisioning_runs",
        ["state"],
        postgresql_where=sa.text("state = 'echec'"),
    )
    op.drop_column("provisioning_runs", "provider_ref")
    op.drop_column("provisioning_runs", "provider")
    op.drop_column("provisioning_runs", "noeud")
    op.execute(
        "UPDATE provisioning_runs SET state = 'echec' WHERE state IN "
        "('echec_avant_creation','echec_apres_creation','indetermine')"
    )
    op.drop_constraint("ck_provisioning_state", "provisioning_runs", type_="check")
    op.create_check_constraint(
        "ck_provisioning_state",
        "provisioning_runs",
        "state IN ('decide','en_cours','fait','echec')",
    )

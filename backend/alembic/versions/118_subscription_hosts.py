"""Ce qu'un abonnement a obtenu, machine par machine.

Jusqu'ici, le lien entre un abonne et sa machine passait par `host_ownership`,
dont la cle primaire est le nom de la machine : UNE machine, UN proprietaire.
Cela decrit une machine dediee et rien d'autre. Une machine mutualisee est
partagee par plusieurs abonnes, et ce modele ne sait pas l'ecrire.

Cette table le dit. Une ligne = « cet abonnement dispose de tant de workspaces
sur cette machine ». Les deux cas du catalogue ne different que par la presence
d'une part :

- `allocated_workspaces` NULL : machine DEDIEE. Le forfait limite le nombre de
  MACHINES, pas les workspaces — seule la capacite physique borne ce qui tourne
  dessus.
- un entier : part sur une machine MUTUALISEE, avec ses deux invariants — la
  somme des parts d'un abonnement tient dans le quota du forfait (commercial),
  la somme des parts sur une machine tient dans sa capacite (physique).

La cle primaire (abonnement, machine) porte l'idempotence : un webhook rejoue
REMPLACE la part, il n'en ajoute pas une seconde.

Le rattachement pend de l'ABONNEMENT et non du compte : un meme compte peut
souscrire deux fois la meme offre, et le couple (compte, offre) les confondrait.

Revision ID: 118
Revises: 117
Create Date: 2026-08-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "118"
down_revision: str | Sequence[str] | None = "117"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subscription_hosts",
        sa.Column(
            "subscription_id",
            UUID(as_uuid=False),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "host_name",
            sa.Text(),
            sa.ForeignKey("hosts.name", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("allocated_workspaces", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "allocated_workspaces IS NULL OR allocated_workspaces > 0",
            name="ck_subscription_host_part",
        ),
    )
    # Lecture par machine : « qui occupe celle-ci, et pour combien de places ».
    # C'est la question du pool a chaque souscription.
    op.create_index("ix_subscription_hosts_host", "subscription_hosts", ["host_name"])


def downgrade() -> None:
    op.drop_index("ix_subscription_hosts_host", table_name="subscription_hosts")
    op.drop_table("subscription_hosts")

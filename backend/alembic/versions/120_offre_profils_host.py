"""Profils de host qu'une offre sait provisionner, par ordre de priorite.

`billing.provisioning` sait deja dire qu'il faut ouvrir une machine — VM dediee
ou host mutualise — mais rien ne disait LAQUELLE : l'offre ne portait aucun lien
vers un profil de host. Le profil de host donne le profil de machine, donc le
type d'hyperviseur, donc le script de creation.

L'ordre EST la priorite : `priorite` = 0 est le gabarit essaye en premier. Une
table SQL n'a pas d'ordre propre, et sans rang la liste reviendrait melangee a
chaque relecture. Le rang est reecrit en bloc a chaque enregistrement, comme les
prix.

FK RESTRICT vers `host_profiles` : supprimer un profil reference par une offre
rendrait cette offre improvisionnable en silence. La route le refuse en 409.

Aucune reprise de donnees : les offres existantes partent sans profil, donc non
publiables en l'etat. C'est voulu — une offre que rien ne sait provisionner ne
doit pas etre republiee sans qu'on le lui ait dit. Les offres DEJA publiees ne
sont pas depubliees ici ; le garde-fou ne mord qu'a la prochaine ecriture.

Revision ID: 120
Revises: 119
Create Date: 2026-08-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "120"
down_revision: str | Sequence[str] | None = "119"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "offer_host_profiles",
        sa.Column("offer_slug", sa.Text(), nullable=False),
        sa.Column("profile_slug", sa.Text(), nullable=False),
        sa.Column("priorite", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["offer_slug"], ["offers.slug"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_slug"], ["host_profiles.slug"], ondelete="RESTRICT"),
        sa.UniqueConstraint("offer_slug", "profile_slug", name="uq_offer_host_profile"),
        sa.CheckConstraint("priorite >= 0", name="ck_offer_host_profile_priorite"),
    )
    op.create_index("ix_offer_host_profiles_profile", "offer_host_profiles", ["profile_slug"])


def downgrade() -> None:
    op.drop_index("ix_offer_host_profiles_profile", table_name="offer_host_profiles")
    op.drop_table("offer_host_profiles")
